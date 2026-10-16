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

            client = genai.Client(api_key=self.api_key)
            prompt = build_prompt(request)
            response = client.models.generate_content(
                model=request.model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.8, top_p=0.9),
            )
            text = (response.text or "").strip()
            comments = parse_comments(text)
            if len(comments) != request.student_count:
                repair_prompt = build_prompt(request, repair_text=text)
                repair_response = client.models.generate_content(
                    model=request.model,
                    contents=repair_prompt,
                    config=types.GenerateContentConfig(temperature=0.5, top_p=0.8),
                )
                repair_text = (repair_response.text or "").strip()
                return GenerationResult(parse_comments(repair_text), repair_text, repaired=True)
            return GenerationResult(comments, text)
        except Exception as exc:
            raise AIProviderError(f"Gemini 생성 실패: {exc}") from exc

    def generate_behavior(self, request: BehaviorGenerationRequest) -> BehaviorGenerationResult:
        if not self.api_key:
            raise AIProviderError("Gemini API 키가 설정되어 있지 않습니다.")
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            text = self._request_behavior(client, request.model, build_behavior_prompt(request), 0.35)
            results = map_behavior_results(request, parse_behavior_response(text))
            return BehaviorGenerationResult(results, text)
        except Exception as exc:
            raise AIProviderError(f"Gemini 행동발달 생성 실패: {exc}") from exc

    @staticmethod
    def _request_behavior(client, model: str, prompt: str, temperature: float) -> str:
        from google.genai import types

        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=temperature,
                    top_p=0.8,
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
                    temperature=temperature,
                    top_p=0.8,
                    response_mime_type="application/json",
                ),
            )
        return (response.text or "").strip()
