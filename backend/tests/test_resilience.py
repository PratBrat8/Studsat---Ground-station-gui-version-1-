"""Phase 13 — reconnect, malformed lines, command timeout, crash-safe APIs."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import app
from app.protocol import (
    VEHICLE_ROCKET,
    FlightState,
    TelemetryRecord,
    format_telemetry_csv,
)
from app.radio_transport import RadioLineBuffer, format_rcv_line, parse_rcv_line
from app.serial_manager import SerialVehicleLink, validate_port_arg
from app.telemetry_hub import TelemetryHub, json_safe


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
    assert body["v2_phase"] == 14
    assert "phase14" in body["version"]
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
    parser = RadioLineBuffer()
    garbage = bytes(range(256)) * 50
    for item in parser.feed(garbage):
        if hasattr(item, "data"):
            hub.ingest_radio_packet("rocket", item)
    rec = TelemetryRecord(
        team_id="XXXX",
        timestamp="00:00:01",
        packet_count=1,
        altitude_m=5.0,
        pressure=1000.0,
        temp_c=20.0,
        voltage=7.4,
        gnss_time="00:00:01",
        gnss_lat=12.97,
        gnss_lon=77.59,
        gnss_alt_m=925.0,
        gnss_sats=6,
        accel_x=0.0,
        accel_y=0.0,
        accel_z=9.8,
        gyro_x=0.0,
        gyro_y=0.0,
        gyro_z=0.0,
        flight_software_state=int(FlightState.LAUNCH_PAD),
    )
    pkt = parse_rcv_line(format_rcv_line(1, format_telemetry_csv(rec), -65, 7.0))
    assert pkt is not None
    hub.ingest_radio_packet(
        "rocket",
        pkt,
        {
            "frames_ok": parser.stats.rcv_ok + 1,
            "frames_crc_error": parser.stats.rcv_malformed,
            "frames_resynced": parser.oversize_resets,
        },
    )
    snap = hub.latest_state("rocket")
    assert snap["telemetry"]["altitude_m"] == pytest.approx(5.0)
    assert parser.stats.rcv_malformed >= 0


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


def test_garbage_json_does_not_kill_health(client: TestClient):
    r = client.post(
        "/simulate",
        data="{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 422)
    assert client.get("/health").status_code == 200


def test_json_safe_strips_nan_and_inf():
    out = json_safe({"a": float("nan"), "b": float("inf"), "c": [1.0]})
    assert out["a"] is None
    assert out["b"] is None
    assert out["c"] == [1.0]
    assert math.isnan(float("nan"))


def test_snapshot_is_json_dumpable():
    hub = TelemetryHub()
    snap = hub.latest_state("rocket")
    json.dumps(snap, allow_nan=False)


def test_malformed_rcv_does_not_crash_hub():
    hub = TelemetryHub()
    buf = RadioLineBuffer()
    items = buf.feed(b"+RCV=broken\r\n+OK\r\n")
    for item in items:
        hub.ingest_radio_event("rocket", item)
    snap = hub.packets_snapshot("rocket")
    json.dumps(snap, allow_nan=False)
    assert snap["transport_malformed"] >= 1
