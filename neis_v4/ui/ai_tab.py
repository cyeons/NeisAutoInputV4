from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QThread, QTimer, Signal
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

from neis_v4.ai import ClaudeProvider, GeminiProvider, OpenAIProvider, SolarProvider
from neis_v4.ai.base import AIProviderError, call_with_retry, parse_comments
from neis_v4.models import AchievementStandard, AppSettings, GenerationRequest, GenerationResult
from neis_v4.secrets import SecretStore, no_key_message
from neis_v4.storage import Storage
from neis_v4.ui.api_keys import ApiKeyManagerDialog
from neis_v4.ui.provider_controls import ModelSelector, ProviderSelector
from neis_v4.ui.theme import COLORS, icon
from neis_v4.ui.widgets import (
    ChoiceSegmentedControl,
    NeisInputControls,
    NumberStepper,
    estimated_progress,
    set_faded_text,
)

# 평어 생성 예상 시간(초) = 기본 시간 + 학생 1명당 시간. 진행률(%) 어림에 씁니다.
# 2026-11 가짜 학생 10~30명으로 여러 번 잰 값이고, 재지 못한 서비스(OpenAI·Claude)는 대략값입니다.
# 생성할 때마다 실제 걸린 시간으로 보정하므로 정확할 필요는 없습니다.
COMMENT_SECONDS = {"Upstage": (10.0, 1.2), "Gemini": (20.0, 0.4)}
DEFAULT_COMMENT_SECONDS = (15.0, 1.5)


class GenerationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    retrying = Signal(str)

    def __init__(self, request: GenerationRequest, api_key: str, parent=None) -> None:
        super().__init__(parent)
        self.request = request
        self.api_key = api_key

    def run(self) -> None:
        try:
            providers = {
                "Gemini": GeminiProvider,
                "OpenAI": OpenAIProvider,
                "Claude": ClaudeProvider,
                "Upstage": SolarProvider,
            }
            provider = providers[self.request.provider](self.api_key)
            result = call_with_retry(
                lambda: provider.generate_comments(self.request),
                on_retry=lambda attempt, limit: self.retrying.emit(
                    f"AI 서버가 바빠 다시 시도하는 중입니다 ({attempt}/{limit}회)"
                ),
                sleep=lambda seconds: self.msleep(int(seconds * 1000)),
            )
            self.succeeded.emit(result)
        except AIProviderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"생성 중 오류가 발생했습니다: {exc}")


def selected_line_numbers(text: str, start: int, end: int) -> list[int]:
    """Return indexes of non-empty lines touched by the text range [start, end]."""
    lines = text.split("\n")
    if end > start and text[end - 1] == "\n":
        end -= 1  # 줄 끝까지 드래그해 다음 줄 맨 앞에서 멈춘 경우
    first = text.count("\n", 0, start)
    last = text.count("\n", 0, max(start, end))
    return [index for index in range(first, last + 1) if index < len(lines) and lines[index].strip()]


def replace_lines(text: str, line_numbers: list[int], new_lines: list[str]) -> str:
    lines = text.split("\n")
    for index, value in zip(line_numbers, new_lines):
        lines[index] = value
    return "\n".join(lines)


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
    settings_changed = Signal()
    api_keys_changed = Signal()
    # 바로 NEIS 자동 입력: (평어 목록, 이동 칸). 메인 창이 표에 넣고 입력을 시작합니다.
    auto_input_requested = Signal(list, int)
    stop_input_requested = Signal()

    def __init__(self, storage: Storage, settings: AppSettings, secrets: SecretStore, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.secrets = secrets
        self.worker: GenerationWorker | None = None
        # 취소했지만 아직 응답을 기다리는 요청 (프로그램 종료 전에 끝나야 합니다)
        self._abandoned: list[GenerationWorker] = []
        self._requested_student_count = 0
        # 다시 생성 중인 결과 줄 번호. 비어 있으면 전체 생성입니다.
        self._regenerate_lines: list[int] = []
        self._started_at = 0.0
        self._expected_seconds = 0.0
        self._base_expected = 0.0
        self._timing_key = ("", "")
        self._retry_note = ""
        # (AI 서비스, 모델)별 '실제 걸린 시간 ÷ 기본 예상 시간'. 1.5면 예상보다 1.5배 느렸다는 뜻입니다.
        self._speed_ratio: dict[tuple[str, str], float] = {}
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        # NEIS 표에 평어를 넣는 함수 (넣은 개수를 돌려줌). 메인 창에서 연결합니다.
        self.comment_sink: Callable[[list[str]], int] | None = None
        self.achievement_data = self.storage.load_achievement_data()
        self.standard_cards: list[StandardCard] = []
        self.standard_checks: list[QCheckBox] = []
        self.domain_sections: list[DomainSection] = []
        self.subject_buttons: dict[str, QPushButton] = {}
        self.selected_standards: dict[str, AchievementStandard] = {}
        self.last_comments: list[str] = []
        # 생성했지만 아직 NEIS 표에 넣지 않은 결과가 있으면 True. 학년·교과를 바꿀 때 지워도 되는지 묻습니다.
        self._result_unsent = False
        self._grade_name = ""

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
        self.regenerate_button = QPushButton("선택한 줄 다시 생성")
        self.regenerate_button.setProperty("variant", "secondary")
        self.regenerate_button.setIcon(icon("sparkles", COLORS["muted"]))
        self.regenerate_button.setToolTip(
            "결과에서 마음에 들지 않는 줄을 드래그해 선택하거나 커서를 둔 뒤 누르세요.\n"
            "선택한 줄만 새로 만들고 나머지는 그대로 둡니다."
        )
        self.regenerate_button.setEnabled(False)
        self.input_controls = NeisInputControls(settings.ai_tab_count)
        self.cancel_button = QPushButton("생성 취소")
        self.cancel_button.setProperty("variant", "secondary")
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
        for count in (20, 25, 30):
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
        # 화면이 낮아도 성취기준 카드가 몇 개는 보이도록 최소 높이를 둡니다.
        scroll.setMinimumHeight(220)
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

        # 1366×768처럼 낮은 화면에서는 왼쪽 칸 전체를 위아래로 스크롤합니다.
        container = QScrollArea()
        container.setObjectName("LeftColumnScroll")
        container.setWidgetResizable(True)
        container.setFrameShape(QFrame.NoFrame)
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container.setStyleSheet("QScrollArea#LeftColumnScroll { background: transparent; }")
        container.viewport().setAutoFillBackground(False)
        left.setAutoFillBackground(False)
        container.setMinimumWidth(470)
        container.setMaximumWidth(680)
        container.setWidget(left)
        return container

    def _build_right(self) -> QWidget:
        right = QWidget()
        right.setMinimumWidth(360)
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("3. 생성 결과")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(self.result_stack, 1)
        # 결과 바로 아래에 둡니다. 아래 버튼 줄이나 제목 줄에 두면 1366×768 화면의 기본 창 크기에서 잘립니다.
        input_row = QHBoxLayout()
        input_row.addStretch(1)
        input_row.addWidget(self.input_controls)
        layout.addLayout(input_row)
        return right

    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("role", "Dock")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self.selection_status)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.regenerate_button)
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
        self.loading_title = title
        self.elapsed_label = QLabel("0초 경과")
        self.elapsed_label.setObjectName("MutedLabel")
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        self.elapsed_label.setWordWrap(True)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setTextVisible(False)  # %는 위 안내 글에 이미 있습니다.
        self.loading_progress = progress
        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        cancel_row.addWidget(self.cancel_button)
        cancel_row.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(self.elapsed_label)
        layout.addSpacing(12)
        layout.addWidget(progress)
        layout.addSpacing(12)
        layout.addLayout(cancel_row)
        layout.addStretch(1)
        return page

    def _connect(self) -> None:
        self.provider.valueChanged.connect(self._on_provider_changed)
        self.model.modelChanged.connect(self._on_model_changed)
        self.grade.valueChanged.connect(self._on_grade_changed)
        self.search.textChanged.connect(self._filter_standards)
        self.clear_selection.clicked.connect(self._clear_standard_selection)
        self.key_button.clicked.connect(self._manage_api_keys)
        self.generate_button.clicked.connect(self._generate)
        self.copy_button.clicked.connect(self._copy_result)
        self.apply_button.clicked.connect(self._apply_result)
        self.regenerate_button.clicked.connect(self._regenerate_selected)
        self.cancel_button.clicked.connect(self._cancel_generation)
        self.result.textChanged.connect(self._update_result_buttons)
        self.student_count.valueChanged.connect(lambda _value: self._update_selection_status())
        self.custom_prompt_toggle.toggled.connect(self._toggle_custom_prompt)
        self.custom_prompt.textChanged.connect(self._on_custom_prompt_changed)
        self.input_controls.start_requested.connect(self._request_auto_input)
        self.input_controls.stop_requested.connect(self.stop_input_requested.emit)
        self.input_controls.tab_count_changed.connect(self._on_input_tab_count_changed)

    def refresh_from_settings(self) -> None:
        selected = self.provider.refresh_availability(self.secrets, self.settings.ai_provider)
        if selected:
            self.settings.ai_provider = selected
            self.model.set_provider(selected, self.settings.model_for(selected))
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
        selected_model = self.model.set_provider(provider, self.settings.model_for(provider))
        self._store_model(provider, selected_model)
        self._refresh_key_status()
        self.settings_changed.emit()

    def _on_model_changed(self, model_id: str) -> None:
        provider = self.provider.value()
        if provider:
            self._store_model(provider, model_id)
            self.settings_changed.emit()

    def _store_model(self, provider: str, model_id: str) -> None:
        self.settings.set_model(provider, model_id)

    def _confirm_clear_result(self) -> bool:
        """학년·교과를 바꾸면 결과를 지우므로, 표에 넣지 않은 결과가 있을 때만 물어봅니다."""
        if not self._result_unsent or not self.result.toPlainText().strip():
            return True
        return QMessageBox.question(
            self,
            "생성 결과 지우기",
            "학년이나 교과를 바꾸면 지금 생성 결과가 지워집니다.\n"
            "아직 NEIS 표에 넣지 않은 결과입니다. 그래도 바꿀까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

    def _clear_result(self) -> None:
        """이전 교과의 결과와 중복 방지용 문장을 지웁니다. 다른 교과 문장이 섞이지 않게 합니다."""
        had_result = bool(self.result.toPlainText().strip())
        self.result.clear()
        self.last_comments = []
        self._result_unsent = False
        self.result_stack.setCurrentWidget(self.empty_state)
        if had_result:
            set_faded_text(self.status, "학년·교과가 바뀌어 이전 생성 결과를 지웠습니다.")

    def _on_grade_changed(self, grade_name: str) -> None:
        if grade_name == self._grade_name:
            return  # 이미 고른 학년을 다시 누른 경우
        if not self._confirm_clear_result():
            self.grade.setValue(self._grade_name)  # setValue는 신호를 다시 보내지 않습니다.
            return
        self._load_subjects(grade_name)

    def _on_subject_clicked(self, subject: str) -> None:
        if subject != self.current_subject and self._confirm_clear_result():
            self._select_subject(subject)
            return
        for name, button in self.subject_buttons.items():
            button.setChecked(name == self.current_subject)

    def _load_subjects(self, grade_name: str) -> None:
        self._grade_name = grade_name
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
                lambda _checked=False, selected=subject: self._on_subject_clicked(selected)
            )
            self.subject_buttons[subject] = button
            self.subject_layout.addWidget(button)
        self.subject_layout.addStretch(1)
        if subjects:
            self._select_subject(subjects[0])

    def _select_subject(self, subject: str) -> None:
        self.current_subject = subject
        self._clear_result()
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
        # 생성 중에 학년·교과를 바꾸면 이전 교과 결과가 새 교과 화면에 도착하므로 잠급니다.
        self.grade.setEnabled(not self.worker)
        self.subject_bar.setEnabled(not self.worker)
        self._update_result_buttons()

    def _update_result_buttons(self) -> None:
        has_result = bool(self.result.toPlainText().strip()) and not self.worker
        self.copy_button.setEnabled(has_result)
        self.apply_button.setEnabled(has_result)
        # 입력 중·시작 키 대기 중에는 멈출 수 있도록 결과가 없어도 켜 둡니다.
        self.input_controls.button.setEnabled(has_result or self.input_controls.state != "idle")
        self.regenerate_button.setEnabled(
            has_result and bool(self.selected_standards) and bool(self.provider.value())
        )

    def is_busy(self) -> bool:
        """생성 중이거나, 취소한 요청의 응답을 아직 기다리는 중이면 True입니다."""
        return self.worker is not None or any(worker.isRunning() for worker in self._abandoned)

    def _refresh_key_status(self) -> None:
        provider = self.provider.value()
        if not provider:
            self.key_status.setText("API 키 없음")
            badge = "warning"
            set_faded_text(self.status, no_key_message())
        else:
            self.key_status.setText(self.secrets.key_status_text(provider))
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
        self._start_generation([])

    def _regenerate_selected(self) -> None:
        cursor = self.result.textCursor()
        lines = selected_line_numbers(
            self.result.toPlainText(), cursor.selectionStart(), cursor.selectionEnd()
        )
        if not lines:
            QMessageBox.information(
                self, "줄 선택 필요", "다시 생성할 줄을 결과에서 드래그해 선택하거나 그 줄에 커서를 두세요."
            )
            return
        self._start_generation(lines)

    def _start_generation(self, regenerate_lines: list[int]) -> None:
        if self.worker:
            return
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
        standards = self._confirm_mixed_standards(standards)
        if not standards:
            return
        model = self.model.model_id()
        self._store_model(provider, model)
        self.settings.ai_provider = provider
        self.settings_changed.emit()
        if regenerate_lines:
            # 다시 만들 줄을 뺀 나머지는 중복 방지용으로 함께 보냅니다.
            lines = self.result.toPlainText().split("\n")
            previous = [
                line for index, line in enumerate(lines)
                if index not in regenerate_lines and line.strip()
            ]
            student_count = len(regenerate_lines)
        else:
            previous = self.last_comments
            student_count = int(self.student_count.value())
        request = GenerationRequest(
            provider=provider,
            model=model,
            standards=standards,
            student_count=student_count,
            sentence_count=int(self.sentence_count.value() or "3"),
            previous_outputs=previous,
            custom_prompt=self.custom_prompt.toPlainText(),
        )
        self._requested_student_count = request.student_count
        self._regenerate_lines = list(regenerate_lines)
        self.generate_button.setEnabled(False)
        self.loading_title.setText(
            f"선택한 {student_count}줄을 다시 생성하고 있습니다"
            if regenerate_lines
            else "교과 평어를 생성하고 있습니다"
        )
        self.result_stack.setCurrentWidget(self.loading_state)
        set_faded_text(self.status, "생성 중...")
        self.worker = GenerationWorker(request, api_key, self)
        self.worker.succeeded.connect(self._on_generated)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.retrying.connect(self._on_retrying)
        self._retry_note = ""
        self._started_at = time.monotonic()
        self._timing_key = (provider, model)
        base, per_student = COMMENT_SECONDS.get(provider, DEFAULT_COMMENT_SECONDS)
        self._base_expected = base + per_student * student_count
        self._expected_seconds = self._base_expected * self._speed_ratio.get(self._timing_key, 1.0)
        self._update_elapsed()
        self._elapsed_timer.start()
        self._update_selection_status()
        self.worker.start()

    def _confirm_mixed_standards(
        self, standards: list[AchievementStandard]
    ) -> list[AchievementStandard] | None:
        """지금 교과가 아닌 성취기준이 섞여 있으면 어떻게 할지 묻습니다. 취소하면 None입니다."""
        current = {card.standard.code for card in self.standard_cards}
        others = [standard for standard in standards if standard.code not in current]
        if not others:
            return standards
        remaining = [standard for standard in standards if standard.code in current]
        codes = ", ".join(standard.code for standard in others[:5])
        if len(others) > 5:
            codes += f" 외 {len(others) - 5}개"
        question = (
            "다른 교과 성취기준을 빼고 생성할까요?"
            if remaining
            else f"{self.current_subject} 성취기준은 하나도 선택되지 않았습니다. 그대로 생성할까요?"
        )
        box = QMessageBox(
            QMessageBox.Question,
            "다른 교과 성취기준이 섞여 있습니다",
            f"지금 교과({self.grade.value()} {self.current_subject})가 아닌 성취기준 "
            f"{len(others)}개가 함께 선택되어 있습니다.\n{codes}\n\n{question}",
            parent=self,
        )
        drop = box.addButton("다른 교과 빼고 생성", QMessageBox.AcceptRole) if remaining else None
        keep = box.addButton("그대로 생성", QMessageBox.ActionRole)
        cancel = box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(drop or cancel)
        box.exec()
        clicked = box.clickedButton()
        if drop is not None and clicked is drop:
            for standard in others:
                self.selected_standards.pop(standard.code, None)
            self._update_selection_status()
            return remaining
        return standards if clicked is keep else None

    def _update_elapsed(self) -> None:
        elapsed = time.monotonic() - self._started_at
        percent = estimated_progress(elapsed, self._expected_seconds)
        self.loading_progress.setValue(percent)
        remaining = int(self._expected_seconds - elapsed)
        if remaining > 0:
            left = f"{remaining}초" if remaining < 60 else f"{remaining // 60}분 {remaining % 60}초"
            text = f"약 {percent}% · {int(elapsed)}초 경과 · 약 {left} 남음"
            if self._timing_key not in self._speed_ratio:
                text += "\n처음 생성이라 남은 시간은 대략적인 값입니다."
        else:
            text = (
                f"{int(elapsed)}초 경과 · 예상보다 오래 걸리고 있습니다.\n"
                "응답이 없으면 5분 뒤 자동으로 멈추고 알려 드립니다."
            )
        if self._retry_note:
            text += f"\n{self._retry_note}"
        self.elapsed_label.setText(text)

    def _on_retrying(self, message: str) -> None:
        self._retry_note = message
        self._update_elapsed()

    def _cancel_generation(self) -> None:
        worker = self.worker
        if not worker:
            return
        # 이미 보낸 요청은 중간에 끊을 수 없어서, 결과만 버리고 화면을 되돌립니다.
        worker.succeeded.disconnect()
        worker.failed.disconnect()
        worker.finished.disconnect()
        worker.retrying.disconnect()
        self._abandoned.append(worker)
        worker.finished.connect(lambda done=worker: self._abandoned.remove(done))
        self._worker_finished()
        self._show_previous_result()
        set_faded_text(self.status, "생성을 취소했습니다. 이미 보낸 요청은 요금이 나올 수 있습니다.")

    def _show_previous_result(self) -> None:
        has_result = bool(self.result.toPlainText().strip())
        self.result_stack.setCurrentWidget(self.result if has_result else self.empty_state)

    def _worker_finished(self) -> None:
        self.worker = None
        self._elapsed_timer.stop()
        self._update_selection_status()

    def _on_generated(self, result: GenerationResult) -> None:
        # 예상보다 얼마나 빨랐는지(느렸는지)를 지난번 값과 평균 내어 다음 어림에 씁니다.
        ratio = (time.monotonic() - self._started_at) / max(self._base_expected, 1)
        previous = self._speed_ratio.get(self._timing_key)
        self._speed_ratio[self._timing_key] = ratio if previous is None else (previous + ratio) / 2
        lines = self._regenerate_lines
        self._regenerate_lines = []
        suffix = " · 자동 보정 1회 수행" if result.repaired else ""
        if lines:
            self.result_stack.setCurrentWidget(self.result)
            if len(result.comments) != len(lines):
                QMessageBox.warning(
                    self,
                    "평어 개수 확인",
                    f"{len(lines)}줄을 요청했지만 {len(result.comments)}개가 생성되어 기존 결과를 그대로 두었습니다.\n"
                    "다시 시도해 보세요.",
                )
                set_faded_text(self.status, "다시 생성 실패 · 기존 결과 유지")
                return
            self.result.setPlainText(
                replace_lines(self.result.toPlainText(), lines, result.comments)
            )
            self.last_comments = parse_comments(self.result.toPlainText())
            self._result_unsent = True
            set_faded_text(self.status, f"{len(lines)}줄을 다시 생성했습니다{suffix}")
            return
        self.last_comments = result.comments
        self._result_unsent = True
        self.result.setPlainText("\n".join(result.comments))
        self.result_stack.setCurrentWidget(self.result)
        set_faded_text(self.status, f"{len(result.comments)}개 평어 생성 완료{suffix}")
        requested = self._requested_student_count
        if requested and len(result.comments) != requested:
            QMessageBox.warning(
                self,
                "평어 개수 확인",
                f"학생 {requested}명을 요청했지만 평어가 {len(result.comments)}개 생성되었습니다.\n"
                "결과를 확인한 뒤 NEIS 입력 표에 넣거나 다시 생성하세요.",
            )

    def _on_failed(self, message: str) -> None:
        self._regenerate_lines = []
        QMessageBox.critical(self, "생성 실패", message)
        self._show_previous_result()
        set_faded_text(self.status, "생성 실패")

    def _copy_result(self) -> None:
        self.result.selectAll()
        self.result.copy()
        cursor = self.result.textCursor()
        cursor.clearSelection()
        self.result.setTextCursor(cursor)
        set_faded_text(self.status, "생성 결과를 클립보드에 복사했습니다.")

    def _on_input_tab_count_changed(self, count: int) -> None:
        self.settings.ai_tab_count = count
        self.settings_changed.emit()

    def _request_auto_input(self) -> None:
        # 결과 창에서 직접 고친 내용도 그대로 입력되도록 화면의 글을 씁니다.
        comments = parse_comments(self.result.toPlainText())
        if not comments:
            return
        self._result_unsent = False  # 메인 창이 먼저 NEIS 표에 넣습니다.
        self.auto_input_requested.emit(comments, self.input_controls.value())

    def set_macro_status(self, state: str, text: str) -> None:
        """자동 입력 상태를 버튼과 상태 줄에 보여 줍니다. 화면은 그대로 둡니다."""
        self.input_controls.set_state(state)
        if text:
            set_faded_text(self.status, text)
        self._update_result_buttons()

    def _apply_result(self) -> None:
        # 결과 창에서 직접 고친 내용도 반영되도록 화면의 글을 그대로 씁니다.
        comments = parse_comments(self.result.toPlainText())
        if not comments or not self.comment_sink:
            return
        count = self.comment_sink(comments)
        if count:
            self._result_unsent = False
            set_faded_text(self.status, f"평어 {count}개를 NEIS 입력 표에 넣었습니다.")
        else:
            set_faded_text(self.status, "NEIS 표에 넣기를 취소했습니다.")
