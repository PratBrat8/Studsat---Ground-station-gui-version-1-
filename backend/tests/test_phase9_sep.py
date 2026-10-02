"""Phase 9 — CDR 8-state progress + Rocket PAYLOAD_SEP mission event."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.protocol import FLIGHT_STATE_NAMES, FlightState, TelemetryRecord, format_telemetry_csv
from app.radio_transport import format_rcv_line, parse_rcv_line
from app.telemetry_hub import TelemetryHub


def _pkt(count, state, lat=12.97, lon=77.59, alt=100.0):
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
    return parse_rcv_line(format_rcv_line(1, format_telemetry_csv(rec), -70, 8.0))


def test_cdr_has_eight_named_states():
    assert len(FLIGHT_STATE_NAMES) == 8
    assert list(FLIGHT_STATE_NAMES[s] for s in FlightState) == [
        "BOOT",
        "TEST_MODE",
        "LAUNCH_PAD",
        "ASCENT",
        "PAYLOAD_SEP",
        "DESCENT",
        "AEROBREAK_RELEASE",
        "IMPACT",
    ]


def test_rocket_payload_sep_flags_both_vehicles():
    hub = TelemetryHub()
    hub.ingest_radio_packet(
        "rocket",
        _pkt(1, FlightState.ASCENT, alt=200.0),
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    assert hub.latest_state("rocket")["cansat_separated"] is False
    assert hub.latest_state("satellite")["cansat_separated"] is False

    hub.ingest_radio_packet(
        "rocket",
        _pkt(2, FlightState.PAYLOAD_SEP, alt=250.0),
        {"frames_ok": 2, "frames_crc_error": 0, "frames_resynced": 0},
    )
    rocket = hub.latest_state("rocket")
    sat = hub.latest_state("satellite")
    assert rocket["phase"] == "PAYLOAD_SEP"
    assert rocket["cansat_separated"] is True
    assert sat["cansat_separated"] is True
    assert "CanSat Separated" in rocket["events"]
    assert "CanSat Separated" in sat["events"]


def test_satellite_sep_alone_does_not_set_mission_flag():
    hub = TelemetryHub()
    hub.ingest_radio_packet(
        "satellite",
        _pkt(1, FlightState.PAYLOAD_SEP),
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    assert hub.latest_state("satellite")["phase"] == "PAYLOAD_SEP"
    assert hub.latest_state("satellite")["cansat_separated"] is False
    assert hub.latest_state("rocket")["cansat_separated"] is False


def test_rocket_reset_clears_sep_flag():
    hub = TelemetryHub()
    hub.ingest_radio_packet(
        "rocket",
        _pkt(1, FlightState.PAYLOAD_SEP),
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    assert hub.latest_state("rocket")["cansat_separated"] is True
    hub.reset_vehicle("rocket")
    assert hub.latest_state("rocket")["cansat_separated"] is False
    assert hub.latest_state("satellite")["cansat_separated"] is False
