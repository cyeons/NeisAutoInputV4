from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget


ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "docs" / "manual" / "demo_state"
OUTPUT_DIR = ROOT / "docs" / "manual" / "assets" / "screens"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import neis_v4.storage as storage_module


storage_module.app_data_dir = lambda: STATE_DIR


class DemoSecretStore:
    """Screenshot-only key store that never touches a real credential."""

    def get_api_key(self, provider: str) -> str:
        return f"demo-{provider.lower()}-key"

    def set_api_key(self, provider: str, api_key: str) -> bool:
        return bool(provider and api_key)

    def delete_api_key(self, provider: str) -> bool:
        return bool(provider)

    def has_api_key(self, provider: str) -> bool:
        return provider in {"Gemini", "OpenAI"}

    def registered_providers(self) -> list[str]:
        return ["Gemini", "OpenAI"]

    def has_secure_backend(self) -> bool:
        return True


import neis_v4.ui.main_window as main_window_module
from neis_v4.models import GenerationResult
from neis_v4.ui.api_keys import ApiKeyManagerDialog


main_window_module.SecretStore = DemoSecretStore
MainWindow = main_window_module.MainWindow


def save_screen(window: QWidget, name: str) -> None:
    QTest.qWait(400)
    QApplication.processEvents()
    window.repaint()
    QApplication.processEvents()
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("사용 가능한 화면을 찾지 못했습니다.")
    pixmap = screen.grabWindow(int(window.winId()))
    output = OUTPUT_DIR / name
    if not pixmap.save(str(output), "PNG"):
        raise RuntimeError(f"화면 저장 실패: {output}")


def write_demo_work() -> None:
    student_ids = [
        "manual-01",
        "manual-02",
        "manual-03",
        "manual-04",
        "manual-05",
        "manual-06",
        "manual-07",
        "manual-08",
        "manual-09",
        "manual-10",
        "manual-11",
        "manual-12",
    ]
    work = {
        "schema_version": 3,
        "default_sentence_count": 3,
        "students": [
            {
                "student_id": student_id,
                "name_snapshot": f"학생 {index}",
                "sentence_count_override": None,
                "traits": (
                    [
                        {
                            "trait_id": "subject.korean_0",
                            "level": "strength",
                            "label_snapshot": "독서 습관",
                        },
                        {
                            "trait_id": "behavior.responsibility_1",
                            "level": "standard",
                            "label_snapshot": "책임감",
                        },
                        {
                            "trait_id": "behavior.respect_0",
                            "level": "strength",
                            "label_snapshot": "배려",
                        },
                    ]
                    if index == 1
                    else []
                ),
                "draft": (
                    "규칙적인 독서 습관을 바탕으로 자신의 생각을 풍부하게 표현함. "
                    "맡은 역할을 책임감 있게 수행하며 친구를 배려하는 태도가 돋보임."
                    if index == 1
                    else ""
                ),
                "status": "ok" if index == 1 else "not_generated",
                "error_message": "",
                "used_trait_ids": [],
                "omitted_trait_ids": [],
            }
            for index, student_id in enumerate(student_ids, start=1)
        ],
    }
    (STATE_DIR / "hb_work.json").write_text(
        json.dumps(work, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def new_window(page: int = 0) -> MainWindow:
    window = MainWindow()
    window.resize(1600, 900)
    window._select_page(page)
    return window


def close_window(window: QWidget) -> None:
    window.close()
    QApplication.processEvents()


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_demo_work()

    app = QApplication(sys.argv)

    # 자동 입력: 내용 준비
    window = new_window(0)
    tab = window.neis_tab
    tab.hotkey_start_toggle.setChecked(False)
    tab.start_hotkey.setCurrentText("F2")
    tab._refresh_hotkey_controls()
    window.show()
    save_screen(window, "01-data-ready.png")
    close_window(window)

    # 자동 입력: 키 매핑 및 권장 설정
    window = new_window(0)
    tab = window.neis_tab
    tab.tab_segment.setValue(2)
    tab.delay_stepper.setValue(0.20)
    tab.leading_space_toggle.setChecked(False)
    tab.failsafe_toggle.setChecked(True)
    tab.hotkey_start_toggle.setChecked(True)
    tab.start_hotkey.setCurrentText("F2")
    tab._refresh_hotkey_controls()
    window.show()
    save_screen(window, "02-settings-ready.png")
    close_window(window)

    # 자동 입력: 기능 키 시작 대기
    window = new_window(0)
    tab = window.neis_tab
    tab.hotkey_start_toggle.setChecked(True)
    tab.start_hotkey.setCurrentText("F2")
    tab._refresh_hotkey_controls()
    tab._arm_hotkey_start()
    window.show()
    save_screen(window, "03-hotkey-wait.png")
    tab._cancel_hotkey_wait()
    close_window(window)

    # 자동 입력: 진행 중 상태
    window = new_window(0)
    tab = window.neis_tab
    tab.progress.setValue(33)
    tab.progress_label.setText("4/12 완료")
    tab.status_label.setText("입력 중: 학생 5 (5/12)")
    tab._highlight_row(4)
    tab._set_running(True)
    window.show()
    save_screen(window, "04-input-running.png")
    tab._set_running(False)
    close_window(window)

    # AI 평어: 성취기준 선택
    window = new_window(1)
    ai = window.ai_tab
    for card in ai.standard_cards[:3]:
        card.check.setChecked(True)
    window.show()
    save_screen(window, "05-ai-standards.png")
    close_window(window)

    # AI 평어: 생성 결과
    window = new_window(1)
    ai = window.ai_tab
    sample_comments = [
        "글의 중심 내용을 정확히 파악하고 자신의 생각을 근거와 함께 논리적으로 표현함.",
        "다양한 자료를 활용하여 문제를 해결하고 배운 내용을 새로운 상황에 적용함.",
        "수업 활동에 적극적으로 참여하며 친구의 의견을 존중하는 태도가 돋보임.",
    ]
    ai._on_generated(GenerationResult(sample_comments, "\n".join(sample_comments)))
    window.show()
    save_screen(window, "06-ai-results.png")
    close_window(window)

    # 행동발달: 선택 특성과 결과
    write_demo_work()
    window = new_window(2)
    window.show()
    save_screen(window, "07-behavior.png")
    close_window(window)

    # 환경 설정
    window = new_window(3)
    window.show()
    save_screen(window, "08-settings.png")
    close_window(window)

    # API 키 관리 창
    dialog = ApiKeyManagerDialog(DemoSecretStore())
    dialog.show()
    save_screen(dialog, "09-api-keys.png")
    close_window(dialog)

    QTimer.singleShot(0, app.quit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
