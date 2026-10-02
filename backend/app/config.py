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

# ---------------------------------------------------------------------------
# Competition identity
# ---------------------------------------------------------------------------
# TEMPORARY/UNCONFIRMED — replace with the real competition TEAM_ID.
TEAM_ID = os.environ.get("STUDSAT_TEAM_ID", "XXXX")

# ---------------------------------------------------------------------------
# Reyax RYLR993 (PRD v2 C.2 / Appendix 1.6)
# TEMPORARY/UNCONFIRMED — baud and addresses are placeholders until the
# real USB dongles are configured and measured.
# ---------------------------------------------------------------------------
REYAX_BAUD = int(os.environ.get("STUDSAT_REYAX_BAUD", "115200"))
DEFAULT_BAUD = REYAX_BAUD  # serial_manager still reads DEFAULT_BAUD

# Ground module on the rocket/avionics band (we send AT+SEND from here).
GROUND_ROCKET_ADDR = 0
# Teensy 4.1 / avionics Reyax (downlink sender, EJ uplink destination).
ROCKET_VEHICLE_ADDR = 1
# Ground module on the CanSat band.
GROUND_CANSAT_ADDR = 2
# Raspberry Pi Zero 2W / CanSat Reyax.
CANSAT_VEHICLE_ADDR = 3

# TEMPORARY/UNCONFIRMED (Appendix 1.3): firmware does NOT send an
# application-level "command executed" ACK. UI may only show
# SENT → TRANSMITTED (+OK). Never invent ACKED.
COMMAND_APP_ACK_ENABLED = False
COMMAND_ACK_TIMEOUT_S = 3.0
COMMAND_RATE_LIMIT_S = 3.0

# Manual ejection is sent on the Rocket/Avionics radio line only
# (Appendix 1.7, TEMPORARY/UNCONFIRMED until firmware confirms).
EJECTION_VEHICLE = "rocket"

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
# TEMPORARY/UNCONFIRMED — dual-altitude failsafe threshold (PRD v2 C.6).
ALTITUDE_DISAGREEMENT_THRESHOLD_M = 30.0
# TEMPORARY/UNCONFIRMED — ASCENT trend-line window (PRD v2 C.7).
TRAJECTORY_TREND_WINDOW_SAMPLES = 10

# ---------------------------------------------------------------------------
# Serial reconnect backoff (seconds)
# ---------------------------------------------------------------------------
RECONNECT_BACKOFF_S = [2, 2, 3, 5, 5]
