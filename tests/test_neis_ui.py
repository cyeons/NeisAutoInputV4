from __future__ import annotations

import json
import os
import sys
import tempfile
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
from neis_v4.ui.neis_tab import NeisTab
from neis_v4.ui.widgets import HelpButton


class NeisUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

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


if __name__ == "__main__":
    unittest.main()
