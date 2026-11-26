from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from neis_v4 import APP_DISPLAY_NAME, APP_VERSION_LABEL
from neis_v4.ai.base import build_prompt, parse_comments
from neis_v4.ai.model_catalog import (
    filter_text_models, model_ids, models_for, normalize_model, provider_ids, provider_spec, set_fetched_models,
)
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
from neis_v4.ui.ai_tab import AiTab, replace_lines, selected_line_numbers
from neis_v4.ui.behavior_tab import BehaviorTab
from neis_v4.ui.main_window import MainWindow


class MemorySecrets:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get_api_key(self, provider: str) -> str:
        return self.values.get(provider, "")

    def get_user_api_key(self, provider: str) -> str:
        return self.get_api_key(provider)

    def uses_bundled_key(self, _provider: str) -> bool:
        return False

    def key_status_text(self, provider: str) -> str:
        return f"{provider} 등록됨"

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
        return [item for item in ("Gemini", "OpenAI", "Claude", "Upstage") if self.has_api_key(item)]

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
        self.assertEqual(model_ids("OpenAI"), ("gpt-6-luna", "gpt-6.1-terra", "gpt-6.2-sol"))
        self.assertEqual(
            model_ids("Gemini"),
            ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-hydrogen", "gemini-4-neon"),
        )
        self.assertEqual(
            model_ids("Claude"),
            ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"),
        )
        # 권장 모델은 목록 맨 앞에 '권장'으로 보이고, 처음 쓰는 사용자의 기본값입니다.
        defaults = AppSettings()
        for provider, model in (("Gemini", "gemini-3.5-flash-lite"), ("OpenAI", "gpt-6-luna"), ("Claude", "claude-haiku-5-5")):
            first = models_for(provider)[0]
            self.assertEqual((first.model_id, provider_spec(provider).default_model_id), (model, model))
            self.assertIn("권장", first.display_name)
            self.assertEqual(getattr(defaults, AppSettings._model_field(provider, False)), model)
            self.assertEqual(getattr(defaults, AppSettings._model_field(provider, True)), model)
        self.assertEqual(normalize_model("OpenAI", "gpt-5.5"), "gpt-6-luna")
        # 지원이 끝난 예전 모델은 기본 모델로 바뀝니다.
        self.assertEqual(normalize_model("Gemini", "gemini-3.5-flash"), "gemini-3.5-flash-lite")
        self.assertEqual(normalize_model("OpenAI", "gpt-5.4-nano"), "gpt-6-luna")

    def test_fetched_models_are_filtered_saved_and_kept(self) -> None:
        listed = ["gpt-7", "gpt-7-2026-10-01", "gpt-7-audio", "gpt-7-realtime", "gpt-image-3", "gpt-6.1-terra"]
        self.assertEqual(filter_text_models(listed), ["gpt-7", "gpt-6.1-terra"])
        self.addCleanup(set_fetched_models, "OpenAI", [])
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            storage.save_fetched_models("OpenAI", ["gpt-7", "gpt-6.1-terra"])
            # 기본 목록에 있는 모델은 두 번 들어가지 않고, 불러온 모델은 저장된 설정에서 지워지지 않습니다.
            self.assertEqual(model_ids("OpenAI")[-1], "gpt-7")
            self.assertEqual(model_ids("OpenAI").count("gpt-6.1-terra"), 1)
            set_fetched_models("OpenAI", [])
            storage.save_settings(AppSettings(openai_model="gpt-7"))
            self.assertEqual(storage.load_settings().openai_model, "gpt-7")

    def test_choose_models_keeps_previous_checks(self) -> None:
        from PySide6.QtWidgets import QDialog

        from neis_v4.ui.api_keys import choose_models

        # 창을 띄우는 대신 바로 '목록에 넣기'를 누른 것으로 칩니다.
        with patch.object(QDialog, "exec", lambda self: QDialog.Accepted):
            chosen = choose_models(None, "OpenAI", ["gpt-7", "gpt-7-mini"], ["gpt-7-mini"])
        self.assertEqual(chosen, ["gpt-7-mini"])
        with patch.object(QDialog, "exec", lambda self: QDialog.Rejected):
            self.assertIsNone(choose_models(None, "OpenAI", ["gpt-7"], []))

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
                        "claude_model": "claude-2",
                    }
                ),
                encoding="utf-8",
            )
            settings = Storage(root).load_settings()
            self.assertEqual(settings.openai_model, "gpt-6-luna")
            self.assertEqual(settings.gemini_model, "gemini-3.5-flash-lite")
            self.assertEqual(settings.behavior_openai_model, "gpt-6-luna")
            self.assertEqual(settings.behavior_gemini_model, "gemini-3.5-flash-lite")
            self.assertEqual(settings.claude_model, "claude-haiku-5-5")
            self.assertEqual(settings.behavior_claude_model, "claude-haiku-5-5")

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


class ParseCommentsTests(unittest.TestCase):
    def test_list_markers_and_blank_lines_are_removed(self) -> None:
        text = "1. 첫째 평어임.\n\n2) 둘째 평어임.\n- 셋째 평어임.\n3학년 내용을 이해함.\n1.5배 빠르게 계산함."
        self.assertEqual(
            parse_comments(text),
            ["첫째 평어임.", "둘째 평어임.", "셋째 평어임.", "3학년 내용을 이해함.", "1.5배 빠르게 계산함."],
        )


class RegenerateLinesTests(unittest.TestCase):
    def test_selected_line_numbers_skip_blank_lines(self) -> None:
        text = "첫째\n\n셋째\n넷째"
        self.assertEqual(selected_line_numbers(text, 0, 0), [0])
        # 첫째 줄 가운데부터 셋째 줄까지 드래그
        self.assertEqual(selected_line_numbers(text, 1, text.index("셋째") + 1), [0, 2])
        self.assertEqual(selected_line_numbers(text, len(text), len(text)), [3])

    def test_replace_lines_keeps_other_lines(self) -> None:
        self.assertEqual(
            replace_lines("가\n나\n다", [0, 2], ["새 가", "새 다"]),
            "새 가\n나\n새 다",
        )


class SecretStoreTests(unittest.TestCase):
    def test_provider_keys_are_separate_and_deletable(self) -> None:
        store = SecretStore()
        store._keyring = FakeKeyring()
        with patch("neis_v4.secrets.bundled_api_key", lambda: ""):
            self._check_separate_keys(store)

    def _check_separate_keys(self, store: SecretStore) -> None:
        self.assertTrue(store.set_api_key("OpenAI", "openai-key"))
        self.assertTrue(store.set_api_key("Gemini", "gemini-key"))
        self.assertTrue(store.set_api_key("Claude", "claude-key"))
        self.assertEqual(store.registered_providers(), ["Gemini", "OpenAI", "Claude"])
        self.assertTrue(store.delete_api_key("OpenAI"))
        self.assertEqual(store.get_api_key("OpenAI"), "")
        self.assertEqual(store.get_api_key("Gemini"), "gemini-key")

    def test_solar_uses_bundled_key_until_user_key_is_saved(self) -> None:
        store = SecretStore()
        store._keyring = FakeKeyring()
        with patch("neis_v4.secrets.bundled_api_key", lambda: "bundled"):
            self.assertEqual(store.get_api_key("Upstage"), "bundled")
            self.assertEqual(store.get_api_key("Gemini"), "")
            self.assertTrue(store.uses_bundled_key("Upstage"))
            self.assertIn("기본 키", store.key_status_text("Upstage"))
            self.assertEqual(store.registered_providers(), ["Upstage"])
            store.set_api_key("Upstage", "mine")
            self.assertEqual(store.get_api_key("Upstage"), "mine")
            self.assertFalse(store.uses_bundled_key("Upstage"))
            store.delete_api_key("Upstage")
            self.assertEqual(store.get_api_key("Upstage"), "bundled")


class ProviderUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_new_install_starts_with_solar_bundled_key(self) -> None:
        store = SecretStore()
        store._keyring = FakeKeyring()
        with patch("neis_v4.secrets.bundled_api_key", lambda: "bundled"):
            tab = AiTab(Storage(), AppSettings(), store)
            self.assertEqual(tab.provider.value(), "Upstage")
            self.assertEqual(tab.model.model_id(), "solar-pro4")
            self.assertIn("기본 키", tab.key_status.text())
            tab.close()

    def test_only_registered_provider_can_be_selected(self) -> None:
        settings = AppSettings(ai_provider="Gemini")
        tab = AiTab(Storage(), settings, MemorySecrets({"OpenAI": "key"}))
        self.assertEqual(tab.provider.value(), "OpenAI")
        self.assertFalse(tab.provider.button("Gemini").isEnabled())
        self.assertTrue(tab.provider.button("OpenAI").isEnabled())
        self.assertFalse(tab.model.isEditable())
        self.assertEqual(
            [tab.model.itemData(index) for index in range(tab.model.count())],
            ["gpt-6-luna", "gpt-6.1-terra", "gpt-6.2-sol"],
        )
        tab.close()

    def test_main_window_uses_display_name_and_sidebar_version(self) -> None:
        # 실제 작업 파일(config.json·data.csv 등)과 API 키를 건드리지 않도록 임시 폴더만 씁니다.
        with tempfile.TemporaryDirectory() as temporary, patch(
            "neis_v4.ui.main_window.Storage", lambda: Storage(Path(temporary))
        ), patch("neis_v4.ui.main_window.SecretStore", MemorySecrets), patch(
            "neis_v4.storage.executable_dir", lambda: Path(temporary)
        ), patch("neis_v4.storage.legacy_dir", lambda: None):
            self._check_main_window()

    def _check_main_window(self) -> None:
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

    def test_new_version_is_announced_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "neis_v4.ui.main_window.Storage", lambda: Storage(Path(temporary))
        ), patch("neis_v4.ui.main_window.SecretStore", MemorySecrets), patch(
            "neis_v4.storage.executable_dir", lambda: Path(temporary)
        ), patch("neis_v4.storage.legacy_dir", lambda: None):
            window = MainWindow()
            try:
                url = "https://github.com/cyeons/NeisAutoInputV4/releases/tag/v9.0.0"
                with patch.object(QMessageBox, "exec") as shown:
                    window._on_update_found("v9.0.0", url)
                    window._on_update_found("v9.0.0", url)
                shown.assert_called_once()
                self.assertIn("새 버전 v9.0.0", window.version_label.text())
                self.assertIn(url, window.version_label.text())
                self.assertEqual(Storage(Path(temporary)).load_settings().notified_update_version, "v9.0.0")
            finally:
                window.close()

    def test_ai_result_goes_straight_to_neis_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "neis_v4.ui.main_window.Storage", lambda: Storage(Path(temporary))
        ), patch("neis_v4.ui.main_window.SecretStore", MemorySecrets), patch(
            "neis_v4.storage.executable_dir", lambda: Path(temporary)
        ), patch("neis_v4.storage.legacy_dir", lambda: None):
            window = MainWindow()
            try:
                window.neis_tab.set_rows(
                    [StudentRow("학생 1", "이전 내용"), StudentRow("학생 2", "이전 내용"), StudentRow("학생 3", "남은 행")]
                )
                window.ai_tab.result.setPlainText("평어 1\n평어 2")
                with patch.object(window.neis_tab, "start_macro") as start:
                    window.ai_tab.input_controls.button.click()
                rows, tab_count = start.call_args.args
                # 결과 칸에 보이는 줄만, 평어 화면의 이동 칸(기본 Tab 3번)으로 입력합니다.
                self.assertEqual([row.content for row in rows], ["평어 1", "평어 2"])
                self.assertEqual(tab_count, 3)
                self.assertEqual(
                    [row.content for row in window.neis_tab.rows()], ["평어 1", "평어 2", "남은 행"]
                )
                # 자동 입력 상태가 평어·행발 화면 버튼에도 보입니다.
                window.neis_tab._hotkey_armed = True
                window.neis_tab._announce("시작 키를 누르세요.")
                self.assertEqual(window.ai_tab.input_controls.button.text(), "시작 대기 취소")
                self.assertEqual(window.behavior_tab.input_controls.button.text(), "시작 대기 취소")
                self.assertEqual(window.ai_tab.status.text(), "시작 키를 누르세요.")
            finally:
                window.neis_tab._hotkey_armed = False
                window.close()

    def test_behavior_and_ai_keep_independent_models(self) -> None:
        settings = AppSettings(
            ai_provider="Claude",
            claude_model="claude-haiku-5-5",
            behavior_provider="Gemini",
            behavior_gemini_model="gemini-3.5-flash-lite",
        )
        secrets = MemorySecrets({"OpenAI": "a", "Gemini": "b", "Claude": "c"})
        ai = AiTab(Storage(), settings, secrets)
        behavior = BehaviorTab(
            Storage(),
            settings,
            secrets,
            StudentRoster([StudentRow("학생")]),
            BehaviorWork(),
        )
        self.assertEqual(ai.provider.value(), "Claude")
        self.assertEqual(ai.model.model_id(), "claude-haiku-5-5")
        self.assertEqual(behavior.provider.value(), "Gemini")
        self.assertEqual(behavior.model.model_id(), "gemini-3.5-flash-lite")
        self.assertFalse(behavior.model.isEditable())
        ai.close()
        behavior.close()

    def test_apply_result_uses_edited_text(self) -> None:
        tab = AiTab(Storage(), AppSettings(), MemorySecrets({"Gemini": "a"}))
        received: list[list[str]] = []
        tab.comment_sink = lambda comments: received.append(comments) or len(comments)
        tab.result.setPlainText("첫째 평어\n\n직접 고친 평어")
        self.assertTrue(tab.apply_button.isEnabled())
        tab._apply_result()
        self.assertEqual(received, [["첫째 평어", "직접 고친 평어"]])
        tab.close()

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

    def test_previous_outputs_come_with_no_overlap_instruction(self) -> None:
        request = GenerationRequest(
            provider="OpenAI",
            model="test",
            standards=[AchievementStandard("[4국01-01]", "대화의 즐거움을 안다.")],
            student_count=1,
            sentence_count=1,
        )
        instruction = "위 문장과 표현·구조가 겹치지 않게 작성하십시오."
        self.assertNotIn(instruction, build_prompt(request))
        request.previous_outputs = ["이미 만든 평어임."]
        prompt = build_prompt(request)
        self.assertIn("이미 만든 평어임.\n" + instruction, prompt)

    def test_upstage_is_listed_last(self) -> None:
        self.assertEqual(provider_ids()[-1], "Upstage")

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

    def test_changing_subject_clears_previous_result(self) -> None:
        tab = AiTab(Storage(), AppSettings(), MemorySecrets({"Gemini": "a"}))
        try:
            first, second = list(tab.subject_buttons)[:2]
            tab.result.setPlainText("이전 교과 평어")
            tab.last_comments = ["이전 교과 평어"]
            tab._result_unsent = True
            # 표에 넣지 않은 결과가 있으면 묻고, '아니요'면 교과를 그대로 둡니다.
            with patch("neis_v4.ui.ai_tab.QMessageBox.question", return_value=QMessageBox.No) as ask:
                tab.subject_buttons[second].click()
            ask.assert_called_once()
            self.assertEqual(tab.current_subject, first)
            self.assertTrue(tab.subject_buttons[first].isChecked())
            self.assertFalse(tab.subject_buttons[second].isChecked())
            self.assertEqual(tab.result.toPlainText(), "이전 교과 평어")

            first_grade = tab.grade.value()
            # 이미 고른 학년을 다시 눌러도 아무것도 바뀌지 않습니다.
            with patch("neis_v4.ui.ai_tab.QMessageBox.question") as ask:
                tab.grade.button(first_grade).click()
            ask.assert_not_called()
            self.assertEqual(tab.result.toPlainText(), "이전 교과 평어")
            other_grade = next(value for value in tab.grade._buttons if value != first_grade)
            with patch("neis_v4.ui.ai_tab.QMessageBox.question", return_value=QMessageBox.No):
                tab.grade.button(other_grade).click()
            self.assertEqual(tab.grade.value(), first_grade)
            self.assertEqual(tab.current_subject, first)

            # 이미 표에 넣은 결과는 묻지 않고 지웁니다.
            tab._result_unsent = False
            with patch("neis_v4.ui.ai_tab.QMessageBox.question") as ask:
                tab.subject_buttons[second].click()
            ask.assert_not_called()
            self.assertEqual(tab.current_subject, second)
            self.assertEqual(tab.result.toPlainText(), "")
            self.assertEqual(tab.last_comments, [])
        finally:
            tab.close()

    def test_other_subject_standards_can_be_dropped_before_generation(self) -> None:
        tab = AiTab(Storage(), AppSettings(ai_provider="OpenAI"), MemorySecrets({"OpenAI": "key"}))
        try:
            first, second = list(tab.subject_buttons)[:2]
            tab.standard_cards[0].check.setChecked(True)
            other_code = tab.standard_cards[0].standard.code
            tab.subject_buttons[second].click()
            tab.standard_cards[0].check.setChecked(True)
            current_code = tab.standard_cards[0].standard.code

            def press(label):
                return lambda box: next(b for b in box.buttons() if b.text() == label).click()

            with patch.object(QMessageBox, "exec", press("취소")), patch(
                "neis_v4.ui.ai_tab.GenerationWorker"
            ) as worker_class:
                tab._generate()
            worker_class.assert_not_called()
            with patch.object(QMessageBox, "exec", press("다른 교과 빼고 생성")), patch(
                "neis_v4.ui.ai_tab.GenerationWorker"
            ) as worker_class:
                tab._generate()
            request = worker_class.call_args.args[0]
            self.assertEqual([standard.code for standard in request.standards], [current_code])
            self.assertNotIn(other_code, tab.selected_standards)
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
