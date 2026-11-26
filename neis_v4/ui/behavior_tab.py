from __future__ import annotations

import math
import random
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace

from PySide6.QtCore import QPoint, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neis_v4.ai.base import call_with_retry, is_transient_error
from neis_v4.ai.behavior_response import comment_metrics
from neis_v4.ai.claude_provider import ClaudeProvider
from neis_v4.ai.gemini_provider import GeminiProvider
from neis_v4.ai.openai_provider import OpenAIProvider
from neis_v4.ai.solar_provider import SolarProvider
from neis_v4.behavior_catalog import BehaviorCatalog
from neis_v4.models import (
    AppSettings,
    BehaviorGenerationRequest,
    BehaviorGenerationResult,
    BehaviorStudentInput,
    BehaviorStudentResult,
    BehaviorStudentState,
    BehaviorTraitSelection,
    BehaviorWork,
    StudentRow,
)
from neis_v4.roster import StudentRoster
from neis_v4.secrets import SecretStore, no_key_message
from neis_v4.storage import Storage
from neis_v4.ui.api_keys import ApiKeyManagerDialog
from neis_v4.ui.provider_controls import ModelSelector, ProviderSelector
from neis_v4.ui.theme import COLORS, icon
from neis_v4.ui.widgets import (
    ArrowComboBox,
    ChoiceSegmentedControl,
    CompactNumberInput,
    NeisInputControls,
    estimated_progress,
    set_faded_text,
)


LEVEL_LABELS = {
    "strength": "강점",
    "standard": "일반",
    "growth": "성장 필요",
}
LEVEL_COLORS = {
    "strength": ("#EAF7EF", "#17713C", "#B9DFC7"),
    "standard": ("#EAF1FD", "#235FA7", "#BED1EE"),
    "growth": ("#FFF4E5", "#945712", "#EACB9A"),
}


# 행동발달 묶음(10명)을 몇 개까지 동시에 보낼지 정합니다.
# 동시에 처리 중인 묶음끼리는 서로의 문장을 중복 방지 참고로 쓰지 못합니다.
PARALLEL_BATCHES = 3

# '한 번에 보내는 최대 30명' 1회당 예상 시간(초). 진행률(%) 어림에 씁니다.
# 2026-11 가짜 학생 10~35명으로 잰 값(Upstage 15~28초, Gemini 3.8 Flash 23~285초로 날마다 들쭉날쭉)이고,
# 재지 못한 서비스는 대략값입니다. 생성할 때마다 실제 걸린 시간으로 보정합니다.
SECONDS_PER_WAVE = {"Upstage": 20.0, "Gemini": 90.0}
DEFAULT_SECONDS_PER_WAVE = 40.0


class BehaviorGenerationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress_changed = Signal(int, int)
    status_changed = Signal(str)
    # 묶음 하나가 끝날 때마다 그 묶음 결과를 보내 화면에 바로 보여 줍니다.
    batch_finished = Signal(object)

    def __init__(
        self,
        request: BehaviorGenerationRequest,
        api_key: str,
        batch_size: int = 10,
        parallel_batches: int = PARALLEL_BATCHES,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.request = request
        self.api_key = api_key
        self.batch_size = batch_size
        self.parallel_batches = max(1, parallel_batches)
        self._stop_requested = False

    def request_stop(self) -> None:
        """이미 보낸 묶음은 끝까지 받고, 다음 묶음부터 보내지 않습니다."""
        self._stop_requested = True

    def run(self) -> None:
        try:
            providers = {
                "Gemini": GeminiProvider,
                "OpenAI": OpenAIProvider,
                "Claude": ClaudeProvider,
                "Upstage": SolarProvider,
            }
            provider = providers[self.request.provider](self.api_key)
            students = self.request.students
            total = len(students)
            batches = [
                students[start : start + self.batch_size]
                for start in range(0, total, self.batch_size)
            ]
            previous = list(self.request.previous_outputs)
            results_by_batch: dict[int, list[BehaviorStudentResult]] = {}
            raw_parts: list[str] = []
            done = 0
            # 최대 3묶음을 동시에 보내고, 하나가 끝나면 곧바로 다음 묶음을 보냅니다.
            # (예전에는 3묶음이 모두 끝나야 다음 3묶음을 보내서 느린 묶음 하나가 전체를 붙잡았습니다.)
            # 새로 보내는 묶음은 그때까지 끝난 묶음의 문장을 중복 방지 참고로 받습니다.
            pending: dict = {}
            next_index = 0
            with ThreadPoolExecutor(self.parallel_batches) as pool:
                while True:
                    while (
                        next_index < len(batches)
                        and len(pending) < self.parallel_batches
                        and not self._stop_requested
                    ):
                        future = pool.submit(
                            self._run_batch, provider, next_index, batches[next_index], list(previous)
                        )
                        pending[future] = next_index
                        next_index += 1
                    if not pending:
                        break
                    finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in finished:
                        index = pending.pop(future)
                        results_by_batch[index], raw_text = future.result()
                        if raw_text:
                            raw_parts.append(raw_text)
                        previous.extend(
                            item.comment
                            for item in results_by_batch[index]
                            if item.status == "ok" and item.comment
                        )
                        self.batch_finished.emit(results_by_batch[index])
                        done += len(batches[index])
                        self.progress_changed.emit(done, total)
            self.succeeded.emit(
                BehaviorGenerationResult(
                    results=[item for index in sorted(results_by_batch) for item in results_by_batch[index]],
                    raw_text="\n".join(raw_parts),
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))

    def _run_batch(
        self,
        provider,
        index: int,
        students: list[BehaviorStudentInput],
        previous: list[str],
    ) -> tuple[list[BehaviorStudentResult], str]:
        """한 묶음을 생성합니다. 실패해도 예외 대신 학생별 실패 결과를 돌려줘 다른 묶음은 살립니다."""
        batch_request = replace(self.request, students=students, previous_outputs=previous)
        try:
            generated = self._generate_batch_with_retry(provider, batch_request, index + 1)
            return list(generated.results), generated.raw_text
        except Exception as exc:
            message = f"{index + 1}번째 묶음 생성 실패: {exc}"
            failed = [
                BehaviorStudentResult(
                    student_id=student.student_id,
                    status="failed",
                    reason=message,
                    comment="",
                )
                for student in students
            ]
            return failed, ""

    def _generate_batch_with_retry(
        self,
        provider,
        request: BehaviorGenerationRequest,
        batch_number: int,
    ) -> BehaviorGenerationResult:
        return call_with_retry(
            lambda: provider.generate_behavior(request),
            on_retry=lambda attempt, limit: self.status_changed.emit(
                f"{batch_number}번째 묶음 서버 혼잡 · {attempt}/{limit}회 재시도 중"
            ),
            sleep=lambda seconds: self.msleep(int(seconds * 1000)),
        )

    _is_transient_error = staticmethod(is_transient_error)


class BehaviorTab(QWidget):
    comments_ready = Signal(dict)
    settings_changed = Signal()
    api_keys_changed = Signal()
    # 바로 NEIS 자동 입력: (학생별 초안, 명단 순서의 입력할 행, 이동 칸)
    auto_input_requested = Signal(dict, list, int)
    stop_input_requested = Signal()

    def __init__(
        self,
        storage: Storage,
        settings: AppSettings,
        secrets: SecretStore,
        roster: StudentRoster,
        work: BehaviorWork,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.secrets = secrets
        self.roster = roster
        self.work = work
        self.catalog = BehaviorCatalog(storage)
        self.states = {state.student_id: state for state in work.students}
        self.current_student_id = ""
        self.worker: BehaviorGenerationWorker | None = None
        self.trait_buttons: dict[str, QPushButton] = {}
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self.save_work)
        # 생성 진행률: 묶음이 끝날 때마다 실제 값, 그 사이는 경과 시간으로 어림합니다.
        self._started_at = 0.0
        self._expected_seconds = 0.0
        self._waves = 1
        self._timing_key = ("", "")
        self._done = 0
        self._total = 0
        self._status_note = ""
        self._seconds_per_wave: dict[tuple[str, str], float] = {}
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        self.provider = ProviderSelector()
        self.model = ModelSelector()
        # 좁은 창에서는 모델 칸이 줄어들도록 합니다.
        self.model.setMinimumContentsLength(8)
        default_count = work.default_sentence_count or settings.behavior_sentence_count
        self.default_sentence_count = CompactNumberInput(
            1,
            8,
            default_count if 1 <= default_count <= 8 else 3,
        )
        self.settings.behavior_sentence_count = self.default_sentence_count.value()
        self.key_status = QLabel()
        self.key_button = QPushButton("API 키 관리")
        self.key_button.setIcon(icon("key-round", COLORS["muted"]))

        self.student_search = QLineEdit()
        self.student_search.setPlaceholderText("학생 검색")
        self.student_filter = ArrowComboBox()
        self.student_filter.addItem("전체", "all")
        self.student_filter.addItem("생성 가능", "ready")
        self.student_filter.addItem("완료", "ok")
        self.student_filter.addItem("실패", "failed")
        self.student_list = QListWidget()
        self.student_list.setMinimumWidth(170)
        # 항목이 목록 폭에 맞춰지도록 가로 스크롤을 끕니다 (켜 두면 상태 표시가 오른쪽에서 잘림).
        self.student_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.group_combo = ChoiceSegmentedControl(
            [("교과", "subject"), ("인성·행동·태도", "behavior")]
        )
        self.group_combo.setValue("subject")
        self.current_category = ""
        self.category_buttons: dict[str, QPushButton] = {}
        self.category_bar = QWidget()
        self.category_layout = QHBoxLayout(self.category_bar)
        self.category_layout.setContentsMargins(2, 2, 2, 2)
        self.category_layout.setSpacing(6)
        self.add_trait_button = QPushButton("+ 특성 추가")
        self.add_trait_button.setProperty("variant", "secondary")
        self.trait_box = QWidget()
        self.trait_box.setStyleSheet("background:#FFFFFF;")
        self.trait_grid = QGridLayout(self.trait_box)
        self.trait_grid.setContentsMargins(4, 4, 4, 4)
        self.trait_grid.setSpacing(8)

        self.selected_traits = QListWidget()
        self.selected_traits.setMinimumHeight(120)
        self.sentence_override = CompactNumberInput(
            1, 8, self.work.default_sentence_count
        )
        self.reset_sentence_override = QPushButton()
        self.reset_sentence_override.setIcon(icon("rotate-ccw", COLORS["muted"], 15))
        self.reset_sentence_override.setIconSize(QSize(15, 15))
        self.reset_sentence_override.setFixedSize(32, 32)
        self.reset_sentence_override.setProperty("variant", "ghost")
        self.reset_sentence_override.setToolTip("전체 기본 문장 수를 사용합니다.")
        self.reset_sentence_override.setAccessibleName("개별 문장 수 기본값 사용")
        self.draft = QTextEdit()
        self.draft.setPlaceholderText("생성된 행동특성 및 종합의견이 여기에 표시됩니다.")
        # 1366×768 화면에서 선택한 특성 목록에 밀려 한 줄만 보이지 않게 합니다 (여기서 결과를 고칩니다).
        self.draft.setMinimumHeight(130)
        self.custom_prompt_toggle = QPushButton("▸ 사용자 프롬프트")
        self.custom_prompt_toggle.setCheckable(True)
        self.custom_prompt_toggle.setProperty("variant", "ghost")
        self.custom_prompt_toggle.setToolTip("기본 프롬프트 아래에 추가할 지시를 작성합니다.")
        self.custom_prompt = QTextEdit()
        self.custom_prompt.setPlaceholderText("예: 더 간결하게, 협력 태도를 강조, 반복 표현 줄이기")
        self.custom_prompt.setFixedHeight(88)
        self.custom_prompt.setPlainText(settings.behavior_custom_prompt)
        self.custom_prompt.setVisible(False)
        self.metrics = QLabel("0자 · 0byte · 0문장")
        self.metrics.setObjectName("MutedLabel")
        self.result_info = QLabel("특성을 선택한 뒤 문장을 생성하세요.")
        self.result_info.setWordWrap(True)
        self.result_info.setObjectName("MutedLabel")
        self.generate_current = QPushButton("현재 학생 생성")
        self.generate_current.setProperty("variant", "secondary")
        self.generate_current.setIcon(icon("sparkles", COLORS["blue"]))
        self.generate_all = QPushButton("전체 생성")
        self.generate_all.setProperty("variant", "primary")
        self.generate_all.setIcon(icon("sparkles", "#FFFFFF"))
        self.stop_button = QPushButton("생성 중지")
        self.stop_button.setProperty("variant", "secondary")
        self.stop_button.setIcon(icon("square", COLORS["muted"]))
        self.stop_button.setToolTip("이미 보낸 묶음까지만 받고 나머지 학생은 생성하지 않습니다.")
        self.stop_button.setVisible(False)
        self.apply_button = QPushButton("NEIS 표에 넣기")
        self.apply_button.setProperty("variant", "secondary")
        self.apply_button.setIcon(icon("arrow-right", COLORS["muted"]))
        self.input_controls = NeisInputControls(settings.behavior_tab_count)
        self.save_button = QPushButton("작업 저장")
        self.save_button.setProperty("variant", "secondary")
        self.save_button.setIcon(icon("save", COLORS["muted"]))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.status = QLabel("학생별 특성을 선택하세요.")
        self.status.setObjectName("MutedLabel")

        self._build_layout()
        self._connect()
        self._ensure_states()
        self._refresh_students()
        self._load_categories()
        self.refresh_from_settings()

    def _build_layout(self) -> None:
        self.setObjectName("AppPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        title = QLabel("행동특성 및 종합의견")
        title.setObjectName("PageTitle")
        subtitle = QLabel("학생별 교과·행동 특성을 선택하고 검증된 생활기록부 문단을 생성합니다.")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        toolbar = QFrame()
        toolbar.setProperty("role", "Toolbar")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(6)
        # 서비스가 4개라 한 줄에 모두 넣으면 1366×768 화면에서 글자가 잘려 두 줄로 나눕니다.
        service_row = QHBoxLayout()
        service_row.addWidget(QLabel("AI 서비스"))
        service_row.addWidget(self.provider)
        service_row.addSpacing(8)
        service_row.addWidget(QLabel("모델"))
        service_row.addWidget(self.model, 1)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_status)
        key_row.addWidget(self.key_button)
        key_row.addStretch(1)
        key_row.addWidget(QLabel("전체 기본 문장 수"))
        key_row.addWidget(self.default_sentence_count)
        toolbar_layout.addLayout(service_row)
        toolbar_layout.addLayout(key_row)
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_student_panel())
        splitter.addWidget(self._build_trait_panel())
        splitter.addWidget(self._build_result_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 5)
        splitter.setSizes([230, 420, 540])
        root.addWidget(splitter, 1)

        dock = QFrame()
        dock.setProperty("role", "Dock")
        dock_layout = QVBoxLayout(dock)
        dock_layout.setContentsMargins(12, 10, 12, 10)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.status)
        dock_layout.addLayout(progress_row)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.input_controls)
        buttons.addStretch(1)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.generate_current)
        buttons.addWidget(self.generate_all)
        dock_layout.addLayout(buttons)
        root.addWidget(dock)

    def _build_student_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("role", "Panel")
        layout = QVBoxLayout(panel)
        heading = QLabel("학생 명단")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(self.student_search)
        layout.addWidget(self.student_filter)
        layout.addWidget(self.student_list, 1)
        return panel

    def _build_trait_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("role", "Panel")
        layout = QVBoxLayout(panel)
        heading = QLabel("특성 선택")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(self.group_combo)
        category_scroll = QScrollArea()
        category_scroll.setObjectName("TabScroll")
        category_scroll.setWidgetResizable(True)
        category_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        category_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        category_scroll.setFixedHeight(48)
        category_scroll.setWidget(self.category_bar)
        layout.addWidget(category_scroll)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.trait_box)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.add_trait_button)
        note = QLabel("키워드를 누른 뒤 강점·일반·성장 필요를 선택하세요.")
        note.setObjectName("MutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        return panel

    def _build_result_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("role", "Panel")
        layout = QVBoxLayout(panel)
        heading_row = QHBoxLayout()
        heading = QLabel("선택 및 결과")
        heading.setObjectName("SectionTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(QLabel("개별 문장 수"))
        heading_row.addWidget(self.sentence_override)
        heading_row.addWidget(self.reset_sentence_override)
        layout.addLayout(heading_row)
        selected_label = QLabel("선택한 특성")
        selected_label.setObjectName("MutedLabel")
        layout.addWidget(selected_label)
        layout.addWidget(self.selected_traits)
        layout.addWidget(self.custom_prompt_toggle)
        custom_note = QLabel("기존 작성 규칙과 충돌하지 않는 범위에서만 반영됩니다.")
        custom_note.setObjectName("MutedLabel")
        custom_note.setWordWrap(True)
        self.custom_prompt_note = custom_note
        custom_note.setVisible(False)
        layout.addWidget(custom_note)
        layout.addWidget(self.custom_prompt)
        result_label = QLabel("생성 결과")
        result_label.setObjectName("MutedLabel")
        layout.addWidget(result_label)
        layout.addWidget(self.draft, 1)
        info = QHBoxLayout()
        info.addWidget(self.metrics)
        info.addStretch(1)
        layout.addLayout(info)
        layout.addWidget(self.result_info)
        return panel

    def _connect(self) -> None:
        self.roster.changed.connect(self._on_roster_changed)
        self.student_list.currentItemChanged.connect(self._on_student_changed)
        self.student_search.textChanged.connect(self._refresh_students)
        self.student_filter.currentIndexChanged.connect(self._refresh_students)
        self.group_combo.valueChanged.connect(self._load_categories)
        self.add_trait_button.clicked.connect(self._add_custom_trait)
        self.sentence_override.valueChanged.connect(self._on_override_changed)
        self.reset_sentence_override.clicked.connect(self._reset_override)
        self.default_sentence_count.valueChanged.connect(self._on_default_count_changed)
        self.draft.textChanged.connect(self._on_draft_changed)
        self.provider.valueChanged.connect(self._on_provider_changed)
        self.model.modelChanged.connect(self._on_model_changed)
        self.key_button.clicked.connect(self._manage_api_keys)
        self.generate_current.clicked.connect(lambda: self._generate(False))
        self.generate_all.clicked.connect(lambda: self._generate(True))
        self.stop_button.clicked.connect(self._stop_generation)
        self.apply_button.clicked.connect(self._apply_results)
        self.save_button.clicked.connect(self._save_now)
        self.custom_prompt_toggle.toggled.connect(self._toggle_custom_prompt)
        self.custom_prompt.textChanged.connect(self._on_custom_prompt_changed)
        self.input_controls.start_requested.connect(self._request_auto_input)
        self.input_controls.stop_requested.connect(self.stop_input_requested.emit)
        self.input_controls.tab_count_changed.connect(self._on_input_tab_count_changed)

    def _ensure_states(self) -> None:
        for row in self.roster.rows():
            state = self.states.get(row.student_id)
            if state is None:
                state = BehaviorStudentState(row.student_id, row.name)
                self.states[row.student_id] = state
            state.name_snapshot = row.name

    def _refresh_students(self, *_args) -> None:
        selected_id = self.current_student_id
        query = self.student_search.text().strip().lower()
        status_filter = str(self.student_filter.currentData() or "all")
        self.student_list.blockSignals(True)
        self.student_list.clear()
        selected_item = None
        for row in self.roster.rows():
            state = self.states[row.student_id]
            if state.status == "generating":
                marker = "생성 중"
                status_key = "ready"
                badge = "warning"
            elif state.status == "ok":
                marker = "완료"
                status_key = "ok"
                badge = "success"
            elif state.status == "failed":
                marker = "실패"
                status_key = "failed"
                badge = "danger"
            elif state.traits:
                marker = "가능"
                status_key = "ready"
                badge = "info"
            else:
                marker = "대기"
                status_key = "empty"
                badge = "neutral"
            if query and query not in row.name.lower():
                continue
            if status_filter != "all" and status_key != status_filter:
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row.student_id)
            item.setSizeHint(QSize(0, 46))
            self.student_list.addItem(item)
            widget = QWidget()
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            widget_layout = QHBoxLayout(widget)
            widget_layout.setContentsMargins(6, 3, 6, 3)
            text_box = QVBoxLayout()
            text_box.setSpacing(0)
            name = QLabel(row.name)
            detail = QLabel(f"특성 {len(state.traits)}개")
            detail.setObjectName("MutedLabel")
            text_box.addWidget(name)
            text_box.addWidget(detail)
            marker_label = QLabel(marker)
            marker_label.setProperty("badge", badge)
            widget_layout.addLayout(text_box, 1)
            widget_layout.addWidget(marker_label)
            self.student_list.setItemWidget(item, widget)
            if row.student_id == selected_id:
                selected_item = item
        self.student_list.blockSignals(False)
        if selected_item:
            self.student_list.setCurrentItem(selected_item)
        elif self.student_list.count():
            self.student_list.setCurrentRow(0)
        else:
            self.current_student_id = ""
            self._load_current()
            self._refresh_trait_buttons()

    def _on_roster_changed(self) -> None:
        self._ensure_states()
        self._refresh_students()
        self._schedule_save()

    def count_students_with_work(self, student_ids: list[str]) -> int:
        return sum(
            bool(state and (state.traits or state.draft.strip()))
            for student_id in student_ids
            if (state := self.states.get(student_id)) is not None
        )

    def _on_student_changed(self, current: QListWidgetItem | None, _previous) -> None:
        student_id = str(current.data(Qt.UserRole)) if current else ""
        if student_id and student_id == self.current_student_id:
            # 명단만 다시 그린 경우입니다. 결과 칸을 다시 불러오면 고치던 글의 커서가 맨 앞으로 튀고
            # 조합 중인 한글이 사라지므로 그대로 둡니다. (상태가 바뀌는 곳은 _load_current를 따로 부릅니다.)
            return
        self.current_student_id = student_id
        self._load_current()
        self._refresh_trait_buttons()

    def _current_state(self) -> BehaviorStudentState | None:
        return self.states.get(self.current_student_id)

    def _load_current(self) -> None:
        state = self._current_state()
        self._loading = True
        try:
            self.selected_traits.clear()
            if not state:
                self.draft.clear()
                self.sentence_override.setValue(self.work.default_sentence_count)
                self.reset_sentence_override.setEnabled(False)
                return
            grouped: dict[tuple[str, str], list[tuple[BehaviorTraitSelection, str]]] = {}
            for selection in state.traits:
                definition = self.catalog.get(selection.trait_id)
                label = definition.label if definition else selection.label_snapshot or selection.trait_id
                key = (
                    definition.group if definition else "behavior",
                    definition.category if definition else "custom",
                )
                grouped.setdefault(key, []).append((selection, label))
            for (group_id, category_id), selections in grouped.items():
                category_labels = dict(self.catalog.category_definitions(group_id))
                self._add_trait_group_header(
                    group_id,
                    category_labels.get(category_id, "사용자 특성"),
                    len(selections),
                )
                for selection, label in selections:
                    self._add_selected_trait_item(
                        selection.trait_id, label, selection.level
                    )
            default_count = self.work.default_sentence_count
            self.sentence_override.setValue(
                state.sentence_count_override or default_count
            )
            self.reset_sentence_override.setEnabled(
                state.sentence_count_override is not None
            )
            self.draft.setPlainText(state.draft)
            self._show_result_info(state)
        finally:
            self._loading = False

    def _add_trait_group_header(
        self, group_id: str, category_label: str, count: int
    ) -> None:
        item = QListWidgetItem()
        item.setFlags(Qt.NoItemFlags)
        item.setSizeHint(QSize(260, 38))
        self.selected_traits.addItem(item)
        header = QFrame()
        header.setProperty("role", "TraitGroupHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 4, 8, 4)
        group = QLabel("교과" if group_id == "subject" else "인성·행동·태도")
        group.setProperty("badge", "info" if group_id == "subject" else "neutral")
        category = QLabel(f"›  {category_label}")
        category.setObjectName("SectionTitle")
        amount = QLabel(f"{count}개")
        amount.setObjectName("MutedLabel")
        layout.addWidget(group)
        layout.addWidget(category)
        layout.addStretch(1)
        layout.addWidget(amount)
        self.selected_traits.setItemWidget(item, header)

    def _add_selected_trait_item(self, trait_id: str, label: str, level: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, trait_id)
        item.setSizeHint(QSize(330, 44))
        self.selected_traits.addItem(item)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(18, 3, 6, 3)
        name = QLabel(label)
        level_box = ChoiceSegmentedControl(
            [("강점", "strength"), ("일반", "standard"), ("성장", "growth")]
        )
        for level_id in ("strength", "standard", "growth"):
            button = level_box.button(level_id)
            if button:
                button.setProperty("traitLevel", level_id)
        level_box.setValue(level)
        level_box.valueChanged.connect(
            lambda selected_level, selected=trait_id: self._set_trait_level(
                selected, selected_level
            )
        )
        remove = QPushButton()
        remove.setIcon(icon("trash-2", COLORS["danger"], 15))
        remove.setIconSize(QSize(15, 15))
        remove.setToolTip("특성 제거")
        remove.setAccessibleName(f"{label} 특성 제거")
        remove.setProperty("variant", "ghost")
        remove.setFixedSize(32, 32)
        remove.clicked.connect(lambda _checked=False, selected=trait_id: self._remove_trait(selected))
        layout.addWidget(name, 1)
        layout.addWidget(level_box, 0)
        layout.addWidget(remove)
        self.selected_traits.setItemWidget(item, row)

    def _load_categories(self, *_args) -> None:
        group_id = self.group_combo.value() or "subject"
        previous = self.current_category
        while self.category_layout.count():
            item = self.category_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.category_buttons.clear()
        definitions = self.catalog.category_definitions(group_id)
        for category_id, label in definitions:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("tabChip", True)
            button.clicked.connect(
                lambda _checked=False, selected=category_id: self._select_category(selected)
            )
            self.category_buttons[category_id] = button
            self.category_layout.addWidget(button)
        self.category_layout.addStretch(1)
        ids = [category_id for category_id, _label in definitions]
        self._select_category(previous if previous in ids else (ids[0] if ids else ""))

    def _select_category(self, category_id: str) -> None:
        self.current_category = category_id
        for current, button in self.category_buttons.items():
            button.setChecked(current == category_id)
        self._load_traits()

    def _load_traits(self) -> None:
        while self.trait_grid.count():
            item = self.trait_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.trait_buttons.clear()
        group_id = self.group_combo.value()
        category_id = self.current_category
        for index, definition in enumerate(self.catalog.traits_for(group_id, category_id)):
            button = QPushButton(definition.label)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, trait_id=definition.trait_id, target=button: self._show_trait_menu(
                    trait_id, target
                )
            )
            if definition.custom:
                button.setToolTip("사용자 추가 특성 · 오른쪽 클릭으로 삭제")
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda point, trait_id=definition.trait_id, target=button: self._show_custom_context(
                        trait_id, target, point
                    )
                )
            self.trait_buttons[definition.trait_id] = button
            self.trait_grid.addWidget(button, index // 2, index % 2)
        self.trait_grid.setRowStretch((len(self.trait_buttons) + 1) // 2, 1)
        self._refresh_trait_buttons()

    def _show_trait_menu(self, trait_id: str, target: QWidget) -> None:
        definition = self.catalog.get(trait_id)
        state = self._current_state()
        if not definition or not state:
            return
        menu = QMenu(self)
        for level in ("strength", "standard", "growth"):
            action = menu.addAction(LEVEL_LABELS[level])
            action.triggered.connect(
                lambda _checked=False, selected_level=level: self._set_trait_level(
                    trait_id, selected_level
                )
            )
        if any(item.trait_id == trait_id for item in state.traits):
            menu.addSeparator()
            menu.addAction("선택 해제").triggered.connect(lambda: self._remove_trait(trait_id))
        if isinstance(target, QPushButton):
            point = target.mapToGlobal(QPoint(0, target.height()))
        else:
            point = target.mapToGlobal(QPoint(target.width() // 2, target.height() // 2))
        menu.exec(point)

    def _show_custom_context(self, trait_id: str, target: QWidget, point: QPoint) -> None:
        menu = QMenu(self)
        action = menu.addAction("사용자 특성 삭제")
        if menu.exec(target.mapToGlobal(point)) == action:
            definition = self.catalog.get(trait_id)
            if not definition:
                return
            if QMessageBox.question(
                self,
                "사용자 특성 삭제",
                f"'{definition.label}' 특성을 목록에서 삭제할까요?\n기존 학생의 선택 기록은 유지됩니다.",
            ) == QMessageBox.Yes:
                self.catalog.remove_custom(trait_id)
                self._load_traits()

    def _set_trait_level(self, trait_id: str, level: str) -> None:
        state = self._current_state()
        definition = self.catalog.get(trait_id)
        if not state or not definition:
            return
        existing = next((item for item in state.traits if item.trait_id == trait_id), None)
        if existing:
            existing.level = level
            existing.label_snapshot = definition.label
        else:
            state.traits.append(BehaviorTraitSelection(trait_id, level, definition.label))
        state.status = "not_generated"
        state.error_message = ""
        self._load_current()
        self._refresh_trait_buttons()
        self._refresh_students()
        self._schedule_save()

    def _remove_trait(self, trait_id: str) -> None:
        state = self._current_state()
        if not state:
            return
        state.traits = [item for item in state.traits if item.trait_id != trait_id]
        state.status = "not_generated"
        state.error_message = ""
        self._load_current()
        self._refresh_trait_buttons()
        self._refresh_students()
        self._schedule_save()

    def _refresh_trait_buttons(self) -> None:
        state = self._current_state()
        levels = {item.trait_id: item.level for item in state.traits} if state else {}
        for trait_id, button in self.trait_buttons.items():
            level = levels.get(trait_id)
            if not level:
                button.setStyleSheet("")
                continue
            fill, text, border = LEVEL_COLORS[level]
            button.setStyleSheet(
                f"QPushButton {{background:{fill};color:{text};border:1px solid {border};}}"
            )

    def _add_custom_trait(self) -> None:
        group_id = self.group_combo.value()
        category_id = self.current_category
        label, ok = QInputDialog.getText(self, "사용자 특성 추가", "짧은 특성 키워드")
        label = label.strip()
        if not ok or not label:
            return
        if any(
            item.label == label
            for item in self.catalog.traits_for(group_id, category_id)
        ):
            QMessageBox.information(self, "중복 특성", "같은 카테고리에 이미 있는 키워드입니다.")
            return
        self.catalog.add_custom(label, group_id, category_id)
        self._load_traits()
        self._schedule_save()

    def _on_override_changed(self, value: int) -> None:
        if self._loading:
            return
        state = self._current_state()
        if state:
            state.sentence_count_override = int(value)
            state.status = "not_generated"
            state.error_message = ""
            self.reset_sentence_override.setEnabled(True)
            self._schedule_save()

    def _reset_override(self) -> None:
        state = self._current_state()
        if not state:
            return
        state.sentence_count_override = None
        state.status = "not_generated"
        state.error_message = ""
        self._load_current()
        self._refresh_students()
        self._schedule_save()

    def _on_default_count_changed(self, value: int) -> None:
        count = int(value)
        self.work.default_sentence_count = count
        self.settings.behavior_sentence_count = count
        for state in self.states.values():
            if state.sentence_count_override is None and state.draft:
                state.status = "not_generated"
                state.error_message = ""
        self._load_current()
        self._refresh_students()
        self.settings_changed.emit()
        self._schedule_save()

    def _on_draft_changed(self) -> None:
        if self._loading:
            return
        state = self._current_state()
        if not state:
            return
        old_status = state.status
        state.draft = self.draft.toPlainText().strip()
        if not state.draft:
            state.status = "not_generated"
            state.error_message = ""
        else:
            state.status = "ok"
            state.error_message = ""
        self._show_result_info(state)
        # 글자 하나 칠 때마다 명단 전체를 다시 그리면 타자가 밀리므로, 완료/빈칸 표시가 바뀔 때만 그립니다.
        if state.status != old_status:
            self._refresh_students()
        self._schedule_save()

    def _show_result_info(self, state: BehaviorStudentState) -> None:
        metrics = comment_metrics(state.draft)
        self.metrics.setText(
            f"{metrics['character_count']}자 · {metrics['utf8_byte_count']}byte · "
            f"{metrics['sentence_count']}문장"
        )
        if state.status == "failed" and state.error_message:
            self.result_info.setText(f"생성 실패\n⚠ {state.error_message}")
            self.result_info.setStyleSheet("color:#B42318;")
        elif state.draft and not 250 <= metrics["character_count"] <= 280:
            # behavior_prompt.py의 '250자 이상 280자 이하' 규칙과 맞춥니다.
            count = metrics["character_count"]
            gap = f"{250 - count}자 짧음" if count < 250 else f"{count - 280}자 김"
            self.result_info.setText(f"생성 완료\n⚠ 분량 확인 필요: 권장 250~280자보다 {gap}")
            self.result_info.setStyleSheet("color:#B54708;")
        elif state.draft:
            self.result_info.setText("생성 완료")
            self.result_info.setStyleSheet("color:#17803D;")
        else:
            self.result_info.setText("특성을 선택한 뒤 문장을 생성하세요.")
            self.result_info.setStyleSheet("color:#6E6E73;")

    def _on_provider_changed(self, provider: str) -> None:
        if not provider or not self.secrets.get_api_key(provider):
            return
        self.settings.behavior_provider = provider
        self._sync_model()
        self._refresh_key_status()
        self.settings_changed.emit()

    def _sync_model(self) -> None:
        provider = self.provider.value()
        if not provider:
            self.model.clear()
            self.model.setEnabled(False)
            return
        selected = self.model.set_provider(
            provider, self.settings.model_for(provider, behavior=True)
        )
        self.model.setEnabled(True)
        self._store_model(provider, selected)

    def _on_model_changed(self, value: str) -> None:
        provider = self.provider.value()
        if not provider:
            return
        self._store_model(provider, value)
        self.settings_changed.emit()

    def _store_model(self, provider: str, value: str) -> None:
        self.settings.set_model(provider, value, behavior=True)

    def refresh_from_settings(self) -> None:
        selected = self.provider.refresh_availability(
            self.secrets, self.settings.behavior_provider
        )
        if selected:
            self.settings.behavior_provider = selected
        self._sync_model()
        self._refresh_key_status()
        self._set_generation_availability()

    def refresh_api_keys(self) -> None:
        self.refresh_from_settings()

    def _toggle_custom_prompt(self, checked: bool) -> None:
        self.custom_prompt_toggle.setText(
            f"{'▾' if checked else '▸'} 사용자 프롬프트"
        )
        self.custom_prompt_note.setVisible(checked)
        self.custom_prompt.setVisible(checked)

    def _on_custom_prompt_changed(self) -> None:
        self.settings.behavior_custom_prompt = self.custom_prompt.toPlainText().strip()
        self.settings_changed.emit()

    def _refresh_key_status(self) -> None:
        provider = self.provider.value()
        configured = bool(provider and self.secrets.get_api_key(provider))
        self.key_status.setText(self.secrets.key_status_text(provider) if configured else "API 키 없음")
        self.key_status.setProperty("badge", "success" if configured else "warning")
        self.key_status.style().unpolish(self.key_status)
        self.key_status.style().polish(self.key_status)
        if not configured:
            set_faded_text(self.status, no_key_message())
        elif "API 키" in self.status.text():
            self.status.setText("학생별 특성을 선택하세요.")

    def _manage_api_keys(self) -> None:
        dialog = ApiKeyManagerDialog(self.secrets, self)
        dialog.keys_changed.connect(self._on_api_keys_changed)
        dialog.exec()
        self.refresh_api_keys()

    def _on_api_keys_changed(self) -> None:
        self.refresh_api_keys()
        self.api_keys_changed.emit()

    def _set_generation_availability(self) -> None:
        available = bool(
            self.provider.value() and self.secrets.get_api_key(self.provider.value())
        )
        if not self.worker:
            self.generate_current.setEnabled(available)
            self.generate_all.setEnabled(available)

    def _student_input(self, state: BehaviorStudentState) -> BehaviorStudentInput:
        traits: list[dict[str, str]] = []
        for selection in state.traits:
            definition = self.catalog.get(selection.trait_id)
            if definition:
                label = definition.label
                group = definition.group
                category = definition.category
                meaning = definition.meaning(selection.level)
            else:
                label = selection.label_snapshot or selection.trait_id
                group = "behavior"
                category = "custom"
                if selection.level == "strength":
                    meaning = f"{label} 특성이 뚜렷하게 관찰됨"
                elif selection.level == "growth":
                    meaning = f"{label}과 관련한 연습이나 지원이 필요함"
                else:
                    meaning = f"{label} 특성이 관찰됨"
            traits.append(
                {
                    "trait_id": selection.trait_id,
                    "label": label,
                    "group": group,
                    "category": category,
                    "level": selection.level,
                    "meaning": meaning,
                }
            )
        sentence_count = (
            state.sentence_count_override or self.work.default_sentence_count
        )
        if sentence_count == 1 and traits:
            chosen_trait_id = str(random.choice(traits)["trait_id"])
            for trait in traits:
                trait["generation_role"] = (
                    "required"
                    if trait["trait_id"] == chosen_trait_id
                    else "omit"
                )
        return BehaviorStudentInput(
            student_id=state.student_id,
            sentence_count=sentence_count,
            traits=traits,
        )

    def _generate(self, all_students: bool) -> None:
        if self.worker:
            return
        provider = self.provider.value()
        model = self.model.model_id()
        if not provider:
            QMessageBox.information(self, "API 키 필요", no_key_message())
            return
        api_key = self.secrets.get_api_key(provider)
        if not api_key:
            QMessageBox.information(self, "API 키 필요", f"{provider} API 키를 먼저 등록하세요.")
            return

        if all_students:
            states = [
                self.states[row.student_id]
                for row in self.roster.rows()
                if self.states[row.student_id].traits
            ]
            if not states:
                QMessageBox.information(self, "선택 필요", "특성이 선택된 학생이 없습니다.")
                return
        else:
            state = self._current_state()
            if not state or not state.traits:
                QMessageBox.information(self, "선택 필요", "현재 학생의 특성을 하나 이상 선택하세요.")
                return
            states = [state]

        for state in states:
            state.status = "generating"
            state.error_message = ""
        self._refresh_students()
        request = BehaviorGenerationRequest(
            provider=provider,
            model=model,
            students=[self._student_input(state) for state in states],
            previous_outputs=[
                state.draft for state in self.states.values() if state.draft
            ][-20:],
            custom_prompt=self.custom_prompt.toPlainText(),
        )
        self.worker = BehaviorGenerationWorker(request, api_key, parent=self)
        self.worker.succeeded.connect(self._on_generated)
        self.worker.failed.connect(self._on_generation_failed)
        self.worker.batch_finished.connect(self._on_batch_finished)
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.status_changed.connect(self._set_status_note)
        self.worker.finished.connect(self._worker_finished)
        self._set_generating(True)
        self.progress.setValue(0)
        self._done, self._total, self._status_note = 0, len(states), ""
        # 묶음 10명 × 동시 3묶음 = 한 번에 30명씩 보냅니다.
        self._waves = math.ceil(len(states) / (10 * PARALLEL_BATCHES))
        self._timing_key = (provider, model)
        per_wave = self._seconds_per_wave.get(
            self._timing_key, SECONDS_PER_WAVE.get(provider, DEFAULT_SECONDS_PER_WAVE)
        )
        self._expected_seconds = per_wave * self._waves
        self._started_at = time.monotonic()
        self._update_elapsed()
        self._elapsed_timer.start()
        self.worker.start()

    def _set_status_note(self, message: str) -> None:
        self._status_note = message
        self._update_elapsed()

    def _update_elapsed(self) -> None:
        elapsed = time.monotonic() - self._started_at
        real = int(self._done / max(self._total, 1) * 100)
        self.progress.setValue(max(real, estimated_progress(elapsed, self._expected_seconds)))
        text = f"{self._done}/{self._total}명 완료 · {int(elapsed)}초 경과"
        remaining = int(self._expected_seconds - elapsed)
        if self._status_note:
            text += f" · {self._status_note}"
        elif remaining > 0:
            text += f" · 약 {remaining}초 남음" if remaining < 60 else f" · 약 {remaining // 60}분 남음"
        elif elapsed > self._expected_seconds:
            text += " · 예상보다 오래 걸리고 있습니다. 멈추려면 '중지'를 누르세요."
        self.status.setText(text)

    def _stop_generation(self) -> None:
        if not self.worker:
            return
        self.worker.request_stop()
        self.stop_button.setEnabled(False)
        self._set_status_note("이미 보낸 묶음이 끝나면 멈춥니다...")

    def _reset_unfinished_states(self) -> int:
        """중지되어 결과를 받지 못한 학생을 생성 전 상태로 되돌리고 그 수를 돌려줍니다."""
        count = 0
        for state in self.states.values():
            if state.status == "generating":
                state.status = "ok" if state.draft else "not_generated"
                count += 1
        return count

    def _store_generated(self, results) -> None:
        for result in results:
            state = self.states.get(result.student_id)
            if not state:
                continue
            state.status = result.status
            state.error_message = result.reason
            if result.comment:
                state.draft = result.comment
                state.used_trait_ids = list(result.used_trait_ids)
                state.omitted_trait_ids = list(result.omitted_trait_ids)

    def _on_batch_finished(self, results) -> None:
        self._store_generated(results)
        self._refresh_students()
        if any(result.student_id == self.current_student_id for result in results):
            self._load_current()

    def _on_generated(self, generated: BehaviorGenerationResult) -> None:
        self._elapsed_timer.stop()
        elapsed = time.monotonic() - self._started_at
        self._store_generated(generated.results)
        stopped = self._reset_unfinished_states()
        if not stopped:
            # 중지하지 않고 끝까지 받은 경우만, 지난번 값과 평균 내어 다음 어림에 씁니다 (한 번 튄 값에 덜 흔들림).
            measured = elapsed / self._waves
            previous = self._seconds_per_wave.get(self._timing_key)
            self._seconds_per_wave[self._timing_key] = measured if previous is None else (previous + measured) / 2
            self.progress.setValue(100)
        self._refresh_students()
        self._load_current()
        self._schedule_save()
        ok_count = sum(item.status == "ok" for item in generated.results)
        failed_count = sum(not item.comment for item in generated.results)
        suffix = ""
        if failed_count:
            suffix += f" · 생성 실패 {failed_count}명"
        if stopped:
            suffix += f" · 중지되어 {stopped}명은 생성하지 않음"
        set_faded_text(self.status, f"생성 완료 {ok_count}명{suffix}")

    def _on_generation_failed(self, message: str) -> None:
        self._elapsed_timer.stop()
        for state in self.states.values():
            if state.status == "generating":
                state.status = "failed"
                state.error_message = message
        self._refresh_students()
        self._load_current()
        QMessageBox.critical(self, "행동발달 생성 실패", message)
        set_faded_text(self.status, "생성 실패")

    def _worker_finished(self) -> None:
        self._elapsed_timer.stop()
        self.worker = None
        self._set_generating(False)
        self._set_generation_availability()

    def _on_progress(self, done: int, total: int) -> None:
        self._done, self._total = done, total
        if self.stop_button.isEnabled():
            self._status_note = ""  # 재시도 안내는 묶음이 끝나면 지웁니다. 중지 안내는 남깁니다.
        self._update_elapsed()

    def _set_generating(self, generating: bool) -> None:
        for widget in (
            self.generate_current,
            self.generate_all,
            self.provider,
            self.model,
            self.default_sentence_count,
        ):
            widget.setEnabled(not generating)
        self.stop_button.setVisible(generating)
        self.stop_button.setEnabled(True)

    def _on_input_tab_count_changed(self, count: int) -> None:
        self.settings.behavior_tab_count = count
        self.settings_changed.emit()

    def _sync_draft_from_editor(self) -> None:
        """결과 칸에 보이는 글이 초안과 다를 때만 초안에 반영합니다. (같으면 생성 중·실패 상태를 건드리지 않음)"""
        state = self._current_state()
        if state and self.draft.toPlainText().strip() != state.draft:
            self._on_draft_changed()

    def _request_auto_input(self) -> None:
        self._sync_draft_from_editor()
        rows = self.roster.rows()
        drafts = {
            row.student_id: self.states[row.student_id].draft
            for row in rows
            if self.states[row.student_id].draft
        }
        if not drafts:
            QMessageBox.information(self, "입력할 결과 없음", "생성된 행동발달 결과가 없습니다.")
            return
        # 초안이 없는 학생은 빈 행으로 보냅니다. 표에 남아 있던 다른 내용(예: 교과 평어)이 행발 칸에 들어가지 않게 합니다.
        input_rows = [StudentRow(row.name, drafts.get(row.student_id, ""), row.student_id) for row in rows]
        self.auto_input_requested.emit(drafts, input_rows, self.input_controls.value())

    def set_macro_status(self, state: str, text: str) -> None:
        """자동 입력 상태를 버튼과 상태 줄에 보여 줍니다. 화면은 그대로 둡니다."""
        self.input_controls.set_state(state)
        if text:
            set_faded_text(self.status, text)

    def _apply_results(self) -> None:
        self._sync_draft_from_editor()
        chosen = [
            state
            for state in self.states.values()
            if state.draft
        ]
        if not chosen:
            QMessageBox.information(self, "적용할 결과 없음", "생성된 행동발달 결과가 없습니다.")
            return
        current_rows = {row.student_id: row for row in self.roster.rows()}
        overwrite = [
            current_rows[state.student_id].name
            for state in chosen
            if state.student_id in current_rows and current_rows[state.student_id].content.strip()
        ]
        if overwrite:
            names = "\n".join(f"- {name}" for name in overwrite[:10])
            more = f"\n외 {len(overwrite) - 10}명" if len(overwrite) > 10 else ""
            if QMessageBox.question(
                self,
                "기존 내용 덮어쓰기",
                f"다음 학생의 기존 내용을 덮어씁니다.\n{names}{more}\n\n계속할까요?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        mapping = {state.student_id: state.draft for state in chosen}
        self.comments_ready.emit(mapping)
        set_faded_text(self.status, f"{len(mapping)}명의 결과를 NEIS 표에 넣었습니다.")

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def save_work(self) -> None:
        rows = self.roster.rows()
        self.work.students = []
        for row in rows:
            state = self.states[row.student_id]
            state.name_snapshot = row.name
            self.work.students.append(state)
        self.work.default_sentence_count = int(self.default_sentence_count.value())
        self.storage.save_behavior_work(self.work)

    def _save_now(self) -> None:
        try:
            self.save_work()
            self.storage.save_students(self.roster.rows())
            set_faded_text(self.status, "행동발달 작업을 저장했습니다.")
        except Exception as exc:
            QMessageBox.critical(self, "저장 실패", f"작업을 저장하지 못했습니다.\n\n{exc}")
