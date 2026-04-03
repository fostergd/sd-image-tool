# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os

project_root = Path.cwd()
src_root = project_root / "src"
packaging_root = project_root / "packaging" / "windows"
release_version = os.environ.get("SDTOOL_VERSION", "0.1.1")

block_cipher = None

a = Analysis(
    [str(src_root / "sdtool" / "app.py")],
    pathex=[str(project_root), str(src_root)],
    binaries=[],
    datas=[],
    hiddenimports=["sdtool.app"],
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
    name="SD Image Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(packaging_root / "sd-image-tool.ico"),
    version=str(packaging_root / "file_version_info.txt"),
    manifest=str(packaging_root / "sd-image-tool.manifest"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SD Image Tool",
    contents_dir="_internal",
)
