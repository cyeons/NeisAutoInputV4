from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from neis_v4.ai.behavior_prompt import BEHAVIOR_RESPONSE_SCHEMA, build_behavior_prompt
from neis_v4.ai.behavior_response import (
    comment_metrics,
    map_behavior_results,
)
from neis_v4.behavior_catalog import BehaviorCatalog
from neis_v4.models import (
    AppSettings,
    BehaviorGenerationRequest,
    BehaviorGenerationResult,
    BehaviorStudentInput,
    BehaviorStudentResult,
    BehaviorStudentState,
    BehaviorTraitSelection,
    BehaviorWork,
    StudentRow,
)
from neis_v4.roster import StudentRoster
from neis_v4.storage import Storage
from neis_v4.ui.behavior_tab import BehaviorTab
from neis_v4.ui.behavior_tab import BehaviorGenerationWorker
from neis_v4.ui.widgets import ChoiceSegmentedControl


def valid_comment(length: int = 250, sentence_count: int = 6) -> str:
    base = length // sentence_count
    remainder = length % sentence_count
    sentences = []
    for index in range(sentence_count):
        size = base + (1 if index < remainder else 0)
        sentences.append("가" * (size - 2) + "함.")
    return "".join(sentences)


class FakeSecrets:
    def get_api_key(self, _provider: str) -> str:
        return ""

    def set_api_key(self, _provider: str, _key: str) -> bool:
        return True


class BehaviorCatalogTests(unittest.TestCase):
    def test_catalog_has_unique_ids_and_expected_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = BehaviorCatalog(Storage(Path(temporary)))
            self.assertEqual(len(catalog.traits), len(set(catalog.traits)))
            subject_labels = [label for _key, label in catalog.category_definitions("subject")]
            self.assertNotIn("실과", subject_labels)
            self.assertNotIn("통합교과", subject_labels)
            self.assertIn("기타", subject_labels)
            other = catalog.traits_for("subject", "other")
            self.assertIn("도구 사용", [item.label for item in other])
            self.assertIn("학교생활", [item.label for item in other])

    def test_custom_trait_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            catalog = BehaviorCatalog(storage)
            created = catalog.add_custom("차분한 탐색", "behavior", "confidence")
            loaded = BehaviorCatalog(storage)
            self.assertEqual(loaded.get(created.trait_id).label, "차분한 탐색")
            loaded.remove_custom(created.trait_id)
            self.assertIsNone(BehaviorCatalog(storage).get(created.trait_id))


class BehaviorResponseTests(unittest.TestCase):
    def test_response_schema_contains_only_generated_content_fields(self) -> None:
        properties = BEHAVIOR_RESPONSE_SCHEMA["properties"]["results"]["items"]["properties"]
        self.assertNotIn("status", properties)
        self.assertNotIn("reason", properties)

    def test_result_mapping_uses_student_ids(self) -> None:
        students = [
            BehaviorStudentInput(
                student_id="a",
                sentence_count=6,
                traits=[{"trait_id": "t1"}],
            ),
            BehaviorStudentInput(
                student_id="b",
                sentence_count=6,
                traits=[{"trait_id": "t2"}],
            ),
        ]
        request = BehaviorGenerationRequest("Gemini", "test", students)
        raw = [
            {
                "student_id": "b",
                "comment": valid_comment(),
                "used_trait_ids": ["t2"],
                "omitted_trait_ids": [],
            },
            {
                "student_id": "a",
                "comment": valid_comment(),
                "used_trait_ids": ["t1"],
                "omitted_trait_ids": [],
            },
        ]
        results = map_behavior_results(request, raw)
        self.assertEqual([item.student_id for item in results], ["a", "b"])
        self.assertTrue(all(item.status == "ok" for item in results))
        self.assertEqual(results[0].character_count, 250)

    def test_prompt_contains_no_student_name_field(self) -> None:
        request = BehaviorGenerationRequest(
            "OpenAI",
            "test",
            [
                BehaviorStudentInput(
                    "anonymous-id",
                    6,
                    [
                        {
                            "trait_id": "t1",
                            "label": "책임감",
                            "level": "strength",
                            "meaning": "책임감 특성이 뚜렷하게 관찰됨",
                        }
                    ],
                )
            ],
        )
        prompt = build_behavior_prompt(request)
        self.assertIn("anonymous-id", prompt)
        self.assertNotIn("student_name", prompt)
        self.assertNotIn('"name"', prompt)

    def test_behavior_prompt_appends_custom_prompt(self) -> None:
        request = BehaviorGenerationRequest(
            "OpenAI",
            "test",
            [
                BehaviorStudentInput(
                    "anonymous-id",
                    3,
                    [{"trait_id": "t1", "label": "책임감"}],
                )
            ],
            custom_prompt="친절하고 담백한 문체로 작성",
        )

        prompt = build_behavior_prompt(request)

        self.assertTrue(prompt.endswith("친절하고 담백한 문체로 작성"))
        self.assertIn("# 사용자 추가 지시", prompt)
        self.assertIn("충돌하지 않는 범위", prompt)

    def test_metrics_are_informational_only(self) -> None:
        metrics = comment_metrics("짧은 문장임.")
        self.assertEqual(metrics["sentence_count"], 1)
        self.assertEqual(metrics["character_count"], 7)

    def test_missing_or_empty_result_is_failed(self) -> None:
        request = BehaviorGenerationRequest(
            "OpenAI",
            "test",
            [BehaviorStudentInput("anonymous-id", 3, [])],
        )
        result = map_behavior_results(request, [])[0]
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.comment)


class BehaviorStorageTests(unittest.TestCase):
    def test_work_round_trip_and_id_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            work = BehaviorWork(
                default_sentence_count=7,
                students=[
                    BehaviorStudentState(
                        student_id="stable-id",
                        name_snapshot="가람",
                        traits=[BehaviorTraitSelection("t1", "strength", "책임감")],
                    )
                ],
            )
            storage.save_behavior_work(work)
            loaded = storage.load_behavior_work()
            self.assertEqual(loaded.default_sentence_count, 7)
            rows = storage.reconcile_student_ids([StudentRow("가람")], loaded)
            self.assertEqual(rows[0].student_id, "stable-id")

    def test_saved_work_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            storage.save_behavior_work(BehaviorWork())
            value = json.loads(storage.behavior_work_path.read_text(encoding="utf-8"))
            self.assertEqual(value["schema_version"], 3)
            self.assertEqual(value["default_sentence_count"], 3)

    def test_schema_one_work_migrates_to_three_sentences(self) -> None:
        migrated = BehaviorWork.from_dict(
            {"schema_version": 1, "default_sentence_count": 6, "students": []}
        )
        self.assertEqual(migrated.schema_version, 3)
        self.assertEqual(migrated.default_sentence_count, 3)


class BehaviorUiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_behavior_tab_builds_and_selects_trait(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            roster = StudentRoster([StudentRow("학생 1")])
            tab = BehaviorTab(
                storage,
                AppSettings(),
                FakeSecrets(),
                roster,
                BehaviorWork(),
            )
            self.assertEqual(tab.student_list.count(), 1)
            trait_id = next(iter(tab.catalog.traits))
            tab._set_trait_level(trait_id, "strength")
            self.assertEqual(tab._current_state().traits[0].level, "strength")
            tab.close()

    def test_behavior_work_counter_only_counts_traits_or_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            rows = [StudentRow("학생 1"), StudentRow("학생 2"), StudentRow("학생 3")]
            roster = StudentRoster(rows)
            work = BehaviorWork(
                students=[
                    BehaviorStudentState(
                        student_id=rows[0].student_id,
                        traits=[BehaviorTraitSelection("t1", "standard", "경청")],
                    ),
                    BehaviorStudentState(
                        student_id=rows[1].student_id,
                        draft="작성 중인 초안",
                    ),
                    BehaviorStudentState(
                        student_id=rows[2].student_id,
                        sentence_count_override=7,
                    ),
                ]
            )
            tab = BehaviorTab(storage, AppSettings(), FakeSecrets(), roster, work)
            self.assertEqual(
                tab.count_students_with_work([row.student_id for row in rows]),
                2,
            )
            tab.close()

    def test_sentence_override_is_numeric_and_trait_level_is_one_click(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            row = StudentRow("학생 1")
            roster = StudentRoster([row])
            tab = BehaviorTab(
                storage,
                AppSettings(),
                FakeSecrets(),
                roster,
                BehaviorWork(),
            )
            trait_id = next(iter(tab.catalog.traits))
            tab._set_trait_level(trait_id, "standard")

            self.assertEqual(tab.default_sentence_count.value(), 3)
            tab.default_sentence_count.setValue(1)
            self.assertEqual(tab.work.default_sentence_count, 1)
            tab.sentence_override.setValue(7)
            self.assertEqual(tab._current_state().sentence_count_override, 7)
            tab.default_sentence_count.setValue(8)
            self.assertEqual(tab.work.default_sentence_count, 8)
            tab.default_sentence_count.edit.setText("7")
            tab.default_sentence_count.edit.editingFinished.emit()
            self.assertEqual(tab.work.default_sentence_count, 7)
            tab._reset_override()
            self.assertIsNone(tab._current_state().sentence_count_override)

            trait_row = tab.selected_traits.itemWidget(tab.selected_traits.item(1))
            selector = trait_row.findChild(ChoiceSegmentedControl)
            selector.button("growth").click()
            self.assertEqual(tab._current_state().traits[0].level, "growth")
            tab.close()

    def test_one_sentence_randomly_requires_one_trait(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            row = StudentRow("학생 1")
            tab = BehaviorTab(
                storage,
                AppSettings(),
                FakeSecrets(),
                StudentRoster([row]),
                BehaviorWork(default_sentence_count=1),
            )
            trait_ids = list(tab.catalog.traits)[:3]
            for trait_id in trait_ids:
                tab._set_trait_level(trait_id, "standard")
            chosen = tab.catalog.get(trait_ids[1])
            with patch("neis_v4.ui.behavior_tab.random.choice", return_value={
                "trait_id": chosen.trait_id
            }):
                student_input = tab._student_input(tab._current_state())
            roles = {
                trait["trait_id"]: trait["generation_role"]
                for trait in student_input.traits
            }
            self.assertEqual(student_input.sentence_count, 1)
            self.assertEqual(roles[trait_ids[1]], "required")
            self.assertEqual(
                [trait_id for trait_id, role in roles.items() if role == "omit"],
                [trait_ids[0], trait_ids[2]],
            )
            tab.close()

    def test_generation_failure_is_visible_and_preserves_existing_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            row = StudentRow("학생 1")
            old_draft = valid_comment(length=250, sentence_count=3)
            work = BehaviorWork(
                students=[
                    BehaviorStudentState(
                        student_id=row.student_id,
                        draft=old_draft,
                        status="ok",
                    )
                ]
            )
            tab = BehaviorTab(
                storage,
                AppSettings(),
                FakeSecrets(),
                StudentRoster([row]),
                work,
            )
            message = "503 UNAVAILABLE: The model is overloaded."
            tab._on_generated(
                BehaviorGenerationResult(
                    results=[
                        BehaviorStudentResult(
                            student_id=row.student_id,
                            status="failed",
                            comment="",
                            reason=message,
                        )
                    ],
                    raw_text="",
                )
            )

            self.assertEqual(tab._current_state().draft, old_draft)
            self.assertIn("503 UNAVAILABLE", tab.result_info.text())
            self.assertIn("생성 실패 1명", tab.status.text())
            tab.close()

    def test_generated_draft_applies_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary))
            row = StudentRow("학생 1")
            short_draft = "책임감 있는 태도로 맡은 일을 성실하게 수행함."
            work = BehaviorWork(
                students=[
                    BehaviorStudentState(
                        student_id=row.student_id,
                        draft=short_draft,
                        status="ok",
                    )
                ]
            )
            tab = BehaviorTab(
                storage,
                AppSettings(),
                FakeSecrets(),
                StudentRoster([row]),
                work,
            )
            applied = []
            tab.comments_ready.connect(applied.append)

            tab._apply_results()

            self.assertEqual(applied, [{row.student_id: short_draft}])
            self.assertEqual(tab.result_info.text(), "생성 완료")
            self.assertFalse(hasattr(tab, "apply_check"))
            tab.close()


class BehaviorWorkerTests(unittest.TestCase):
    def test_failed_batch_does_not_discard_successful_batches(self) -> None:
        students = [
            BehaviorStudentInput(str(index), 6, [{"trait_id": f"t{index}"}])
            for index in range(3)
        ]
        request = BehaviorGenerationRequest("OpenAI", "test", students)
        worker = BehaviorGenerationWorker(request, "test-key", batch_size=2)

        class FakeProvider:
            calls = 0

            def generate_behavior(self, batch_request):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("invalid request")
                return type(
                    "Generated",
                    (),
                    {
                        "results": [
                            type(
                                "Result",
                                (),
                                {
                                    "student_id": student.student_id,
                                    "status": "ok",
                                    "comment": valid_comment(),
                                },
                            )()
                            for student in batch_request.students
                        ],
                        "raw_text": "ok",
                        "repaired": False,
                    },
                )()

        captured = []
        worker.succeeded.connect(captured.append)
        import neis_v4.ui.behavior_tab as behavior_module

        original_provider = behavior_module.OpenAIProvider
        try:
            behavior_module.OpenAIProvider = lambda _key: FakeProvider()
            worker.run()
        finally:
            behavior_module.OpenAIProvider = original_provider

        self.assertEqual(len(captured), 1)
        self.assertEqual([item.status for item in captured[0].results], ["ok", "ok", "failed"])
        self.assertIn("invalid request", captured[0].results[-1].reason)

    def test_transient_provider_failure_is_retried(self) -> None:
        request = BehaviorGenerationRequest(
            "Gemini",
            "test",
            [BehaviorStudentInput("student-1", 3, [{"trait_id": "t1"}])],
        )
        worker = BehaviorGenerationWorker(request, "test-key", batch_size=1)

        class FakeProvider:
            calls = 0

            def generate_behavior(self, batch_request):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("503 UNAVAILABLE: model is experiencing high demand")
                return BehaviorGenerationResult(
                    results=[
                        BehaviorStudentResult(
                            student_id=batch_request.students[0].student_id,
                            status="ok",
                            reason="",
                            comment=valid_comment(length=250, sentence_count=3),
                        )
                    ],
                    raw_text="ok",
                )

        provider = FakeProvider()
        captured = []
        statuses = []
        worker.succeeded.connect(captured.append)
        worker.status_changed.connect(statuses.append)
        with (
            patch(
                "neis_v4.ui.behavior_tab.GeminiProvider",
                return_value=provider,
            ),
            patch.object(BehaviorGenerationWorker, "msleep", return_value=None),
        ):
            worker.run()

        self.assertEqual(provider.calls, 2)
        self.assertEqual(captured[0].results[0].status, "ok")
        self.assertTrue(any("재시도" in status for status in statuses))


if __name__ == "__main__":
    unittest.main()
