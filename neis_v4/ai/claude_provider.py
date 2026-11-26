from __future__ import annotations

from .base import (
    REQUEST_TIMEOUT_SECONDS,
    SDK_MAX_RETRIES,
    AIProvider,
    AIProviderError,
    describe_error,
    build_prompt,
    parse_comments,
)
from .behavior_prompt import (
    BEHAVIOR_RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_behavior_prompt,
)
from .behavior_response import (
    map_behavior_results,
    parse_behavior_response,
)
from neis_v4.models import (
    BehaviorGenerationRequest,
    BehaviorGenerationResult,
    GenerationRequest,
    GenerationResult,
)


COMMENT_SYSTEM_PROMPT = "한국 초등학교 교사의 생활기록부 교과 평어 작성 규칙을 엄격히 따르십시오."
REPAIR_SYSTEM_PROMPT = "출력 줄 수 보정만 수행하십시오."

# 안전 필터가 요청을 거절하면 Anthropic 서버가 권장 모델로 한 번 더 시도합니다.
# Haiku는 이 기능을 지원하지 않아 목록에서 뺐습니다.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider(AIProvider):
    name = "Claude"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def generate_comments(self, request: GenerationRequest) -> GenerationResult:
        if not self.api_key:
            raise AIProviderError("Claude API 키가 설정되어 있지 않습니다.")
        try:
            client = self._client()
            text = self._request(client, request.model, COMMENT_SYSTEM_PROMPT, build_prompt(request))
            comments = parse_comments(text)
            if len(comments) != request.student_count:
                repair_text = self._request(
                    client,
                    request.model,
                    REPAIR_SYSTEM_PROMPT,
                    build_prompt(request, repair_text=text),
                )
                return GenerationResult(parse_comments(repair_text), repair_text, repaired=True)
            return GenerationResult(comments, text)
        except Exception as exc:
            raise AIProviderError(f"Claude 생성 실패: {describe_error(exc)}") from exc

    def generate_behavior(self, request: BehaviorGenerationRequest) -> BehaviorGenerationResult:
        if not self.api_key:
            raise AIProviderError("Claude API 키가 설정되어 있지 않습니다.")
        try:
            text = self._request(
                self._client(),
                request.model,
                SYSTEM_PROMPT,
                build_behavior_prompt(request),
                schema=BEHAVIOR_RESPONSE_SCHEMA,
            )
            results = map_behavior_results(request, parse_behavior_response(text))
            return BehaviorGenerationResult(results, text)
        except Exception as exc:
            raise AIProviderError(f"Claude 행동발달 생성 실패: {describe_error(exc)}") from exc

    def _client(self):
        import anthropic

        return anthropic.Anthropic(
            api_key=self.api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=SDK_MAX_RETRIES
        )

    @staticmethod
    def _request(client, model: str, system: str, prompt: str, schema: dict | None = None) -> str:
        output_config: dict = {"effort": "medium"}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        kwargs = {
            "model": model,
            "max_tokens": 64000,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": output_config,
        }
        if model in FALLBACK_MODELS:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        # 학생 수가 많으면 응답이 길어지므로 스트리밍으로 받아 시간 초과를 피합니다.
        with client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise AIProviderError(
                "Claude가 안전 정책에 따라 요청을 거절했습니다. "
                "사용자 프롬프트를 확인하거나 다른 AI 서비스로 다시 시도하세요."
            )
        if message.stop_reason == "max_tokens":
            raise AIProviderError("응답이 최대 길이에 도달해 잘렸습니다. 학생 수를 줄여 다시 시도하세요.")

        texts: list[str] = []
        for block in message.content:
            if block.type == "fallback":
                # 거절된 모델이 쓰다 만 부분은 버리고 대체 모델의 답만 씁니다.
                texts = []
            elif block.type == "text":
                texts.append(block.text)
        return "".join(texts).strip()
