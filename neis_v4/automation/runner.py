from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from neis_v4.models import StudentRow


class MacroRunner(QThread):
    progress = Signal(int, int, str)
    status = Signal(str)
    row_changed = Signal(int)
    finished_with_state = Signal(bool)
    failed = Signal(str)

    def __init__(
        self,
        rows: list[StudentRow],
        tab_count: int,
        delay: float,
        leading_space: bool,
        failsafe: bool,
        start_delay: int = 5,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.rows = rows
        self.tab_count = tab_count
        self.delay = delay
        self.leading_space = leading_space
        self.failsafe = failsafe
        self.start_delay = start_delay
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        escape_hotkey = None
        completed = False
        try:
            import keyboard
            import pyautogui
            import pyperclip

            pyautogui.FAILSAFE = self.failsafe
            escape_hotkey = keyboard.add_hotkey("esc", self.stop)
            total = len(self.rows)
            for remaining in range(self.start_delay, 0, -1):
                if not self._running:
                    break
                self.progress.emit(0, total, f"{remaining}초 안에 NEIS 첫 입력칸을 클릭하세요.")
                time.sleep(1)
            self.status.emit("자동 입력 중...")
            for index, row in enumerate(self.rows):
                if not self._running:
                    break
                self.row_changed.emit(index)
                content = row.content.strip()
                if not content:
                    self.progress.emit(index + 1, total, f"건너뜀: {row.name}")
                    continue
                if self.leading_space:
                    pyautogui.press("space")
                    time.sleep(0.05)
                pyperclip.copy(content)
                time.sleep(0.08)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(self.delay)
                for _ in range(self.tab_count):
                    pyautogui.press("tab")
                    time.sleep(0.05)
                self.progress.emit(index + 1, total, f"입력 중: {row.name} ({index + 1}/{total})")
            completed = self._running
        except Exception as exc:
            self.failed.emit(f"자동 입력 실패: {exc}")
        finally:
            if escape_hotkey is not None:
                try:
                    keyboard.remove_hotkey(escape_hotkey)
                except Exception:
                    pass
            self.finished_with_state.emit(completed)
