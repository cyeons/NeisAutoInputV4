# -*- mode: python ; coding: utf-8 -*-


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
        "keyring.backends.Windows",
        "truststore",
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
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NeisAutoInputV4.2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
