"""
Phase 3 integration: REST /simulate + WebSocket /ws/{vehicle} update stream.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_health_phase3(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # Phase number advances with build plan; API contract stable from Phase 3+
    assert body["phase"] >= 3


def test_ports_endpoint(client: TestClient):
    r = client.get("/ports")
    assert r.status_code == 200
    assert "ports" in r.json()
    assert isinstance(r.json()["ports"], list)


def test_simulate_and_status(client: TestClient):
    r = client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["mode"] == "sim"

    st = client.get("/status").json()
    assert st["connections"]["rocket"]["mode"] == "sim"
    assert st["connections"]["rocket"]["running"] is True

    r2 = client.post("/simulate", json={"vehicle": "rocket", "enabled": False})
    assert r2.status_code == 200
    assert r2.json()["mode"] is None


def test_ws_receives_snapshot_and_updates(client: TestClient):
    # Start sim before opening WS
    assert (
        client.post("/simulate", json={"vehicle": "rocket", "enabled": True}).status_code
        == 200
    )

    with client.websocket_connect("/ws/rocket") as ws:
        # First message must be snapshot
        raw = ws.receive_text()
        snap = json.loads(raw)
        assert snap["type"] == "snapshot"
        assert snap["vehicle"] == "rocket"
        assert "telemetry" in snap
        assert "link" in snap
        assert "history" in snap

        # Collect a few live updates (sim runs at ~10 Hz, throttle ~16 fps)
        updates = []
        for _ in range(30):
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "update":
                updates.append(msg)
            if len(updates) >= 3:
                break

        assert len(updates) >= 3
        last = updates[-1]
        assert last["vehicle"] == "rocket"
        assert last["link"]["state"] in ("CONNECTED", "RECONNECTING", "LINK_LOST")
        # After a short sim run we should have real telemetry numbers
        assert last["telemetry"]["altitude_m"] is not None
        assert last["telemetry"]["battery_v"] is not None
        assert last["phase"] in ("IDLE", "ARMED", "ASCENT", "APOGEE", "DESCENT", "LANDED")
        assert last["link"]["frames_ok"] >= 1

    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})


def test_dual_vehicle_independent_sim(client: TestClient):
    client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    client.post("/simulate", json={"vehicle": "satellite", "enabled": True})

    with client.websocket_connect("/ws/rocket") as ws_r:
        with client.websocket_connect("/ws/satellite") as ws_s:
            snap_r = json.loads(ws_r.receive_text())
            snap_s = json.loads(ws_s.receive_text())
            assert snap_r["vehicle"] == "rocket"
            assert snap_s["vehicle"] == "satellite"

            # Drain a couple of updates on each
            for _ in range(5):
                json.loads(ws_r.receive_text())
                json.loads(ws_s.receive_text())

    client.post("/disconnect", json={"vehicle": "rocket"})
    client.post("/disconnect", json={"vehicle": "satellite"})


def test_bad_vehicle_rejected(client: TestClient):
    r = client.post("/simulate", json={"vehicle": "balloon", "enabled": True})
    assert r.status_code == 400


def test_hub_ingest_unit():
    """Direct hub ingest without HTTP (unit-level)."""
    from app.protocol import VEHICLE_ROCKET, TelemetryFrame, encode_packet
    from app.frame_parser import FrameParser
    from app.telemetry_hub import TelemetryHub

    hub = TelemetryHub()
    parser = FrameParser()
    wire = encode_packet(
        VEHICLE_ROCKET,
        0,
        TelemetryFrame(
            timestamp_ms=1,
            altitude_m=100.0,
            pressure_hpa=1000.0,
            temperature_c=20.0,
            accel_x=0.0,
            accel_y=0.0,
            accel_z=9.8,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            pitch=1.0,
            yaw=2.0,
            roll=3.0,
            battery_v=7.4,
        ),
    )
    frames = parser.feed(wire)
    assert len(frames) == 1
    hub.ingest_raw_frame(
        "rocket",
        frames[0],
        {
            "frames_ok": parser.frames_ok,
            "frames_crc_error": 0,
            "frames_resynced": 0,
        },
    )
    snap = hub.latest_state("rocket")
    assert snap["telemetry"]["altitude_m"] == pytest.approx(100.0)
    assert snap["phase"] == "ARMED"
    assert snap["link"]["frames_ok"] == 1
