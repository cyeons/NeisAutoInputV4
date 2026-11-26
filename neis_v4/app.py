from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME
from .certificates import configure_windows_trust_store
from .storage import Storage, resource_path
from .ui.main_window import MainWindow


def _application_font() -> QFont:
    suit_loaded = False
    for name in ["Regular", "Medium", "SemiBold", "Bold"]:
        # The official TTF build uses Windows' native TrueType rasterizer.
        # Its grid fitting is more reliable for thin Hangul vowel strokes than
        # the CFF outlines in the OTF build at fractional display scales.
        font_path = resource_path(f"resources/fonts/SUIT-{name}.ttf")
        if font_path.exists():
            suit_loaded = QFontDatabase.addApplicationFont(str(font_path)) >= 0 or suit_loaded

    font = QFont()
    if suit_loaded:
        font.setFamilies(["SUIT", "Malgun Gothic"])
    elif sys.platform == "win32":
        font.setFamilies(["Malgun Gothic"])
    font.setPointSizeF(10.5)
    font.setStyleStrategy(QFont.PreferAntialias)
    if sys.platform == "win32":
        # Preserve thin horizontal Hangul strokes on fractional display scales.
        font.setHintingPreference(QFont.PreferFullHinting)
    return font


def run() -> int:
    startup_settings = Storage().load_settings()
    configure_windows_trust_store(startup_settings.use_windows_trust_store)
    app = QApplication(sys.argv)
    # 확인 창의 Yes/No/OK/Cancel 버튼을 '예/아니요/확인/취소'로 보여 줍니다. 파일이 없으면 영어로 둡니다.
    translator = QTranslator(app)
    if translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setFont(_application_font())
    icon_path = resource_path("resources/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    screen = app.primaryScreen()
    if screen:
        available = screen.availableGeometry()
        width = min(1520, max(1000, int(available.width() * 0.88)))
        height = min(920, max(650, int(available.height() * 0.88)))
        window.resize(width, height)
        window.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )
    window.show()
    window.check_for_updates()
    return app.exec()
