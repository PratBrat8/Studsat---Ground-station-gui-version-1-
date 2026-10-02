"""Phase 12 — session telemetry CSV + command log + replay via +RCV."""
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
from app.command_manager import CommandManager
from app.logger import (
    SessionLogger,
    is_command_log_filename,
    list_sessions,
    load_session_commands,
    row_to_wire_bytes,
)
from app.main import app
from app.protocol import VEHICLE_ROCKET
from app.radio_transport import ModuleOk


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_session_logger_writes_telemetry_and_command_files(tmp_path):
    log = SessionLogger("rocket", logs_dir=tmp_path)
    log.log_row(
        {
            "wall_time_iso": "2020-01-01T00:00:00Z",
            "wall_ms": 1,
            "vehicle": "rocket",
            "phase": "LAUNCH_PAD",
            "seq": 0,
            "packet_type_name": "TELEMETRY",
            "raw_hex": "2b 52 43 56 3d",
            "csv": "XXXX,00:00:01,1,10,1000,20,7.4,00:00:01,0,0,10,8,0,0,9.8,0,0,0,2",
            "altitude_m": 10.0,
        }
    )
    log.log_command(
        {
            "wall_time_iso": "2020-01-01T00:00:01Z",
            "command_id": "abc123",
            "vehicle": "rocket",
            "cmd_type": "TX",
            "command_str": "CMD,XXXX,TX,ON",
            "status": "TRANSMITTED",
            "error": "",
            "confirmed": False,
            "dest_addr": 1,
        }
    )
    log.close()
    assert log.path.is_file()
    assert log.command_path.is_file()
    text = log.path.read_text(encoding="utf-8")
    assert "altitude_m" in text
    assert "LAUNCH_PAD" in text
    cmd_text = log.command_path.read_text(encoding="utf-8")
    assert "CMD,XXXX,TX,ON" in cmd_text
    sessions = list_sessions(tmp_path)
    assert len(sessions) == 1
    assert sessions[0]["sample_count"] == 1
    assert sessions[0]["command_count"] == 1
    assert sessions[0]["command_log"] == log.command_filename
    names = {p.name for p in tmp_path.glob("*.csv")}
    listed = {s["filename"] for s in sessions}
    assert log.command_filename not in listed
    assert log.command_filename in names


def test_list_sessions_skips_global_commands_csv(tmp_path):
    (tmp_path / "commands.csv").write_text("wall_time_iso,command_id\n", encoding="utf-8")
    log = SessionLogger("satellite", logs_dir=tmp_path)
    log.log_row({"vehicle": "satellite", "altitude_m": 1, "wall_ms": 10})
    log.close()
    sessions = list_sessions(tmp_path)
    assert all(s["filename"] != "commands.csv" for s in sessions)
    assert not any(is_command_log_filename(s["filename"]) for s in sessions)


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
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    assert "raw_hex" in lines[0]
    assert "csv" in lines[0]
    cmd_path = LOGS_DIR / log_file.replace(".csv", "_commands.csv")
    assert cmd_path.is_file()


def test_sim_command_lands_in_session_command_log(client: TestClient):
    r = client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    assert r.status_code == 200
    log_file = r.json()["log_file"]
    time.sleep(0.3)
    sent = client.post("/command", json={"vehicle": "rocket", "type": "TX", "on": True})
    assert sent.status_code == 200
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})
    listed = client.get(f"/replay/commands?filename={log_file}").json()["commands"]
    assert listed
    assert listed[0]["command"] == "CMD,XXXX,TX,ON"
    assert listed[0]["status"] != "ACKED"
    sessions = client.get("/replay/sessions").json()["sessions"]
    meta = next(s for s in sessions if s["filename"] == log_file)
    assert meta["command_count"] >= 1


def test_list_and_replay_session(client: TestClient):
    r = client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    assert r.status_code == 200
    log_file = r.json()["log_file"]
    time.sleep(0.8)
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})

    sessions = client.get("/replay/sessions").json()["sessions"]
    names = [s["filename"] for s in sessions]
    assert log_file in names
    assert not any(n.endswith("_commands.csv") for n in names)

    load = client.post(
        "/replay/load",
        json={"filename": log_file, "speed": 20.0, "vehicle": "rocket"},
    )
    assert load.status_code == 200
    body = load.json()
    assert body["running"] is True
    assert body["vehicle"] == "rocket"

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


def test_replay_rejects_command_log_filename(client: TestClient):
    r = client.post(
        "/replay/load",
        json={"filename": "commands.csv", "speed": 1.0, "vehicle": "rocket"},
    )
    assert r.status_code in (400, 404)


def test_row_to_wire_from_fields():
    row = {
        "csv": (
            "XXXX,00:00:01,1,12.5,1000,20,7.4,"
            "00:00:01,12.97,77.59,932,8,0,0,9.8,0,0,0,2"
        ),
        "rssi": "-70",
        "snr": "8.0",
    }
    wire = row_to_wire_bytes(row, VEHICLE_ROCKET, 1)
    assert wire is not None
    assert wire.startswith(b"+RCV=")


def test_command_manager_session_sink(tmp_path):
    mgr = CommandManager(logs_dir=tmp_path, rate_limit_s=0.0)
    mgr.set_writer("rocket", lambda _b: True)
    session = SessionLogger("rocket", logs_dir=tmp_path)
    mgr.set_session_sink("rocket", session.log_command)
    rec = mgr.send_command("rocket", "CG")
    mgr.on_module_response("rocket", ModuleOk())
    session.close()
    rows = load_session_commands(session.filename, logs_dir=tmp_path)
    assert len(rows) == 1
    assert rows[0]["id"] == rec["id"]
    assert rows[0]["status"] == "TRANSMITTED"
    assert rows[0]["command"] == "CMD,XXXX,CG,R"
    mgr.close()


def test_health_phase12(client: TestClient):
    body = client.get("/health").json()
    assert body["phase"] >= 10
    assert body["v2_phase"] >= 12
