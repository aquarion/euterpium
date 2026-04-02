# euterpium.spec — PyInstaller build spec
# Build with:  poetry run pyinstaller euterpium.spec

import sys
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)  # noqa: F821  (PyInstaller injects SPECPATH)

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Bundle the default config and icon as data files
        ('euterpium.ini', '.'),
        ('icons/app_icon.png', '.'),
        ('icons/app_listening.png', '.'),
    ],
    hiddenimports=[
        # tkinter and its sub-modules are sometimes missed
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        # winsdk WinRT machinery
        'winsdk.windows.media.control',
        'winsdk.windows.media',
        # win11toast pulls in these at runtime
        'win11toast',
        'winrt',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='euterpium',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icons/app_icon.png',  # taskbar / exe icon
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='euterpium',
)
