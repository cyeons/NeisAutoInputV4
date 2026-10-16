from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .ai.model_catalog import normalize_model, normalize_provider
from .models import AppSettings, BehaviorWork, StudentRow


APP_NAME = "NeisAutoInputV4"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", project_root()))
    return base / relative_path


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()


def app_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.getenv("APPDATA", Path.home()))
        path = base / APP_NAME
    else:
        path = project_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir()

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def data_path(self) -> Path:
        return self.root / "data.csv"

    @property
    def student_path(self) -> Path:
        return self.root / "student.csv"

    @property
    def standards_path(self) -> Path:
        return resource_path("resources/achievement_standards.json")

    @property
    def behavior_traits_path(self) -> Path:
        return resource_path("resources/behavior_traits.json")

    @property
    def behavior_work_path(self) -> Path:
        return self.root / "hb_work.json"

    @property
    def custom_traits_path(self) -> Path:
        return self.root / "hb_custom_traits.json"

    def load_settings(self) -> AppSettings:
        legacy = project_root().parent / "config.json"
        source = self.config_path if self.config_path.exists() else legacy
        if not source.exists():
            return AppSettings()
        try:
            with source.open("r", encoding="utf-8") as f:
                data = json.load(f)
            ai_provider = normalize_provider(str(data.get("ai_provider", "Gemini")))
            behavior_provider = normalize_provider(
                str(data.get("behavior_provider", ai_provider))
            )
            return AppSettings(
                student_count=int(data.get("student_count", 20)),
                geometry=str(data.get("geometry", "")),
                always_on_top=bool(data.get("always_on_top", False)),
                macro_delay=float(data.get("macro_delay", 0.1)),
                start_hotkey=(
                    str(data.get("start_hotkey", "F8"))
                    if str(data.get("start_hotkey", "F8"))
                    in {f"F{number}" for number in range(2, 11)}
                    else "F8"
                ),
                hotkey_start_enabled=bool(data.get("hotkey_start_enabled", False)),
                tab_count=int(data.get("tab_count", 2)),
                leading_space=bool(data.get("leading_space", False)),
                pyautogui_failsafe=bool(data.get("pyautogui_failsafe", True)),
                use_windows_trust_store=bool(data.get("use_windows_trust_store", True)),
                ai_provider=ai_provider,
                gemini_model=normalize_model(
                    "Gemini", str(data.get("gemini_model", "gemini-3.5-flash"))
                ),
                openai_model=normalize_model(
                    "OpenAI", str(data.get("openai_model", "gpt-5.4-mini"))
                ),
                behavior_provider=behavior_provider,
                behavior_gemini_model=normalize_model(
                    "Gemini",
                    str(data.get("behavior_gemini_model", data.get("gemini_model", ""))),
                ),
                behavior_openai_model=normalize_model(
                    "OpenAI",
                    str(data.get("behavior_openai_model", data.get("openai_model", ""))),
                ),
                behavior_sentence_count=int(data.get("behavior_sentence_count", 3)),
                ai_custom_prompt=str(data.get("ai_custom_prompt", "")),
                behavior_custom_prompt=str(data.get("behavior_custom_prompt", "")),
            )
        except Exception:
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, ensure_ascii=False, indent=2)

    def load_students(self, count: int) -> list[StudentRow]:
        rows = self.load_saved_students()
        if rows:
            return rows
        names = self.load_student_names()
        if names:
            return [StudentRow(name=name) for name in names]
        return [StudentRow(name=f"학생 {i + 1}") for i in range(count)]

    def load_saved_students(self) -> list[StudentRow]:
        for path in self._candidate_paths(self.data_path, "data.csv"):
            if path.exists():
                rows = self._read_data_csv(path)
                if rows:
                    return rows
        return []

    def _read_data_csv(self, path: Path) -> list[StudentRow]:
        try:
            with path.open("r", newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader, None)
                return [StudentRow(row[0], row[1] if len(row) > 1 else "") for row in reader if row]
        except Exception:
            return []

    def save_students(self, rows: list[StudentRow]) -> Path:
        return self._write_csv(
            self.data_path,
            ["이름", "내용"],
            ([row.name, row.content] for row in rows),
        )

    def load_student_names(self) -> list[str]:
        for source in self._candidate_paths(self.student_path, "student.csv"):
            if not source.exists():
                continue
            try:
                with source.open("r", newline="", encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    names = [row[0] for row in reader if row and row[0].strip()]
                    if names:
                        return names
            except Exception:
                continue
        return []

    def save_student_names(self, names: list[str]) -> Path:
        return self._write_csv(self.student_path, ["이름"], ([name] for name in names))

    def _candidate_paths(self, primary: Path, filename: str) -> list[Path]:
        candidates = [primary, executable_dir() / filename, project_root().parent / filename]
        unique: list[Path] = []
        for path in candidates:
            resolved = path.resolve()
            if resolved not in unique:
                unique.append(resolved)
        return unique

    @staticmethod
    def _write_csv(path: Path, header: list[str], rows) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(rows)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path

    def load_achievement_data(self) -> dict[str, Any]:
        with self.standards_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def load_behavior_catalog(self) -> dict[str, Any]:
        with self.behavior_traits_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def load_behavior_work(self) -> BehaviorWork:
        if not self.behavior_work_path.exists():
            return BehaviorWork()
        try:
            with self.behavior_work_path.open("r", encoding="utf-8") as f:
                value = json.load(f)
            return BehaviorWork.from_dict(value if isinstance(value, dict) else {})
        except Exception:
            return BehaviorWork()

    def save_behavior_work(self, work: BehaviorWork) -> Path:
        self._write_json(self.behavior_work_path, asdict(work))
        return self.behavior_work_path

    def load_custom_traits(self) -> list[dict[str, str]]:
        if not self.custom_traits_path.exists():
            return []
        try:
            with self.custom_traits_path.open("r", encoding="utf-8") as f:
                value = json.load(f)
            items = value.get("traits", []) if isinstance(value, dict) else []
            return [
                {
                    "trait_id": str(item.get("trait_id", "")),
                    "label": str(item.get("label", "")),
                    "group": str(item.get("group", "behavior")),
                    "category": str(item.get("category", "")),
                }
                for item in items
                if isinstance(item, dict) and item.get("trait_id") and item.get("label")
            ]
        except Exception:
            return []

    def save_custom_traits(self, traits: list[dict[str, str]]) -> Path:
        self._write_json(self.custom_traits_path, {"schema_version": 1, "traits": traits})
        return self.custom_traits_path

    @staticmethod
    def reconcile_student_ids(rows: list[StudentRow], work: BehaviorWork) -> list[StudentRow]:
        """Reuse IDs by row/name first and then by unique remaining name."""
        states = list(work.students)
        used_ids: set[str] = set()
        by_name: dict[str, list] = {}
        for state in states:
            by_name.setdefault(state.name_snapshot.strip(), []).append(state)

        reconciled: list[StudentRow] = []
        for index, row in enumerate(rows):
            matched = None
            if index < len(states):
                candidate = states[index]
                if candidate.name_snapshot.strip() == row.name.strip():
                    matched = candidate
            if matched is None:
                candidates = [
                    item
                    for item in by_name.get(row.name.strip(), [])
                    if item.student_id not in used_ids
                ]
                if len(candidates) == 1:
                    matched = candidates[0]
            student_id = matched.student_id if matched else row.student_id
            used_ids.add(student_id)
            reconciled.append(StudentRow(row.name, row.content, student_id))
        return reconciled

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
