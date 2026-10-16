from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from neis_v4 import APP_DISPLAY_NAME, APP_VERSION_LABEL
from neis_v4.models import AppSettings
from neis_v4.roster import StudentRoster
from neis_v4.secrets import SecretStore
from neis_v4.storage import Storage, resource_path
from neis_v4.ui.ai_tab import AiTab
from neis_v4.ui.behavior_tab import BehaviorTab
from neis_v4.ui.neis_tab import NeisTab
from neis_v4.ui.settings_tab import SettingsTab
from neis_v4.ui.theme import COLORS, STYLE_SHEET, icon


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.storage = Storage()
        self.settings: AppSettings = self.storage.load_settings()
        self.secrets = SecretStore()
        rows = self.storage.load_students(self.settings.student_count)
        behavior_work = self.storage.load_behavior_work()
        rows = self.storage.reconcile_student_ids(rows, behavior_work)
        self.roster = StudentRoster(rows, self)

        self.setWindowTitle(APP_DISPLAY_NAME)
        icon_path = resource_path("resources/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1480, 880)
        self.setMinimumSize(1000, 650)
        if self.settings.always_on_top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.neis_tab = NeisTab(self.storage, self.settings, self.roster)
        self.ai_tab = AiTab(self.storage, self.settings, self.secrets)
        self.behavior_tab = BehaviorTab(
            self.storage,
            self.settings,
            self.secrets,
            self.roster,
            behavior_work,
        )
        self.neis_tab.behavior_work_counter = self.behavior_tab.count_students_with_work
        self.settings_tab = SettingsTab(self.settings, self.secrets)
        self.nav_buttons: list[QPushButton] = []
        self.nav_icon_names: list[str] = []
        self._fade_animation: QPropertyAnimation | None = None
        self._fade_page: QWidget | None = None
        self.stack = QStackedWidget()
        self._build_shell()

        self.neis_tab.settings_changed.connect(self.save_settings)
        self.ai_tab.settings_changed.connect(self._on_runtime_settings_changed)
        self.behavior_tab.settings_changed.connect(self._on_runtime_settings_changed)
        self.settings_tab.settings_changed.connect(self.apply_settings)
        self.ai_tab.api_keys_changed.connect(self._refresh_api_keys)
        self.behavior_tab.api_keys_changed.connect(self._refresh_api_keys)
        self.settings_tab.api_keys_changed.connect(self._refresh_api_keys)
        self.ai_tab.comments_ready.connect(self.neis_tab.put_comments)
        self.behavior_tab.comments_ready.connect(self.neis_tab.put_comments_by_id)

        self.setStyleSheet(STYLE_SHEET)
        self._select_page(0)

    def _build_shell(self) -> None:
        shell = QWidget()
        shell.setObjectName("AppShell")
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(154)
        sidebar.setMaximumWidth(176)
        sidebar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 16, 10, 16)
        sidebar_layout.setSpacing(8)

        self._add_page(sidebar_layout, "자동 입력", "keyboard", self.neis_tab)
        self._add_page(sidebar_layout, "AI 평어", "sparkles", self.ai_tab)
        self._add_page(sidebar_layout, "행동발달", "shield-check", self.behavior_tab)
        self._add_page(sidebar_layout, "환경 설정", "settings-2", self.settings_tab)
        sidebar_layout.addStretch(1)

        version = QLabel(APP_VERSION_LABEL)
        version.setObjectName("SidebarCaption")
        sidebar_layout.addWidget(version)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(shell)

    def _add_page(self, sidebar_layout: QVBoxLayout, title: str, icon_name: str, page: QWidget) -> None:
        index = self.stack.addWidget(page)
        button = QPushButton(title)
        button.setCheckable(True)
        button.setProperty("nav", True)
        button.setIcon(icon(icon_name, COLORS["muted"], 17))
        button.setIconSize(QSize(17, 17))
        button.clicked.connect(lambda _checked=False, page_index=index: self._select_page(page_index))
        sidebar_layout.addWidget(button)
        self.nav_buttons.append(button)
        self.nav_icon_names.append(icon_name)

    def _select_page(self, index: int) -> None:
        changed = self.stack.currentIndex() != index
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            selected = button_index == index
            button.setChecked(selected)
            color = COLORS["blue"] if selected else COLORS["muted"]
            button.setIcon(icon(self.nav_icon_names[button_index], color, 17))
        if changed:
            self._fade_current_page()

    def _fade_current_page(self) -> None:
        if self._fade_animation:
            self._fade_animation.stop()
        if self._fade_page:
            self._fade_page.setGraphicsEffect(None)
        page = self.stack.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(140)
        animation.setStartValue(0.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda: self._finish_fade(page))
        self._fade_animation = animation
        self._fade_page = page
        animation.start()

    def _finish_fade(self, page: QWidget) -> None:
        page.setGraphicsEffect(None)
        if self._fade_page is page:
            self._fade_page = None
            self._fade_animation = None

    def apply_settings(self) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.settings.always_on_top)
        self.show()
        self.ai_tab.refresh_from_settings()
        self.behavior_tab.refresh_from_settings()
        self.save_settings()

    def _on_runtime_settings_changed(self) -> None:
        self.settings_tab.refresh_from_settings()
        self.save_settings()

    def _refresh_api_keys(self) -> None:
        self.ai_tab.refresh_api_keys()
        self.behavior_tab.refresh_api_keys()
        self.settings_tab.refresh_api_keys()

    def save_settings(self) -> None:
        self.storage.save_settings(self.settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_settings()
        self.storage.save_students(self.neis_tab.rows())
        self.behavior_tab.save_work()
        super().closeEvent(event)
