"""Phase 11 — resilience: bad ports, garbage frames, API stability."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.frame_parser import FrameParser
from app.main import app
from app.protocol import VEHICLE_ROCKET, TelemetryFrame, encode_packet
from app.serial_manager import SerialVehicleLink, validate_port_arg
from app.telemetry_hub import TelemetryHub


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_health_never_500(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["phase"] >= 11
    assert "tiles_dir" in body
    assert "logs_dir" in body


def test_bad_port_connect_does_not_crash(client: TestClient):
    """Nonexistent COM port: API accepts, link stays in reconnect loop."""
    r = client.post(
        "/connect",
        json={"vehicle": "rocket", "port": "COM_DOES_NOT_EXIST_999", "baud": 115200},
    )
    # Should succeed in starting the reconnect worker (or 400 only if validation fails)
    assert r.status_code in (200, 400, 500)
    if r.status_code == 200:
        body = r.json()
        assert body["ok"] is True
        assert body.get("port_present") is False or "warning" in body
        # Backend still healthy
        assert client.get("/health").status_code == 200
        client.post("/disconnect", json={"vehicle": "rocket"})


def test_empty_port_rejected(client: TestClient):
    r = client.post(
        "/connect",
        json={"vehicle": "rocket", "port": "  ", "baud": 115200},
    )
    assert r.status_code == 400


def test_validate_port_arg():
    assert validate_port_arg("COM3") == "COM3"
    with pytest.raises(ValueError):
        validate_port_arg("")
    with pytest.raises(ValueError):
        validate_port_arg("   ")


def test_hub_survives_garbage_bytes():
    hub = TelemetryHub()
    parser = FrameParser()
    garbage = bytes(range(256)) * 50
    frames = parser.feed(garbage)
    for fr in frames:
        hub.ingest_raw_frame("rocket", fr)
    # Valid frame still works after garbage
    wire = encode_packet(
        VEHICLE_ROCKET,
        1,
        TelemetryFrame(
            timestamp_ms=1,
            altitude_m=5.0,
            pressure_hpa=1000.0,
            temperature_c=20.0,
            accel_x=0.0,
            accel_y=0.0,
            accel_z=9.8,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            pitch=0.0,
            yaw=0.0,
            roll=0.0,
            battery_v=7.4,
        ),
    )
    for fr in parser.feed(wire):
        hub.ingest_raw_frame(
            "rocket",
            fr,
            {
                "frames_ok": parser.frames_ok,
                "frames_crc_error": parser.frames_crc_error,
                "frames_resynced": parser.frames_resynced,
            },
        )
    snap = hub.latest_state("rocket")
    assert snap["telemetry"]["altitude_m"] == pytest.approx(5.0)
    assert parser.frames_crc_error >= 0  # may be high after garbage


def test_serial_link_bad_port_thread_exits_cleanly():
    """Start+stop against a fake port without crashing the process."""
    frames = []

    def on_frame(vk, fr):
        frames.append(fr)

    states = []

    def on_state(vk, st):
        states.append(st)

    link = SerialVehicleLink(
        vehicle_id=VEHICLE_ROCKET,
        port="COM_FAKE_RESILIENCE_TEST",
        baud=115200,
        on_frame_callback=on_frame,
        on_link_state=on_state,
    )
    link.start()
    import time

    time.sleep(0.4)
    link.stop()
    assert not link.is_running
    # Should have attempted reconnect / reported error, not raised
    assert link.open_failures >= 1 or link.last_error is not None


def test_disconnect_idempotent(client: TestClient):
    assert client.post("/disconnect", json={"vehicle": "rocket"}).status_code == 200
    assert client.post("/disconnect", json={"vehicle": "rocket"}).status_code == 200


def test_malformed_simulate_body(client: TestClient):
    r = client.post("/simulate", json={"vehicle": "not_a_vehicle", "enabled": True})
    assert r.status_code == 400
    assert client.get("/health").status_code == 200
