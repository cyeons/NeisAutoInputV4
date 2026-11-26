from __future__ import annotations

import json
import sys
import types
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import patch

from neis_v4.ai.base import AIProviderError
from neis_v4.ai.solar_provider import SolarProvider
from neis_v4.models import (
    AchievementStandard,
    BehaviorGenerationRequest,
    BehaviorStudentInput,
    GenerationRequest,
)
from neis_v4.secrets import BUNDLED_KEY_EXPIRES, bundled_api_key, obfuscate_key, reveal_key
from neis_v4.ui.behavior_tab import BehaviorGenerationWorker


class FakeStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeOpenAI:
    created: list[dict] = []
    error: Exception | None = None
    calls: list[dict] = []
    failing_ids: set[str] = set()
    comment_items: list[dict] | None = None
    echoed_id: str = ""

    def __init__(self, **kwargs) -> None:
        FakeOpenAI.created.append(kwargs)
        self.responses = self

    def create(self, **kwargs):
        FakeOpenAI.calls.append(kwargs)
        if FakeOpenAI.error:
            raise FakeOpenAI.error
        if kwargs["text"]["format"]["name"] == "comments":
            items = FakeOpenAI.comment_items or [{"number": 1, "text": "첫째 평어임."}, {"number": 2, "text": "둘째\n평어임."}]
            return types.SimpleNamespace(output_text=json.dumps({"comments": items}, ensure_ascii=False))
        # 행동발달: 프롬프트에 들어 있는 학생 ID로 문장 배열을 돌려줍니다.
        student_id = next(sid for sid in ("s1", "s2") if f'"{sid}"' in kwargs["input"])
        if student_id in FakeOpenAI.failing_ids:
            raise FakeStatusError(500)
        result = {"student_id": FakeOpenAI.echoed_id or student_id, "sentences": ["책임감이 드러남", "배려를 실천함."],
                  "used_trait_ids": ["t1"], "omitted_trait_ids": []}
        return types.SimpleNamespace(output_text=json.dumps({"results": [result]}, ensure_ascii=False))


def behavior_request() -> BehaviorGenerationRequest:
    students = [BehaviorStudentInput(sid, 2, [{"trait_id": "t1", "label": "책임감"}]) for sid in ("s1", "s2")]
    return BehaviorGenerationRequest("Upstage", "solar-pro4", students)


def request() -> GenerationRequest:
    return GenerationRequest("Upstage", "solar-pro4", [AchievementStandard("[4국01-01]", "대화한다.")], 2, 1)


class SolarProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeOpenAI.created = []
        FakeOpenAI.error = None
        FakeOpenAI.calls = []
        FakeOpenAI.failing_ids = set()
        FakeOpenAI.comment_items = None
        FakeOpenAI.echoed_id = ""
        patcher = patch("openai.OpenAI", FakeOpenAI)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uses_upstage_base_url(self) -> None:
        result = SolarProvider("test-key").generate_comments(request())
        # 문단 안 줄바꿈은 공백으로 바뀌어 학생 1명 = 1줄이 됩니다.
        self.assertEqual(result.comments, ["첫째 평어임.", "둘째 평어임."])
        self.assertFalse(result.repaired)
        self.assertEqual(FakeOpenAI.created[0]["base_url"], "https://api.upstage.ai/v1")

    def test_custom_prompt_goes_last(self) -> None:
        custom = "협력 장면을 넣으십시오."
        SolarProvider("test-key").generate_comments(replace(request(), custom_prompt=custom))
        SolarProvider("test-key").generate_behavior(replace(behavior_request(), custom_prompt=custom))
        self.assertEqual(len(FakeOpenAI.calls), 3)
        for call in FakeOpenAI.calls:
            self.assertTrue(call["input"].rstrip().endswith(custom))

    def test_comment_custom_prompt_is_also_a_system_instruction(self) -> None:
        custom = "각 문장은 40자 이내로 써 주세요."
        SolarProvider("test-key").generate_comments(replace(request(), custom_prompt=custom))
        call = FakeOpenAI.calls[0]
        self.assertIn(custom, call["instructions"])
        self.assertIn(f"사용자 추가 지시를 반영하십시오: {custom}", call["input"])
        FakeOpenAI.calls = []
        SolarProvider("test-key").generate_comments(request())  # 지시가 없으면 그대로
        self.assertNotIn("사용자 추가 지시", FakeOpenAI.calls[0]["instructions"])
        self.assertNotIn("사용자 추가 지시", FakeOpenAI.calls[0]["input"])

    def test_behavior_asks_each_student_for_sentence_list(self) -> None:
        result = SolarProvider("test-key").generate_behavior(behavior_request())
        self.assertEqual(len(FakeOpenAI.calls), 2)  # 학생마다 한 번씩
        self.assertEqual([r.comment for r in result.results], ["책임감이 드러남. 배려를 실천함."] * 2)
        self.assertEqual([r.status for r in result.results], ["ok", "ok"])
        schema = FakeOpenAI.calls[0]["text"]["format"]["schema"]
        self.assertIn("sentences", schema["properties"]["results"]["items"]["properties"])

    def test_comments_follow_student_numbers(self) -> None:
        FakeOpenAI.comment_items = [{"number": 2, "text": "둘째 평어임."}, {"number": 1, "text": "첫째 평어임."}]
        result = SolarProvider("test-key").generate_comments(request())
        self.assertEqual(result.comments, ["첫째 평어임.", "둘째 평어임."])

    def test_behavior_keeps_result_when_model_changes_student_id(self) -> None:
        FakeOpenAI.echoed_id = "s1-잘못 적은 번호"
        result = SolarProvider("test-key").generate_behavior(behavior_request())
        self.assertEqual([r.student_id for r in result.results], ["s1", "s2"])
        self.assertEqual([r.status for r in result.results], ["ok", "ok"])

    def test_behavior_marks_only_failed_student(self) -> None:
        FakeOpenAI.failing_ids = {"s2"}
        result = SolarProvider("test-key").generate_behavior(behavior_request())
        self.assertEqual([r.status for r in result.results], ["ok", "failed"])
        self.assertIn("Upstage 요청 실패", result.results[1].reason)

    def test_behavior_all_failed_raises_for_worker_retry(self) -> None:
        FakeOpenAI.error = FakeStatusError(429)
        with self.assertRaises(AIProviderError) as caught:
            SolarProvider("test-key").generate_behavior(behavior_request())
        self.assertTrue(BehaviorGenerationWorker._is_transient_error(caught.exception))

    def test_rate_limit_and_rejected_key_have_korean_hints(self) -> None:
        for status, hint in ((429, "1분쯤 뒤"), (401, "내 Upstage 키를 등록")):
            FakeOpenAI.error = FakeStatusError(status)
            with self.assertRaises(AIProviderError) as caught:
                SolarProvider("test-key").generate_comments(request())
            self.assertIn("Upstage 생성 실패", str(caught.exception))
            self.assertIn(hint, str(caught.exception))
        # 행동발달 탭은 메시지 속 "429"를 보고 자동 재시도합니다.
        FakeOpenAI.error = FakeStatusError(429)
        with self.assertRaises(AIProviderError) as caught:
            SolarProvider("test-key").generate_comments(request())
        self.assertTrue(BehaviorGenerationWorker._is_transient_error(caught.exception))


class BundledKeyTests(unittest.TestCase):
    def test_obfuscated_key_round_trips_and_hides_text(self) -> None:
        hidden = obfuscate_key("up_fake-key-123")
        self.assertNotIn("fake", hidden)
        self.assertEqual(reveal_key(hidden), "up_fake-key-123")

    def test_bundled_key_stops_after_expiry(self) -> None:
        module = types.SimpleNamespace(DATA=obfuscate_key("up_fake"))
        with patch.dict(sys.modules, {"neis_v4._bundled_key": module}):
            self.assertEqual(bundled_api_key(BUNDLED_KEY_EXPIRES), "up_fake")
            self.assertEqual(bundled_api_key(date(2027, 4, 1)), "")


if __name__ == "__main__":
    unittest.main()
