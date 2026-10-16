from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from neis_v4.models import (
    BehaviorGenerationRequest,
    BehaviorStudentInput,
    BehaviorStudentResult,
)


def normalize_comment(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip())


def comment_metrics(text: str) -> dict[str, int]:
    normalized = normalize_comment(text)
    sentences = [
        item.strip()
        for item in re.split(r"[.!?]+", normalized)
        if item.strip()
    ]
    return {
        "character_count": len(normalized),
        "utf8_byte_count": len(normalized.encode("utf-8")),
        "sentence_count": len(sentences),
    }


def parse_behavior_response(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    value = json.loads(cleaned)
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise ValueError("행동발달 응답에 results 배열이 없습니다.")
    return [item for item in value["results"] if isinstance(item, dict)]


def map_behavior_results(
    request: BehaviorGenerationRequest,
    raw_results: list[dict[str, Any]],
) -> list[BehaviorStudentResult]:
    raw_by_id = {
        str(item.get("student_id", "")): item
        for item in raw_results
        if item.get("student_id")
    }
    return [
        _map_student_result(student, raw_by_id.get(student.student_id))
        for student in request.students
    ]


def _map_student_result(
    student: BehaviorStudentInput,
    item: dict[str, Any] | None,
) -> BehaviorStudentResult:
    if item is None:
        return BehaviorStudentResult(
            student_id=student.student_id,
            status="failed",
            reason="응답에서 학생 결과가 누락됨",
            comment="",
        )

    comment = normalize_comment(str(item.get("comment", "")))
    if not comment:
        return BehaviorStudentResult(
            student_id=student.student_id,
            status="failed",
            reason="생성된 문장이 비어 있음",
            comment="",
        )

    metrics = comment_metrics(comment)
    return BehaviorStudentResult(
        student_id=student.student_id,
        status="ok",
        reason="",
        comment=comment,
        used_trait_ids=[str(value) for value in item.get("used_trait_ids", [])],
        omitted_trait_ids=[str(value) for value in item.get("omitted_trait_ids", [])],
        character_count=metrics["character_count"],
        utf8_byte_count=metrics["utf8_byte_count"],
        sentence_count=metrics["sentence_count"],
    )
