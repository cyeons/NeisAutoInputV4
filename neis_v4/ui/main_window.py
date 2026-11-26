from __future__ import annotations

import html
import threading

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from neis_v4 import APP_DISPLAY_NAME, APP_VERSION_LABEL, __version__
from neis_v4.models import AppSettings
from neis_v4.roster import StudentRoster
from neis_v4.secrets import SecretStore
from neis_v4.storage import Storage, resource_path
from neis_v4.ui.ai_tab import AiTab
from neis_v4.ui.behavior_tab import BehaviorTab
from neis_v4.ui.neis_tab import NeisTab
from neis_v4.ui.settings_tab import SettingsTab
from neis_v4.ui.theme import COLORS, STYLE_SHEET, icon
from neis_v4.updates import fetch_latest_release, is_newer


class MainWindow(QMainWindow):
    # 새 버전을 찾으면 (태그, 내려받기 페이지 주소)를 보냅니다. 확인은 뒤에서 하고 결과만 화면으로 넘깁니다.
    update_found = Signal(str, str)

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
        self.ai_tab.comment_sink = self.neis_tab.receive_ai_comments
        self.behavior_tab.comments_ready.connect(self.neis_tab.put_comments_by_id)
        self.ai_tab.auto_input_requested.connect(self._input_ai_comments)
        self.behavior_tab.auto_input_requested.connect(self._input_behavior_comments)
        for tab in (self.ai_tab, self.behavior_tab):
            tab.stop_input_requested.connect(self.neis_tab.stop_or_cancel)
            self.neis_tab.macro_status_changed.connect(tab.set_macro_status)

        self.update_found.connect(self._on_update_found)

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
        self.version_label = version
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

    def check_for_updates(self) -> None:
        """새 버전이 있는지 뒤에서 확인합니다. 인터넷이 안 되면 아무것도 띄우지 않습니다."""

        def check() -> None:
            try:
                tag, url = fetch_latest_release()
                if is_newer(tag, __version__):
                    self.update_found.emit(tag, url)
            except Exception:
                pass  # 오프라인·학교망 차단·창을 먼저 닫은 경우 모두 조용히 넘어갑니다.

        threading.Thread(target=check, daemon=True).start()

    def _on_update_found(self, tag: str, url: str) -> None:
        self.version_label.setText(
            f'{APP_VERSION_LABEL}<br><a href="{html.escape(url, quote=True)}">새 버전 {html.escape(tag)} 받기</a>'
        )
        self.version_label.setOpenExternalLinks(True)
        self.version_label.setToolTip("누르면 내려받기 페이지가 열립니다.")
        if self.settings.notified_update_version == tag:
            return  # 안내 창은 버전마다 한 번만 띄웁니다.
        if self.neis_tab.input_state() != "idle":
            return  # 자동 입력 중에 창이 뜨면 붙여넣기가 그 창으로 갑니다. 다음 실행 때 알립니다.
        self.settings.notified_update_version = tag
        self.save_settings()
        box = QMessageBox(
            QMessageBox.Information,
            "새 버전이 나왔습니다",
            f"새 버전 {tag}이(가) 나왔습니다. 지금 쓰는 버전은 {APP_VERSION_LABEL}입니다.\n\n"
            "내려받기 페이지에서 새 실행 파일을 받아 쓰세요. 작업 내용과 설정, API 키는 그대로 남습니다.\n"
            "왼쪽 아래 '새 버전 받기'를 눌러도 언제든 페이지를 열 수 있습니다.",
            parent=self,
        )
        open_page = box.addButton("내려받기 페이지 열기", QMessageBox.AcceptRole)
        box.addButton("나중에", QMessageBox.RejectRole)
        box.setDefaultButton(open_page)
        box.exec()
        if box.clickedButton() is open_page:
            QDesktopServices.openUrl(QUrl(url))

    def apply_settings(self) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.settings.always_on_top)
        self.show()
        self.ai_tab.refresh_from_settings()
        self.behavior_tab.refresh_from_settings()
        self.neis_tab.refresh_lengths()
        self.save_settings()

    def _on_runtime_settings_changed(self) -> None:
        self.settings_tab.refresh_from_settings()
        self.save_settings()

    def _input_ai_comments(self, comments: list[str], tab_count: int) -> None:
        """결과 칸에 보이는 그대로 1번 행부터 덮어쓰고(Ctrl+Z로 되돌리기 가능) 그 행들만 입력합니다."""
        if self.neis_tab.input_state() != "idle":
            return
        self.neis_tab.put_comments(comments)
        self.neis_tab.start_macro(self.neis_tab.rows()[: len(comments)], tab_count)

    def _input_behavior_comments(self, drafts: dict[str, str], rows: list, tab_count: int) -> None:
        if self.neis_tab.input_state() != "idle":
            return
        self.neis_tab.put_comments_by_id(drafts)
        self.neis_tab.start_macro(rows, tab_count)

    def _refresh_api_keys(self) -> None:
        self.ai_tab.refresh_api_keys()
        self.behavior_tab.refresh_api_keys()
        self.settings_tab.refresh_api_keys()

    def save_settings(self) -> None:
        self.storage.save_settings(self.settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        # AI 요청은 중간에 끊을 수 없으므로 끝날 때까지 닫기를 미룹니다.
        if self.ai_tab.is_busy() or self.behavior_tab.worker:
            QMessageBox.information(
                self,
                "AI 생성 중",
                "AI 문장을 생성하는 중입니다. 취소한 요청도 응답이 올 때까지 기다립니다.\n생성이 끝난 뒤 다시 닫아 주세요.\n"
                "행동발달은 '생성 중지'를 누르면 이미 보낸 묶음까지만 받고 멈춥니다.",
            )
            event.ignore()
            return
        runner = self.neis_tab.runner
        if runner:
            runner.stop()
            runner.wait(5000)

        # 하나가 실패해도 나머지는 저장되도록 따로 시도합니다.
        failures = []
        for label, save in (
            ("환경 설정", self.save_settings),
            ("NEIS 입력 표 (data.csv)", lambda: self.storage.save_students(self.neis_tab.rows())),
            ("행동발달 작업", self.behavior_tab.save_work),
        ):
            try:
                save()
            except Exception as exc:
                failures.append(f"· {label}: {exc}")
        if failures:
            answer = QMessageBox.warning(
                self,
                "저장 실패",
                "다음 항목을 저장하지 못했습니다.\n"
                "엑셀 등 다른 프로그램에서 파일을 열어 두었다면 닫고 다시 시도하세요.\n\n"
                + "\n".join(failures)
                + "\n\n저장하지 않고 닫을까요?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        super().closeEvent(event)
