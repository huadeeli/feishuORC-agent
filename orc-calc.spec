# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['orc-calc.py'],
    pathex=[],
    binaries=[],
    datas=[('static', 'static'), ('config', 'config'), ('jianhui 模板.jpg', '.'), ('jingzhou 模板.jpg', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['paddleocr', 'paddlex', 'paddle'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='orc-calc',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='orc-calc',
)
