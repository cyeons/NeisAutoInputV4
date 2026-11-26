from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from neis_v4.models import StudentRow


class StudentRoster(QObject):
    """Shared in-memory roster used by the NEIS and behavior screens."""

    changed = Signal()

    def __init__(self, rows: list[StudentRow], parent=None) -> None:
        super().__init__(parent)
        self._rows = list(rows)

    def rows(self) -> list[StudentRow]:
        return [StudentRow(row.name, row.content, row.student_id) for row in self._rows]

    def replace(self, rows: list[StudentRow], emit: bool = True) -> None:
        # changed는 명단(이름·순서·학생 수)이 바뀔 때만 보냅니다. 평어 내용만 고친 경우
        # 행동발달 화면이 명단을 다시 그리고 작업 파일을 다시 저장할 필요가 없습니다.
        names_changed = [(row.name, row.student_id) for row in rows] != [
            (row.name, row.student_id) for row in self._rows
        ]
        self._rows = list(rows)
        if emit and names_changed:
            self.changed.emit()

    def update_from_rows(self, rows: list[StudentRow]) -> None:
        existing_ids = [row.student_id for row in self._rows]
        normalized: list[StudentRow] = []
        for index, row in enumerate(rows):
            student_id = row.student_id
            if not student_id and index < len(existing_ids):
                student_id = existing_ids[index]
            normalized.append(StudentRow(row.name, row.content, student_id))
        self.replace(normalized)

    def update_content(self, contents: dict[str, str]) -> None:
        changed = False
        for row in self._rows:
            if row.student_id in contents and row.content != contents[row.student_id]:
                row.content = contents[row.student_id]
                changed = True
        if changed:
            self.changed.emit()

    def find(self, student_id: str) -> StudentRow | None:
        return next((row for row in self._rows if row.student_id == student_id), None)
