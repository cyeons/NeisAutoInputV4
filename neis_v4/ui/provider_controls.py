from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QWidget

from neis_v4.ai.model_catalog import PROVIDERS, normalize_model, provider_spec
from neis_v4.secrets import SecretStore
from neis_v4.ui.widgets import ArrowComboBox, ChoiceSegmentedControl


class ProviderSelector(ChoiceSegmentedControl):
    def __init__(self, parent=None) -> None:
        super().__init__([(item.label, item.provider_id) for item in PROVIDERS], parent)

    def refresh_availability(self, secrets: SecretStore, preferred: str) -> str:
        available = [
            item.provider_id
            for item in PROVIDERS
            if bool(secrets.get_api_key(item.provider_id))
        ]
        for provider in (item.provider_id for item in PROVIDERS):
            self.setOptionEnabled(provider, provider in available, locked_label=True)
        selected = preferred if preferred in available else (available[0] if available else "")
        if selected:
            self.setValue(selected)
        else:
            self.clear()
        return selected


class ModelSelector(ArrowComboBox):
    modelChanged = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(False)
        self.setMinimumContentsLength(16)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.currentIndexChanged.connect(self._emit_model)

    def set_provider(self, provider: str, selected_model_id: str) -> str:
        selected_model_id = normalize_model(provider, selected_model_id)
        self.blockSignals(True)
        self.clear()
        for model in provider_spec(provider).models:
            self.addItem(model.display_name, model.model_id)
            index = self.count() - 1
            self.setItemData(index, model.model_id, 3)
            self.setItemData(index, model.description, 5)
        index = self.findData(selected_model_id)
        self.setCurrentIndex(index if index >= 0 else 0)
        self.blockSignals(False)
        return self.model_id()

    def model_id(self) -> str:
        return str(self.currentData() or "")

    def _emit_model(self) -> None:
        if self.model_id():
            self.modelChanged.emit(self.model_id())
