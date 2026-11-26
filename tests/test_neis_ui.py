from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox

from neis_v4.automation.runner import MacroRunner
from neis_v4.models import AppSettings, StudentRow
from neis_v4.roster import StudentRoster
from neis_v4.storage import Storage
from neis_v4.ui.neis_tab import (
    LENGTH_COLUMN,
    NeisTab,
    content_bytes,
    empty_rows_before_last_content,
    fill_empty_rows,
)
from neis_v4.ui.widgets import HelpButton


class NeisUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_rows_before_last_content_are_reported(self) -> None:
        rows = [
            StudentRow("학생 1", "내용"),
            StudentRow("학생 2", " "),
            StudentRow("학생 3", "내용"),
            StudentRow("학생 4", ""),
        ]
        # 마지막 내용 뒤의 빈 행(4번)은 다른 학생을 밀지 않으므로 제외합니다.
        self.assertEqual(empty_rows_before_last_content(rows), [2])
        self.assertEqual(empty_rows_before_last_content([StudentRow("학생 1")]), [])

    def test_input_settings_expose_hotkeys_and_help(self) -> None:
        fake_keyboard = MagicMock()
        fake_keyboard.add_hotkey.return_value = "hotkey-handle"
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            sys.modules,
            {"keyboard": fake_keyboard},
        ):
            settings = AppSettings(start_hotkey="F8")
            row = StudentRow("학생 1", "입력 내용")
            tab = NeisTab(
                Storage(Path(temporary)),
                settings,
                StudentRoster([row]),
            )

            self.assertEqual(
                [tab.start_hotkey.itemText(index) for index in range(tab.start_hotkey.count())],
                [f"F{number}" for number in range(2, 11)],
            )
            self.assertEqual(tab.start_hotkey.currentText(), "F8")
            self.assertFalse(tab.hotkey_start_toggle.isChecked())
            self.assertTrue(tab.start_hotkey.isHidden())
            self.assertEqual(len(tab.findChildren(HelpButton)), 3)
            self.assertEqual(
                tab.tab_help.help_text,
                "Tab 2번: 창체/행발\nTab 3번: 교과평어",
            )

            tab.hotkey_start_toggle.setChecked(True)
            self.assertFalse(tab.start_hotkey.isHidden())
            tab.start_hotkey.setCurrentText("F10")
            self.assertEqual(settings.start_hotkey, "F10")
            fake_keyboard.add_hotkey.assert_called_with(
                "f10",
                tab.start_hotkey_pressed.emit,
            )
            tab.close()
            fake_keyboard.remove_hotkey.assert_called()

    def test_default_start_uses_five_seconds_and_armed_hotkey_starts_immediately(self) -> None:
        runner = MacroRunner(
            rows=[StudentRow("학생 1", "입력 내용")],
            tab_count=2,
            delay=0.1,
            leading_space=False,
            failsafe=True,
        )
        self.assertEqual(runner.start_delay, 5)

        fake_keyboard = MagicMock()
        fake_keyboard.add_hotkey.return_value = "hotkey-handle"
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            sys.modules,
            {"keyboard": fake_keyboard},
        ):
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster([StudentRow("학생 1", "입력 내용")]),
            )
            with (
                patch(
                    "neis_v4.ui.neis_tab.QMessageBox.information",
                    return_value=QMessageBox.Ok,
                ),
                patch.object(tab, "_start_runner") as start_runner,
            ):
                tab.start_macro()
                self.assertEqual(start_runner.call_args.kwargs["start_delay"], 5)

            tab.hotkey_start_toggle.setChecked(True)
            with (
                patch("neis_v4.ui.neis_tab.QMessageBox.information"),
                patch.object(tab, "_start_runner") as start_runner,
            ):
                tab.start_macro()
                self.assertTrue(tab._hotkey_armed)
                start_runner.assert_not_called()
                tab._start_from_hotkey()
                self.assertFalse(tab._hotkey_armed)
                self.assertEqual(start_runner.call_args.kwargs["start_delay"], 0)
            tab.close()

    def test_unsupported_saved_hotkey_falls_back_to_f8(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config.json").write_text(
                json.dumps({"start_hotkey": "F11", "hotkey_start_enabled": True}),
                encoding="utf-8",
            )
            settings = Storage(root).load_settings()
            self.assertEqual(settings.start_hotkey, "F8")
            self.assertTrue(settings.hotkey_start_enabled)

    def test_excel_table_paste_expands_rows_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = AppSettings()
            tab = NeisTab(
                Storage(Path(temporary)),
                settings,
                StudentRoster([StudentRow("학생 1", "")]),
            )
            QApplication.clipboard().setText(
                '"가 학생"\t"첫 줄\n둘째 줄"\r\n나 학생\t두 번째 내용\r\n'
            )
            tab.table.setCurrentCell(0, 0)
            tab.table.setFocus()
            QTest.keyClick(tab.table, Qt.Key_V, Qt.ControlModifier)
            QApplication.processEvents()

            self.assertEqual(tab.table.rowCount(), 2)
            self.assertEqual(tab.table.item(0, 0).text(), "가 학생")
            self.assertEqual(tab.table.item(0, 1).text(), "첫 줄\n둘째 줄")
            self.assertEqual(tab.table.item(1, 0).text(), "나 학생")
            self.assertEqual(tab.table.item(1, 1).text(), "두 번째 내용")
            self.assertEqual(settings.student_count, 2)
            tab.close()

    def test_single_column_hwp_paste_fills_content_downward(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster(
                    [
                        StudentRow("학생 1", ""),
                        StudentRow("학생 2", ""),
                    ]
                ),
            )
            QApplication.clipboard().setText("첫 번째 평어\r\n두 번째 평어\r\n")
            tab.table.setCurrentCell(0, 1)
            tab.table.setFocus()
            QTest.keyClick(tab.table, Qt.Key_V, Qt.ControlModifier)
            QApplication.processEvents()

            self.assertEqual(tab.table.item(0, 0).text(), "학생 1")
            self.assertEqual(tab.table.item(1, 0).text(), "학생 2")
            self.assertEqual(tab.table.item(0, 1).text(), "첫 번째 평어")
            self.assertEqual(tab.table.item(1, 1).text(), "두 번째 평어")
            tab.close()

    def test_table_selects_only_the_current_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster(
                    [
                        StudentRow("학생 1", "첫 내용"),
                        StudentRow("학생 2", "둘째 내용"),
                    ]
                ),
            )
            tab.table.setCurrentCell(0, 1)
            selected = {
                (index.row(), index.column())
                for index in tab.table.selectionModel().selectedIndexes()
            }
            self.assertEqual(
                tab.table.selectionBehavior(),
                QAbstractItemView.SelectItems,
            )
            self.assertEqual(selected, {(0, 1)})
            tab.close()

    def test_ctrl_z_undoes_cell_edit_and_grouped_paste(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            original = StudentRow("학생 1", "원래 내용")
            settings = AppSettings()
            tab = NeisTab(
                Storage(Path(temporary)),
                settings,
                StudentRoster([original]),
            )

            tab.table.item(0, 1).setText("수정한 내용")
            tab.table.setCurrentCell(0, 1)
            tab.table.setFocus()
            QTest.keyClick(tab.table, Qt.Key_Z, Qt.ControlModifier)
            QApplication.processEvents()
            self.assertEqual(tab.table.item(0, 1).text(), "원래 내용")
            self.assertEqual(tab.rows()[0].student_id, original.student_id)

            QApplication.clipboard().setText("붙여넣기 1\r\n붙여넣기 2\r\n")
            tab.table.setCurrentCell(0, 1)
            QTest.keyClick(tab.table, Qt.Key_V, Qt.ControlModifier)
            QApplication.processEvents()
            self.assertEqual(tab.table.rowCount(), 2)
            self.assertEqual(settings.student_count, 2)

            QTest.keyClick(tab.table, Qt.Key_Z, Qt.ControlModifier)
            QApplication.processEvents()
            self.assertEqual(tab.table.rowCount(), 1)
            self.assertEqual(tab.table.item(0, 1).text(), "원래 내용")
            self.assertEqual(settings.student_count, 1)
            self.assertEqual(tab.rows()[0].student_id, original.student_id)
            tab.close()

    def test_ctrl_z_restores_reset_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster(
                    [
                        StudentRow("학생 1", "첫 내용"),
                        StudentRow("학생 2", "둘째 내용"),
                    ]
                ),
            )
            with patch(
                "neis_v4.ui.neis_tab.QMessageBox.question",
                return_value=QMessageBox.Yes,
            ):
                tab.reset_contents()
            self.assertEqual([row.content for row in tab.rows()], ["", ""])

            tab.table.setCurrentCell(0, 1)
            tab.table.setFocus()
            QTest.keyClick(tab.table, Qt.Key_Z, Qt.ControlModifier)
            QApplication.processEvents()
            self.assertEqual(
                [row.content for row in tab.rows()],
                ["첫 내용", "둘째 내용"],
            )
            tab.close()

    def test_fill_empty_rows_keeps_existing_content(self) -> None:
        self.assertEqual(
            fill_empty_rows(["기존", "", " ", "기존2"], ["새1", "새2", "새3"]),
            ["기존", "새1", "새2", "기존2", "새3"],
        )
        self.assertEqual(fill_empty_rows(["", ""], ["새1"]), ["새1", ""])

    def test_length_column_marks_rows_over_byte_limit(self) -> None:
        self.assertEqual(content_bytes(" 가a "), 4)
        with tempfile.TemporaryDirectory() as temporary:
            settings = AppSettings(content_byte_limit=100)
            tab = NeisTab(
                Storage(Path(temporary)),
                settings,
                StudentRoster([StudentRow("학생 1", "가" * 34), StudentRow("학생 2", "짧음")]),
            )
            over = tab.table.item(0, LENGTH_COLUMN)
            self.assertEqual(over.text(), "34자 · 102byte")
            self.assertIsNotNone(over.data(Qt.ForegroundRole))
            self.assertIsNone(tab.table.item(1, LENGTH_COLUMN).data(Qt.ForegroundRole))
            self.assertEqual(tab.over_limit_rows(tab.rows()), [1])
            # 분량 칸은 표시용이라 저장되는 행 데이터에 섞이지 않습니다.
            self.assertEqual([row.content for row in tab.rows()], ["가" * 34, "짧음"])

            settings.content_byte_limit = 200
            tab.refresh_lengths()
            self.assertIsNone(tab.table.item(0, LENGTH_COLUMN).data(Qt.ForegroundRole))
            tab.close()

    def test_start_from_selected_row_passes_remaining_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster([StudentRow(f"학생 {i}", f"내용 {i}") for i in range(1, 4)]),
            )
            with (
                patch.object(tab, "_ask_start_index", return_value=1),
                patch("neis_v4.ui.neis_tab.QMessageBox.information", return_value=QMessageBox.Ok),
                patch.object(tab, "_start_runner") as start_runner,
            ):
                tab.start_macro()
            rows = start_runner.call_args.args[0]
            self.assertEqual([row.name for row in rows], ["학생 2", "학생 3"])
            self.assertEqual(tab._start_index, 1)
            tab.close()

    def test_finished_status_summarizes_skipped_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster([StudentRow("학생 1", "내용")]),
            )
            tab._start_index = 2
            tab.runner = MagicMock(entered=5, skipped=[0, 3])
            tab._on_finished(True)
            self.assertIn("5명 입력", tab.status_label.toolTip())
            self.assertIn("빈 행 2개 건너뜀(3, 6번)", tab.status_label.toolTip())
            tab.close()

    def test_stop_selects_next_student_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rows = [StudentRow(f"학생 {number}", "내용") for number in range(1, 6)]
            tab = NeisTab(Storage(Path(temporary)), AppSettings(), StudentRoster(rows))
            # 1번 입력, 2번 빈 행, 3번 입력 뒤 Esc → 3번은 이미 들어갔으므로 4번이 골라져야 합니다.
            tab.runner = types.SimpleNamespace(entered=2, skipped=[1], rows=rows)
            tab._on_finished(False)
            self.assertEqual({index.row() for index in tab.table.selectedIndexes()}, {3})
            self.assertIn("중지되었습니다", tab.status_label.toolTip())
            # 마지막 학생을 넣다가 멈췄다면 다 끝난 것입니다.
            tab.runner = types.SimpleNamespace(entered=5, skipped=[], rows=rows)
            tab._on_finished(False)
            self.assertEqual(tab.table.selectedIndexes(), [])
            self.assertIn("완료되었습니다", tab.status_label.toolTip())
            tab.close()

    def test_start_macro_uses_given_rows_and_tab_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, {"keyboard": MagicMock()}):
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(tab_count=2),
                StudentRoster([StudentRow("학생 1", "표에 있던 내용")]),
            )
            rows = [StudentRow("학생 1", "평어")]
            with (
                patch("neis_v4.ui.neis_tab.QMessageBox.information", return_value=QMessageBox.Ok),
                patch.object(tab, "_start_runner") as start_runner,
            ):
                tab.start_macro(rows, 3)
            self.assertEqual(start_runner.call_args.args[0], rows)
            self.assertEqual(start_runner.call_args.kwargs["tab_count"], 3)

            # 키로 시작할 때도 대기를 걸 때 받은 행과 이동 칸을 씁니다. 대기 중에 또 시작하면 무시합니다.
            tab.hotkey_start_toggle.setChecked(True)
            with (
                patch("neis_v4.ui.neis_tab.QMessageBox.information"),
                patch.object(tab, "_start_runner") as start_runner,
            ):
                tab.start_macro(rows, 4)
                self.assertEqual(tab.input_state(), "armed")
                tab.start_macro([StudentRow("학생 1", "다른 내용")], 2)
                tab._start_from_hotkey()
            start_runner.assert_called_once()
            self.assertEqual(start_runner.call_args.args[0], rows)
            self.assertEqual(start_runner.call_args.kwargs["tab_count"], 4)

            # 자동 입력 화면에서 시작했다면 키를 기다리는 동안 표에서 고친 내용이 들어갑니다.
            with (
                patch("neis_v4.ui.neis_tab.QMessageBox.information"),
                patch.object(tab, "_start_runner") as start_runner,
            ):
                tab.start_macro()
                tab.table.item(0, 1).setText("기다리는 동안 고친 내용")
                tab._start_from_hotkey()
            self.assertEqual([row.content for row in start_runner.call_args.args[0]], ["기다리는 동안 고친 내용"])
            self.assertEqual(start_runner.call_args.kwargs["tab_count"], 2)
            tab.close()

    def test_overwrite_is_the_default_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster([StudentRow("학생 1", "이전 내용"), StudentRow("학생 2")]),
            )
            shown = []

            def press_enter(box):
                shown.append(box.defaultButton().text())
                box.defaultButton().click()

            with patch.object(QMessageBox, "exec", press_enter):
                self.assertEqual(tab.receive_ai_comments(["새 평어"]), 1)
            self.assertEqual(shown, ["덮어쓰기"])
            self.assertEqual([row.content for row in tab.rows()], ["새 평어", ""])
            tab.close()

    def test_ai_comments_go_straight_into_empty_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tab = NeisTab(
                Storage(Path(temporary)),
                AppSettings(),
                StudentRoster([StudentRow("학생 1"), StudentRow("학생 2")]),
            )
            self.assertEqual(tab.receive_ai_comments(["평어 1", "평어 2"]), 2)
            self.assertEqual([row.content for row in tab.rows()], ["평어 1", "평어 2"])
            tab.close()


if __name__ == "__main__":
    unittest.main()
