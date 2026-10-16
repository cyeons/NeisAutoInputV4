from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

from datetime import datetime

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neis_v4.automation import MacroRunner
from neis_v4.models import AppSettings, StudentRow
from neis_v4.roster import StudentRoster
from neis_v4.storage import Storage
from neis_v4.ui.theme import COLORS, icon
from neis_v4.ui.widgets import (
    ArrowComboBox,
    HelpButton,
    NumberStepper,
    SegmentedControl,
    ToggleSwitch,
    set_faded_text,
)


def parse_tabular_clipboard(text: str) -> list[list[str]]:
    """Parse spreadsheet/HWP clipboard text while preserving quoted line breaks."""
    normalized = (
        text.replace("\x00", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
    )
    if not normalized:
        return []
    try:
        rows = list(csv.reader(io.StringIO(normalized), delimiter="\t"))
    except csv.Error:
        rows = [line.split("\t") for line in normalized.split("\n")]
    while rows and all(cell == "" for cell in rows[-1]):
        rows.pop()
    if rows and rows[0]:
        rows[0][0] = rows[0][0].lstrip("\ufeff")
    return rows


CellState = tuple[str, object] | None
TableState = tuple[int, dict[tuple[int, int], CellState]]


@dataclass(frozen=True)
class TableChange:
    before_row_count: int
    after_row_count: int
    before: dict[tuple[int, int], CellState]
    after: dict[tuple[int, int], CellState]


class SpreadsheetTableWidget(QTableWidget):
    tabular_paste_requested = Signal(str, int, int)
    undo_applied = Signal()

    def __init__(self, rows: int, columns: int, parent=None) -> None:
        super().__init__(rows, columns, parent)
        self._undo_changes: list[TableChange] = []
        self._known_cells: dict[tuple[int, int], CellState] = {}
        self._restoring_undo = False
        self.itemChanged.connect(self._capture_item_change)
        self.reset_undo_history()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            mime_data = QApplication.clipboard().mimeData()
            if mime_data and mime_data.hasText():
                self.tabular_paste_requested.emit(
                    mime_data.text(),
                    max(0, self.currentRow()),
                    max(0, self.currentColumn()),
                )
                event.accept()
                return
        if event.matches(QKeySequence.StandardKey.Undo) and self.undo_table_change():
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _item_state(item: QTableWidgetItem | None) -> CellState:
        if item is None:
            return None
        return item.text(), item.data(Qt.UserRole)

    def _state(self) -> TableState:
        cells: dict[tuple[int, int], CellState] = {}
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                state = self._item_state(self.item(row, column))
                if state is not None:
                    cells[(row, column)] = state
        return self.rowCount(), cells

    def begin_grouped_change(self) -> TableState:
        return self._state()

    def commit_grouped_change(self, before: TableState) -> None:
        after = self._state()
        before_count, before_cells = before
        after_count, after_cells = after
        coordinates = before_cells.keys() | after_cells.keys()
        changed = {
            coordinate
            for coordinate in coordinates
            if before_cells.get(coordinate) != after_cells.get(coordinate)
        }
        if changed or before_count != after_count:
            self._push_change(
                TableChange(
                    before_count,
                    after_count,
                    {coordinate: before_cells.get(coordinate) for coordinate in changed},
                    {coordinate: after_cells.get(coordinate) for coordinate in changed},
                )
            )
        self._known_cells = after_cells

    def reset_undo_history(self) -> None:
        self._undo_changes.clear()
        self._known_cells = self._state()[1]

    def _capture_item_change(self, item: QTableWidgetItem) -> None:
        if self._restoring_undo:
            return
        coordinate = item.row(), item.column()
        before = self._known_cells.get(coordinate)
        after = self._item_state(item)
        if before == after:
            return
        self._push_change(
            TableChange(
                self.rowCount(),
                self.rowCount(),
                {coordinate: before},
                {coordinate: after},
            )
        )
        if after is None:
            self._known_cells.pop(coordinate, None)
        else:
            self._known_cells[coordinate] = after

    def _push_change(self, change: TableChange) -> None:
        self._undo_changes.append(change)
        if len(self._undo_changes) > 100:
            del self._undo_changes[0]

    def undo_table_change(self) -> bool:
        if not self._undo_changes:
            return False
        change = self._undo_changes.pop()
        self._restoring_undo = True
        self.blockSignals(True)
        try:
            self.setRowCount(change.before_row_count)
            for (row, column), state in change.before.items():
                if row >= change.before_row_count or column >= self.columnCount():
                    continue
                if state is None:
                    self.takeItem(row, column)
                    continue
                text, user_data = state
                item = self.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.setItem(row, column, item)
                item.setText(text)
                item.setData(Qt.UserRole, user_data)
        finally:
            self.blockSignals(False)
            self._restoring_undo = False
        self._known_cells = self._state()[1]
        self.undo_applied.emit()
        return True


class NeisTab(QWidget):
    MAX_STUDENT_COUNT = 1000

    settings_changed = Signal()
    rows_changed = Signal()
    start_hotkey_pressed = Signal()

    def __init__(
        self,
        storage: Storage,
        settings: AppSettings,
        roster: StudentRoster,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.roster = roster
        self.behavior_work_counter: Callable[[list[str]], int] | None = None
        self.runner: MacroRunner | None = None
        self._hotkey_armed = False
        self._hotkey_handle = None
        self._keyboard_module = None
        self._resizing_rows = False
        rows = roster.rows()

        self.table = SpreadsheetTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["이름", "내용"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 140)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.verticalHeader().setMinimumWidth(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.tabular_paste_requested.connect(self._paste_tabular_text)
        self.table.undo_applied.connect(self._on_table_undo_applied)

        self.status_label = QLabel("준비 완료")
        self.status_label.setObjectName("MutedLabel")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)

        self.delay_stepper = NumberStepper(0.05, 1.0, 0.05, decimals=2, suffix="초")
        self.delay_stepper.setValue(max(0.05, self.settings.macro_delay))
        self.delay_stepper.setToolTip("학생 한 명을 입력한 뒤 다음 입력까지 기다리는 시간입니다.")
        self.tab_segment = SegmentedControl([("2", 2), ("3", 3), ("4", 4)])
        self.tab_segment.setValue(self.settings.tab_count)
        self.tab_segment.setToolTip("내용 입력 후 Tab 키로 이동할 칸 수입니다.")
        self.tab_help = HelpButton(
            "이동 칸",
            "Tab 2번: 창체/행발\nTab 3번: 교과평어",
        )
        self.leading_space_toggle = ToggleSwitch(self.settings.leading_space)
        self.leading_space_toggle.setToolTip("각 학생의 내용 맨 앞에 공백 한 칸을 추가합니다.")
        self.leading_space_help = HelpButton(
            "앞에 빈칸",
            "입력할 내용 맨 앞에 공백 한 칸을 먼저 넣습니다.\n"
            "NEIS에서 첫 글자가 누락되거나 앞 내용과 붙어 보이는 경우 사용하세요.",
        )
        self.failsafe_toggle = ToggleSwitch(self.settings.pyautogui_failsafe)
        self.failsafe_toggle.setToolTip("자동 입력 중 마우스를 화면 모서리로 옮기면 즉시 중지합니다.")
        self.failsafe_help = HelpButton(
            "긴급 중지",
            "켜 두면 자동 입력 중 마우스를 화면 네 모서리 중 하나로 옮겨 즉시 중지할 수 있습니다.\n"
            "Esc 키로도 언제든 자동 입력을 중지할 수 있습니다.",
        )
        self.hotkey_start_toggle = ToggleSwitch(self.settings.hotkey_start_enabled)
        self.hotkey_start_toggle.setToolTip(
            "활성화하면 시작 버튼을 누른 뒤 선택한 기능 키로 즉시 입력을 시작합니다."
        )
        self.start_hotkey = ArrowComboBox()
        self.start_hotkey.addItems([f"F{number}" for number in range(2, 11)])
        selected_hotkey = (
            self.settings.start_hotkey
            if self.settings.start_hotkey in {f"F{number}" for number in range(2, 11)}
            else "F8"
        )
        self.start_hotkey.setCurrentText(selected_hotkey)
        self.start_hotkey.setMinimumWidth(86)
        self.start_hotkey.setToolTip("시작 대기 중 선택한 키를 누르면 즉시 입력합니다.")
        self.settings.start_hotkey = selected_hotkey
        self.hotkey_note = QLabel()
        self.hotkey_note.setObjectName("MutedLabel")
        self.student_count_stepper = NumberStepper(1, self.MAX_STUDENT_COUNT, 1)
        self.student_count_stepper.setValue(len(rows))
        self.student_count_stepper.setToolTip("학생 수에 맞춰 표의 행을 추가하거나 줄입니다.")
        self.settings.student_count = len(rows)

        self.save_button = QPushButton("작업 저장")
        self.save_button.setProperty("variant", "secondary")
        self.save_button.setIcon(icon("save", COLORS["muted"]))
        self.load_button = QPushButton("작업 불러오기")
        self.load_button.setProperty("variant", "secondary")
        self.load_button.setIcon(icon("folder-open", COLORS["muted"]))
        self.reset_button = QPushButton("내용 지우기")
        self.reset_button.setProperty("variant", "destructive")
        self.reset_button.setIcon(icon("trash-2", COLORS["danger"]))
        self.names_button = QPushButton("명단 저장")
        self.names_button.setProperty("variant", "secondary")
        self.names_button.setIcon(icon("users", COLORS["muted"]))
        self.run_button = QPushButton("NEIS 입력 시작")
        self.run_button.setProperty("variant", "primary")
        self.run_button.setIcon(icon("play", "#FFFFFF"))

        self.progress_label = QLabel(f"0/{len(rows)} 완료")
        self.progress_label.setObjectName("MetricValue")

        self._build_layout()
        self.set_rows(rows)
        self.status_label.setText(f"학생 {len(rows)}명 준비됨")
        self._connect()
        self._refresh_hotkey_controls()
        if self.settings.hotkey_start_enabled:
            self._register_start_hotkey()

    def _build_layout(self) -> None:
        self.setObjectName("AppPage")

        header = QVBoxLayout()
        title = QLabel("NEIS 자동 입력")
        title.setObjectName("PageTitle")
        subtitle = QLabel("학생별 행동발달 내용을 정리하고 현재 NEIS 입력칸부터 순서대로 자동 입력합니다.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(subtitle)
        header.setSpacing(4)

        toolbar = QFrame()
        toolbar.setProperty("role", "Toolbar")
        data_controls = QHBoxLayout()
        data_controls.setContentsMargins(12, 10, 12, 10)
        data_controls.setSpacing(8)
        data_title = QLabel("내용 준비")
        data_title.setObjectName("SectionTitle")
        data_controls.addWidget(data_title)
        data_controls.addSpacing(8)
        data_controls.addWidget(QLabel("학생 수"))
        data_controls.addWidget(self.student_count_stepper)
        data_controls.addSpacing(8)
        for button in [self.save_button, self.load_button, self.reset_button, self.names_button]:
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            data_controls.addWidget(button)
        data_controls.addStretch(1)
        toolbar.setLayout(data_controls)

        dock = QFrame()
        dock.setProperty("role", "Dock")
        dock_layout = QVBoxLayout(dock)
        dock_layout.setContentsMargins(14, 10, 14, 12)
        dock_layout.setSpacing(10)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.status_label)
        progress_row.addWidget(self.progress_label)
        dock_layout.addLayout(progress_row)

        controls = QVBoxLayout()
        controls.setSpacing(8)
        option_row = QHBoxLayout()
        option_row.setSpacing(9)
        settings_title = QLabel("입력 설정")
        settings_title.setObjectName("SectionTitle")
        option_row.addWidget(settings_title)
        option_row.addSpacing(4)
        option_row.addWidget(self._label_with_help("이동 칸", self.tab_help))
        option_row.addWidget(self.tab_segment)
        option_row.addWidget(QLabel("입력 간격"))
        option_row.addWidget(self.delay_stepper)
        option_row.addWidget(
            self._toggle_row(
                "앞에 빈칸",
                self.leading_space_toggle,
                self.leading_space_help,
            )
        )
        option_row.addWidget(
            self._toggle_row(
                "긴급 중지",
                self.failsafe_toggle,
                self.failsafe_help,
            )
        )
        option_row.addStretch(1)
        controls.addLayout(option_row)

        start_row = QHBoxLayout()
        start_row.setSpacing(9)
        start_label = QLabel("키를 눌러 시작")
        start_label.setObjectName("SectionTitle")
        start_row.addWidget(start_label)
        start_row.addWidget(self.hotkey_start_toggle)
        start_row.addWidget(self.start_hotkey)
        start_row.addWidget(self.hotkey_note)
        start_row.addStretch(1)
        start_row.addWidget(self.run_button)
        controls.addLayout(start_row)
        dock_layout.addLayout(controls)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(toolbar)
        layout.addWidget(self.table, 1)
        layout.addWidget(dock)

    @staticmethod
    def _label_with_help(label: str, help_button: HelpButton) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(QLabel(label))
        layout.addWidget(help_button)
        return row

    @staticmethod
    def _toggle_row(
        label: str,
        toggle: ToggleSwitch,
        help_button: HelpButton,
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(QLabel(label))
        layout.addWidget(help_button)
        layout.addWidget(toggle)
        return row

    def _connect(self) -> None:
        self.save_button.clicked.connect(self.save_data)
        self.load_button.clicked.connect(self.load_data)
        self.reset_button.clicked.connect(self.reset_contents)
        self.names_button.clicked.connect(self.save_names)
        self.student_count_stepper.valueChanged.connect(self._change_student_count)
        self.run_button.clicked.connect(self._toggle_macro)
        self.tab_segment.valueChanged.connect(self._sync_settings)
        self.delay_stepper.valueChanged.connect(self._sync_settings)
        self.leading_space_toggle.toggled.connect(self._sync_settings)
        self.failsafe_toggle.toggled.connect(self._sync_settings)
        self.hotkey_start_toggle.toggled.connect(self._on_hotkey_mode_toggled)
        self.start_hotkey.currentTextChanged.connect(self._on_start_hotkey_changed)
        self.start_hotkey_pressed.connect(self._start_from_hotkey)

    def _toggle_macro(self) -> None:
        if self.runner:
            self.stop_macro()
        elif self._hotkey_armed:
            self._cancel_hotkey_wait()
        else:
            self.start_macro()

    def _change_student_count(self, value: float) -> None:
        if self._resizing_rows:
            return
        new_count = int(value)
        current_count = self.table.rowCount()
        if new_count == current_count:
            return
        self._commit_table_edits()

        if new_count < current_count:
            removed_rows = self.rows()[new_count:]
            content_count = sum(bool(row.content.strip()) for row in removed_rows)
            behavior_count = (
                self.behavior_work_counter([row.student_id for row in removed_rows])
                if self.behavior_work_counter
                else 0
            )
            if content_count or behavior_count:
                details = []
                if content_count:
                    details.append(f"작성된 NEIS 내용 {content_count}명")
                if behavior_count:
                    details.append(f"행동발달 특성 또는 초안 {behavior_count}명")
                answer = QMessageBox.question(
                    self,
                    "학생 수 줄이기",
                    f"마지막 {current_count - new_count}개의 행이 삭제됩니다.\n"
                    f"삭제 대상에 {' · '.join(details)}이 있습니다.\n\n계속할까요?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    self._set_student_count_value(current_count)
                    return

        undo_state = self.table.begin_grouped_change()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(new_count)
            if new_count > current_count:
                for row in range(current_count, new_count):
                    new_student = StudentRow(f"학생 {row + 1}")
                    name_item = QTableWidgetItem(new_student.name)
                    name_item.setData(Qt.UserRole, new_student.student_id)
                    self.table.setItem(row, 0, name_item)
                    self.table.setItem(row, 1, QTableWidgetItem(""))
        finally:
            self.table.blockSignals(False)
        self.table.commit_grouped_change(undo_state)

        self.settings.student_count = new_count
        self.progress.setValue(0)
        self.progress_label.setText(f"0/{new_count} 완료")
        set_faded_text(self.status_label, f"학생 수를 {new_count}명으로 변경했습니다.")
        self.roster.replace(self.rows())
        self.rows_changed.emit()
        self.settings_changed.emit()

    def _set_student_count_value(self, count: int) -> None:
        self._resizing_rows = True
        try:
            self.student_count_stepper.setValue(count)
        finally:
            self._resizing_rows = False

    def _sync_settings(self) -> None:
        self.settings.tab_count = self.tab_segment.value()
        self.settings.macro_delay = self.delay_stepper.value()
        self.settings.leading_space = self.leading_space_toggle.isChecked()
        self.settings.pyautogui_failsafe = self.failsafe_toggle.isChecked()
        self.settings.start_hotkey = self.start_hotkey.currentText()
        self.settings.hotkey_start_enabled = self.hotkey_start_toggle.isChecked()
        self.settings_changed.emit()

    def _on_hotkey_mode_toggled(self, enabled: bool) -> None:
        self.settings.hotkey_start_enabled = enabled
        self._cancel_hotkey_wait()
        self._refresh_hotkey_controls()
        if enabled:
            self._register_start_hotkey()
        else:
            self._unregister_start_hotkey()
        self.settings_changed.emit()

    def _on_start_hotkey_changed(self, hotkey: str) -> None:
        self.settings.start_hotkey = hotkey
        self._cancel_hotkey_wait()
        if self.settings.hotkey_start_enabled:
            self._register_start_hotkey()
        self._refresh_hotkey_controls()
        self.settings_changed.emit()

    def _refresh_hotkey_controls(self) -> None:
        enabled = self.hotkey_start_toggle.isChecked()
        self.start_hotkey.setVisible(enabled)
        self.hotkey_note.setVisible(enabled)
        self.hotkey_note.setText(
            f"시작 버튼 → NEIS 첫 입력칸 선택 → {self.start_hotkey.currentText()} 키"
        )

    def _register_start_hotkey(self) -> None:
        self._unregister_start_hotkey()
        try:
            import keyboard

            self._keyboard_module = keyboard
            self._hotkey_handle = keyboard.add_hotkey(
                self.settings.start_hotkey.lower(),
                self.start_hotkey_pressed.emit,
            )
            self.start_hotkey.setToolTip(
                f"시작 대기 중 {self.settings.start_hotkey} 키를 누르면 즉시 입력합니다."
            )
        except Exception as exc:
            self._hotkey_handle = None
            self.start_hotkey.setToolTip(f"시작 키 등록 실패: {exc}")

    def _unregister_start_hotkey(self) -> None:
        if self._hotkey_handle is None or self._keyboard_module is None:
            return
        try:
            self._keyboard_module.remove_hotkey(self._hotkey_handle)
        except Exception:
            pass
        self._hotkey_handle = None

    def _start_from_hotkey(self) -> None:
        if self._hotkey_armed and not self.runner:
            self._hotkey_armed = False
            self._start_runner(self.rows(), start_delay=0)

    def _arm_hotkey_start(self) -> None:
        self._hotkey_armed = True
        hotkey = self.settings.start_hotkey
        set_faded_text(
            self.status_label,
            f"NEIS 첫 입력칸을 선택하고 {hotkey} 키를 누르세요.",
        )
        self.run_button.setText("시작 대기 취소")
        self.run_button.setProperty("variant", "secondary")
        self.run_button.setIcon(icon("clock-3", COLORS["muted"]))
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)

    def _cancel_hotkey_wait(self) -> None:
        if not self._hotkey_armed:
            return
        self._hotkey_armed = False
        set_faded_text(self.status_label, "시작 대기를 취소했습니다.")
        self._set_running(False)

    def rows(self) -> list[StudentRow]:
        rows: list[StudentRow] = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            content_item = self.table.item(row, 1)
            student_id = str(name_item.data(Qt.UserRole) or "") if name_item else ""
            rows.append(
                StudentRow(
                    name_item.text() if name_item else "",
                    content_item.text() if content_item else "",
                    student_id,
                )
            )
        return rows

    def set_rows(self, rows: list[StudentRow], *, record_undo: bool = False) -> None:
        undo_state = self.table.begin_grouped_change() if record_undo else None
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            name_item = QTableWidgetItem(row.name)
            name_item.setData(Qt.UserRole, row.student_id)
            self.table.setItem(index, 0, name_item)
            self.table.setItem(index, 1, QTableWidgetItem(row.content))
        self.table.blockSignals(False)
        if undo_state is None:
            self.table.reset_undo_history()
        else:
            self.table.commit_grouped_change(undo_state)
        self.roster.replace(rows)
        if hasattr(self, "progress_label"):
            self.progress_label.setText(f"0/{len(rows)} 완료")
        if hasattr(self, "student_count_stepper"):
            self._set_student_count_value(len(rows))
            self.settings.student_count = len(rows)

    def put_comments(self, comments: list[str]) -> None:
        undo_state = self.table.begin_grouped_change()
        previous_count = self.table.rowCount()
        self.table.blockSignals(True)
        try:
            if self.table.rowCount() < len(comments):
                self.table.setRowCount(len(comments))
                for index in range(len(comments)):
                    if not self.table.item(index, 0):
                        new_student = StudentRow(f"학생 {index + 1}")
                        name_item = QTableWidgetItem(new_student.name)
                        name_item.setData(Qt.UserRole, new_student.student_id)
                        self.table.setItem(index, 0, name_item)
            for index, comment in enumerate(comments):
                self.table.setItem(index, 1, QTableWidgetItem(comment))
        finally:
            self.table.blockSignals(False)
        self.table.commit_grouped_change(undo_state)
        if self.table.rowCount() != previous_count:
            self.settings.student_count = self.table.rowCount()
            self._set_student_count_value(self.table.rowCount())
            self.progress_label.setText(f"0/{self.table.rowCount()} 완료")
            self.settings_changed.emit()
        self.roster.replace(self.rows())
        self.rows_changed.emit()

    def put_comments_by_id(self, comments: dict[str, str]) -> None:
        if not comments:
            return
        undo_state = self.table.begin_grouped_change()
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                name_item = self.table.item(row, 0)
                student_id = str(name_item.data(Qt.UserRole) or "") if name_item else ""
                if student_id in comments:
                    self.table.setItem(row, 1, QTableWidgetItem(comments[student_id]))
        finally:
            self.table.blockSignals(False)
        self.table.commit_grouped_change(undo_state)
        self.roster.replace(self.rows())
        self.rows_changed.emit()

    def save_data(self) -> None:
        self._commit_table_edits()
        try:
            path = self.storage.save_students(self.rows())
        except Exception as exc:
            QMessageBox.critical(self, "작업 저장 실패", f"작업을 저장하지 못했습니다.\n\n{exc}")
            return
        time_text = datetime.now().strftime("%H:%M:%S")
        set_faded_text(self.status_label, f"작업 저장 완료 · {time_text}")
        self.status_label.setToolTip(f"저장 위치: {path}")

    def load_data(self) -> None:
        rows = self.storage.load_saved_students()
        if not rows:
            QMessageBox.information(self, "저장된 작업 없음", "불러올 작업 파일이 없습니다.")
            return
        rows = self.storage.reconcile_student_ids(rows, self.storage.load_behavior_work())
        self.set_rows(rows, record_undo=True)
        self.settings_changed.emit()
        set_faded_text(self.status_label, f"작업 불러오기 완료 · 학생 {len(rows)}명")

    def save_names(self) -> None:
        self._commit_table_edits()
        rows = self.rows()
        names = [row.name.strip() for row in rows if row.name.strip()]
        if not names:
            QMessageBox.information(self, "저장할 명단 없음", "이름 칸에 학생 이름을 먼저 입력하세요.")
            return
        try:
            path = self.storage.save_student_names(names)
            self.storage.save_students(rows)
        except Exception as exc:
            QMessageBox.critical(self, "학생 명단 저장 실패", f"학생 명단을 저장하지 못했습니다.\n\n{exc}")
            return
        set_faded_text(self.status_label, f"학생 명단 {len(names)}명 저장 완료")
        self.status_label.setToolTip(f"저장 위치: {path}")
        QMessageBox.information(
            self,
            "학생 명단 저장 완료",
            f"학생 {len(names)}명의 명단을 저장했습니다.\n다음 실행에서도 현재 이름이 유지됩니다.",
        )

    def _commit_table_edits(self) -> None:
        self.table.clearFocus()
        QApplication.processEvents()

    def _on_table_item_changed(self, _item: QTableWidgetItem) -> None:
        self.roster.replace(self.rows())
        self.rows_changed.emit()

    def _on_table_undo_applied(self) -> None:
        row_count = self.table.rowCount()
        count_changed = self.settings.student_count != row_count
        self.settings.student_count = row_count
        self._set_student_count_value(row_count)
        self.progress.setValue(0)
        self.progress_label.setText(f"0/{row_count} 완료")
        self.roster.replace(self.rows())
        self.rows_changed.emit()
        if count_changed:
            self.settings_changed.emit()
        set_faded_text(self.status_label, "실행 취소 완료")

    def _paste_tabular_text(self, text: str, start_row: int, start_column: int) -> None:
        clipboard_rows = parse_tabular_clipboard(text)
        if not clipboard_rows or start_column >= self.table.columnCount():
            return

        max_rows = self.MAX_STUDENT_COUNT
        available_rows = max(0, max_rows - start_row)
        clipboard_rows = clipboard_rows[:available_rows]
        if not clipboard_rows:
            return

        previous_count = self.table.rowCount()
        required_count = max(previous_count, start_row + len(clipboard_rows))
        changed_cells = 0
        last_row = start_row
        last_column = start_column

        undo_state = self.table.begin_grouped_change()
        self.table.blockSignals(True)
        try:
            if required_count > previous_count:
                self.table.setRowCount(required_count)
            for row in range(previous_count, required_count):
                student = StudentRow(f"학생 {row + 1}")
                name_item = QTableWidgetItem(student.name)
                name_item.setData(Qt.UserRole, student.student_id)
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, QTableWidgetItem(""))

            for row_offset, values in enumerate(clipboard_rows):
                target_row = start_row + row_offset
                for column_offset, value in enumerate(values):
                    target_column = start_column + column_offset
                    if target_column >= self.table.columnCount():
                        break
                    item = self.table.item(target_row, target_column)
                    if item is None:
                        item = QTableWidgetItem()
                        if target_column == 0:
                            item.setData(Qt.UserRole, StudentRow("").student_id)
                        self.table.setItem(target_row, target_column, item)
                    item.setText(value)
                    changed_cells += 1
                    last_row = target_row
                    last_column = target_column
        finally:
            self.table.blockSignals(False)
        self.table.commit_grouped_change(undo_state)

        if required_count != previous_count:
            self.settings.student_count = required_count
            self._set_student_count_value(required_count)
            self.progress_label.setText(f"0/{required_count} 완료")
            self.settings_changed.emit()
        self.roster.replace(self.rows())
        self.rows_changed.emit()
        self.table.setCurrentCell(last_row, last_column)
        set_faded_text(
            self.status_label,
            f"붙여넣기 완료 · {len(clipboard_rows)}행, {changed_cells}칸",
        )

    def reset_contents(self) -> None:
        if QMessageBox.question(self, "확인", "내용 칸을 모두 비울까요?") != QMessageBox.Yes:
            return
        rows = [StudentRow(row.name, "", row.student_id) for row in self.rows()]
        self.set_rows(rows, record_undo=True)
        self.status_label.setText("내용을 초기화했습니다.")

    def start_macro(self) -> None:
        self._sync_settings()
        rows = self.rows()
        if not any(row.content.strip() for row in rows):
            QMessageBox.information(self, "입력할 내용 없음", "표의 '내용' 칸을 먼저 작성하거나 불러오세요.")
            return
        if self.settings.hotkey_start_enabled:
            QMessageBox.information(
                self,
                "키를 눌러 시작",
                f"NEIS 첫 입력칸을 선택하고 {self.settings.start_hotkey} 키를 누르세요.\n"
                "선택한 키를 누르면 바로 자동 입력이 시작됩니다.",
            )
            self._arm_hotkey_start()
            return
        if QMessageBox.information(
            self,
            "NEIS 자동 입력 시작",
            "확인을 누르면 5초 카운트다운이 시작됩니다.\n그동안 NEIS의 첫 입력칸을 클릭하세요.\n\n입력 중에는 Esc 키 또는 화면 모서리로 긴급 중지할 수 있습니다.",
            QMessageBox.Ok | QMessageBox.Cancel,
        ) != QMessageBox.Ok:
            return
        self._start_runner(rows, start_delay=5)

    def _start_runner(self, rows: list[StudentRow], start_delay: int) -> None:
        self.runner = MacroRunner(
            rows=rows,
            tab_count=self.settings.tab_count,
            delay=self.settings.macro_delay,
            leading_space=self.settings.leading_space,
            failsafe=self.settings.pyautogui_failsafe,
            start_delay=start_delay,
        )
        self.runner.progress.connect(self._on_progress)
        self.runner.row_changed.connect(self._highlight_row)
        self.runner.failed.connect(lambda message: QMessageBox.critical(self, "오류", message))
        self.runner.finished_with_state.connect(self._on_finished)
        self._set_running(True)
        self.progress.setValue(0)
        self.progress_label.setText(f"0/{len(rows)} 완료")
        self.runner.start()

    def stop_macro(self) -> None:
        if self.runner:
            self.runner.stop()
        set_faded_text(self.status_label, "중지 요청됨")

    def _on_progress(self, done: int, total: int, text: str) -> None:
        self.progress.setValue(int(done / max(total, 1) * 100))
        self.progress_label.setText(f"{done}/{total} 완료")
        set_faded_text(self.status_label, text)

    def _highlight_row(self, row: int) -> None:
        self.table.clearSelection()
        self.table.selectRow(row)
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                item.setBackground(QColor("#E7F1FF"))
        self.table.scrollToItem(self.table.item(row, 0), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_finished(self, completed: bool) -> None:
        self._set_running(False)
        set_faded_text(self.status_label, "완료되었습니다." if completed else "중지되었습니다.")
        self.runner = None

    def _set_running(self, running: bool) -> None:
        self.hotkey_start_toggle.setEnabled(not running)
        self.start_hotkey.setEnabled(not running)
        self.run_button.setText("입력 중지" if running else "NEIS 입력 시작")
        self.run_button.setProperty("variant", "destructive" if running else "primary")
        color = COLORS["danger"] if running else "#FFFFFF"
        self.run_button.setIcon(icon("square" if running else "play", color))
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)

    def closeEvent(self, event: QEvent) -> None:
        self._unregister_start_hotkey()
        super().closeEvent(event)
