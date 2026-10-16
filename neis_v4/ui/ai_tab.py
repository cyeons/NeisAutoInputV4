from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from neis_v4.ai import GeminiProvider, OpenAIProvider
from neis_v4.ai.base import AIProviderError
from neis_v4.models import AchievementStandard, AppSettings, GenerationRequest, GenerationResult
from neis_v4.secrets import SecretStore
from neis_v4.storage import Storage
from neis_v4.ui.api_keys import ApiKeyManagerDialog
from neis_v4.ui.provider_controls import ModelSelector, ProviderSelector
from neis_v4.ui.theme import COLORS, icon
from neis_v4.ui.widgets import ChoiceSegmentedControl, NumberStepper, set_faded_text


class GenerationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, request: GenerationRequest, api_key: str, parent=None) -> None:
        super().__init__(parent)
        self.request = request
        self.api_key = api_key

    def run(self) -> None:
        try:
            provider = (
                GeminiProvider(self.api_key)
                if self.request.provider == "Gemini"
                else OpenAIProvider(self.api_key)
            )
            self.succeeded.emit(provider.generate_comments(self.request))
        except AIProviderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"생성 중 오류가 발생했습니다: {exc}")


class StandardCard(QFrame):
    toggled = Signal()

    def __init__(self, standard: AchievementStandard, parent=None) -> None:
        super().__init__(parent)
        self.standard = standard
        self.setProperty("role", "SelectableCard")
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        self.check = QCheckBox()
        self.label = QLabel(f"{standard.code}  {standard.description}")
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.check, 0, Qt.AlignTop)
        layout.addWidget(self.label, 1)
        self.check.toggled.connect(self._sync_selected)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.check.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def _sync_selected(self) -> None:
        self.setProperty("selected", self.check.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)
        self.toggled.emit()

    def matches(self, query: str) -> bool:
        searchable = f"{self.standard.code} {self.standard.description} {self.standard.domain}".lower()
        return query.lower() in searchable


class DomainSection(QWidget):
    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self.cards: list[StandardCard] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        header = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setText(f"▾  {name}")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setProperty("domainHeader", True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.select_all = QPushButton("영역 전체 선택")
        self.select_all.setProperty("variant", "ghost")
        header.addWidget(self.toggle, 1)
        header.addWidget(self.select_all)
        root.addLayout(header)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        root.addWidget(self.body)
        self.toggle.toggled.connect(self._toggle_body)
        self.select_all.clicked.connect(self._toggle_all)

    def add_card(self, card: StandardCard) -> None:
        self.cards.append(card)
        self.body_layout.addWidget(card)

    def _toggle_body(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        name = self.toggle.text().lstrip("▾▸ ").strip()
        self.toggle.setText(f"{'▾' if expanded else '▸'}  {name}")

    def _toggle_all(self) -> None:
        visible = [card for card in self.cards if card.isVisible()]
        should_select = any(not card.check.isChecked() for card in visible)
        for card in visible:
            card.check.setChecked(should_select)


class AiTab(QWidget):
    comments_ready = Signal(list)
    settings_changed = Signal()
    api_keys_changed = Signal()

    def __init__(self, storage: Storage, settings: AppSettings, secrets: SecretStore, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.secrets = secrets
        self.worker: GenerationWorker | None = None
        self.achievement_data = self.storage.load_achievement_data()
        self.standard_cards: list[StandardCard] = []
        self.standard_checks: list[QCheckBox] = []
        self.domain_sections: list[DomainSection] = []
        self.subject_buttons: dict[str, QPushButton] = {}
        self.selected_standards: dict[str, AchievementStandard] = {}
        self.last_comments: list[str] = []

        self.provider = ProviderSelector()
        self.model = ModelSelector()
        grades = [str(item.get("grade", "")) for item in self.achievement_data.get("grades", [])]
        self.grade = ChoiceSegmentedControl([(value, value) for value in grades])
        self.current_subject = ""
        self.subject_bar = QWidget()
        self.subject_layout = QHBoxLayout(self.subject_bar)
        self.subject_layout.setContentsMargins(2, 2, 2, 2)
        self.subject_layout.setSpacing(6)
        self.subject_layout.addStretch(1)

        self.student_count = NumberStepper(1, 200, 1)
        self.student_count.setValue(settings.student_count)
        self.sentence_count = ChoiceSegmentedControl(
            [(f"{count}문장", str(count)) for count in (1, 2, 3, 4)]
        )
        self.sentence_count.setValue("3")
        self.search = QLineEdit()
        self.search.setPlaceholderText("성취기준 검색")
        self.clear_selection = QPushButton("전체 해제")
        self.clear_selection.setProperty("variant", "ghost")
        self.selected_codes = QLabel("선택된 성취기준 없음")
        self.selected_codes.setObjectName("MutedLabel")
        self.selected_codes.setWordWrap(True)
        self.selected_chip_bar = QWidget()
        self.selected_chip_layout = QHBoxLayout(self.selected_chip_bar)
        self.selected_chip_layout.setContentsMargins(2, 2, 2, 2)
        self.selected_chip_layout.setSpacing(6)
        self.selected_chip_layout.addStretch(1)

        self.standards_box = QWidget()
        self.standards_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.standards_layout = QVBoxLayout(self.standards_box)
        self.standards_layout.setContentsMargins(6, 6, 6, 6)
        self.standards_layout.setSpacing(10)

        self.result = QTextEdit()
        self.result.setPlaceholderText("생성된 교과 평어가 여기에 표시됩니다.")
        self.custom_prompt_toggle = QPushButton("▸ 사용자 프롬프트")
        self.custom_prompt_toggle.setCheckable(True)
        self.custom_prompt_toggle.setProperty("variant", "ghost")
        self.custom_prompt_toggle.setToolTip("기본 프롬프트 아래에 추가할 지시를 작성합니다.")
        self.custom_prompt = QTextEdit()
        self.custom_prompt.setPlaceholderText("예: 더 간결하게, 협력 태도를 강조, 반복 표현 줄이기")
        self.custom_prompt.setFixedHeight(92)
        self.custom_prompt.setPlainText(settings.ai_custom_prompt)
        self.custom_prompt.setVisible(False)
        self.generate_button = QPushButton("평어 생성")
        self.generate_button.setProperty("variant", "primary")
        self.generate_button.setIcon(icon("sparkles", "#FFFFFF"))
        self.copy_button = QPushButton("결과 복사")
        self.copy_button.setProperty("variant", "secondary")
        self.copy_button.setIcon(icon("copy", COLORS["muted"]))
        self.copy_button.setEnabled(False)
        self.apply_button = QPushButton("NEIS 표에 넣기")
        self.apply_button.setProperty("variant", "secondary")
        self.apply_button.setIcon(icon("arrow-right", COLORS["muted"]))
        self.apply_button.setEnabled(False)
        self.key_button = QPushButton("API 키 관리")
        self.key_button.setProperty("variant", "secondary")
        self.key_button.setIcon(icon("key-round", COLORS["muted"]))
        self.key_status = QLabel()
        self.selection_status = QLabel("성취기준 0개")
        self.selection_status.setObjectName("MutedLabel")
        self.status = QLabel("성취기준을 선택한 뒤 평어를 생성하세요.")
        self.status.setObjectName("MutedLabel")
        self.status.setWordWrap(True)

        self.result_stack = QStackedWidget()
        self.empty_state = self._build_empty_state()
        self.loading_state = self._build_loading_state()
        self.result_stack.addWidget(self.empty_state)
        self.result_stack.addWidget(self.loading_state)
        self.result_stack.addWidget(self.result)

        self._build_layout()
        self._connect()
        if grades:
            self.grade.setValue(grades[0])
            self._load_subjects(grades[0])
        self.refresh_from_settings()

    def _build_layout(self) -> None:
        self.setObjectName("AppPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)

        title = QLabel("AI 교과 평어 생성")
        title.setObjectName("PageTitle")
        subtitle = QLabel("성취기준과 학생 수를 기준으로 교과 평어를 생성하고 NEIS 입력 표로 보냅니다.")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([620, 700])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)
        root.addWidget(self._build_action_bar())

    def _build_left(self) -> QWidget:
        left = QWidget()
        left.setMinimumWidth(470)
        left.setMaximumWidth(680)
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        setup = QFrame()
        setup.setProperty("role", "Panel")
        setup_layout = QVBoxLayout(setup)
        setup_layout.setContentsMargins(14, 12, 14, 12)
        header = QHBoxLayout()
        heading = QLabel("1. AI와 생성 범위")
        heading.setObjectName("SectionTitle")
        header.addWidget(heading)
        header.addStretch(1)
        header.addWidget(self.key_status)
        header.addWidget(self.key_button)
        setup_layout.addLayout(header)
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("AI 서비스"))
        provider_row.addWidget(self.provider, 1)
        setup_layout.addLayout(provider_row)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("사용 모델"))
        model_row.addWidget(self.model, 1)
        setup_layout.addLayout(model_row)

        counts = QHBoxLayout()
        counts.addWidget(QLabel("학생 수"))
        counts.addWidget(self.student_count)
        for count in (10, 15, 20):
            button = QPushButton(str(count))
            button.setProperty("variant", "ghost")
            button.clicked.connect(lambda _checked=False, value=count: self.student_count.setValue(value))
            counts.addWidget(button)
        counts.addStretch(1)
        setup_layout.addLayout(counts)
        sentences = QHBoxLayout()
        sentences.addWidget(QLabel("학생당 문장 수"))
        sentences.addWidget(self.sentence_count, 1)
        setup_layout.addLayout(sentences)
        setup_layout.addWidget(self.custom_prompt_toggle)
        custom_note = QLabel("기존 작성 규칙과 충돌하지 않는 범위에서만 반영됩니다.")
        custom_note.setObjectName("MutedLabel")
        custom_note.setWordWrap(True)
        self.custom_prompt_note = custom_note
        custom_note.setVisible(False)
        setup_layout.addWidget(custom_note)
        setup_layout.addWidget(self.custom_prompt)
        layout.addWidget(setup)

        standards = QFrame()
        standards.setProperty("role", "Panel")
        standards_layout = QVBoxLayout(standards)
        standards_layout.setContentsMargins(14, 12, 14, 12)
        standards_layout.setSpacing(8)
        heading = QLabel("2. 성취기준 선택")
        heading.setObjectName("SectionTitle")
        standards_layout.addWidget(heading)
        standards_layout.addWidget(self.grade)
        subject_scroll = QScrollArea()
        subject_scroll.setObjectName("TabScroll")
        subject_scroll.setWidgetResizable(True)
        subject_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        subject_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        subject_scroll.setFixedHeight(48)
        subject_scroll.setWidget(self.subject_bar)
        standards_layout.addWidget(subject_scroll)
        tools = QHBoxLayout()
        tools.addWidget(self.search, 1)
        tools.addWidget(self.clear_selection)
        standards_layout.addLayout(tools)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.standards_box)
        standards_layout.addWidget(scroll, 1)
        standards_layout.addWidget(self.selected_codes)
        self.selected_chip_scroll = QScrollArea()
        self.selected_chip_scroll.setObjectName("TabScroll")
        self.selected_chip_scroll.setWidgetResizable(True)
        self.selected_chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.selected_chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.selected_chip_scroll.setFixedHeight(42)
        self.selected_chip_scroll.setWidget(self.selected_chip_bar)
        standards_layout.addWidget(self.selected_chip_scroll)
        layout.addWidget(standards, 1)
        return left

    def _build_right(self) -> QWidget:
        right = QWidget()
        right.setMinimumWidth(360)
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("3. 생성 결과")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(self.result_stack, 1)
        return right

    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("role", "Dock")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self.selection_status)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.generate_button)
        return bar

    def _build_empty_state(self) -> QWidget:
        page = QFrame()
        page.setProperty("role", "Panel")
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        image = QLabel()
        image.setPixmap(icon("sparkles", COLORS["blue"], 34).pixmap(34, 34))
        image.setAlignment(Qt.AlignCenter)
        title = QLabel("생성된 평어가 여기에 표시됩니다")
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignCenter)
        detail = QLabel("학년과 과목을 고른 뒤 성취기준 카드를 선택하세요.")
        detail.setObjectName("MutedLabel")
        detail.setAlignment(Qt.AlignCenter)
        focus = QPushButton("성취기준 찾기")
        focus.setProperty("variant", "secondary")
        focus.clicked.connect(self.search.setFocus)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(focus)
        row.addStretch(1)
        layout.addWidget(image)
        layout.addSpacing(8)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _build_loading_state(self) -> QWidget:
        page = QFrame()
        page.setProperty("role", "Panel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(80, 24, 80, 24)
        layout.addStretch(1)
        title = QLabel("교과 평어를 생성하고 있습니다")
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignCenter)
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(title)
        layout.addSpacing(12)
        layout.addWidget(progress)
        layout.addStretch(1)
        return page

    def _connect(self) -> None:
        self.provider.valueChanged.connect(self._on_provider_changed)
        self.model.modelChanged.connect(self._on_model_changed)
        self.grade.valueChanged.connect(self._load_subjects)
        self.search.textChanged.connect(self._filter_standards)
        self.clear_selection.clicked.connect(self._clear_standard_selection)
        self.key_button.clicked.connect(self._manage_api_keys)
        self.generate_button.clicked.connect(self._generate)
        self.copy_button.clicked.connect(self._copy_result)
        self.apply_button.clicked.connect(self._apply_result)
        self.student_count.valueChanged.connect(lambda _value: self._update_selection_status())
        self.custom_prompt_toggle.toggled.connect(self._toggle_custom_prompt)
        self.custom_prompt.textChanged.connect(self._on_custom_prompt_changed)

    def refresh_from_settings(self) -> None:
        selected = self.provider.refresh_availability(self.secrets, self.settings.ai_provider)
        if selected:
            self.settings.ai_provider = selected
            model = self.settings.gemini_model if selected == "Gemini" else self.settings.openai_model
            self.model.set_provider(selected, model)
        else:
            self.model.clear()
        self.model.setEnabled(bool(selected))
        self._refresh_key_status()
        self._update_selection_status()

    def refresh_api_keys(self) -> None:
        self.refresh_from_settings()

    def _on_provider_changed(self, provider: str) -> None:
        if not provider or not self.secrets.get_api_key(provider):
            return
        self.settings.ai_provider = provider
        model = self.settings.gemini_model if provider == "Gemini" else self.settings.openai_model
        selected_model = self.model.set_provider(provider, model)
        self._store_model(provider, selected_model)
        self._refresh_key_status()
        self.settings_changed.emit()

    def _on_model_changed(self, model_id: str) -> None:
        provider = self.provider.value()
        if provider:
            self._store_model(provider, model_id)
            self.settings_changed.emit()

    def _store_model(self, provider: str, model_id: str) -> None:
        if provider == "Gemini":
            self.settings.gemini_model = model_id
        else:
            self.settings.openai_model = model_id

    def _load_subjects(self, grade_name: str) -> None:
        while self.subject_layout.count():
            item = self.subject_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.subject_buttons.clear()
        subjects = []
        for grade in self.achievement_data.get("grades", []):
            if grade.get("grade") == grade_name:
                subjects = [str(item.get("subject", "")) for item in grade.get("subjects", [])]
                break
        for subject in subjects:
            button = QPushButton(subject)
            button.setCheckable(True)
            button.setProperty("tabChip", True)
            button.clicked.connect(
                lambda _checked=False, selected=subject: self._select_subject(selected)
            )
            self.subject_buttons[subject] = button
            self.subject_layout.addWidget(button)
        self.subject_layout.addStretch(1)
        if subjects:
            self._select_subject(subjects[0])

    def _select_subject(self, subject: str) -> None:
        self.current_subject = subject
        for name, button in self.subject_buttons.items():
            button.setChecked(name == subject)
        self._load_standards()

    def _load_standards(self) -> None:
        while self.standards_layout.count():
            item = self.standards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.standard_cards.clear()
        self.standard_checks.clear()
        self.domain_sections.clear()
        grade_name = self.grade.value()
        for grade in self.achievement_data.get("grades", []):
            if grade.get("grade") != grade_name:
                continue
            for subject in grade.get("subjects", []):
                if subject.get("subject") != self.current_subject:
                    continue
                for domain in subject.get("domains", []):
                    section = DomainSection(str(domain.get("domain", "영역")))
                    for raw in domain.get("standards", []):
                        standard = AchievementStandard.from_json(
                            raw, domain=str(domain.get("domain", ""))
                        )
                        card = StandardCard(standard)
                        card.toggled.connect(
                            lambda target=card: self._on_standard_toggled(target)
                        )
                        section.add_card(card)
                        self.standard_cards.append(card)
                        self.standard_checks.append(card.check)
                        if standard.code in self.selected_standards:
                            card.check.setChecked(True)
                    self.domain_sections.append(section)
                    self.standards_layout.addWidget(section)
        self.standards_layout.addStretch(1)
        self._filter_standards(self.search.text())
        self._update_selection_status()

    def _filter_standards(self, query: str) -> None:
        query = query.strip()
        for section in self.domain_sections:
            visible_count = 0
            for card in section.cards:
                visible = not query or card.matches(query)
                card.setVisible(visible)
                visible_count += int(visible)
            section.setVisible(visible_count > 0)

    def _clear_standard_selection(self) -> None:
        self.selected_standards.clear()
        for card in self.standard_cards:
            card.check.setChecked(False)
        self._update_selection_status()

    def _on_standard_toggled(self, card: StandardCard) -> None:
        if card.check.isChecked():
            self.selected_standards[card.standard.code] = card.standard
        else:
            self.selected_standards.pop(card.standard.code, None)
        self._update_selection_status()

    def _remove_selected_standard(self, code: str) -> None:
        self.selected_standards.pop(code, None)
        for card in self.standard_cards:
            if card.standard.code == code:
                card.check.setChecked(False)
                break
        self._update_selection_status()

    def _update_selection_status(self) -> None:
        selected = list(self.selected_standards.values())
        self.selection_status.setText(
            f"성취기준 {len(selected)}개 · 학생 {int(self.student_count.value())}명"
        )
        codes = [standard.code for standard in selected]
        self.selected_codes.setText(
            f"선택한 성취기준 {len(codes)}개"
            if codes
            else "선택된 성취기준 없음"
        )
        while self.selected_chip_layout.count():
            item = self.selected_chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for standard in selected:
            chip = QPushButton(standard.code)
            chip.setProperty("tabChip", True)
            chip.setToolTip("클릭하면 선택한 성취기준에서 제거합니다.")
            chip.setAccessibleName(f"{standard.code} 성취기준 선택 해제")
            chip.clicked.connect(
                lambda _checked=False, code=standard.code: self._remove_selected_standard(code)
            )
            self.selected_chip_layout.addWidget(chip)
        self.selected_chip_layout.addStretch(1)
        self.selected_chip_scroll.setVisible(bool(selected))
        ready = bool(selected and self.provider.value() and not self.worker)
        self.generate_button.setEnabled(ready)

    def _refresh_key_status(self) -> None:
        provider = self.provider.value()
        if not provider:
            self.key_status.setText("API 키 없음")
            badge = "warning"
            set_faded_text(self.status, "OpenAI 또는 Gemini API 키를 먼저 등록하세요.")
        else:
            self.key_status.setText(f"{provider} 등록됨")
            badge = "success"
            if "API 키" in self.status.text():
                self.status.setText("성취기준을 선택한 뒤 평어를 생성하세요.")
        self.key_status.setProperty("badge", badge)
        self.key_status.style().unpolish(self.key_status)
        self.key_status.style().polish(self.key_status)

    def _manage_api_keys(self) -> None:
        dialog = ApiKeyManagerDialog(self.secrets, self)
        dialog.keys_changed.connect(self._on_api_keys_changed)
        dialog.exec()
        self.refresh_api_keys()

    def _on_api_keys_changed(self) -> None:
        self.refresh_api_keys()
        self.api_keys_changed.emit()

    def _selected_standards(self) -> list[AchievementStandard]:
        return list(self.selected_standards.values())

    def _toggle_custom_prompt(self, checked: bool) -> None:
        self.custom_prompt_toggle.setText(
            f"{'▾' if checked else '▸'} 사용자 프롬프트"
        )
        self.custom_prompt_note.setVisible(checked)
        self.custom_prompt.setVisible(checked)

    def _on_custom_prompt_changed(self) -> None:
        self.settings.ai_custom_prompt = self.custom_prompt.toPlainText().strip()
        self.settings_changed.emit()

    def _generate(self) -> None:
        standards = self._selected_standards()
        if not standards:
            QMessageBox.information(self, "선택 필요", "성취기준을 하나 이상 선택하세요.")
            return
        provider = self.provider.value()
        api_key = self.secrets.get_api_key(provider)
        if not provider or not api_key:
            QMessageBox.information(self, "API 키 필요", "선택한 AI 서비스의 API 키를 등록하세요.")
            self.refresh_api_keys()
            return
        model = self.model.model_id()
        self._store_model(provider, model)
        self.settings.ai_provider = provider
        self.settings_changed.emit()
        request = GenerationRequest(
            provider=provider,
            model=model,
            standards=standards,
            student_count=int(self.student_count.value()),
            sentence_count=int(self.sentence_count.value() or "3"),
            previous_outputs=self.last_comments,
            custom_prompt=self.custom_prompt.toPlainText(),
        )
        self.generate_button.setEnabled(False)
        self.result_stack.setCurrentWidget(self.loading_state)
        set_faded_text(self.status, "생성 중...")
        self.worker = GenerationWorker(request, api_key, self)
        self.worker.succeeded.connect(self._on_generated)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self) -> None:
        self.worker = None
        self._update_selection_status()

    def _on_generated(self, result: GenerationResult) -> None:
        self.last_comments = result.comments
        self.result.setPlainText("\n".join(result.comments))
        self.result_stack.setCurrentWidget(self.result)
        self.copy_button.setEnabled(bool(result.comments))
        self.apply_button.setEnabled(bool(result.comments))
        suffix = " · 자동 보정 1회 수행" if result.repaired else ""
        set_faded_text(self.status, f"{len(result.comments)}개 평어 생성 완료{suffix}")

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "생성 실패", message)
        self.result_stack.setCurrentWidget(self.empty_state)
        set_faded_text(self.status, "생성 실패")

    def _copy_result(self) -> None:
        self.result.selectAll()
        self.result.copy()
        cursor = self.result.textCursor()
        cursor.clearSelection()
        self.result.setTextCursor(cursor)
        set_faded_text(self.status, "생성 결과를 클립보드에 복사했습니다.")

    def _apply_result(self) -> None:
        self.comments_ready.emit(self.last_comments)
        set_faded_text(self.status, f"평어 {len(self.last_comments)}개를 NEIS 입력 표에 넣었습니다.")
