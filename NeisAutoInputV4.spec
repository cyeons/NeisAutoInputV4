# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path


def _bundle_solar_key() -> None:
    """.env의 UPSTAGE_API_KEY를 가려서 neis_v4/_bundled_key.py로 만듭니다 (두 파일 모두 Git 제외)."""
    root = Path(SPECPATH)
    target = root / "neis_v4" / "_bundled_key.py"
    env_file = root / ".env"
    key = ""
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "UPSTAGE_API_KEY":
                key = value.strip().strip("'\"")
    if key:
        sys.path.insert(0, str(root))
        from neis_v4.secrets import obfuscate_key

        target.write_text(f"DATA = {obfuscate_key(key)!r}\n", encoding="utf-8", newline="\n")
        print("Upstage 기본 키를 exe에 포함합니다.")
    elif target.exists():
        print("알림: .env에 UPSTAGE_API_KEY가 없어 예전에 만든 neis_v4/_bundled_key.py를 그대로 넣습니다. 기본 키를 빼려면 이 파일을 지우세요.")
    else:
        print("경고: .env에 UPSTAGE_API_KEY가 없어 Upstage 기본 키 없이 빌드합니다.")


_bundle_solar_key()

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("resources/achievement_standards.json", "resources"),
        ("resources/behavior_traits.json", "resources"),
        ("resources/icon.ico", "resources"),
        ("resources/fonts/*.ttf", "resources/fonts"),
        ("resources/icons", "resources/icons"),
    ],
    hiddenimports=[
        "google.genai",
        "openai",
        "anthropic",
        "keyring.backends.Windows",
        "truststore",
        "neis_v4._bundled_key",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "tkinter.test",
        "unittest",
        "pydoc",
        "doctest",
        "numpy",
        "PIL.AvifImagePlugin",
        "PIL.ImageTk",
        "PIL.SpiderImagePlugin",
        "pip",
        "setuptools",
        "wheel",
        "pkg_resources",
    ],
    noarchive=False,
    optimize=2,
)

# The application uses classic Qt Widgets only. PySide's generic hook also
# collects large optional QML/Quick/PDF/virtual-keyboard/OpenGL fallbacks and
# image codecs that are not used by this application.
_unused_binary_parts = (
    # Git Bash에서 빌드하면 Git의 OpenSSL이 딸려 들어옵니다. 쓰는 곳이 없고, 파이썬은 자기 OpenSSL(libcrypto-3.dll)을 씁니다.
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "pyside6/opengl32sw.dll",
    "pyside6/qt6open",
    "pyside6/qt6network",
    "pyside6/qtnetwork",
    "pyside6/qt6pdf",
    "pyside6/qt6qml",
    "pyside6/qt6quick",
    "pyside6/qt6virtualkeyboard",
    "pyside6/plugins/generic/",
    "pyside6/plugins/networkinformation/",
    "pyside6/plugins/platforminputcontexts/",
    "pyside6/plugins/platforms/qdirect2d",
    "pyside6/plugins/platforms/qminimal",
    "pyside6/plugins/platforms/qoffscreen",
    "pyside6/plugins/tls/",
    "pyside6/plugins/imageformats/qgif",
    "pyside6/plugins/imageformats/qicns",
    "pyside6/plugins/imageformats/qjpeg",
    "pyside6/plugins/imageformats/qpdf",
    "pyside6/plugins/imageformats/qtga",
    "pyside6/plugins/imageformats/qtiff",
    "pyside6/plugins/imageformats/qwbmp",
    "pyside6/plugins/imageformats/qwebp",
    "pil/_avif",
    "pil/_imagingcms",
    "pil/_imagingmath",
    "pil/_imagingtk",
    "pil/_webp",
)
a.binaries = [
    item
    for item in a.binaries
    if not item[0].replace("\\", "/").lower().startswith(_unused_binary_parts)
]


def _unused_translation(name: str) -> bool:
    # 확인 창 버튼 번역은 한국어(qtbase_ko.qm)만 씁니다(app.py). 다른 언어 번역 파일은 뺍니다.
    name = name.replace("\\", "/").lower()
    return name.startswith("pyside6/translations/") and not name.endswith("/qtbase_ko.qm")


a.binaries = [item for item in a.binaries if not _unused_translation(item[0])]
a.datas = [item for item in a.datas if not _unused_translation(item[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NEISAutoInput",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 압축은 학교 백신(V3·알약 등)의 오탐 원인이 되기 쉬워 끕니다.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["resources/icon.ico"],
)
