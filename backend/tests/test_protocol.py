"""Unit tests for protocol encode/decode and CRC (PRD Phase 2)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

# Allow `pytest` from backend/ or repo root
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.protocol import (
    GPS_PAYLOAD_SIZE,
    STATUS_PAYLOAD_SIZE,
    SYNC0,
    SYNC1,
    TELEMETRY_PAYLOAD_SIZE,
    TYPE_EVENT,
    TYPE_GPS,
    TYPE_STATUS,
    TYPE_TELEMETRY,
    VEHICLE_ROCKET,
    VEHICLE_SATELLITE,
    EventFrame,
    GpsFrame,
    ProtocolError,
    StatusFrame,
    TelemetryFrame,
    crc16_ccitt,
    decode_payload,
    encode_frame,
    encode_packet,
    encode_telemetry,
)


def _sample_telem(**overrides) -> TelemetryFrame:
    base = dict(
        timestamp_ms=12_345,
        altitude_m=812.4,
        pressure_hpa=934.2,
        temperature_c=21.4,
        accel_x=0.1,
        accel_y=-0.2,
        accel_z=9.81,
        gyro_x=1.0,
        gyro_y=2.0,
        gyro_z=3.0,
        pitch=12.3,
        yaw=88.0,
        roll=-4.1,
        battery_v=7.62,
    )
    base.update(overrides)
    return TelemetryFrame(**base)


def test_telemetry_payload_size():
    assert TELEMETRY_PAYLOAD_SIZE == 56
    assert GPS_PAYLOAD_SIZE == 30
    assert STATUS_PAYLOAD_SIZE == 6


def test_crc16_known_vector():
    # Self-consistency + non-trivial output for empty/simple inputs
    assert crc16_ccitt(b"") == 0xFFFF
    c1 = crc16_ccitt(b"123456789")
    # CRC-16/CCITT-FALSE ("123456789") classic check value is 0x29B1
    assert c1 == 0x29B1
    assert crc16_ccitt(b"\x01\x02") != crc16_ccitt(b"\x02\x01")


def test_encode_decode_telemetry_roundtrip():
    t = _sample_telem()
    payload = encode_telemetry(t)
    assert len(payload) == TELEMETRY_PAYLOAD_SIZE
    decoded = decode_payload(TYPE_TELEMETRY, payload)
    assert isinstance(decoded, TelemetryFrame)
    assert decoded.timestamp_ms == t.timestamp_ms
    assert decoded.altitude_m == pytest.approx(t.altitude_m)
    assert decoded.battery_v == pytest.approx(t.battery_v)
    assert decoded.pitch == pytest.approx(t.pitch)


def test_encode_decode_gps_roundtrip():
    g = GpsFrame(
        gps_timestamp=99,
        lat=12.9716,
        lon=77.5946,
        alt_msl_m=910.5,
        num_sats=9,
        hdop=0.9,
        fix_type=2,
    )
    wire = encode_packet(VEHICLE_ROCKET, 7, g)
    assert wire[0] == SYNC0 and wire[1] == SYNC1
    assert wire[2] == VEHICLE_ROCKET
    assert wire[3] == TYPE_GPS
    assert wire[4] == 7
    assert wire[5] == GPS_PAYLOAD_SIZE
    payload = wire[6 : 6 + GPS_PAYLOAD_SIZE]
    decoded = decode_payload(TYPE_GPS, payload)
    assert isinstance(decoded, GpsFrame)
    assert decoded.lat == pytest.approx(12.9716)
    assert decoded.lon == pytest.approx(77.5946)
    assert decoded.num_sats == 9
    assert decoded.fix_type == 2


def test_encode_decode_status_and_event():
    s = StatusFrame(phase_hint=0, battery_v=7.5, error_flags=0x03)
    decoded_s = decode_payload(TYPE_STATUS, encode_packet(VEHICLE_SATELLITE, 1, s)[6:-2])
    # easier via encode helpers
    from app.protocol import encode_status

    decoded_s = decode_payload(TYPE_STATUS, encode_status(s))
    assert decoded_s.battery_v == pytest.approx(7.5)
    assert decoded_s.error_flags == 0x03

    e = EventFrame(message="LAUNCH_DETECT")
    wire = encode_packet(VEHICLE_ROCKET, 2, e)
    assert wire[3] == TYPE_EVENT
    decoded_e = decode_payload(TYPE_EVENT, wire[6:-2])
    assert decoded_e.message == "LAUNCH_DETECT"


def test_frame_crc_covers_header_and_payload():
    t = _sample_telem()
    wire = encode_packet(VEHICLE_ROCKET, 0xAB, t)
    body = wire[2:-2]
    crc_wire = struct.unpack("<H", wire[-2:])[0]
    assert crc16_ccitt(body) == crc_wire


def test_encode_frame_rejects_oversize_payload():
    with pytest.raises(ProtocolError):
        encode_frame(VEHICLE_ROCKET, TYPE_TELEMETRY, 0, b"x" * 256)


def test_unknown_packet_type_raises():
    with pytest.raises(ProtocolError):
        decode_payload(0x7F, b"\x00")
