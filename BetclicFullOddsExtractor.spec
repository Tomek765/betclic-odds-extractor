# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve()
browser_root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" / "chromium-1169" / "chrome-win"
if not (browser_root / "chrome.exe").is_file():
    raise FileNotFoundError(f"Official Playwright Chromium 1169 not found: {browser_root}")

datas = [(str(browser_root), "browser/chrome-win")]
binaries = []
hiddenimports = collect_submodules("apex_context_engine") + [
    "release_self_test",
    "playwright_stealth",
    "playwright_stealth.stealth",
    "playwright_stealth.context_managers",
]
for package in ("playwright", "playwright_stealth"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(root / "gui.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="APEX_Context_Engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="APEX_Context_Engine",
)
