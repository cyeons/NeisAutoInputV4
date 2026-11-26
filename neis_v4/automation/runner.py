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
        # 완료 후 요약 표시용: 입력한 학생 수와 건너뛴 행 번호(0부터)
        self.entered = 0
        self.skipped: list[int] = []

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        escape_hotkey = None
        completed = False
        pyperclip = None
        original_clipboard = ""
        try:
            import keyboard
            import pyautogui
            import pyperclip

            # 입력이 끝나면 선생님이 원래 복사해 둔 글을 되돌려 놓습니다.
            # (그림 등 글이 아닌 내용은 읽을 수 없어 되돌리지 못합니다.)
            try:
                original_clipboard = pyperclip.paste() or ""
            except Exception:
                original_clipboard = ""
            pyautogui.FAILSAFE = self.failsafe
            # pyautogui는 키를 누를 때마다 0.1초씩 몰래 쉽니다(기본값). 아래에 적은 대기 시간만 쓰도록 끕니다.
            # 그래야 환경 설정의 '입력 간격'이 실제 속도와 맞습니다. (학생 1명당 약 0.58초 → 0.38초)
            pyautogui.PAUSE = 0
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
                    self.skipped.append(index)
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
                    # NEIS(웹 화면)가 다음 칸으로 넘어갈 여유를 둡니다. 너무 짧으면 다른 학생 칸에 들어갈 수 있습니다.
                    time.sleep(0.1)
                self.entered += 1
                self.progress.emit(index + 1, total, f"입력 중: {row.name} ({index + 1}/{total})")
            completed = self._running
        except Exception as exc:
            # 마우스를 화면 모서리로 옮긴 긴급 중지는 오류가 아니라 정상 중지입니다.
            if type(exc).__name__ != "FailSafeException":
                self.failed.emit(f"자동 입력 실패: {exc}")
        finally:
            if escape_hotkey is not None:
                try:
                    keyboard.remove_hotkey(escape_hotkey)
                except Exception:
                    pass
            if pyperclip is not None and original_clipboard:
                try:
                    pyperclip.copy(original_clipboard)
                except Exception:
                    pass
            self.finished_with_state.emit(completed)
