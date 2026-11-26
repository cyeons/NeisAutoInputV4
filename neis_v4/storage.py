from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .ai.model_catalog import normalize_model, normalize_provider, set_fetched_models
from .models import AppSettings, BehaviorWork, StudentRow


APP_NAME = "NeisAutoInputV4"  # 프로그램 이름이 바뀌어도 그대로 둡니다. 바꾸면 기존 작업·설정 폴더(%APPDATA%)를 못 찾습니다.


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


def legacy_dir() -> Path | None:
    """이전 버전 파일 위치(프로젝트 상위 폴더). exe에서는 임시 폴더라 쓰지 않습니다."""
    if getattr(sys, "frozen", False):
        return None
    return project_root().parent


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir()

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def fetched_models_path(self) -> Path:
        return self.root / "fetched_models.json"

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

    def load_fetched_models(self) -> None:
        """'최신 모델 불러오기'로 받아 둔 모델을 목록에 다시 붙입니다. 저장된 모델이 지워지지 않도록 설정보다 먼저 읽습니다."""
        try:
            with self.fetched_models_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for provider, model_list in data.items() if isinstance(data, dict) else ():
            if isinstance(model_list, list):
                set_fetched_models(str(provider), [str(item) for item in model_list])

    def save_fetched_models(self, provider: str, model_list: list[str]) -> None:
        try:
            with self.fetched_models_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data[provider] = model_list
        self._write_json(self.fetched_models_path, data)
        set_fetched_models(provider, model_list)

    def load_settings(self) -> AppSettings:
        self.load_fetched_models()
        legacy = legacy_dir()
        source = self.config_path
        if not source.exists() and legacy is not None:
            source = legacy / "config.json"
        defaults = AppSettings()
        if not source.exists():
            return defaults
        try:
            with source.open("r", encoding="utf-8") as f:
                data = json.load(f)
            ai_provider = normalize_provider(str(data.get("ai_provider", defaults.ai_provider)))
            behavior_provider = normalize_provider(
                str(data.get("behavior_provider", ai_provider))
            )
            ai_tab_count = int(data.get("ai_tab_count", defaults.ai_tab_count))
            behavior_tab_count = int(data.get("behavior_tab_count", defaults.behavior_tab_count))
            return AppSettings(
                student_count=int(data.get("student_count", defaults.student_count)),
                geometry=str(data.get("geometry", defaults.geometry)),
                always_on_top=bool(data.get("always_on_top", defaults.always_on_top)),
                macro_delay=float(data.get("macro_delay", defaults.macro_delay)),
                start_hotkey=(
                    str(data.get("start_hotkey", defaults.start_hotkey))
                    if str(data.get("start_hotkey", defaults.start_hotkey))
                    in {f"F{number}" for number in range(2, 11)}
                    else defaults.start_hotkey
                ),
                hotkey_start_enabled=bool(data.get("hotkey_start_enabled", defaults.hotkey_start_enabled)),
                tab_count=int(data.get("tab_count", defaults.tab_count)),
                ai_tab_count=ai_tab_count if ai_tab_count in (2, 3, 4) else defaults.ai_tab_count,
                behavior_tab_count=(
                    behavior_tab_count if behavior_tab_count in (2, 3, 4) else defaults.behavior_tab_count
                ),
                content_byte_limit=int(data.get("content_byte_limit", defaults.content_byte_limit)),
                leading_space=bool(data.get("leading_space", defaults.leading_space)),
                pyautogui_failsafe=bool(data.get("pyautogui_failsafe", defaults.pyautogui_failsafe)),
                use_windows_trust_store=bool(data.get("use_windows_trust_store", defaults.use_windows_trust_store)),
                ai_provider=ai_provider,
                upstage_model=normalize_model(
                    "Upstage", str(data.get("upstage_model", defaults.upstage_model))
                ),
                gemini_model=normalize_model(
                    "Gemini", str(data.get("gemini_model", defaults.gemini_model))
                ),
                openai_model=normalize_model(
                    "OpenAI", str(data.get("openai_model", defaults.openai_model))
                ),
                claude_model=normalize_model(
                    "Claude", str(data.get("claude_model", defaults.claude_model))
                ),
                behavior_provider=behavior_provider,
                behavior_upstage_model=normalize_model(
                    "Upstage",
                    str(data.get("behavior_upstage_model", data.get("upstage_model", defaults.behavior_upstage_model))),
                ),
                behavior_gemini_model=normalize_model(
                    "Gemini",
                    str(data.get("behavior_gemini_model", data.get("gemini_model", defaults.behavior_gemini_model))),
                ),
                behavior_openai_model=normalize_model(
                    "OpenAI",
                    str(data.get("behavior_openai_model", data.get("openai_model", defaults.behavior_openai_model))),
                ),
                behavior_claude_model=normalize_model(
                    "Claude",
                    str(data.get("behavior_claude_model", data.get("claude_model", defaults.behavior_claude_model))),
                ),
                behavior_sentence_count=int(data.get("behavior_sentence_count", defaults.behavior_sentence_count)),
                ai_custom_prompt=str(data.get("ai_custom_prompt", defaults.ai_custom_prompt)),
                behavior_custom_prompt=str(data.get("behavior_custom_prompt", defaults.behavior_custom_prompt)),
                notified_update_version=str(data.get("notified_update_version", defaults.notified_update_version)),
            )
        except Exception:
            return defaults

    def save_settings(self, settings: AppSettings) -> None:
        self._write_json(self.config_path, asdict(settings))

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
        candidates = [primary, executable_dir() / filename]
        legacy = legacy_dir()
        if legacy is not None:
            candidates.append(legacy / filename)
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
