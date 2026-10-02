"""
Application-layer protocol — competition CSV telemetry + CMD builders (PRD v2 C.3).

This module does not speak Reyax AT. Radio framing is radio_transport.py.

TEMPORARY/UNCONFIRMED (Appendix 1.1): CSV layout assumes 3 separate
accelerometer fields and 3 separate gyro fields (19 columns total).
Confirm against a real firmware sample line before flight.

TEMPORARY/UNCONFIRMED (Appendix 1.3): firmware is assumed NOT to send
an application-level command ACK. Do not parse or invent ACKED here.

TEMPORARY/UNCONFIRMED (Appendix 1.7): cmd_manual_ejection() builds
CMD,<TEAM_ID>,EJ,R — routing that string onto the Rocket/Avionics
Reyax (not CanSat) is the serial/command layer's job.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Sequence

from app.config import TEAM_ID

# Pipeline ids (not Reyax module addresses — those live in config.py).
VEHICLE_ROCKET = 0x01
VEHICLE_SATELLITE = 0x02
VEHICLE_CANSAT = VEHICLE_SATELLITE

# TEMPORARY/UNCONFIRMED — 19 fields, accel/gyro split into 3 axes each.
CSV_FIELDS: Sequence[str] = (
    "TEAM_ID",
    "TIMESTAMP",
    "PACKET_COUNT",
    "ALTITUDE",
    "PRESSURE",
    "TEMP",
    "VOLTAGE",
    "GNSS_TIME",
    "GNSS_LAT",
    "GNSS_LON",
    "GNSS_ALT",
    "GNSS_SATS",
    "ACCEL_X",
    "ACCEL_Y",
    "ACCEL_Z",
    "GYRO_X",
    "GYRO_Y",
    "GYRO_Z",
    "FLIGHT_SOFTWARE_STATE",
)
CSV_FIELD_COUNT = len(CSV_FIELDS)  # 19


class FlightState(IntEnum):
    """CDR 8-state flight software field (PRD v2 B.3)."""

    BOOT = 0
    TEST_MODE = 1
    LAUNCH_PAD = 2
    ASCENT = 3
    PAYLOAD_SEP = 4
    DESCENT = 5
    AEROBREAK_RELEASE = 6
    IMPACT = 7


FLIGHT_STATE_NAMES = {
    FlightState.BOOT: "BOOT",
    FlightState.TEST_MODE: "TEST_MODE",
    FlightState.LAUNCH_PAD: "LAUNCH_PAD",
    FlightState.ASCENT: "ASCENT",
    FlightState.PAYLOAD_SEP: "PAYLOAD_SEP",
    FlightState.DESCENT: "DESCENT",
    FlightState.AEROBREAK_RELEASE: "AEROBREAK_RELEASE",
    FlightState.IMPACT: "IMPACT",
}


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    team_id: str
    timestamp: str
    packet_count: int
    altitude_m: float
    pressure: float
    temp_c: float
    voltage: float
    gnss_time: str
    gnss_lat: float
    gnss_lon: float
    gnss_alt_m: float
    gnss_sats: int
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    flight_software_state: int


@dataclass
class CsvParseStats:
    ok: int = 0
    field_count_error: int = 0
    type_error: int = 0

    @property
    def errors(self) -> int:
        return self.field_count_error + self.type_error

    def reset(self) -> None:
        self.ok = 0
        self.field_count_error = 0
        self.type_error = 0


def _f(value: str) -> float:
    return float(value.strip())


def _i(value: str) -> int:
    return int(value.strip())


def parse_telemetry_csv(
    data: str,
    stats: Optional[CsvParseStats] = None,
) -> Optional[TelemetryRecord]:
    """
    Split a competition CSV line, validate count + types.

    Returns None (and increments stats) on any mismatch — never raises.
    """
    if data is None:
        if stats is not None:
            stats.field_count_error += 1
        return None
    line = data.strip("\r\n")
    if not line:
        if stats is not None:
            stats.field_count_error += 1
        return None
    parts: List[str] = line.split(",")
    if len(parts) != CSV_FIELD_COUNT:
        if stats is not None:
            stats.field_count_error += 1
        return None
    try:
        record = TelemetryRecord(
            team_id=parts[0].strip(),
            timestamp=parts[1].strip(),
            packet_count=_i(parts[2]),
            altitude_m=_f(parts[3]),
            pressure=_f(parts[4]),
            temp_c=_f(parts[5]),
            voltage=_f(parts[6]),
            gnss_time=parts[7].strip(),
            gnss_lat=_f(parts[8]),
            gnss_lon=_f(parts[9]),
            gnss_alt_m=_f(parts[10]),
            gnss_sats=_i(parts[11]),
            accel_x=_f(parts[12]),
            accel_y=_f(parts[13]),
            accel_z=_f(parts[14]),
            gyro_x=_f(parts[15]),
            gyro_y=_f(parts[16]),
            gyro_z=_f(parts[17]),
            flight_software_state=_i(parts[18]),
        )
    except (TypeError, ValueError):
        if stats is not None:
            stats.type_error += 1
        return None
    if stats is not None:
        stats.ok += 1
    return record


def format_telemetry_csv(record: TelemetryRecord) -> str:
    """Serialize a record to the 19-field CSV line (no trailing CR/LF)."""
    return ",".join(
        [
            str(record.team_id),
            str(record.timestamp),
            str(int(record.packet_count)),
            f"{record.altitude_m:.2f}",
            f"{record.pressure:.2f}",
            f"{record.temp_c:.2f}",
            f"{record.voltage:.2f}",
            str(record.gnss_time),
            f"{record.gnss_lat:.6f}",
            f"{record.gnss_lon:.6f}",
            f"{record.gnss_alt_m:.2f}",
            str(int(record.gnss_sats)),
            f"{record.accel_x:.3f}",
            f"{record.accel_y:.3f}",
            f"{record.accel_z:.3f}",
            f"{record.gyro_x:.3f}",
            f"{record.gyro_y:.3f}",
            f"{record.gyro_z:.3f}",
            str(int(record.flight_software_state)),
        ]
    )


def cmd_telemetry_power(team_id: str, on: bool) -> str:
    return f"CMD,{team_id},TX,{'ON' if on else 'OFF'}"


def cmd_set_time(team_id: str, utc_time: str) -> str:
    return f"CMD,{team_id},ST,{utc_time}"


def cmd_calibrate(team_id: str, which: str) -> str:
    """which: 'CG' gyro, 'CB' baro, 'CA' accel."""
    code = which.strip().upper()
    if code not in ("CG", "CB", "CA"):
        raise ValueError(f"unknown calibrate code: {which}")
    return f"CMD,{team_id},{code},R"


def cmd_manual_ejection(team_id: str) -> str:
    """
    CUSTOM command (not in CDR).

    TEMPORARY/UNCONFIRMED (Appendix 1.7): send on the Rocket/Avionics
    radio line only — the Teensy owns the separation mechanism.
    """
    return f"CMD,{team_id},EJ,R"


def default_team_id() -> str:
    return TEAM_ID


def vehicle_name(vehicle_id: int) -> str:
    if vehicle_id == VEHICLE_ROCKET:
        return "rocket"
    if vehicle_id == VEHICLE_SATELLITE:
        return "satellite"
    return f"unknown_{vehicle_id}"


def vehicle_reyax_addr(vehicle_id: int) -> int:
    """Placeholder mapping pipeline id → vehicle-side Reyax address."""
    from app.config import CANSAT_VEHICLE_ADDR, ROCKET_VEHICLE_ADDR

    if vehicle_id == VEHICLE_ROCKET:
        return ROCKET_VEHICLE_ADDR
    if vehicle_id == VEHICLE_SATELLITE:
        return CANSAT_VEHICLE_ADDR
    raise ValueError(f"unsupported vehicle_id: {vehicle_id}")
