"""Phase 10 — continuous CSV logging + replay through real parser path."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.config import LOGS_DIR
from app.logger import (
    SessionLogger,
    list_sessions,
    load_session,
    row_to_wire_bytes,
)
from app.main import app
from app.protocol import VEHICLE_ROCKET, TYPE_TELEMETRY


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_session_logger_writes_csv(tmp_path):
    log = SessionLogger("rocket", logs_dir=tmp_path)
    log.log_row(
        {
            "wall_time_iso": "2020-01-01T00:00:00Z",
            "wall_ms": 1,
            "vehicle": "rocket",
            "phase": "ARMED",
            "seq": 0,
            "packet_type": TYPE_TELEMETRY,
            "packet_type_name": "TELEMETRY",
            "raw_hex": "aa 55",
            "altitude_m": 10.0,
        }
    )
    log.close()
    assert log.path.is_file()
    text = log.path.read_text(encoding="utf-8")
    assert "altitude_m" in text
    assert "ARMED" in text
    sessions = list_sessions(tmp_path)
    assert len(sessions) == 1
    assert sessions[0]["sample_count"] == 1


def test_sim_creates_log_file(client: TestClient):
    before = set(p.name for p in LOGS_DIR.glob("rocket_*.csv")) if LOGS_DIR.exists() else set()
    r = client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    assert r.status_code == 200
    log_file = r.json().get("log_file")
    assert log_file
    time.sleep(0.6)
    stop = client.post("/simulate", json={"vehicle": "rocket", "enabled": False})
    assert stop.status_code == 200
    path = LOGS_DIR / log_file
    assert path.is_file()
    # Continuous logging should have multiple rows
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2  # header + data
    assert "raw_hex" in lines[0]


def test_list_and_replay_session(client: TestClient):
    # Create a short sim log
    r = client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    assert r.status_code == 200
    log_file = r.json()["log_file"]
    time.sleep(0.8)
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})

    sessions = client.get("/replay/sessions").json()["sessions"]
    names = [s["filename"] for s in sessions]
    assert log_file in names

    load = client.post(
        "/replay/load",
        json={"filename": log_file, "speed": 20.0, "vehicle": "rocket"},
    )
    assert load.status_code == 200
    body = load.json()
    assert body["running"] is True
    assert body["vehicle"] == "rocket"

    # Wait for some progress
    deadline = time.time() + 5.0
    saw_progress = False
    while time.time() < deadline:
        st = client.get("/replay/status").json()
        if st.get("index", 0) > 0 or not st.get("running"):
            saw_progress = True
            break
        time.sleep(0.1)
    assert saw_progress

    client.post("/replay/stop")
    st2 = client.get("/replay/status").json()
    assert st2["running"] is False


def test_row_to_wire_from_fields():
    row = {
        "packet_type": str(TYPE_TELEMETRY),
        "altitude_m": "12.5",
        "pressure_hpa": "1000",
        "temperature_c": "20",
        "battery_v": "7.4",
        "accel_z": "9.8",
        "pitch": "1",
        "yaw": "2",
        "roll": "3",
    }
    wire = row_to_wire_bytes(row, VEHICLE_ROCKET, 1)
    assert wire is not None
    assert wire[0] == 0xAA and wire[1] == 0x55


def test_health_phase10(client: TestClient):
    assert client.get("/health").json()["phase"] >= 10
