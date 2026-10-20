from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from neis_v4 import APP_DISPLAY_NAME, APP_VERSION_LABEL
from neis_v4.ai.base import build_prompt
from neis_v4.ai.model_catalog import model_ids, normalize_model
from neis_v4.models import (
    AchievementStandard,
    AppSettings,
    BehaviorStudentState,
    BehaviorTraitSelection,
    BehaviorWork,
    GenerationRequest,
    StudentRow,
)
from neis_v4.roster import StudentRoster
from neis_v4.secrets import SecretStore
from neis_v4.storage import Storage
from neis_v4.ui.ai_tab import AiTab
from neis_v4.ui.behavior_tab import BehaviorTab
from neis_v4.ui.main_window import MainWindow


class MemorySecrets:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get_api_key(self, provider: str) -> str:
        return self.values.get(provider, "")

    def set_api_key(self, provider: str, value: str) -> bool:
        if not value.strip():
            return False
        self.values[provider] = value.strip()
        return True

    def delete_api_key(self, provider: str) -> bool:
        self.values.pop(provider, None)
        return True

    def has_api_key(self, provider: str) -> bool:
        return bool(self.get_api_key(provider))

    def registered_providers(self) -> list[str]:
        return [item for item in ("Gemini", "OpenAI") if self.has_api_key(item)]

    def has_secure_backend(self) -> bool:
        return True


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str):
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        del self.values[(service, account)]


class ModelCatalogTests(unittest.TestCase):
    def test_only_supported_small_models_are_exposed(self) -> None:
        self.assertEqual(model_ids("OpenAI"), ("gpt-6-luna", "gpt-5.4-mini", "gpt-5.4-nano"))
        self.assertEqual(
            model_ids("Gemini"),
            ("gemini-3.5-flash", "gemini-3.1-flash-lite"),
        )
        self.assertEqual(normalize_model("OpenAI", "gpt-5.5"), "gpt-5.4-mini")

    def test_invalid_saved_models_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "ai_provider": "OpenAI",
                        "openai_model": "custom-model",
                        "gemini_model": "gemini-2.0-flash",
                        "behavior_openai_model": "gpt-5.5",
                        "behavior_gemini_model": "gemini-pro",
                    }
                ),
                encoding="utf-8",
            )
            settings = Storage(root).load_settings()
            self.assertEqual(settings.openai_model, "gpt-5.4-mini")
            self.assertEqual(settings.gemini_model, "gemini-3.5-flash")
            self.assertEqual(settings.behavior_openai_model, "gpt-5.4-mini")
            self.assertEqual(settings.behavior_gemini_model, "gemini-3.5-flash")

    def test_custom_prompts_round_trip_with_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            settings = AppSettings(
                ai_custom_prompt="표현을 더 간결하게 작성",
                behavior_custom_prompt="협력 태도를 중심으로 작성",
            )
            storage.save_settings(settings)

            loaded = storage.load_settings()

            self.assertEqual(loaded.ai_custom_prompt, "표현을 더 간결하게 작성")
            self.assertEqual(loaded.behavior_custom_prompt, "협력 태도를 중심으로 작성")

    def test_windows_trust_store_setting_defaults_on_and_round_trips(self) -> None:
        self.assertTrue(AppSettings().use_windows_trust_store)
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            storage.save_settings(AppSettings(use_windows_trust_store=False))

            loaded = storage.load_settings()

            self.assertFalse(loaded.use_windows_trust_store)


class SecretStoreTests(unittest.TestCase):
    def test_provider_keys_are_separate_and_deletable(self) -> None:
        store = SecretStore()
        store._keyring = FakeKeyring()
        self.assertTrue(store.set_api_key("OpenAI", "openai-key"))
        self.assertTrue(store.set_api_key("Gemini", "gemini-key"))
        self.assertEqual(store.registered_providers(), ["Gemini", "OpenAI"])
        self.assertTrue(store.delete_api_key("OpenAI"))
        self.assertEqual(store.get_api_key("OpenAI"), "")
        self.assertEqual(store.get_api_key("Gemini"), "gemini-key")


class ProviderUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_only_registered_provider_can_be_selected(self) -> None:
        settings = AppSettings(ai_provider="Gemini")
        tab = AiTab(Storage(), settings, MemorySecrets({"OpenAI": "key"}))
        self.assertEqual(tab.provider.value(), "OpenAI")
        self.assertFalse(tab.provider.button("Gemini").isEnabled())
        self.assertTrue(tab.provider.button("OpenAI").isEnabled())
        self.assertFalse(tab.model.isEditable())
        self.assertEqual(
            [tab.model.itemData(index) for index in range(tab.model.count())],
            ["gpt-6-luna", "gpt-5.4-mini", "gpt-5.4-nano"],
        )
        tab.close()

    def test_main_window_uses_display_name_and_sidebar_version(self) -> None:
        window = MainWindow()
        try:
            self.assertEqual(window.windowTitle(), APP_DISPLAY_NAME)
            captions = [
                label.text()
                for label in window.findChildren(QLabel)
                if label.objectName() == "SidebarCaption"
            ]
            self.assertIn(APP_VERSION_LABEL, captions)
        finally:
            window.close()

    def test_behavior_and_ai_keep_independent_models(self) -> None:
        settings = AppSettings(
            ai_provider="OpenAI",
            openai_model="gpt-5.4-nano",
            behavior_provider="Gemini",
            behavior_gemini_model="gemini-3.1-flash-lite",
        )
        secrets = MemorySecrets({"OpenAI": "a", "Gemini": "b"})
        ai = AiTab(Storage(), settings, secrets)
        behavior = BehaviorTab(
            Storage(),
            settings,
            secrets,
            StudentRoster([StudentRow("학생")]),
            BehaviorWork(),
        )
        self.assertEqual(ai.provider.value(), "OpenAI")
        self.assertEqual(ai.model.model_id(), "gpt-5.4-nano")
        self.assertEqual(behavior.provider.value(), "Gemini")
        self.assertEqual(behavior.model.model_id(), "gemini-3.1-flash-lite")
        self.assertFalse(behavior.model.isEditable())
        ai.close()
        behavior.close()

    def test_active_provider_falls_back_after_key_deletion(self) -> None:
        settings = AppSettings(ai_provider="OpenAI")
        secrets = MemorySecrets({"OpenAI": "a", "Gemini": "b"})
        tab = AiTab(Storage(), settings, secrets)
        secrets.delete_api_key("OpenAI")
        tab.refresh_api_keys()
        self.assertEqual(tab.provider.value(), "Gemini")
        self.assertFalse(tab.provider.button("OpenAI").isEnabled())
        self.assertFalse(tab.generate_button.isEnabled())
        tab.close()

    def test_standard_cards_support_filter_and_clear(self) -> None:
        tab = AiTab(
            Storage(),
            AppSettings(ai_provider="OpenAI"),
            MemorySecrets({"OpenAI": "key"}),
        )
        self.assertTrue(tab.standard_cards)
        first = tab.standard_cards[0]
        first.check.setChecked(True)
        self.assertEqual(tab.selected_chip_layout.count(), 2)
        chip = tab.selected_chip_layout.itemAt(0).widget()
        self.assertEqual(chip.text(), first.standard.code)
        self.assertNotIn("제거", chip.text())
        chip.click()
        self.assertFalse(first.check.isChecked())
        first.check.setChecked(True)
        tab.search.setText(first.standard.code)
        self.assertFalse(first.isHidden())
        tab._clear_standard_selection()
        self.assertFalse(first.check.isChecked())
        tab.close()

    def test_selected_standards_persist_across_subject_changes(self) -> None:
        tab = AiTab(
            Storage(),
            AppSettings(ai_provider="OpenAI"),
            MemorySecrets({"OpenAI": "key"}),
        )
        try:
            subjects = list(tab.subject_buttons)
            self.assertGreaterEqual(len(subjects), 2)
            first_subject = tab.current_subject
            other_subject = next(subject for subject in subjects if subject != first_subject)

            first_card = tab.standard_cards[0]
            selected_code = first_card.standard.code
            first_card.check.setChecked(True)

            tab._select_subject(other_subject)

            self.assertIn(selected_code, tab.selected_standards)
            self.assertEqual(tab.selection_status.text(), "성취기준 1개 · 학생 20명")
            self.assertEqual(tab.selected_chip_layout.itemAt(0).widget().text(), selected_code)
            self.assertEqual([standard.code for standard in tab._selected_standards()], [selected_code])

            tab._select_subject(first_subject)
            restored_card = next(
                card for card in tab.standard_cards if card.standard.code == selected_code
            )
            self.assertTrue(restored_card.check.isChecked())
        finally:
            tab.close()

    def test_ai_comment_supports_one_sentence_generation(self) -> None:
        tab = AiTab(
            Storage(),
            AppSettings(ai_provider="OpenAI"),
            MemorySecrets({"OpenAI": "key"}),
        )
        try:
            self.assertIsNotNone(tab.sentence_count.button("1"))
            tab.sentence_count.setValue("1")
            tab.standard_cards[0].check.setChecked(True)

            with patch("neis_v4.ui.ai_tab.GenerationWorker") as worker_class:
                worker = worker_class.return_value
                tab._generate()

            request = worker_class.call_args.args[0]
            self.assertEqual(request.sentence_count, 1)
            worker.succeeded.connect.assert_called()
            worker.failed.connect.assert_called()
            worker.finished.connect.assert_called()
            worker.start.assert_called_once()
        finally:
            tab.worker = None
            tab.close()

    def test_ai_prompt_describes_standard_distribution_rules(self) -> None:
        request = GenerationRequest(
            provider="OpenAI",
            model="test",
            standards=[
                AchievementStandard("[4국01-01]", "대화의 즐거움을 안다.", domain="듣기"),
                AchievementStandard("[4국02-01]", "중심 생각을 파악한다.", domain="읽기"),
            ],
            student_count=2,
            sentence_count=1,
        )

        prompt = build_prompt(request)

        self.assertIn("문장별 성취기준 배분 규칙", prompt)
        self.assertIn("성취기준 수가 학생 1인당 문장 수보다 많으면", prompt)
        self.assertIn("성취기준 수와 학생 1인당 문장 수가 같으면", prompt)
        self.assertIn("문장 수가 선택한 성취기준 수보다 많으면", prompt)
        self.assertIn("각 줄은 정확히 1개 문장만 작성", prompt)

    def test_ai_prompt_appends_custom_prompt_after_base_rules(self) -> None:
        request = GenerationRequest(
            provider="OpenAI",
            model="test",
            standards=[AchievementStandard("[4국01-01]", "대화의 즐거움을 안다.")],
            student_count=1,
            sentence_count=1,
            custom_prompt="더 담백한 문체로 작성",
        )

        prompt = build_prompt(request)

        self.assertTrue(prompt.endswith("더 담백한 문체로 작성"))
        self.assertIn("# 사용자 추가 지시", prompt)
        self.assertIn("충돌하지 않는 범위", prompt)

    def test_empty_custom_prompt_does_not_change_ai_prompt(self) -> None:
        base_request = GenerationRequest(
            provider="OpenAI",
            model="test",
            standards=[AchievementStandard("[4국01-01]", "대화의 즐거움을 안다.")],
            student_count=1,
            sentence_count=1,
        )
        custom_request = GenerationRequest(
            provider="OpenAI",
            model="test",
            standards=[AchievementStandard("[4국01-01]", "대화의 즐거움을 안다.")],
            student_count=1,
            sentence_count=1,
            custom_prompt="   ",
        )

        self.assertEqual(build_prompt(base_request), build_prompt(custom_request))

    def test_ai_custom_prompt_is_sent_to_generation_request(self) -> None:
        tab = AiTab(
            Storage(),
            AppSettings(ai_provider="OpenAI", ai_custom_prompt="짧게 작성"),
            MemorySecrets({"OpenAI": "key"}),
        )
        try:
            tab.standard_cards[0].check.setChecked(True)

            with patch("neis_v4.ui.ai_tab.GenerationWorker") as worker_class:
                tab._generate()

            request = worker_class.call_args.args[0]
            self.assertEqual(request.custom_prompt, "짧게 작성")
        finally:
            tab.worker = None
            tab.close()

    def test_behavior_student_status_filter(self) -> None:
        rows = [StudentRow("완료 학생"), StudentRow("준비 학생")]
        work = BehaviorWork(
            students=[
                BehaviorStudentState(rows[0].student_id, rows[0].name, status="ok"),
                BehaviorStudentState(
                    rows[1].student_id,
                    rows[1].name,
                    traits=[BehaviorTraitSelection("subject.korean.reading", "standard", "독서 습관")],
                ),
            ]
        )
        tab = BehaviorTab(
            Storage(),
            AppSettings(),
            MemorySecrets(),
            StudentRoster(rows),
            work,
        )
        tab.student_filter.setCurrentIndex(tab.student_filter.findData("ok"))
        self.assertEqual(tab.student_list.count(), 1)
        self.assertEqual(tab.student_list.item(0).data(Qt.UserRole), rows[0].student_id)
        tab.close()

    def test_behavior_custom_prompt_is_sent_to_generation_request(self) -> None:
        row = StudentRow("학생")
        tab = BehaviorTab(
            Storage(),
            AppSettings(
                behavior_provider="OpenAI",
                behavior_custom_prompt="협력 태도를 강조",
            ),
            MemorySecrets({"OpenAI": "key"}),
            StudentRoster([row]),
            BehaviorWork(),
        )
        try:
            trait_id = next(iter(tab.catalog.traits))
            tab._set_trait_level(trait_id, "standard")

            with patch("neis_v4.ui.behavior_tab.BehaviorGenerationWorker") as worker_class:
                tab._generate(False)

            request = worker_class.call_args.args[0]
            self.assertEqual(request.custom_prompt, "협력 태도를 강조")
        finally:
            tab.worker = None
            tab.close()


if __name__ == "__main__":
    unittest.main()
