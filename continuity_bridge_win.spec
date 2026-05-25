# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec – Windows

block_cipher = None

a = Analysis(
    ['ale_merger_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('AppIcon.png', '.'),
    ],
    hiddenimports=[
        'pdfplumber',
        'pdfminer',
        'pdfminer.high_level',
        'pdfminer.layout',
        'pdfminer.converter',
        'pdfminer.pdfinterp',
        'pdfminer.pdfdevice',
        'pdfminer.pdfparser',
        'pdfminer.pdfdocument',
        'pdfminer.pdfpage',
        'Pillow',
        'PIL',
        'PIL.Image',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'urllib.request',
        'json',
        'hmac',
        'hashlib',
        'base64',
        'threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['objc', 'AppKit'],
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
    name='ContinuityBridge',
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
    icon='AppIcon.ico',
)
