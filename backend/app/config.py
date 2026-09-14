"""
STUDSAT Ground Station — runtime configuration & mission thresholds.
All values are overridable from Settings UI in later phases (PRD C.6 / C.7).

Phase 12: path resolution works for:
  - dev: repo/backend/app/config.py → repo/{tiles,logs}
  - PyInstaller onefile/onedir next to Electron resources
  - env overrides: STUDSAT_TILES_DIR, STUDSAT_LOGS_DIR
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _runtime_roots() -> tuple[Path, Path, Path]:
    """
    Returns (app_dir, tiles_dir, logs_dir).
    """
    env_tiles = os.environ.get("STUDSAT_TILES_DIR")
    env_logs = os.environ.get("STUDSAT_LOGS_DIR")

    if getattr(sys, "frozen", False):
        # PyInstaller: studsat-backend.exe lives in resources/backend/
        exe_dir = Path(sys.executable).resolve().parent
        resources = exe_dir.parent  # resources/
        # Fallback: same folder as exe
        tiles = Path(env_tiles) if env_tiles else (resources / "tiles")
        if not tiles.is_dir() and (exe_dir / "tiles").is_dir():
            tiles = exe_dir / "tiles"
        logs = Path(env_logs) if env_logs else (resources / "logs")
        return exe_dir, tiles, logs

    app_dir = Path(__file__).resolve().parent
    backend_dir = app_dir.parent
    repo_root = backend_dir.parent
    tiles = Path(env_tiles) if env_tiles else (repo_root / "tiles")
    logs = Path(env_logs) if env_logs else (repo_root / "logs")
    return app_dir, tiles, logs


APP_DIR, TILES_DIR, LOGS_DIR = _runtime_roots()
BACKEND_DIR = APP_DIR.parent if not getattr(sys, "frozen", False) else APP_DIR
REPO_ROOT = BACKEND_DIR.parent if not getattr(sys, "frozen", False) else APP_DIR.parent

# ---------------------------------------------------------------------------
# HTTP / WebSocket server
# ---------------------------------------------------------------------------
HOST = os.environ.get("STUDSAT_HOST", "127.0.0.1")
PORT = int(os.environ.get("STUDSAT_PORT", "8765"))
DEFAULT_BAUD = 115200  # [ASSUMED] — confirm with firmware team

# ---------------------------------------------------------------------------
# Telemetry hub
# ---------------------------------------------------------------------------
RING_BUFFER_SAMPLES = 3600  # ~3 min at 20 Hz
GPS_TRACK_MAX_POINTS = 5000
PACKET_RING_SIZE = 50
WS_BROADCAST_INTERVAL_MS = 60  # ~16 fps to renderer

# ---------------------------------------------------------------------------
# Mission phase FSM thresholds (PRD B.4 / C.6)
# ---------------------------------------------------------------------------
LAUNCH_ACCEL_THRESHOLD_G = 2.0
APOGEE_VSPEED_EPS = 0.5  # m/s
LANDED_ALT_EPS_M = 5.0
LANDED_SPEED_EPS = 1.0  # m/s
LANDED_CONFIRM_SAMPLES = 15
PREDICTION_WINDOW_SAMPLES = 15

# ---------------------------------------------------------------------------
# Serial reconnect backoff (seconds)
# ---------------------------------------------------------------------------
RECONNECT_BACKOFF_S = [2, 2, 3, 5, 5]
