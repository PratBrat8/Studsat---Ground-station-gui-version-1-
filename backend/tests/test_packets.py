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
from app.frame_parser import FrameParser
from app.protocol import VEHICLE_ROCKET, TelemetryFrame, encode_packet
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


def test_packets_endpoint_bad_vehicle(client: TestClient):
    assert client.get("/packets/balloon").status_code == 400


def test_hub_packet_record_has_hex_and_fields():
    hub = TelemetryHub()
    parser = FrameParser()
    wire = encode_packet(
        VEHICLE_ROCKET,
        3,
        TelemetryFrame(
            timestamp_ms=42,
            altitude_m=100.5,
            pressure_hpa=980.0,
            temperature_c=21.0,
            accel_x=0.0,
            accel_y=0.0,
            accel_z=9.8,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            pitch=1.5,
            yaw=90.0,
            roll=-2.0,
            battery_v=7.6,
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
    snap = hub.packets_snapshot("rocket")
    assert snap["frames_ok"] >= 1
    assert len(snap["recent"]) >= 1
    rec = snap["recent"][0]
    assert "hex" in rec and len(rec["hex"]) > 10
    assert rec["hex"].lower().startswith("aa 55")
    assert rec["type_name"] == "TELEMETRY"
    assert rec["ok"] is True
    assert rec["fields"]["altitude_m"] == pytest.approx(100.5, rel=1e-3)
    assert rec["fields"]["battery_v"] == pytest.approx(7.6, rel=1e-3)
    assert "1" in snap["last_by_type"] or 1 in [
        int(k) for k in snap["last_by_type"].keys()
    ]


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
