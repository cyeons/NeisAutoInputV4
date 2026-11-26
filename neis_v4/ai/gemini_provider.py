from __future__ import annotations

from .base import (
    REQUEST_TIMEOUT_SECONDS,
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


class GeminiProvider(AIProvider):
    name = "Gemini"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def generate_comments(self, request: GenerationRequest) -> GenerationResult:
        if not self.api_key:
            raise AIProviderError("Gemini API 키가 설정되어 있지 않습니다.")
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1),  # 재시도는 프로그램이 한 곳에서만 합니다.
                ),
            )
            prompt = build_prompt(request)
            response = client.models.generate_content(
                model=request.model,
                contents=prompt,
            )
            text = (response.text or "").strip()
            comments = parse_comments(text)
            if len(comments) != request.student_count:
                repair_prompt = build_prompt(request, repair_text=text)
                repair_response = client.models.generate_content(
                    model=request.model,
                    contents=repair_prompt,
                )
                repair_text = (repair_response.text or "").strip()
                return GenerationResult(parse_comments(repair_text), repair_text, repaired=True)
            return GenerationResult(comments, text)
        except Exception as exc:
            raise AIProviderError(f"Gemini 생성 실패: {describe_error(exc)}") from exc

    def generate_behavior(self, request: BehaviorGenerationRequest) -> BehaviorGenerationResult:
        if not self.api_key:
            raise AIProviderError("Gemini API 키가 설정되어 있지 않습니다.")
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1),  # 재시도는 프로그램이 한 곳에서만 합니다.
                ),
            )
            text = self._request_behavior(client, request.model, build_behavior_prompt(request))
            results = map_behavior_results(request, parse_behavior_response(text))
            return BehaviorGenerationResult(results, text)
        except Exception as exc:
            raise AIProviderError(f"Gemini 행동발달 생성 실패: {describe_error(exc)}") from exc

    @staticmethod
    def _request_behavior(client, model: str, prompt: str) -> str:
        # Gemini 3.8부터 temperature·top_p는 권장되지 않아 기본값을 씁니다.
        from google.genai import types

        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_json_schema=BEHAVIOR_RESPONSE_SCHEMA,
                ),
            )
        except Exception as exc:
            message = str(exc).lower()
            if not any(token in message for token in ("schema", "unsupported", "response_json")):
                raise
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                ),
            )
        return (response.text or "").strip()
