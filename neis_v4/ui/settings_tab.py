from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from neis_v4.models import AppSettings
from neis_v4.secrets import SecretStore
from neis_v4.ui.api_keys import ApiKeyManagerDialog
from neis_v4.ui.provider_controls import ModelSelector, ProviderSelector
from neis_v4.ui.theme import icon
from neis_v4.ui.widgets import ToggleSwitch


class ProviderModelEditor(QFrame):
    changed = Signal()

    def __init__(self, title: str, secrets: SecretStore, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "SubPanel")
        self.secrets = secrets
        self.models = {"Gemini": "gemini-3.5-flash", "OpenAI": "gpt-5.4-mini"}
        self.provider = ProviderSelector()
        self.model = ModelSelector()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        row = QHBoxLayout()
        row.addWidget(self.provider, 1)
        row.addWidget(self.model, 2)
        layout.addLayout(row)
        self.provider.valueChanged.connect(self._provider_changed)
        self.model.modelChanged.connect(self._model_changed)

    def refresh(self, provider: str, models: dict[str, str]) -> None:
        self.models.update(models)
        selected = self.provider.refresh_availability(self.secrets, provider)
        if selected:
            self.model.set_provider(selected, self.models[selected])
        else:
            self.model.clear()
        self.model.setEnabled(bool(selected))

    def value(self) -> str:
        return self.provider.value()

    def _provider_changed(self, provider: str) -> None:
        if not provider:
            return
        self.model.set_provider(provider, self.models[provider])
        self.changed.emit()

    def _model_changed(self, model_id: str) -> None:
        provider = self.provider.value()
        if provider:
            self.models[provider] = model_id
            self.changed.emit()


class SettingsTab(QWidget):
    settings_changed = Signal()
    api_keys_changed = Signal()

    def __init__(self, settings: AppSettings, secrets: SecretStore, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.secrets = secrets
        self._loading = False

        self.always_on_top = ToggleSwitch(settings.always_on_top)
        self.use_windows_trust_store = ToggleSwitch(settings.use_windows_trust_store)
        self.ai_defaults = ProviderModelEditor("AI 평어 기본값", secrets)
        self.behavior_defaults = ProviderModelEditor("행동발달 기본값", secrets)

        self.secure_status = QLabel()
        self.secure_status.setWordWrap(True)
        self.key_button = QPushButton("API 키 관리")
        self.key_button.setProperty("variant", "secondary")
        self.key_button.setIcon(icon("key-round"))
        self.save_button = QPushButton("설정 저장")
        self.save_button.setProperty("variant", "primary")
        self.save_button.setIcon(icon("save", "#FFFFFF"))
        self.save_button.setEnabled(False)
        self.save_status = QLabel("저장됨")
        self.save_status.setObjectName("MutedLabel")

        self._build_layout()
        self.save_button.clicked.connect(self.apply_to_settings)
        self.key_button.clicked.connect(self._manage_api_keys)
        self._connect_dirty_state()
        self.refresh_from_settings()

    def _build_layout(self) -> None:
        self.setObjectName("AppPage")
        header = QVBoxLayout()
        title = QLabel("환경 설정")
        title.setObjectName("PageTitle")
        subtitle = QLabel("AI 서비스 기본값, API 키와 창 동작을 관리합니다.")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setObjectName("SettingsViewport")
        canvas = QWidget()
        canvas.setObjectName("AppPage")
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)

        content = QFrame()
        content.setProperty("role", "Panel")
        content.setMinimumWidth(650)
        content.setMaximumWidth(820)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        general_title = QLabel("일반")
        general_title.setObjectName("SectionTitle")
        general = QFrame()
        general.setProperty("role", "SubPanel")
        general_layout = QVBoxLayout(general)
        always_row = QHBoxLayout()
        always_row.addWidget(QLabel("창을 항상 위에 고정"))
        always_row.addWidget(self.always_on_top)
        always_row.addStretch(1)
        general_layout.addLayout(always_row)
        cert_row = QHBoxLayout()
        cert_label = QLabel("Windows 인증서 저장소 사용")
        cert_help = QLabel("교육청·기관 보안망 SSL 인증서 오류 완화용 · 변경 후 재시작 필요")
        cert_help.setObjectName("MutedLabel")
        cert_help.setWordWrap(True)
        cert_row.addWidget(cert_label)
        cert_row.addWidget(self.use_windows_trust_store)
        cert_row.addWidget(cert_help, 1)
        general_layout.addLayout(cert_row)
        layout.addWidget(general_title)
        layout.addWidget(general)

        ai_title = QLabel("AI 서비스 기본값")
        ai_title.setObjectName("SectionTitle")
        layout.addWidget(ai_title)
        layout.addWidget(self.ai_defaults)
        layout.addWidget(self.behavior_defaults)

        security_title = QLabel("API 키 보안 저장소")
        security_title.setObjectName("SectionTitle")
        security = QFrame()
        security.setProperty("role", "SubPanel")
        security_layout = QHBoxLayout(security)
        security_layout.addWidget(self.secure_status, 1)
        security_layout.addWidget(self.key_button)
        layout.addWidget(security_title)
        layout.addWidget(security)

        actions = QHBoxLayout()
        actions.addWidget(self.save_status)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        canvas_layout.addStretch(1)
        canvas_layout.addWidget(content, 0, Qt.AlignTop)
        canvas_layout.addStretch(1)
        scroll.setWidget(canvas)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(scroll, 1)

    def _connect_dirty_state(self) -> None:
        self.always_on_top.toggled.connect(self._mark_dirty)
        self.use_windows_trust_store.toggled.connect(self._mark_dirty)
        self.ai_defaults.changed.connect(self._mark_dirty)
        self.behavior_defaults.changed.connect(self._mark_dirty)

    def refresh_from_settings(self) -> None:
        self._loading = True
        try:
            self.always_on_top.setChecked(self.settings.always_on_top)
            self.use_windows_trust_store.setChecked(
                self.settings.use_windows_trust_store
            )
            self.ai_defaults.refresh(
                self.settings.ai_provider,
                {
                    "Gemini": self.settings.gemini_model,
                    "OpenAI": self.settings.openai_model,
                },
            )
            self.behavior_defaults.refresh(
                self.settings.behavior_provider,
                {
                    "Gemini": self.settings.behavior_gemini_model,
                    "OpenAI": self.settings.behavior_openai_model,
                },
            )
            self._refresh_key_status()
        finally:
            self._loading = False
        self.save_button.setEnabled(False)
        self.save_status.setText("저장됨")

    def refresh_api_keys(self) -> None:
        self.refresh_from_settings()

    def _refresh_key_status(self) -> None:
        registered = self.secrets.registered_providers()
        if registered:
            text = " · ".join(f"{provider} 등록됨" for provider in registered)
            badge = "success"
        else:
            text = "등록된 API 키가 없습니다."
            badge = "warning"
        self.secure_status.setText(text)
        self.secure_status.setProperty("badge", badge)
        self.secure_status.style().unpolish(self.secure_status)
        self.secure_status.style().polish(self.secure_status)

    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        self.save_button.setEnabled(True)
        self.save_status.setText("저장되지 않은 변경사항")

    def _manage_api_keys(self) -> None:
        dialog = ApiKeyManagerDialog(self.secrets, self)
        dialog.keys_changed.connect(self._on_api_keys_changed)
        dialog.exec()
        self.refresh_api_keys()

    def _on_api_keys_changed(self) -> None:
        self.refresh_api_keys()
        self.api_keys_changed.emit()

    def apply_to_settings(self) -> None:
        self.settings.always_on_top = self.always_on_top.isChecked()
        self.settings.use_windows_trust_store = self.use_windows_trust_store.isChecked()
        if self.ai_defaults.value():
            self.settings.ai_provider = self.ai_defaults.value()
        self.settings.gemini_model = self.ai_defaults.models["Gemini"]
        self.settings.openai_model = self.ai_defaults.models["OpenAI"]
        if self.behavior_defaults.value():
            self.settings.behavior_provider = self.behavior_defaults.value()
        self.settings.behavior_gemini_model = self.behavior_defaults.models["Gemini"]
        self.settings.behavior_openai_model = self.behavior_defaults.models["OpenAI"]
        self.settings_changed.emit()
        self.save_button.setEnabled(False)
        self.save_status.setText("저장됨")
