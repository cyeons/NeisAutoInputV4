from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from neis_v4.storage import resource_path


COLORS = {
    "text": "#1D1D1F",
    "muted": "#6E6E73",
    "blue": "#3478F6",
    "blue_hover": "#2568DB",
    "blue_soft": "#E8F0FE",
    "danger": "#D92D20",
    "success": "#17803D",
}


@lru_cache(maxsize=128)
def icon(name: str, color: str = "#5F6368", size: int = 16) -> QIcon:
    path = resource_path(f"resources/icons/{name}.svg")
    if not path.exists():
        return QIcon()
    svg = path.read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


STYLE_SHEET = """
* {
    font-size: 10.5pt;
    color: #1D1D1F;
    outline: 0;
}

QMainWindow, QWidget#AppShell, QWidget#AppPage, QWidget#SettingsViewport {
    background: #F5F5F7;
}

QFrame#Sidebar {
    min-width: 154px;
    max-width: 176px;
    background: #F0F1F4;
    border: 0;
    border-right: 1px solid #E2E3E7;
}

QLabel#SidebarCaption {
    color: #9A9AA0;
    padding: 8px 8px;
}

QPushButton[nav="true"] {
    color: #5E5E63;
    background: transparent;
    min-height: 40px;
    padding: 0 12px;
    border: 0;
    border-radius: 9px;
    text-align: left;
    font-weight: 600;
}

QPushButton[nav="true"]:hover:!checked {
    background: #E7E8EB;
    color: #1D1D1F;
}

QPushButton[nav="true"]:checked {
    color: #185ABD;
    background: #E1EAFB;
    font-weight: 700;
}

QPushButton[nav="true"]:focus {
    border: 0;
}

QLabel#PageTitle {
    color: #1D1D1F;
    font-size: 20pt;
    font-weight: 700;
}

QLabel#PageSubtitle, QLabel#MutedLabel {
    color: #6E6E73;
}

QLabel#SectionTitle {
    color: #333338;
    font-size: 11.5pt;
    font-weight: 700;
}

QLabel#MetricValue {
    color: #1D1D1F;
    font-size: 12pt;
    font-weight: 700;
}

QFrame[role="Panel"], QFrame[role="Toolbar"], QFrame[role="Dock"] {
    background: #FFFFFF;
    border: 1px solid #E2E3E7;
    border-radius: 12px;
}

QFrame[role="SubPanel"] {
    background: #F8F8FA;
    border: 1px solid #E5E5E8;
    border-radius: 10px;
}

QFrame[role="SelectableCard"] {
    background: #FFFFFF;
    border: 1px solid #E4E5E8;
    border-radius: 9px;
}

QFrame[role="SelectableCard"]:hover {
    background: #F7FAFF;
    border-color: #BFD3F4;
}

QFrame[role="SelectableCard"][selected="true"] {
    background: #EAF2FF;
    border-color: #78A8FA;
}

QFrame[role="TraitGroupHeader"] {
    background: #F3F6FA;
    border: 1px solid #DDE5EF;
    border-radius: 8px;
}

QPushButton {
    min-height: 36px;
    padding: 0 14px;
    border: 1px solid #D7D8DC;
    border-radius: 8px;
    background: #FFFFFF;
    color: #3A3A3C;
    font-weight: 600;
}

QPushButton:hover {
    background: #F2F2F4;
    border-color: #C6C7CC;
}

QPushButton:pressed {
    background: #E7E8EB;
}

QPushButton:focus {
    border: 2px solid #78A8FA;
}

QPushButton:disabled {
    color: #A7A7AC;
    background: #F4F4F6;
    border-color: #E6E6E9;
}

QPushButton[variant="primary"] {
    color: #FFFFFF;
    background: #3478F6;
    border-color: #3478F6;
}

QPushButton[variant="primary"]:hover {
    background: #2568DB;
    border-color: #2568DB;
}

QPushButton[variant="primary"]:disabled {
    color: #A7A7AC;
    background: #E9E9EC;
    border-color: #E0E0E4;
}

QPushButton[variant="secondary"] {
    color: #3A3A3C;
    background: #FFFFFF;
}

QPushButton[variant="ghost"] {
    color: #55555A;
    background: transparent;
    border-color: transparent;
}

QPushButton[variant="ghost"]:hover {
    color: #1D1D1F;
    background: #ECECEF;
}

QPushButton[variant="destructive"] {
    color: #C43228;
    background: #FFF7F6;
    border-color: #F3C2BE;
}

QPushButton[variant="destructive"]:hover {
    background: #FDEAE8;
    border-color: #EBA8A2;
}

QPushButton[segment="true"] {
    min-height: 30px;
    padding: 0 12px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: #66666B;
}

QPushButton[segment="true"]:checked {
    background: #FFFFFF;
    color: #185ABD;
    font-weight: 700;
}

QPushButton[segment="true"]:disabled {
    color: #A0A0A6;
    background: #E7E7EA;
}

QPushButton[segment="true"][traitLevel="strength"]:checked {
    background: #EAF7EF;
    color: #17713C;
}

QPushButton[segment="true"][traitLevel="standard"]:checked {
    background: #EAF1FD;
    color: #235FA7;
}

QPushButton[segment="true"][traitLevel="growth"]:checked {
    background: #FFF4E5;
    color: #945712;
}

QPushButton[tabChip="true"] {
    min-height: 30px;
    padding: 0 12px;
    background: #FFFFFF;
    color: #55555B;
    border: 1px solid #D9DADE;
    border-radius: 15px;
}

QPushButton[tabChip="true"]:hover {
    border-color: #9BB9EA;
    background: #F5F9FF;
}

QPushButton[tabChip="true"]:checked {
    border-color: #3478F6;
    background: #E8F1FF;
    color: #185ABD;
    font-weight: 700;
}

QToolButton[domainHeader="true"] {
    min-height: 30px;
    padding: 0 4px;
    border: 0;
    background: transparent;
    text-align: left;
    font-weight: 700;
    color: #303034;
}

QToolButton[helpButton="true"] {
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 0;
    color: #4F6585;
    background: #F3F6FA;
    border: 1px solid #D6E0ED;
    border-radius: 7px;
    font-weight: 800;
}

QToolButton[helpButton="true"]:hover {
    color: #185ABD;
    background: #E8F1FF;
    border-color: #AFC8EE;
}

QToolButton[helpButton="true"]:pressed {
    background: #DCE9FD;
}

QFrame[role="Segmented"] {
    background: #ECECEF;
    border: 1px solid #E0E0E4;
    border-radius: 8px;
}

QComboBox, QSpinBox, QLineEdit {
    min-height: 36px;
    padding: 0 10px;
    border: 1px solid #D7D8DC;
    border-radius: 8px;
    background: #FFFFFF;
    selection-background-color: #DCE9FD;
}

QComboBox:hover, QSpinBox:hover, QLineEdit:hover {
    border-color: #BFC0C5;
}

QComboBox:focus, QSpinBox:focus, QLineEdit:focus {
    border: 2px solid #78A8FA;
}

QFrame#CompactNumberInput {
    min-width: 76px;
    max-width: 76px;
    min-height: 32px;
    max-height: 32px;
    background: #FFFFFF;
    border: 1px solid #D7D8DC;
    border-radius: 8px;
}

QFrame#CompactNumberInput:focus-within {
    border: 2px solid #78A8FA;
}

QLineEdit#CompactNumberEdit {
    min-height: 28px;
    max-height: 28px;
    min-width: 28px;
    max-width: 28px;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
}

QLineEdit#CompactNumberEdit:focus {
    border: 0;
}

QToolButton#NumericStepButton {
    border: 0;
    border-radius: 6px;
    background: transparent;
}

QToolButton#NumericStepButton:hover {
    background: #E8EEF8;
}

QComboBox::drop-down {
    width: 30px;
    border: 0;
    border-left: 1px solid #E5E5E8;
    background: #F8F8FA;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
}

QToolButton#StepButton {
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: #3A3A3C;
    font-size: 13pt;
    font-weight: 600;
}

QToolButton#StepButton:hover {
    background: #E1E2E6;
}

QFrame#NumberStepper {
    background: #FFFFFF;
    border: 1px solid #D7D8DC;
    border-radius: 8px;
}

QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #FAFAFB;
    border: 1px solid #E2E3E7;
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: #E5EFFD;
    selection-color: #1D1D1F;
}

QHeaderView::section {
    background: #F7F7F9;
    color: #626268;
    font-weight: 700;
    border: 0;
    border-bottom: 1px solid #E2E3E7;
    padding: 9px 10px;
}

QTableCornerButton::section {
    background: #F7F7F9;
    border: 0;
    border-bottom: 1px solid #E2E3E7;
}

QTextEdit, QScrollArea, QListWidget {
    background: #FFFFFF;
    border: 1px solid #E2E3E7;
    border-radius: 10px;
}

QTextEdit::viewport, QScrollArea::viewport, QListWidget::viewport {
    background: #FFFFFF;
}

QListWidget {
    alternate-background-color: #FAFAFB;
    selection-background-color: #E5EFFD;
    selection-color: #1D1D1F;
    padding: 4px;
}

QListWidget::item {
    min-height: 30px;
    padding: 3px 6px;
    border-radius: 6px;
}

QListWidget::item:selected {
    border-left: 3px solid #3478F6;
    background: #E5EFFD;
}

QScrollArea#SettingsScroll {
    background: transparent;
    border: 0;
}

QScrollArea#TabScroll {
    background: transparent;
    border: 0;
}

QScrollArea#TabScroll > QWidget > QWidget {
    background: transparent;
}

QScrollBar:horizontal {
    min-height: 6px;
    max-height: 6px;
    background: transparent;
    margin: 0;
}

QScrollBar::handle:horizontal {
    min-width: 28px;
    border-radius: 3px;
    background: #C9CBD0;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: transparent;
}

QProgressBar {
    min-height: 6px;
    max-height: 6px;
    border: 0;
    border-radius: 3px;
    background: #E7E8EB;
    color: transparent;
}

QProgressBar::chunk {
    border-radius: 3px;
    background: #3478F6;
}

QLabel[badge="success"] {
    color: #147A3D;
    background: #E9F7EF;
    border: 1px solid #C5E8D2;
    border-radius: 8px;
    padding: 4px 8px;
    font-weight: 600;
}

QLabel[badge="warning"] {
    color: #9A5B13;
    background: #FFF7E5;
    border: 1px solid #F4DBA7;
    border-radius: 8px;
    padding: 4px 8px;
    font-weight: 600;
}

QLabel[badge="danger"] {
    color: #B42318;
    background: #FDECEC;
    border: 1px solid #F4C7C3;
    border-radius: 8px;
    padding: 4px 8px;
    font-weight: 600;
}

QLabel[badge="info"] {
    color: #185ABD;
    background: #E8F1FF;
    border: 1px solid #C3D8F8;
    border-radius: 8px;
    padding: 4px 8px;
    font-weight: 600;
}

QLabel[badge="neutral"] {
    color: #66666B;
    background: #F0F0F2;
    border: 1px solid #DEDFE2;
    border-radius: 8px;
    padding: 4px 8px;
    font-weight: 600;
}

QSplitter::handle {
    background: transparent;
}
"""
