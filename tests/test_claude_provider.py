from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from neis_v4.ai.base import AIProviderError
from neis_v4.ai.behavior_prompt import BEHAVIOR_RESPONSE_SCHEMA
from neis_v4.ai.claude_provider import ClaudeProvider
from neis_v4.models import (
    AchievementStandard,
    BehaviorGenerationRequest,
    BehaviorStudentInput,
    GenerationRequest,
)


def block(kind: str, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(type=kind, text=text)


class FakeClaudeClient:
    """Records each request and replies with prepared messages, without network calls."""

    def __init__(self, *messages: SimpleNamespace) -> None:
        self.replies = list(messages)
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        message = self.replies.pop(0)

        class Stream:
            def __enter__(self):
                return SimpleNamespace(get_final_message=lambda: message)

            def __exit__(self, *_args):
                return False

        return Stream()


def reply(*blocks: SimpleNamespace, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class ClaudeProviderTests(unittest.TestCase):
    def provider_with(self, client: FakeClaudeClient) -> ClaudeProvider:
        provider = ClaudeProvider("test-key")
        provider._client = lambda: client
        return provider

    def comment_request(self, model: str, student_count: int = 2) -> GenerationRequest:
        return GenerationRequest(
            provider="Claude",
            model=model,
            standards=[AchievementStandard("[4국01-01]", "성취기준 설명")],
            student_count=student_count,
            sentence_count=1,
        )

    def test_comment_request_uses_fallback_and_no_sampling_parameters(self) -> None:
        client = FakeClaudeClient(reply(block("thinking"), block("text", "첫째 평어임.\n둘째 평어임.")))

        result = self.provider_with(client).generate_comments(self.comment_request("claude-opus-5-5"))

        self.assertEqual(result.comments, ["첫째 평어임.", "둘째 평어임."])
        call = client.calls[0]
        self.assertEqual(call["fallbacks"], "default")
        self.assertEqual(call["betas"], ["server-side-fallback-2026-07-01"])
        self.assertNotIn("temperature", call)
        self.assertNotIn("top_p", call)
        self.assertNotIn("format", call["output_config"])

    def test_haiku_request_has_no_fallback(self) -> None:
        client = FakeClaudeClient(reply(block("text", "첫째 평어임.\n둘째 평어임.")))

        self.provider_with(client).generate_comments(self.comment_request("claude-haiku-5-5"))

        self.assertNotIn("fallbacks", client.calls[0])
        self.assertNotIn("betas", client.calls[0])

    def test_text_written_before_a_fallback_is_discarded(self) -> None:
        client = FakeClaudeClient(
            reply(
                block("text", "거절된 모델이 쓰다 만"),
                block("fallback"),
                block("text", "첫째 평어임.\n둘째 평어임."),
            )
        )

        result = self.provider_with(client).generate_comments(self.comment_request("claude-opus-5-5"))

        self.assertEqual(result.comments, ["첫째 평어임.", "둘째 평어임."])

    def test_wrong_line_count_triggers_one_repair_request(self) -> None:
        client = FakeClaudeClient(
            reply(block("text", "한 줄만 있음.")),
            reply(block("text", "첫째 평어임.\n둘째 평어임.")),
        )

        result = self.provider_with(client).generate_comments(self.comment_request("claude-sonnet-5-5"))

        self.assertTrue(result.repaired)
        self.assertEqual(len(client.calls), 2)

    def test_refusal_is_reported_as_error(self) -> None:
        client = FakeClaudeClient(reply(stop_reason="refusal"))

        with self.assertRaises(AIProviderError) as raised:
            self.provider_with(client).generate_comments(self.comment_request("claude-opus-5-5"))

        self.assertIn("거절", str(raised.exception))

    def test_behavior_request_asks_for_json_schema_without_names(self) -> None:
        student = BehaviorStudentInput("uuid-1", 3, [{"trait_id": "t1", "label": "성실함"}])
        request = BehaviorGenerationRequest("Claude", "claude-opus-5-5", [student])
        answer = {
            "results": [
                {
                    "student_id": "uuid-1",
                    "comment": "맡은 일을 성실하게 해냄.",
                    "used_trait_ids": ["t1"],
                    "omitted_trait_ids": [],
                    "character_count": 13,
                    "utf8_byte_count": 33,
                    "sentence_count": 1,
                }
            ]
        }
        client = FakeClaudeClient(reply(block("text", json.dumps(answer, ensure_ascii=False))))

        result = self.provider_with(client).generate_behavior(request)

        self.assertEqual(result.results[0].status, "ok")
        call = client.calls[0]
        self.assertEqual(
            call["output_config"]["format"],
            {"type": "json_schema", "schema": BEHAVIOR_RESPONSE_SCHEMA},
        )
        self.assertNotIn("학생 1", call["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
