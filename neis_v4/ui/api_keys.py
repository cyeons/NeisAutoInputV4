from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neis_v4.ai.model_catalog import PROVIDERS, fetch_latest_models, fetched_model_ids, provider_spec
from neis_v4.secrets import (
    BUNDLED_KEY_EXPIRES,
    BUNDLED_KEY_LIMITS,
    BUNDLED_KEY_PROVIDER,
    EXPIRY_WARNING_DAYS,
    SecretStore,
    bundled_days_left,
    bundled_key_expired,
)
from neis_v4.storage import Storage
from neis_v4.ui.theme import COLORS, icon


def choose_models(parent, provider: str, candidates: list[str], checked: list[str]) -> list[str] | None:
    """불러온 모델 중 목록에 넣을 모델을 체크해서 고릅니다. 취소하면 None을 돌려줍니다."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"{provider} 모델 고르기")
    dialog.setMinimumWidth(420)
    layout = QVBoxLayout(dialog)
    guide = QLabel(
        "모델 선택 목록에 넣을 모델을 체크하세요. 최신 모델이 위에 있습니다.\n"
        "이 프로그램에서 아직 시험하지 않은 모델이라 결과가 다를 수 있습니다."
    )
    guide.setWordWrap(True)
    model_list = QListWidget()
    for model_id in candidates:
        item = QListWidgetItem(model_id)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if model_id in checked else Qt.Unchecked)
        model_list.addItem(item)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton("취소")
    cancel.setProperty("variant", "secondary")
    cancel.clicked.connect(dialog.reject)
    save = QPushButton("목록에 넣기")
    save.setProperty("variant", "primary")
    save.clicked.connect(dialog.accept)
    buttons.addWidget(cancel)
    buttons.addWidget(save)
    layout.addWidget(guide)
    layout.addWidget(model_list, 1)
    layout.addLayout(buttons)
    if dialog.exec() != QDialog.Accepted:
        return None
    items = (model_list.item(index) for index in range(model_list.count()))
    return [item.text() for item in items if item.checkState() == Qt.Checked]


class ApiKeyManagerDialog(QDialog):
    keys_changed = Signal()

    def __init__(self, secrets: SecretStore, parent=None) -> None:
        super().__init__(parent)
        self.secrets = secrets
        self.setWindowTitle("AI 서비스 API 키 관리")
        self.setMinimumWidth(560)
        self._statuses: dict[str, QLabel] = {}
        self._entries: dict[str, QLineEdit] = {}
        self._delete_buttons: dict[str, QPushButton] = {}
        self._fetch_buttons: dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)
        title = QLabel("API 키 관리")
        title.setObjectName("PageTitle")
        detail = QLabel(
            "API 키는 서비스별로 나누어 Windows 보안 저장소에 보관합니다. "
            f"{BUNDLED_KEY_PROVIDER}는 기본 키가 들어 있어 {BUNDLED_KEY_EXPIRES.isoformat()}까지 "
            "키를 등록하지 않아도 바로 쓸 수 있습니다. 내 키를 등록하면 내 키를 먼저 씁니다.\n"
            f"기본 키 사용 한도: {BUNDLED_KEY_LIMITS} (이 프로그램을 쓰는 모든 선생님이 함께 씀). "
            "한도를 넘으면 1분쯤 뒤에 다시 시도하면 됩니다."
        )
        detail.setObjectName("PageSubtitle")
        detail.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(detail)

        for provider in PROVIDERS:
            root.addWidget(self._provider_card(provider.provider_id))

        note = QLabel("저장된 키의 원문은 다시 표시되지 않습니다. 새 값을 입력하면 기존 키를 변경합니다.")
        note.setObjectName("MutedLabel")
        note.setWordWrap(True)
        root.addWidget(note)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("닫기")
        close_button.setProperty("variant", "secondary")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        root.addLayout(close_row)
        self._refresh()

    def _provider_card(self, provider: str) -> QWidget:
        card = QFrame()
        card.setProperty("role", "Panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        name = QLabel(provider)
        name.setObjectName("SectionTitle")
        status = QLabel()
        self._statuses[provider] = status
        header.addWidget(name)
        header.addStretch(1)
        key_url = provider_spec(provider).key_url
        if key_url:
            open_page = QPushButton("키 발급 페이지 열기")
            open_page.setProperty("variant", "ghost")
            open_page.setToolTip(f"웹 브라우저에서 엽니다: {key_url}")
            open_page.clicked.connect(lambda _checked=False, url=key_url: QDesktopServices.openUrl(QUrl(url)))
            header.addWidget(open_page)
        if provider != BUNDLED_KEY_PROVIDER:
            fetch = QPushButton("최신 모델 불러오기")
            fetch.setProperty("variant", "ghost")
            fetch.setToolTip("이 키로 쓸 수 있는 최신 모델을 받아, 고른 모델만 모델 선택 목록에 넣습니다.")
            fetch.clicked.connect(lambda _checked=False, selected=provider: self._fetch_models(selected))
            self._fetch_buttons[provider] = fetch
            header.addWidget(fetch)
        header.addWidget(status)
        layout.addLayout(header)

        row = QHBoxLayout()
        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.Password)
        entry.setPlaceholderText(
            f"내 {provider} API 키 입력 (비워 두면 기본 키 사용)"
            if provider == BUNDLED_KEY_PROVIDER
            else f"새 {provider} API 키 입력"
        )
        entry.returnPressed.connect(lambda selected=provider: self._save(selected))
        self._entries[provider] = entry
        save = QPushButton("등록/변경")
        save.setProperty("variant", "primary")
        save.setIcon(icon("save", "#FFFFFF"))
        save.clicked.connect(lambda _checked=False, selected=provider: self._save(selected))
        delete = QPushButton("삭제")
        delete.setProperty("variant", "destructive")
        delete.clicked.connect(lambda _checked=False, selected=provider: self._delete(selected))
        self._delete_buttons[provider] = delete
        row.addWidget(entry, 1)
        row.addWidget(save)
        row.addWidget(delete)
        layout.addLayout(row)
        return card

    def _save(self, provider: str) -> None:
        value = self._entries[provider].text().strip()
        if not value:
            QMessageBox.information(self, "API 키 입력", f"{provider} API 키를 입력하세요.")
            return
        if not self.secrets.set_api_key(provider, value):
            QMessageBox.warning(self, "저장 실패", "Windows 보안 저장소에 API 키를 저장하지 못했습니다.")
            return
        self._entries[provider].clear()
        self._refresh()
        self.keys_changed.emit()

    def _delete(self, provider: str) -> None:
        if QMessageBox.question(
            self,
            "API 키 삭제",
            f"저장된 {provider} API 키를 삭제할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        if not self.secrets.delete_api_key(provider):
            QMessageBox.warning(self, "삭제 실패", "Windows 보안 저장소에서 API 키를 삭제하지 못했습니다.")
            return
        self._refresh()
        self.keys_changed.emit()

    def _fetch_models(self, provider: str) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            model_list = fetch_latest_models(provider, self.secrets.get_api_key(provider))
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(
                self,
                "모델 불러오기 실패",
                f"{provider} 모델 목록을 받지 못했습니다. 키가 맞는지, 인터넷이 연결되어 있는지 확인하세요.\n\n"
                f"{str(exc)[:300]}",
            )
            return
        QApplication.restoreOverrideCursor()
        builtin = {item.model_id for item in provider_spec(provider).models}
        candidates = [model_id for model_id in model_list if model_id not in builtin]
        if not candidates:
            QMessageBox.information(self, "모델 불러오기", f"{provider}에 새로 추가할 모델이 없습니다.")
            return
        chosen = choose_models(self, provider, candidates, fetched_model_ids(provider))
        if chosen is None:
            return
        Storage().save_fetched_models(provider, chosen)
        self.keys_changed.emit()

    def _refresh(self) -> None:
        for provider in self._statuses:
            user_key = bool(self.secrets.get_user_api_key(provider))
            bundled = self.secrets.uses_bundled_key(provider)
            status = self._statuses[provider]
            if user_key:
                status.setText("등록됨")
            elif bundled and (days := bundled_days_left()) <= EXPIRY_WARNING_DAYS:
                status.setText("기본 키 · 오늘까지" if days == 0 else f"기본 키 · {days}일 뒤 끝남")
            elif bundled:
                status.setText(f"기본 키 사용 중 ({BUNDLED_KEY_EXPIRES.isoformat()}까지)")
            elif provider == BUNDLED_KEY_PROVIDER and bundled_key_expired():
                status.setText(f"기본 키 기간 끝남 ({BUNDLED_KEY_EXPIRES.isoformat()})")
            else:
                status.setText("미등록")
            status.setProperty("badge", "success" if user_key or bundled else "warning")
            status.style().unpolish(status)
            status.style().polish(status)
            # 삭제는 직접 등록한 키만 지웁니다. 기본 키는 지울 수 없습니다.
            self._delete_buttons[provider].setEnabled(user_key)
            if provider in self._fetch_buttons:
                self._fetch_buttons[provider].setEnabled(user_key)
