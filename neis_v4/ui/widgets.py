from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QIcon, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)


def estimated_progress(elapsed: float, expected: float) -> int:
    """AI는 진행 상황을 알려 주지 않아서 경과 시간 / 예상 시간으로 어림합니다. 끝나기 전에는 95%에서 멈춥니다."""
    return min(95, int(elapsed / max(expected, 1) * 100))


def set_faded_text(label: QLabel, text: str) -> None:
    animation = getattr(label, "_text_fade_animation", None)
    if animation:
        animation.stop()
    label.setText(text)
    effect = QGraphicsOpacityEffect(label)
    label.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", label)
    animation.setDuration(140)
    animation.setStartValue(0.35)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.finished.connect(lambda: label.setGraphicsEffect(None))
    label._text_fade_animation = animation
    animation.start()


class HelpButton(QToolButton):
    def __init__(self, title: str, help_text: str, parent=None) -> None:
        super().__init__(parent)
        self.help_title = title
        self.help_text = help_text
        self.setText("?")
        self.setProperty("helpButton", True)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{title} 도움말")
        self.setAccessibleName(f"{title} 도움말")
        self.clicked.connect(self._show_help)

    def _show_help(self) -> None:
        QMessageBox.information(self, self.help_title, self.help_text)


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._position = 1.0 if checked else 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._set_position)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(42, 24)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def _set_position(self, value: float) -> None:
        self._position = float(value)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        if not self.isEnabled():
            track = QColor("#D9D9DD")
        else:
            track = QColor("#3478F6") if self.isChecked() else QColor("#C7C7CC")
        painter.setBrush(track)
        painter.drawRoundedRect(self.rect(), 12, 12)
        diameter = 20
        x = 2 + self._position * (self.width() - diameter - 4)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(x), 2, diameter, diameter)

    position = Property(float, lambda self: self._position, _set_position)


class SegmentedControl(QFrame):
    valueChanged = Signal(int)

    def __init__(self, options: list[tuple[str, int]], parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "Segmented")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        for label, value in options:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setProperty("segmentValue", value)
            self._group.addButton(button, value)
            layout.addWidget(button)
        self._group.idClicked.connect(self.valueChanged.emit)

    def value(self) -> int:
        return self._group.checkedId()

    def setValue(self, value: int) -> None:
        button = self._group.button(value)
        if button:
            button.setChecked(True)


class ChoiceSegmentedControl(QFrame):
    valueChanged = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "Segmented")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._labels = {value: label for label, value in options}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        for label, value in options:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.clicked.connect(lambda _checked=False, selected=value: self.valueChanged.emit(selected))
            self._group.addButton(button)
            self._buttons[value] = button
            layout.addWidget(button)

    def value(self) -> str:
        for value, button in self._buttons.items():
            if button.isChecked():
                return value
        return ""

    def setValue(self, value: str) -> None:
        button = self._buttons.get(value)
        if button and button.isEnabled():
            button.setChecked(True)

    def clear(self) -> None:
        self._group.setExclusive(False)
        for button in self._buttons.values():
            button.setChecked(False)
        self._group.setExclusive(True)

    def setOptionEnabled(self, value: str, enabled: bool, locked_label: bool = False) -> None:
        button = self._buttons[value]
        button.setEnabled(enabled)
        label = self._labels[value]
        button.setText(label if enabled or not locked_label else f"🔒 {label}")
        button.setToolTip("" if enabled else f"{label} API 키 미등록")

    def button(self, value: str) -> QPushButton | None:
        return self._buttons.get(value)


class NeisInputControls(QWidget):
    """AI 평어·행동발달 화면에서 바로 NEIS에 입력하는 '이동 칸' 선택과 시작·중지 버튼입니다."""

    start_requested = Signal()
    stop_requested = Signal()
    tab_count_changed = Signal(int)

    def __init__(self, tab_count: int, parent=None) -> None:
        super().__init__(parent)
        self.state = "idle"
        self.tab_count = SegmentedControl([("2", 2), ("3", 3), ("4", 4)])
        self.tab_count.setValue(tab_count)
        self.tab_count.setToolTip("내용을 붙여 넣은 뒤 Tab 키로 이동할 칸 수입니다.")
        self.tab_count.setAccessibleName("이동 칸")
        self.button = QPushButton()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel("이동 칸"))
        layout.addWidget(HelpButton("이동 칸", "Tab 2번: 창체/행발\nTab 3번: 교과평어"))
        layout.addWidget(self.tab_count)
        layout.addWidget(self.button)
        self.tab_count.valueChanged.connect(self.tab_count_changed.emit)
        self.button.clicked.connect(self._on_clicked)
        # 좁은 창에서도 버튼 글자가 잘리지 않게 가장 긴 글자에 맞춥니다.
        widths = []
        for state in ("armed", "running", "idle"):
            self.set_state(state)
            widths.append(self.button.sizeHint().width())
        self.button.setMinimumWidth(max(widths))

    def value(self) -> int:
        return self.tab_count.value()

    def _on_clicked(self) -> None:
        (self.start_requested if self.state == "idle" else self.stop_requested).emit()

    def set_state(self, state: str) -> None:
        """자동 입력 화면의 시작 버튼과 같은 글자·색으로 바꿉니다."""
        from neis_v4.ui.theme import COLORS, icon

        self.state = state
        text, variant, icon_name, color = {
            "idle": ("NEIS 자동 입력", "secondary", "play", COLORS["muted"]),
            "armed": ("시작 대기 취소", "secondary", "", COLORS["muted"]),
            "running": ("입력 중지", "destructive", "square", COLORS["danger"]),
        }[state]
        self.button.setText(text)
        self.button.setProperty("variant", variant)
        self.button.setIcon(icon(icon_name, color) if icon_name else QIcon())
        self.button.setToolTip(
            "결과를 NEIS 표에 넣고 바로 NEIS에 자동 입력합니다." if state == "idle" else "Esc 키로도 멈출 수 있습니다."
        )
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
        self.tab_count.setEnabled(state == "idle")


class ArrowComboBox(QComboBox):
    """Combo box with a painted chevron that does not depend on font glyphs."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#77777D" if self.isEnabled() else "#B8B8BD")
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        center_x = self.width() - 15
        center_y = self.height() / 2
        painter.drawPolyline(
            [
                QPointF(center_x - 4, center_y - 2),
                QPointF(center_x, center_y + 2),
                QPointF(center_x + 4, center_y - 2),
            ]
        )


class _NumberIconButton(QToolButton):
    def __init__(self, operation: str, parent=None) -> None:
        super().__init__(parent)
        self.operation = operation
        self.setObjectName("NumericStepButton")
        self.setFixedSize(22, 28)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#3A3A3C" if self.isEnabled() else "#B8B8BD")
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        center_x = self.width() / 2
        center_y = self.height() / 2
        painter.drawLine(
            QPointF(center_x - 3.5, center_y),
            QPointF(center_x + 3.5, center_y),
        )
        if self.operation == "plus":
            painter.drawLine(
                QPointF(center_x, center_y - 3.5),
                QPointF(center_x, center_y + 3.5),
            )


class CompactNumberInput(QFrame):
    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompactNumberInput")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._minimum = minimum
        self._maximum = maximum
        self._value = min(maximum, max(minimum, value))
        self.minus = _NumberIconButton("minus")
        self.plus = _NumberIconButton("plus")
        self.edit = QLineEdit(str(self._value))
        self.edit.setObjectName("CompactNumberEdit")
        self.edit.setValidator(QIntValidator(minimum, maximum, self.edit))
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setFixedWidth(28)
        self.edit.setMaxLength(len(str(maximum)))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(self.minus)
        layout.addWidget(self.edit)
        layout.addWidget(self.plus)
        self.minus.clicked.connect(lambda: self.setValue(self._value - 1))
        self.plus.clicked.connect(lambda: self.setValue(self._value + 1))
        self.edit.editingFinished.connect(self._commit_text)
        self._refresh()

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        value = min(self._maximum, max(self._minimum, int(value)))
        changed = value != self._value
        self._value = value
        self._refresh()
        if changed:
            self.valueChanged.emit(value)

    def _commit_text(self) -> None:
        text = self.edit.text().strip()
        self.setValue(int(text) if text else self._value)

    def _refresh(self) -> None:
        self.edit.setText(str(self._value))
        self.minus.setEnabled(self._value > self._minimum)
        self.plus.setEnabled(self._value < self._maximum)


class NumberStepper(QFrame):
    valueChanged = Signal(float)

    def __init__(
        self,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int = 0,
        suffix: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NumberStepper")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._decimals = decimals
        self._suffix = suffix
        self._value = minimum

        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(4)
        self.minus = QToolButton()
        self.minus.setObjectName("StepButton")
        self.minus.setText("−")
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumWidth(62)
        self.plus = QToolButton()
        self.plus.setObjectName("StepButton")
        self.plus.setText("+")
        layout.addWidget(self.minus)
        layout.addWidget(self.label)
        layout.addWidget(self.plus)
        self.minus.clicked.connect(lambda: self.setValue(self._value - self._step))
        self.plus.clicked.connect(lambda: self.setValue(self._value + self._step))
        self._refresh()

    def value(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:
        value = min(self._maximum, max(self._minimum, value))
        value = round(value, self._decimals)
        if value == self._value:
            return
        self._value = value
        self._refresh()
        self.valueChanged.emit(value)

    def _refresh(self) -> None:
        self.label.setText(f"{self._value:.{self._decimals}f}{self._suffix}")
        self.minus.setEnabled(self._value > self._minimum)
        self.plus.setEnabled(self._value < self._maximum)
