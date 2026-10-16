from __future__ import annotations

import json
import unittest
from pathlib import Path


RESOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "achievement_standards.json"
)


class AchievementStandardsTests(unittest.TestCase):
    def test_grade_56_uses_2022_revised_standards(self) -> None:
        data = json.loads(RESOURCE_PATH.read_text(encoding="utf-8"))
        grade = next(item for item in data["grades"] if item["grade"] == "5~6학년군")

        subjects = [item["subject"] for item in grade["subjects"]]
        self.assertEqual(
            subjects,
            ["국어", "사회", "도덕", "수학", "과학", "실과", "체육", "음악", "미술", "영어"],
        )
        self.assertEqual(len(subjects), len(set(subjects)))

        standards = [
            standard
            for subject in grade["subjects"]
            for domain in subject["domains"]
            for standard in domain["standards"]
        ]
        self.assertEqual(len(standards), 280)
        self.assertEqual(len({item["code"] for item in standards}), 280)
        self.assertTrue(
            all(item["explanation"].startswith("성취수준(B): ") for item in standards)
        )

        by_code = {item["code"]: item["description"] for item in standards}
        self.assertEqual(
            by_code["[6국06-01]"],
            "정보 검색 도구를 활용하여 자신의 목적에 맞는 매체 자료를 찾는다.",
        )
        self.assertEqual(
            by_code["[6실05-05]"],
            "인공지능이 만들어지는 과정을 체험하고, 인공지능이 사회에 미치는 영향을 탐색한다.",
        )


if __name__ == "__main__":
    unittest.main()
