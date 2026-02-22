# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['E:\\AIEmbeddedSystemHelperPlugin\\backend\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('E:\\AIEmbeddedSystemHelperPlugin\\backend\\embedded_system_helper', 'embedded_system_helper')],
    hiddenimports=['uvicorn.logging', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'google.adk', 'litellm', 'embedded_system_helper', 'embedded_system_helper.agent', 'embedded_system_helper.memory', 'embedded_system_helper.search_agent', 'embedded_system_helper.filesystem_tools'],
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
    a.binaries,
    a.datas,
    [],
    name='backend-win',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
