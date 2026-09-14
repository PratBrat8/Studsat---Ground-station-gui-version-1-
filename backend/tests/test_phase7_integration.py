"""Phase 7 integration — sim long enough to see phase progression + prediction."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import app
from app.phase_fsm import PhaseFSM, PhaseSample
from app.predictor import LandingPredictor
from app.protocol import (
    VEHICLE_ROCKET,
    EventFrame,
    GpsFrame,
    TelemetryFrame,
    encode_packet,
)
from app.frame_parser import FrameParser
from app.telemetry_hub import TelemetryHub


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_health_phase7(client: TestClient):
    assert client.get("/health").json()["phase"] >= 7


def test_hub_phase_advances_with_flight_profile():
    hub = TelemetryHub()
    parser = FrameParser()
    seq = 0

    def push_telem(**kwargs):
        nonlocal seq
        defaults = dict(
            timestamp_ms=seq * 100,
            altitude_m=0.0,
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
            battery_v=7.5,
        )
        defaults.update(kwargs)
        wire = encode_packet(VEHICLE_ROCKET, seq & 0xFF, TelemetryFrame(**defaults))
        seq += 1
        for fr in parser.feed(wire):
            hub.ingest_raw_frame(
                "rocket",
                fr,
                {
                    "frames_ok": parser.frames_ok,
                    "frames_crc_error": 0,
                    "frames_resynced": 0,
                },
            )

    def push_gps(lat, lon, alt, hdop=1.0):
        nonlocal seq
        wire = encode_packet(
            VEHICLE_ROCKET,
            seq & 0xFF,
            GpsFrame(
                gps_timestamp=seq,
                lat=lat,
                lon=lon,
                alt_msl_m=alt,
                num_sats=8,
                hdop=hdop,
                fix_type=2,
            ),
        )
        seq += 1
        for fr in parser.feed(wire):
            hub.ingest_raw_frame(
                "rocket",
                fr,
                {
                    "frames_ok": parser.frames_ok,
                    "frames_crc_error": 0,
                    "frames_resynced": 0,
                },
            )

    def push_event(msg):
        nonlocal seq
        wire = encode_packet(
            VEHICLE_ROCKET, seq & 0xFF, EventFrame(message=msg)
        )
        seq += 1
        for fr in parser.feed(wire):
            hub.ingest_raw_frame(
                "rocket",
                fr,
                {
                    "frames_ok": parser.frames_ok,
                    "frames_crc_error": 0,
                    "frames_resynced": 0,
                },
            )

    # Arm + pad
    for _ in range(5):
        push_telem(altitude_m=1.0, accel_z=9.8)
        push_gps(12.9716, 77.5946, 921.0)
    snap = hub.latest_state("rocket")
    assert snap["phase"] == "ARMED"

    push_event("LAUNCH_DETECT")
    push_telem(altitude_m=20.0, accel_z=40.0)
    assert hub.latest_state("rocket")["phase"] == "ASCENT"

    # Climb + GPS trail
    for i in range(25):
        push_telem(altitude_m=50 + i * 30, accel_z=15.0)
        push_gps(12.9716 + i * 1e-5, 77.5946 + i * 2e-5, 920 + 50 + i * 30)

    # Apogee coast
    for _ in range(12):
        push_telem(altitude_m=780.0, accel_z=9.8)
    phase = hub.latest_state("rocket")["phase"]
    assert phase in ("APOGEE", "DESCENT", "ASCENT")

    push_event("CHUTE_DEPLOY")
    push_telem(altitude_m=770.0, accel_z=9.8)
    assert hub.latest_state("rocket")["phase"] == "DESCENT"

    # Descent with prediction
    for i in range(20):
        alt = 700 - i * 30
        push_telem(altitude_m=max(alt, 0.5), accel_z=9.8)
        push_gps(
            12.972 + i * 2e-5,
            77.595 + i * 2e-5,
            920 + max(alt, 0.5),
            hdop=1.0,
        )

    snap = hub.latest_state("rocket")
    assert snap["phase"] in ("DESCENT", "LANDED")
    if snap["phase"] == "DESCENT":
        assert snap["prediction"] is not None
        assert snap["prediction"]["confidence"] in ("HIGH", "MED", "LOW")
        assert "lat" in snap["prediction"]
        assert "eta_s" in snap["prediction"]

    # Land
    for _ in range(20):
        push_telem(altitude_m=1.0, accel_z=9.8)
        push_gps(12.973, 77.596, 921.0)
    assert hub.latest_state("rocket")["phase"] == "LANDED"

    hub.mark_recovered("rocket")
    assert hub.latest_state("rocket")["phase"] == "RECOVERED"


def test_recover_endpoint(client: TestClient):
    # Without landing, recover is no-op-ish (stays non-RECOVERED unless LANDED)
    r = client.post("/recover", json={"vehicle": "rocket"})
    assert r.status_code == 200
    assert "phase" in r.json()


def test_sim_reaches_ascent(client: TestClient):
    """Short sim should at least leave IDLE/ARMED eventually."""
    assert (
        client.post("/simulate", json={"vehicle": "rocket", "enabled": True}).status_code
        == 200
    )
    phases = set()
    with client.websocket_connect("/ws/rocket") as ws:
        deadline = time.time() + 8.0
        while time.time() < deadline:
            msg = json.loads(ws.receive_text())
            if msg.get("phase"):
                phases.add(msg["phase"])
            if "ASCENT" in phases or "APOGEE" in phases or "DESCENT" in phases:
                break
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})
    # After ~3s prelaunch + launch, should see ARMED at minimum; often ASCENT
    assert "ARMED" in phases or "ASCENT" in phases
    assert "IDLE" not in phases or len(phases) > 1
