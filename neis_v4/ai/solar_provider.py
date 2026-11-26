from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from neis_v4.models import (
    BehaviorGenerationRequest,
    BehaviorGenerationResult,
    BehaviorStudentInput,
    GenerationRequest,
    GenerationResult,
)

from .base import (
    REQUEST_TIMEOUT_SECONDS,
    SDK_MAX_RETRIES,
    AIProviderError,
    append_custom_prompt,
    build_prompt,
    describe_error,
)

# 행발은 학생마다 따로 요청해서, 한 학생만 혼잡(429)으로 실패하면 프로그램의 묶음 재시도가 돌지 않습니다.
# 그래서 행발 요청만 라이브러리 재시도를 1번 남깁니다.
BEHAVIOR_SDK_RETRIES = 1
# 학생마다 같은 '최근 결과'를 보내므로 개수를 줄여 요청을 가볍게 합니다 (공용 프롬프트는 20개).
SOLAR_PREVIOUS_OUTPUTS = 10
from .behavior_prompt import SYSTEM_PROMPT, build_behavior_prompt
from .behavior_response import map_behavior_results, parse_behavior_response
from .openai_provider import OpenAIProvider

# Solar는 문단 하나로 받으면 문장 수·마침표를 자주 어겨서, 문장을 배열로 받아 프로그램이 이어 붙입니다.
SENTENCES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "student_id": {"type": "string"},
                    "sentences": {"type": "array", "items": {"type": "string"}},
                    "used_trait_ids": {"type": "array", "items": {"type": "string"}},
                    "omitted_trait_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["student_id", "sentences", "used_trait_ids", "omitted_trait_ids"],
            },
        }
    },
    "required": ["results"],
}

SENTENCES_NOTE = """

# 출력 형식 (comment 대신 sentences)
- comment를 쓰지 말고 문장을 하나씩 sentences 배열에 넣으십시오.
- sentences 배열의 항목 수는 sentence_count와 정확히 같아야 합니다.
- 각 문장은 명사형 종결(~함, ~임, ~보임 등)과 마침표로 끝냅니다.
- 모든 문장을 이어 붙인 길이는 공백 포함 250~280자입니다. 문장 수가 적으면 한 문장을 길게 풀어 씁니다.
- 각 문장에는 어떤 상황에서, 어떤 행동을 하며, 그 행동이 어떤 태도나 성장을 보여 주는지를 함께 담아 충분히 길게 풀어 씁니다. 짧게 끊어 쓰면 분량 미달로 실패합니다."""

# Solar는 평어를 줄 단위로 받으면 학생 수(줄 수)를 자주 틀려(실측 10번 중 6번) 다시 요청하느라 2배 오래 걸렸습니다.
# 번호를 붙인 배열로 받으면 6번 중 6번 맞았습니다.
COMMENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"number": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["number", "text"],
            },
        }
    },
    "required": ["comments"],
}

# 한 학생씩 동시에 요청합니다. 기본 키 한도(1분에 400회)는 모든 사용자가 함께 쓰므로 너무 크게 잡지 않습니다.
MAX_PARALLEL_REQUESTS = 5

COMMENT_INSTRUCTIONS = "한국 초등학교 교사의 생활기록부 교과 평어 작성 규칙을 엄격히 따르십시오."


def with_custom_instruction(instructions: str, custom_prompt: str) -> str:
    """Solar는 사용자 지시를 시스템 지시(instructions)에도 적어야 잘 따릅니다.

    2026-11 실측(가짜 학생 10명 × 10번): 평어 '문장 40자 이내' 85%→100%, '협력 강조' 87%→100%,
    형식 규칙(문장 수·명사형 종결) 97%→99%. 지시가 없으면 아무것도 덧붙이지 않습니다.
    """
    custom = custom_prompt.strip()
    if not custom:
        return instructions
    return f"{instructions}\n\n# 사용자 추가 지시 (작성 규칙과 충돌하지 않는 범위에서 반드시 반영)\n{custom}"


def join_sentences(sentences: list[str]) -> str:
    cleaned = [sentence.strip() for sentence in sentences if sentence.strip()]
    return " ".join(sentence if sentence.endswith(".") else f"{sentence}." for sentence in cleaned)


class SolarProvider(OpenAIProvider):
    """Upstage(Solar 모델). OpenAI와 호출 방식이 같아서 접속 주소만 바꿔 씁니다."""

    name = "Upstage"
    base_url = "https://api.upstage.ai/v1"

    def generate_comments(self, request: GenerationRequest) -> GenerationResult:
        if not self.api_key:
            raise AIProviderError(f"{self.name} API 키가 설정되어 있지 않습니다.")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=SDK_MAX_RETRIES)
            comments = self._comments_once(client, request)
            if len(comments) != request.student_count:
                comments = self._comments_once(client, request, repair_text="\n".join(comments))
                return GenerationResult(comments, "\n".join(comments), repaired=True)
            return GenerationResult(comments, "\n".join(comments))
        except Exception as exc:
            raise AIProviderError(f"{self.name} 생성 실패: {self._error_detail(exc)}") from exc

    @staticmethod
    def _comments_once(client, request: GenerationRequest, repair_text: str = "") -> list[str]:
        count = request.student_count
        custom = request.custom_prompt.strip()
        # 사용자 추가 지시는 형식 안내 뒤 맨 끝에 둡니다. 중간에 두면 Solar가 뒤쪽 안내에 밀려 덜 따릅니다.
        prompt = build_prompt(replace(request, custom_prompt=""), repair_text) + (
            f"\n\n# 출력 형식 (줄 대신 JSON)\n- comments 배열에 학생 1번부터 {count}번까지 정확히 {count}개를 넣으십시오."
            "\n- number는 학생 번호, text는 그 학생의 평어 한 문단입니다."
        )
        if custom:
            prompt += f"\n- 모든 학생의 평어에 사용자 추가 지시를 반영하십시오: {custom}"
        response = client.responses.create(
            model=request.model,
            instructions=with_custom_instruction(COMMENT_INSTRUCTIONS, custom),
            input=append_custom_prompt(prompt, custom),
            text={"format": {"type": "json_schema", "name": "comments", "strict": True, "schema": COMMENTS_SCHEMA}},
        )
        items = sorted(json.loads(response.output_text)["comments"], key=lambda item: item["number"])
        # 한 학생 = 한 줄이어야 NEIS 표에 맞게 들어가므로 문단 안 줄바꿈은 공백으로 바꿉니다.
        return [" ".join(item["text"].split()) for item in items if item["text"].strip()]

    def generate_behavior(self, request: BehaviorGenerationRequest) -> BehaviorGenerationResult:
        if not self.api_key:
            raise AIProviderError(f"{self.name} API 키가 설정되어 있지 않습니다.")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=BEHAVIOR_SDK_RETRIES)
            # ponytail: 학생별로 따로 요청해 같은 묶음 학생끼리는 서로의 문장을 못 봄 (중복 방지는 이전 묶음 결과만 참고).
            with ThreadPoolExecutor(MAX_PARALLEL_REQUESTS) as pool:
                outcomes = list(
                    pool.map(lambda student: self._behavior_one(client, request, student), request.students)
                )
            items = [item for outcome in outcomes if isinstance(outcome, list) for item in outcome]
            errors = {
                student.student_id: outcome
                for student, outcome in zip(request.students, outcomes)
                if isinstance(outcome, Exception)
            }
            if errors and not items:
                # 모두 실패하면 행동발달 탭의 자동 재시도(429 등)가 동작하도록 오류로 올려 보냅니다.
                raise next(iter(errors.values()))
            text = json.dumps({"results": items}, ensure_ascii=False)
            results = map_behavior_results(request, parse_behavior_response(text))
            for result in results:
                if result.student_id in errors:
                    result.reason = f"{self.name} 요청 실패: {self._error_detail(errors[result.student_id])}"
            return BehaviorGenerationResult(results, text)
        except Exception as exc:
            raise AIProviderError(f"{self.name} 행동발달 생성 실패: {self._error_detail(exc)}") from exc

    @staticmethod
    def _behavior_one(client, request: BehaviorGenerationRequest, student: BehaviorStudentInput):
        """한 학생의 결과 목록을 돌려주고, 실패하면 예외 객체를 돌려줍니다."""
        try:
            # 사용자 추가 지시는 Solar 전용 형식 안내 뒤 맨 끝에 둡니다 (중간에 두면 뒤쪽 안내에 밀림).
            single = replace(
                request,
                students=[student],
                custom_prompt="",
                previous_outputs=request.previous_outputs[-SOLAR_PREVIOUS_OUTPUTS:],
            )
            low = round(255 / student.sentence_count)
            high = round(275 / student.sentence_count)
            prompt = append_custom_prompt(
                build_behavior_prompt(single)
                + SENTENCES_NOTE
                + f"\n- 이 학생은 sentences {student.sentence_count}개, 문장마다 {low}~{high}자로 씁니다.",
                request.custom_prompt,
            )
            response = client.responses.create(
                model=request.model,
                instructions=SYSTEM_PROMPT,
                input=prompt,
                temperature=0.35,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "behavior_response",
                        "strict": True,
                        "schema": SENTENCES_SCHEMA,
                    }
                },
            )
            items = json.loads(response.output_text)["results"][:1]
            for item in items:
                # 학생 한 명만 보냈으므로 AI가 번호를 줄이거나 바꿔 적어도 실제 학생 번호를 씁니다.
                item["student_id"] = student.student_id
                item["comment"] = join_sentences(item.pop("sentences", []))
            return items
        except Exception as exc:
            return exc

    @staticmethod
    def _error_detail(exc: Exception) -> str:
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            return (
                "API 키가 거절되었습니다. 기본 키 사용 기간이 끝났을 수 있으니 "
                "환경 설정 > API 키 관리에서 내 Upstage 키를 등록하세요."
            )
        if status == 429:
            # "429"는 행동발달 탭의 자동 재시도 판단(_is_transient_error)에 쓰이므로 지우지 마세요.
            return "요청이 많아 잠시 막혔습니다(429). 1분쯤 뒤에 다시 시도하세요."
        return describe_error(exc)
