# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path


project_root = Path(SPECPATH).resolve()
icon = project_root / (
    "packaging/spineworks.icns"
    if sys.platform == "darwin"
    else "src/spineworks/assets/spineworks.png"
)

a = Analysis(
    ["src/spineworks/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[("src/spineworks/assets/spineworks.png", "spineworks/assets")],
    hiddenimports=[],
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
    name="SPINEWORKS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(icon),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SPINEWORKS",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SPINEWORKS.app",
        icon=str(icon),
        bundle_identifier="pl.aborzym.spineworks",
    )
