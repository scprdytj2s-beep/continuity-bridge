# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec – macOS (Intel + Silicon)

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
        'objc',
        'AppKit',
        'Foundation',
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Continuity Bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Continuity Bridge',
)

app = BUNDLE(
    coll,
    name='Continuity Bridge.app',
    icon='AppIcon.icns',
    bundle_identifier='nl.michielboesveldt.continuitybridge',
    info_plist={
        'CFBundleName': 'Continuity Bridge',
        'CFBundleDisplayName': 'Continuity Bridge',
        'CFBundleVersion': '1.3.0',
        'CFBundleShortVersionString': '1.3',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'NSRequiresAquaSystemAppearance': False,
        'CFBundleDocumentTypes': [],
    },
)
