# PyInstaller spec for KorNet
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("psutil")

a = Analysis(
    ["source/lan_scanner.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/kornet.ico", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KorNet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/kornet.ico",
    disable_windowed_traceback=False,
)
