from __future__ import annotations

from .base import AIProvider, AIProviderError, build_prompt, parse_comments
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


class OpenAIProvider(AIProvider):
    name = "OpenAI"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def generate_comments(self, request: GenerationRequest) -> GenerationResult:
        if not self.api_key:
            raise AIProviderError("OpenAI API 키가 설정되어 있지 않습니다.")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            prompt = build_prompt(request)
            response = client.responses.create(
                model=request.model,
                instructions="한국 초등학교 교사의 생활기록부 교과 평어 작성 규칙을 엄격히 따르십시오.",
                input=prompt,
            )
            text = response.output_text.strip()
            comments = parse_comments(text)
            if len(comments) != request.student_count:
                repair_response = client.responses.create(
                    model=request.model,
                    instructions="출력 줄 수 보정만 수행하십시오.",
                    input=build_prompt(request, repair_text=text),
                )
                repair_text = repair_response.output_text.strip()
                return GenerationResult(parse_comments(repair_text), repair_text, repaired=True)
            return GenerationResult(comments, text)
        except Exception as exc:
            raise AIProviderError(f"OpenAI 생성 실패: {exc}") from exc

    def generate_behavior(self, request: BehaviorGenerationRequest) -> BehaviorGenerationResult:
        if not self.api_key:
            raise AIProviderError("OpenAI API 키가 설정되어 있지 않습니다.")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            text = self._request_behavior(client, request.model, build_behavior_prompt(request), 0.35)
            results = map_behavior_results(request, parse_behavior_response(text))
            return BehaviorGenerationResult(results, text)
        except Exception as exc:
            raise AIProviderError(f"OpenAI 행동발달 생성 실패: {exc}") from exc

    @staticmethod
    def _request_behavior(client, model: str, prompt: str, temperature: float) -> str:
        kwargs = {
            "model": model,
            "instructions": SYSTEM_PROMPT,
            "input": prompt,
            "temperature": temperature,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "behavior_response",
                    "strict": True,
                    "schema": BEHAVIOR_RESPONSE_SCHEMA,
                }
            },
        }
        try:
            response = client.responses.create(**kwargs)
        except Exception as exc:
            message = str(exc).lower()
            if "temperature" in message:
                kwargs.pop("temperature", None)
                response = client.responses.create(**kwargs)
            elif any(token in message for token in ("json_schema", "text.format", "unsupported", "unknown parameter")):
                kwargs.pop("text", None)
                response = client.responses.create(**kwargs)
            else:
                raise
        return response.output_text.strip()
