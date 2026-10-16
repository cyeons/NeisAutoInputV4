from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neis_v4.ai.model_catalog import PROVIDERS
from neis_v4.secrets import SecretStore
from neis_v4.ui.theme import COLORS, icon


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

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)
        title = QLabel("API 키 관리")
        title.setObjectName("PageTitle")
        detail = QLabel("OpenAI와 Gemini 키는 서로 분리해 Windows 보안 저장소에 보관합니다.")
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
        header.addWidget(status)
        layout.addLayout(header)

        row = QHBoxLayout()
        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.Password)
        entry.setPlaceholderText(f"새 {provider} API 키 입력")
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

    def _refresh(self) -> None:
        for provider in self._statuses:
            configured = self.secrets.has_api_key(provider)
            status = self._statuses[provider]
            status.setText("등록됨" if configured else "미등록")
            status.setProperty("badge", "success" if configured else "warning")
            status.style().unpolish(status)
            status.style().polish(status)
            self._delete_buttons[provider].setEnabled(configured)
