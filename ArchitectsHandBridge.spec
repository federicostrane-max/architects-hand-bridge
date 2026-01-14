# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Architect's Hand Bridge Launcher

Build command:
  pyinstaller ArchitectsHandBridge.spec

Output:
  dist/ArchitectsHandBridge.exe
"""

import sys
from pathlib import Path

block_cipher = None

# Percorso base
BASE_DIR = Path(SPECPATH)

a = Analysis(
    ['launcher.py'],
    pathex=[str(BASE_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=['tkinter', 'tkinter.ttk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ArchitectsHandBridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # False = GUI mode (nessuna console nera)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico',  # Decommenta se hai un'icona
)
