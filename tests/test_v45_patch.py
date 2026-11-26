"""V4.5 패치: 오류 안내, 기본 키 만료 안내, 자동 입력 클립보드 복원, 표 자동 저장, 행동발달 중지."""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidgetItem

from neis_v4.ai.base import describe_error
from neis_v4.automation.runner import MacroRunner
from neis_v4.models import (
    AppSettings,
    BehaviorGenerationRequest,
    BehaviorGenerationResult,
    BehaviorStudentInput,
    BehaviorStudentResult,
    StudentRow,
)
from neis_v4.roster import StudentRoster
from neis_v4.secrets import (
    BUNDLED_KEY_EXPIRES,
    SecretStore,
    bundled_key_expired,
    no_key_message,
    obfuscate_key,
)
from neis_v4.storage import Storage
from neis_v4.ui.behavior_tab import BehaviorGenerationWorker
from neis_v4.ui.neis_tab import NeisTab


class StatusError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class DescribeErrorTests(unittest.TestCase):
    def test_common_errors_get_korean_hint_and_keep_original(self) -> None:
        rejected = describe_error(StatusError("Error code: 401 - Incorrect API key provided", 401))
        self.assertIn("API 키가 거절", rejected)
        self.assertIn("Incorrect API key", rejected)  # 원문도 함께 보여 줌
        busy = describe_error(StatusError("Error code: 429 - rate limit", 429))
        self.assertIn("1분쯤 뒤", busy)
        self.assertIn("429", busy)  # 행동발달 자동 재시도는 원문의 429를 보고 판단함
        self.assertTrue(BehaviorGenerationWorker._is_transient_error(RuntimeError(busy)))

    def test_unknown_error_is_left_as_is(self) -> None:
        self.assertEqual(describe_error(ValueError("줄 수가 맞지 않음")), "줄 수가 맞지 않음")


class BundledKeyExpiryTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(sys.modules, {"neis_v4._bundled_key": types.SimpleNamespace(DATA=obfuscate_key("up_fake"))})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_days_left_shown_in_last_month(self) -> None:
        store = SecretStore()
        store._keyring = None
        near = BUNDLED_KEY_EXPIRES - timedelta(days=10)
        with patch("neis_v4.secrets.date") as fake_date:
            fake_date.today.return_value = near
            self.assertEqual(store.key_status_text("Upstage"), "Upstage 기본 키 · 10일 뒤 끝남")

    def test_expired_bundled_key_explains_why_upstage_is_off(self) -> None:
        after = BUNDLED_KEY_EXPIRES + timedelta(days=1)
        self.assertTrue(bundled_key_expired(after))
        self.assertIn("무료 사용 기간", no_key_message(after))
        self.assertNotIn("무료 사용 기간", no_key_message(BUNDLED_KEY_EXPIRES))


class RunnerClipboardTests(unittest.TestCase):
    def test_original_clipboard_is_restored_after_input(self) -> None:
        clipboard = {"text": "선생님이 복사해 둔 글"}
        fake_pyperclip = types.SimpleNamespace(
            paste=lambda: clipboard["text"],
            copy=lambda text: clipboard.__setitem__("text", text),
        )
        modules = {"keyboard": MagicMock(), "pyautogui": MagicMock(), "pyperclip": fake_pyperclip}
        with patch.dict(sys.modules, modules), patch("neis_v4.automation.runner.time.sleep"):
            runner = MacroRunner([StudentRow("학생 1", "입력할 문장")], 2, 0.0, False, True, start_delay=0)
            runner.run()
        self.assertEqual(runner.entered, 1)
        self.assertEqual(clipboard["text"], "선생님이 복사해 둔 글")


class TableAutosaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_edit_schedules_save_to_data_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            tab = NeisTab(storage, AppSettings(), StudentRoster([StudentRow("학생 1")]))
            tab.table.setItem(0, 1, QTableWidgetItem("고친 내용"))
            self.assertTrue(tab._autosave_timer.isActive())
            tab._autosave()
            self.assertEqual(storage.load_saved_students()[0].content, "고친 내용")
            tab._autosave_timer.stop()
            tab.close()


class BehaviorStopTests(unittest.TestCase):
    def test_stop_keeps_finished_batches_and_skips_the_rest(self) -> None:
        students = [BehaviorStudentInput(str(index), 3, [{"trait_id": "t"}]) for index in range(4)]
        request = BehaviorGenerationRequest("OpenAI", "test", students)
        worker = BehaviorGenerationWorker(request, "key", batch_size=2, parallel_batches=1)

        class FakeProvider:
            def generate_behavior(self, batch_request):
                worker.request_stop()  # 첫 묶음을 처리하는 동안 중지 버튼을 누른 상황
                return BehaviorGenerationResult(
                    [BehaviorStudentResult(s.student_id, "ok", "", "문장임.") for s in batch_request.students],
                    "ok",
                )

        captured = []
        worker.succeeded.connect(captured.append)
        with patch("neis_v4.ui.behavior_tab.OpenAIProvider", return_value=FakeProvider()):
            worker.run()
        self.assertEqual([item.student_id for item in captured[0].results], ["0", "1"])


if __name__ == "__main__":
    unittest.main()
