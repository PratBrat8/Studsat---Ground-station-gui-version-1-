"""CSV telemetry + CMD builders (PRD v2 Phase 2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.protocol import (
    CSV_FIELD_COUNT,
    VEHICLE_ROCKET,
    CsvParseStats,
    FlightState,
    TelemetryRecord,
    cmd_calibrate,
    cmd_manual_ejection,
    cmd_set_time,
    cmd_telemetry_power,
    format_telemetry_csv,
    parse_telemetry_csv,
    vehicle_name,
    vehicle_reyax_addr,
)


def _sample(**overrides) -> TelemetryRecord:
    base = dict(
        team_id="XXXX",
        timestamp="00:00:05",
        packet_count=12,
        altitude_m=812.4,
        pressure=934.2,
        temp_c=21.4,
        voltage=7.6,
        gnss_time="00:00:05",
        gnss_lat=12.9716,
        gnss_lon=77.5946,
        gnss_alt_m=1732.4,
        gnss_sats=10,
        accel_x=0.1,
        accel_y=-0.2,
        accel_z=9.81,
        gyro_x=1.0,
        gyro_y=2.0,
        gyro_z=0.5,
        flight_software_state=int(FlightState.ASCENT),
    )
    base.update(overrides)
    return TelemetryRecord(**base)


def test_csv_field_count_is_19_with_3_accel_3_gyro():
    assert CSV_FIELD_COUNT == 19
    line = format_telemetry_csv(_sample())
    assert len(line.split(",")) == 19


def test_roundtrip_csv():
    stats = CsvParseStats()
    original = _sample()
    parsed = parse_telemetry_csv(format_telemetry_csv(original), stats)
    assert parsed is not None
    assert stats.ok == 1
    assert parsed.team_id == "XXXX"
    assert parsed.packet_count == 12
    assert parsed.accel_x == pytest.approx(0.1, abs=0.001)
    assert parsed.accel_y == pytest.approx(-0.2, abs=0.001)
    assert parsed.accel_z == pytest.approx(9.81, abs=0.001)
    assert parsed.gyro_x == pytest.approx(1.0, abs=0.001)
    assert parsed.gyro_y == pytest.approx(2.0, abs=0.001)
    assert parsed.gyro_z == pytest.approx(0.5, abs=0.001)
    assert parsed.flight_software_state == int(FlightState.ASCENT)


def test_wrong_field_count_returns_none():
    stats = CsvParseStats()
    line = format_telemetry_csv(_sample())
    short = ",".join(line.split(",")[:-1])
    assert parse_telemetry_csv(short, stats) is None
    assert stats.field_count_error == 1
    assert stats.ok == 0


def test_non_numeric_field_returns_none():
    stats = CsvParseStats()
    line = format_telemetry_csv(_sample())
    parts = line.split(",")
    parts[3] = "not-a-number"  # ALTITUDE
    assert parse_telemetry_csv(",".join(parts), stats) is None
    assert stats.type_error == 1


def test_empty_and_none():
    stats = CsvParseStats()
    assert parse_telemetry_csv("", stats) is None
    assert parse_telemetry_csv("   \r\n", stats) is None
    assert parse_telemetry_csv(None, stats) is None  # type: ignore[arg-type]
    assert stats.field_count_error == 3


def test_command_builders():
    assert cmd_telemetry_power("XXXX", True) == "CMD,XXXX,TX,ON"
    assert cmd_telemetry_power("XXXX", False) == "CMD,XXXX,TX,OFF"
    assert cmd_set_time("XXXX", "12:34:56") == "CMD,XXXX,ST,12:34:56"
    assert cmd_calibrate("XXXX", "CG") == "CMD,XXXX,CG,R"
    assert cmd_calibrate("XXXX", "cb") == "CMD,XXXX,CB,R"
    assert cmd_calibrate("XXXX", "CA") == "CMD,XXXX,CA,R"
    with pytest.raises(ValueError):
        cmd_calibrate("XXXX", "XX")


def test_manual_ejection_command_string():
    # Routing onto the rocket radio is Phase 3; the payload is this string.
    assert cmd_manual_ejection("XXXX") == "CMD,XXXX,EJ,R"


def test_vehicle_helpers():
    assert vehicle_name(VEHICLE_ROCKET) == "rocket"
    assert vehicle_reyax_addr(VEHICLE_ROCKET) == 1
