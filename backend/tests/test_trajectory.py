"""Phase 8 — trajectory path, climb angle, ASCENT trend-line."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.protocol import FlightState, TelemetryRecord, format_telemetry_csv
from app.radio_transport import format_rcv_line, parse_rcv_line
from app.telemetry_hub import TelemetryHub, _predictor_phase
from app.trajectory import ascent_trend, climb_angle_deg, linear_fit


def test_climb_prefers_imu_pitch():
    deg, src = climb_angle_deg(12.5, 20.0, 5.0)
    assert src == "imu_pitch"
    assert deg == pytest.approx(12.5)


def test_climb_falls_back_to_atan2():
    deg, src = climb_angle_deg(None, 10.0, 10.0)
    assert src == "atan2"
    assert deg == pytest.approx(45.0, abs=0.2)


def test_linear_fit_and_trend_projects_forward():
    intercept, slope = linear_fit([0.0, 10.0, 20.0], [0.0, 50.0, 100.0])
    assert intercept == pytest.approx(0.0, abs=1e-6)
    assert slope == pytest.approx(5.0, abs=1e-6)
    path = [
        {"range_m": 0.0, "alt_m": 10.0},
        {"range_m": 20.0, "alt_m": 40.0},
        {"range_m": 40.0, "alt_m": 70.0},
        {"range_m": 60.0, "alt_m": 100.0},
    ]
    trend = ascent_trend(path, window=10, extra_range_m=40.0, steps=4)
    assert len(trend) >= 2
    assert trend[-1]["range_m"] > path[-1]["range_m"]
    assert trend[-1]["alt_m"] > path[-1]["alt_m"]


def test_predictor_phase_payload_sep_is_descent():
    assert _predictor_phase("PAYLOAD_SEP") == "DESCENT"
    assert _predictor_phase("ASCENT") == "ASCENT"
    assert _predictor_phase("IMPACT") == "LANDED"


def _pkt(count, lat, lon, alt, state, rssi=-70):
    rec = TelemetryRecord(
        team_id="XXXX",
        timestamp="00:00:01",
        packet_count=count,
        altitude_m=alt,
        pressure=1000.0,
        temp_c=20.0,
        voltage=7.4,
        gnss_time="00:00:01",
        gnss_lat=lat,
        gnss_lon=lon,
        gnss_alt_m=alt + 900.0,
        gnss_sats=8,
        accel_x=0.0,
        accel_y=0.0,
        accel_z=9.8,
        gyro_x=0.0,
        gyro_y=0.0,
        gyro_z=0.0,
        flight_software_state=int(state),
    )
    return parse_rcv_line(format_rcv_line(1, format_telemetry_csv(rec), rssi, 8.0))


def test_hub_ascent_builds_path_and_trend():
    hub = TelemetryHub()
    lat0, lon0 = 12.9716, 77.5946
    for i in range(8):
        pkt = _pkt(
            i + 1,
            lat0 + i * 0.0002,
            lon0,
            50.0 + i * 20.0,
            FlightState.ASCENT,
        )
        hub.ingest_radio_packet(
            "rocket",
            pkt,
            {"frames_ok": i + 1, "frames_crc_error": 0, "frames_resynced": 0},
        )
    snap = hub.latest_state("rocket")
    traj = snap["trajectory"]
    assert snap["phase"] == "ASCENT"
    assert traj["trend_active"] is True
    assert len(traj["path"]) == 8
    assert traj["path"][-1]["range_m"] > traj["path"][0]["range_m"]
    assert traj["path"][-1]["alt_m"] > traj["path"][0]["alt_m"]
    assert traj["trend"][-1]["range_m"] > traj["path"][-1]["range_m"]
    sat = hub.latest_state("satellite")
    assert sat["trajectory"]["path"] == []


def test_vehicles_keep_independent_origins():
    hub = TelemetryHub()
    hub.ingest_radio_packet(
        "rocket",
        _pkt(1, 12.97, 77.59, 10.0, FlightState.LAUNCH_PAD),
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    hub.ingest_radio_packet(
        "satellite",
        _pkt(1, 13.10, 77.70, 10.0, FlightState.LAUNCH_PAD),
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    r = hub.latest_state("rocket")["trajectory"]["origin"]
    s = hub.latest_state("satellite")["trajectory"]["origin"]
    assert r["lat"] == pytest.approx(12.97)
    assert s["lat"] == pytest.approx(13.10)
