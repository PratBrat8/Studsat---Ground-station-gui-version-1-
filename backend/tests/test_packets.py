"""Phase 8 — packet monitor API and enriched frame records."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import app
from app.protocol import FlightState, TelemetryRecord, format_telemetry_csv
from app.radio_transport import format_rcv_line, parse_rcv_line
from app.telemetry_hub import TelemetryHub


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_packets_endpoint_empty(client: TestClient):
    r = client.get("/packets/rocket")
    assert r.status_code == 200
    body = r.json()
    assert body["vehicle"] == "rocket"
    assert body["frames_ok"] == 0
    assert body["recent"] == []
    assert "frames_crc_error" in body
    assert "frames_resynced" in body
    assert "transport_malformed" in body
    assert "app_parse_error" in body
    assert "rssi" in body


def test_packets_endpoint_bad_vehicle(client: TestClient):
    assert client.get("/packets/balloon").status_code == 400


def test_hub_packet_record_has_hex_and_fields():
    hub = TelemetryHub()
    rec_in = TelemetryRecord(
        team_id="XXXX",
        timestamp="00:00:01",
        packet_count=3,
        altitude_m=100.5,
        pressure=980.0,
        temp_c=21.0,
        voltage=7.6,
        gnss_time="00:00:01",
        gnss_lat=12.97,
        gnss_lon=77.59,
        gnss_alt_m=932.5,
        gnss_sats=8,
        accel_x=0.0,
        accel_y=0.0,
        accel_z=9.8,
        gyro_x=0.0,
        gyro_y=0.0,
        gyro_z=0.0,
        flight_software_state=int(FlightState.LAUNCH_PAD),
    )
    pkt = parse_rcv_line(format_rcv_line(1, format_telemetry_csv(rec_in), -70, 8.0))
    assert pkt is not None
    hub.ingest_radio_packet(
        "rocket",
        pkt,
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    snap = hub.packets_snapshot("rocket")
    assert snap["frames_ok"] >= 1
    assert len(snap["recent"]) >= 1
    rec = snap["recent"][0]
    assert "hex" in rec and len(rec["hex"]) > 10
    assert rec["layer"] == "application"
    assert rec["type_name"] == "TELEMETRY"
    assert rec["ok"] is True
    assert rec["rssi"] == -70
    assert rec["fields"]["altitude_m"] == pytest.approx(100.5, rel=1e-3)
    assert rec["fields"]["voltage"] == pytest.approx(7.6, rel=1e-3)
    assert "TELEMETRY" in snap["last_by_type"]


def test_packets_via_http_after_sim(client: TestClient):
    client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    import time

    time.sleep(0.8)
    r = client.get("/packets/rocket?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["frames_ok"] >= 1
    assert len(body["recent"]) >= 1
    assert body["recent"][0]["hex"]
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})


def test_health_phase8(client: TestClient):
    assert client.get("/health").json()["phase"] >= 8
