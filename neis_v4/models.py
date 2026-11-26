from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class AppSettings:
    student_count: int = 20
    geometry: str = ""
    always_on_top: bool = False
    macro_delay: float = 0.1
    start_hotkey: str = "F8"
    hotkey_start_enabled: bool = False
    tab_count: int = 2
    # AI 평어·행동발달 화면에서 바로 입력할 때의 이동 칸 (교과 평어는 Tab 3번, 행발은 Tab 2번)
    ai_tab_count: int = 3
    behavior_tab_count: int = 2
    # NEIS 입력칸 최대 바이트(한글 1자 = 3byte). 초과한 행을 표에서 빨간색으로 표시합니다.
    content_byte_limit: int = 1500
    leading_space: bool = False
    pyautogui_failsafe: bool = True
    use_windows_trust_store: bool = True
    ai_provider: str = "Upstage"
    upstage_model: str = "solar-pro4"
    gemini_model: str = "gemini-3.5-flash-lite"
    openai_model: str = "gpt-6-luna"
    claude_model: str = "claude-haiku-5-5"
    behavior_provider: str = "Upstage"
    behavior_upstage_model: str = "solar-pro4"
    behavior_gemini_model: str = "gemini-3.5-flash-lite"
    behavior_openai_model: str = "gpt-6-luna"
    behavior_claude_model: str = "claude-haiku-5-5"
    behavior_sentence_count: int = 3
    ai_custom_prompt: str = ""
    behavior_custom_prompt: str = ""
    # 새 버전 안내 창을 이미 띄운 버전 (같은 버전은 한 번만 알립니다)
    notified_update_version: str = ""

    @staticmethod
    def _model_field(provider: str, behavior: bool) -> str:
        # 예: "Gemini" → gemini_model, 행동발달용은 behavior_gemini_model
        return f"{'behavior_' if behavior else ''}{provider.lower()}_model"

    def model_for(self, provider: str, *, behavior: bool = False) -> str:
        return str(getattr(self, self._model_field(provider, behavior), ""))

    def set_model(self, provider: str, model_id: str, *, behavior: bool = False) -> None:
        field_name = self._model_field(provider, behavior)
        if hasattr(self, field_name):
            setattr(self, field_name, model_id)


@dataclass
class StudentRow:
    name: str
    content: str = ""
    student_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class AchievementStandard:
    code: str
    description: str
    explanation: str = ""
    domain: str = ""

    @classmethod
    def from_json(cls, value: dict[str, Any], domain: str = "") -> "AchievementStandard":
        return cls(
            code=str(value.get("code", "")),
            description=str(value.get("description", "")),
            explanation=str(value.get("explanation", "")),
            domain=domain,
        )


@dataclass
class GenerationRequest:
    provider: str
    model: str
    standards: list[AchievementStandard]
    student_count: int
    sentence_count: int
    previous_outputs: list[str] = field(default_factory=list)
    custom_prompt: str = ""


@dataclass
class GenerationResult:
    comments: list[str]
    raw_text: str
    repaired: bool = False


@dataclass(frozen=True)
class BehaviorTraitDefinition:
    trait_id: str
    label: str
    group: str
    category: str
    custom: bool = False

    def meaning(self, level: str) -> str:
        if level == "strength":
            return f"{self.label} 특성이 뚜렷하거나 지속적으로 관찰됨"
        if level == "growth":
            return f"{self.label}과 관련한 연습이나 지원이 필요함"
        return f"{self.label} 특성이 관찰됨"


@dataclass
class BehaviorTraitSelection:
    trait_id: str
    level: str
    label_snapshot: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BehaviorTraitSelection":
        return cls(
            trait_id=str(value.get("trait_id", "")),
            level=str(value.get("level", "standard")),
            label_snapshot=str(value.get("label_snapshot", "")),
        )


@dataclass
class BehaviorStudentState:
    student_id: str
    name_snapshot: str = ""
    sentence_count_override: int | None = None
    traits: list[BehaviorTraitSelection] = field(default_factory=list)
    draft: str = ""
    status: str = "not_generated"
    error_message: str = ""
    used_trait_ids: list[str] = field(default_factory=list)
    omitted_trait_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BehaviorStudentState":
        override = value.get("sentence_count_override")
        draft = str(value.get("draft", ""))
        saved_status = str(value.get("status", "not_generated"))
        if saved_status not in {"not_generated", "generating", "ok", "failed"}:
            saved_status = "ok" if draft else "not_generated"
        return cls(
            student_id=str(value.get("student_id", "")),
            name_snapshot=str(value.get("name_snapshot", "")),
            sentence_count_override=(
                int(override)
                if isinstance(override, (int, float)) and 1 <= int(override) <= 8
                else None
            ),
            traits=[
                BehaviorTraitSelection.from_dict(item)
                for item in value.get("traits", [])
                if isinstance(item, dict)
            ],
            draft=draft,
            status=saved_status,
            error_message=str(value.get("error_message", "")),
            used_trait_ids=[str(item) for item in value.get("used_trait_ids", [])],
            omitted_trait_ids=[str(item) for item in value.get("omitted_trait_ids", [])],
        )


@dataclass
class BehaviorWork:
    schema_version: int = 3
    default_sentence_count: int = 3
    students: list[BehaviorStudentState] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BehaviorWork":
        schema_version = int(value.get("schema_version", 1))
        sentence_count = int(value.get("default_sentence_count", 3))
        if schema_version < 2 or not 1 <= sentence_count <= 8:
            sentence_count = 3
        return cls(
            schema_version=3,
            default_sentence_count=sentence_count,
            students=[
                BehaviorStudentState.from_dict(item)
                for item in value.get("students", [])
                if isinstance(item, dict) and item.get("student_id")
            ],
        )


@dataclass(frozen=True)
class BehaviorStudentInput:
    student_id: str
    sentence_count: int
    traits: list[dict[str, str]]


@dataclass(frozen=True)
class BehaviorGenerationRequest:
    provider: str
    model: str
    students: list[BehaviorStudentInput]
    previous_outputs: list[str] = field(default_factory=list)
    custom_prompt: str = ""


@dataclass
class BehaviorStudentResult:
    student_id: str
    status: str
    reason: str
    comment: str
    used_trait_ids: list[str] = field(default_factory=list)
    omitted_trait_ids: list[str] = field(default_factory=list)
    character_count: int = 0
    utf8_byte_count: int = 0
    sentence_count: int = 0


@dataclass
class BehaviorGenerationResult:
    results: list[BehaviorStudentResult]
    raw_text: str
