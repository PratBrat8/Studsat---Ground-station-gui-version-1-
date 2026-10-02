# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Phase 14 packaging (PRD v2 D.14 / C.7).
# Build from backend/:  pyinstaller build_backend.spec
# Output: dist/studsat-backend.exe
# Do not bundle CadQuery, STEP files, or tools/cad-venv (build-time CAD only).

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

hidden = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'anyio._backends._asyncio',
    'multipart',
    'serial',
    'serial.tools',
    'serial.tools.list_ports',
    'serial.tools.list_ports_windows',
    'serial.tools.list_ports_common',
    'pydantic',
    'pydantic.deprecated.decorator',
    'email.mime.multipart',
    'email.mime.text',
    'app',
    'app.main',
    'app.config',
    'app.protocol',
    'app.radio_transport',
    'app.power',
    'app.command_manager',
    'app.frame_parser',
    'app.serial_manager',
    'app.simulator',
    'app.telemetry_hub',
    'app.phase_fsm',
    'app.predictor',
    'app.trajectory',
    'app.logger',
    'app.connection_manager',
    'app.rest_routes',
    'app.ws_routes',
    'app.tile_server',
]

# Pull uvicorn + starlette submodules when available
for pkg in ('uvicorn', 'starlette', 'fastapi', 'anyio'):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass

a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=sorted(set(hidden)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'PIL', 'IPython', 'cadquery'],
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
    name='studsat-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # keep console for reliable stdio when Electron spawns the child
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
