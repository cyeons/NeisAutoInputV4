"""효율화 작업(재시도 한 곳, 묶음 이어 보내기, 명단 다시 그리기 줄이기) 확인용 테스트. 가짜 데이터만 씁니다."""
from __future__ import annotations

import sys
import threading
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from neis_v4.ai.base import call_with_retry, is_transient_error
from neis_v4.models import (
    AppSettings,
    BehaviorGenerationRequest,
    BehaviorGenerationResult,
    BehaviorStudentInput,
    BehaviorStudentResult,
    BehaviorStudentState,
    BehaviorWork,
    StudentRow,
)
from neis_v4.roster import StudentRoster
from neis_v4.storage import Storage
from neis_v4.ui.behavior_tab import BehaviorGenerationWorker, BehaviorTab

app = QApplication.instance() or QApplication(sys.argv)


class RetryTests(unittest.TestCase):
    def test_busy_server_is_retried_but_timeout_is_not(self) -> None:
        self.assertTrue(is_transient_error(RuntimeError("Error code: 503 - overloaded")))
        self.assertFalse(is_transient_error(RuntimeError("Request timed out")))
        self.assertFalse(is_transient_error(RuntimeError("timeout")))
        # 다른 숫자 속에 섞인 500·503은 서버 혼잡이 아닙니다. (요금이 나가는 헛된 재시도 방지)
        self.assertFalse(is_transient_error(RuntimeError("400 input token count (1050045) exceeds maximum")))
        self.assertFalse(is_transient_error(RuntimeError("400 bad request, request_id: req_503abc")))
        status_error = RuntimeError("overloaded")
        status_error.status_code = 400
        self.assertFalse(is_transient_error(status_error))
        status_error.status_code = 503
        self.assertTrue(is_transient_error(status_error))

        calls = []

        def busy_then_ok():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("429 rate limit")
            return "ok"

        notes = []
        result = call_with_retry(busy_then_ok, on_retry=lambda a, n: notes.append((a, n)), sleep=lambda s: None)
        self.assertEqual(result, "ok")
        self.assertEqual(notes, [(1, 2), (2, 2)])

        calls.clear()

        def timed_out():
            calls.append(1)
            raise RuntimeError("Request timed out")

        with self.assertRaises(RuntimeError):
            call_with_retry(timed_out, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)  # 시간 초과는 다시 기다리게 하지 않습니다.


class SlidingBatchTests(unittest.TestCase):
    def test_next_batch_starts_when_any_batch_finishes(self) -> None:
        students = [BehaviorStudentInput(str(index), 3, [{"trait_id": "t"}]) for index in range(3)]
        request = BehaviorGenerationRequest("OpenAI", "test", students)
        worker = BehaviorGenerationWorker(request, "key", batch_size=1, parallel_batches=2)
        slow_release = threading.Event()
        seen_previous: dict[str, list[str]] = {}

        class FakeProvider:
            def generate_behavior(self, batch_request):
                student_id = batch_request.students[0].student_id
                seen_previous[student_id] = list(batch_request.previous_outputs)
                if student_id == "0":
                    # 첫 묶음은 세 번째 묶음이 시작될 때까지 끝나지 않습니다(느린 묶음).
                    self.assert_true(slow_release.wait(5))
                if student_id == "2":
                    slow_release.set()
                return BehaviorGenerationResult(
                    [BehaviorStudentResult(student_id, "ok", "", f"문장 {student_id}임.")], "ok"
                )

            @staticmethod
            def assert_true(value):
                if not value:
                    raise AssertionError("느린 묶음을 기다리느라 다음 묶음이 시작되지 않았습니다.")

        got = []
        worker.succeeded.connect(got.append)
        with patch("neis_v4.ui.behavior_tab.OpenAIProvider", lambda key: FakeProvider()):
            worker.run()
        self.assertEqual([item.student_id for item in got[0].results], ["0", "1", "2"])
        # 세 번째 묶음은 먼저 끝난 두 번째 묶음의 문장을 중복 방지 참고로 받습니다.
        self.assertIn("문장 1임.", seen_previous["2"])
        self.assertEqual(seen_previous["0"], [])


class RosterAndDraftTests(unittest.TestCase):
    def test_roster_signals_only_when_names_change(self) -> None:
        rows = [StudentRow("학생 1", "", "a"), StudentRow("학생 2", "", "b")]
        roster = StudentRoster(rows)
        emitted = []
        roster.changed.connect(lambda: emitted.append(1))
        roster.replace([StudentRow("학생 1", "평어임.", "a"), StudentRow("학생 2", "", "b")])
        self.assertEqual(emitted, [])
        self.assertEqual(roster.rows()[0].content, "평어임.")  # 내용은 그대로 반영됩니다.
        roster.replace([StudentRow("학생 1", "평어임.", "a"), StudentRow("새 이름", "", "b")])
        self.assertEqual(emitted, [1])

    def test_typing_in_draft_redraws_list_only_when_status_changes(self) -> None:
        rows = [StudentRow("학생 1")]
        work = BehaviorWork(students=[BehaviorStudentState(rows[0].student_id, "학생 1")])
        tab = BehaviorTab(Storage(), AppSettings(), _NoKeys(), StudentRoster(rows), work)
        try:
            with patch.object(tab, "_refresh_students") as refresh, patch.object(tab, "_schedule_save"):
                tab.draft.setPlainText("가")  # 빈칸 → 완료: 다시 그림
                tab.draft.setPlainText("가나")  # 완료 → 완료: 다시 그리지 않음
                tab.draft.setPlainText("가나다")
            self.assertEqual(refresh.call_count, 1)
        finally:
            tab.close()


class _NoKeys:
    def get_api_key(self, provider):
        return ""

    def key_status_text(self, provider):
        return ""

    def registered_providers(self):
        return []

    def uses_bundled_key(self, provider):
        return False


if __name__ == "__main__":
    unittest.main()
