"""
Wire protocol for STUDSAT ground-station telemetry (PRD C.2).

[ASSUMED] frame layout — isolated here so firmware format changes are a
one-file edit. Mirror field order/sizes in firmware and (later) protocol.ts.

Frame (serial byte stream, little-endian payloads):

  SYNC0 | SYNC1 | VEHICLE_ID | PACKET_TYPE | SEQ | LEN | PAYLOAD[N] | CRC16
  0xAA    0x55     1 B           1 B          1 B   1 B    N B         2 B

CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, xorout 0x0000, refin/refout false.
CRC covers VEHICLE_ID .. end of PAYLOAD (not sync bytes, not CRC itself).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SYNC0 = 0xAA
SYNC1 = 0x55

VEHICLE_ROCKET = 0x01
VEHICLE_SATELLITE = 0x02

TYPE_TELEMETRY = 0x01
TYPE_GPS = 0x02
TYPE_STATUS = 0x03
TYPE_EVENT = 0x04

HEADER_SIZE = 4  # VEHICLE_ID + TYPE + SEQ + LEN
CRC_SIZE = 2
SYNC_SIZE = 2
MIN_FRAME_SIZE = SYNC_SIZE + HEADER_SIZE + CRC_SIZE  # 8, zero-length payload

# Payload struct formats (little-endian)
# TELEMETRY: u32 + 13×f32 = 4 + 52 = 56
_TELEMETRY_FMT = "<I13f"
TELEMETRY_PAYLOAD_SIZE = struct.calcsize(_TELEMETRY_FMT)  # 56

# GPS: u32 + 2×f64 + f32 + u8 + f32 + u8 = 4+16+4+1+4+1 = 30
_GPS_FMT = "<IddfBfB"
GPS_PAYLOAD_SIZE = struct.calcsize(_GPS_FMT)  # 30

# STATUS: u8 + f32 + u8 = 6
_STATUS_FMT = "<BfB"
STATUS_PAYLOAD_SIZE = struct.calcsize(_STATUS_FMT)  # 6

MAX_PAYLOAD_LEN = 255
MAX_EVENT_LEN = 200


class VehicleId(IntEnum):
    ROCKET = VEHICLE_ROCKET
    SATELLITE = VEHICLE_SATELLITE


class PacketType(IntEnum):
    TELEMETRY = TYPE_TELEMETRY
    GPS = TYPE_GPS
    STATUS = TYPE_STATUS
    EVENT = TYPE_EVENT


# ---------------------------------------------------------------------------
# CRC-16/CCITT-FALSE
# ---------------------------------------------------------------------------
def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE over *data* (poly 0x1021, init 0xFFFF)."""
    crc = init & 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


# ---------------------------------------------------------------------------
# Typed payload dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TelemetryFrame:
    timestamp_ms: int
    altitude_m: float
    pressure_hpa: float
    temperature_c: float
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    pitch: float
    yaw: float
    roll: float
    battery_v: float


@dataclass(frozen=True, slots=True)
class GpsFrame:
    gps_timestamp: int
    lat: float
    lon: float
    alt_msl_m: float
    num_sats: int
    hdop: float
    fix_type: int  # 0=no fix, 1=2D, 2=3D


@dataclass(frozen=True, slots=True)
class StatusFrame:
    phase_hint: int  # 0 = let ground station decide
    battery_v: float
    error_flags: int


@dataclass(frozen=True, slots=True)
class EventFrame:
    message: str


DecodedPayload = Union[TelemetryFrame, GpsFrame, StatusFrame, EventFrame]


@dataclass(frozen=True, slots=True)
class RawFrame:
    """Validated frame after CRC check; payload still raw bytes."""

    vehicle_id: int
    packet_type: int
    seq: int
    payload: bytes
    # Full on-wire bytes including sync + CRC (for Packet Monitor hex view)
    raw_bytes: bytes


class ProtocolError(ValueError):
    """Raised when encode/decode inputs are invalid (never from live parser path)."""


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------
def encode_telemetry(frame: TelemetryFrame) -> bytes:
    return struct.pack(
        _TELEMETRY_FMT,
        int(frame.timestamp_ms) & 0xFFFFFFFF,
        float(frame.altitude_m),
        float(frame.pressure_hpa),
        float(frame.temperature_c),
        float(frame.accel_x),
        float(frame.accel_y),
        float(frame.accel_z),
        float(frame.gyro_x),
        float(frame.gyro_y),
        float(frame.gyro_z),
        float(frame.pitch),
        float(frame.yaw),
        float(frame.roll),
        float(frame.battery_v),
    )


def encode_gps(frame: GpsFrame) -> bytes:
    return struct.pack(
        _GPS_FMT,
        int(frame.gps_timestamp) & 0xFFFFFFFF,
        float(frame.lat),
        float(frame.lon),
        float(frame.alt_msl_m),
        int(frame.num_sats) & 0xFF,
        float(frame.hdop),
        int(frame.fix_type) & 0xFF,
    )


def encode_status(frame: StatusFrame) -> bytes:
    return struct.pack(
        _STATUS_FMT,
        int(frame.phase_hint) & 0xFF,
        float(frame.battery_v),
        int(frame.error_flags) & 0xFF,
    )


def encode_event(frame: EventFrame) -> bytes:
    raw = frame.message.encode("utf-8")
    if len(raw) > MAX_EVENT_LEN:
        raise ProtocolError(f"event message too long: {len(raw)} > {MAX_EVENT_LEN}")
    return raw


def encode_frame(
    vehicle_id: int,
    packet_type: int,
    seq: int,
    payload: bytes,
) -> bytes:
    """Build a complete on-wire frame (sync + header + payload + CRC)."""
    if not (0 <= vehicle_id <= 0xFF):
        raise ProtocolError(f"vehicle_id out of range: {vehicle_id}")
    if not (0 <= packet_type <= 0xFF):
        raise ProtocolError(f"packet_type out of range: {packet_type}")
    if not (0 <= seq <= 0xFF):
        raise ProtocolError(f"seq out of range: {seq}")
    if len(payload) > MAX_PAYLOAD_LEN:
        raise ProtocolError(f"payload too long: {len(payload)}")

    header = bytes(
        [
            vehicle_id & 0xFF,
            packet_type & 0xFF,
            seq & 0xFF,
            len(payload) & 0xFF,
        ]
    )
    body = header + payload
    crc = crc16_ccitt(body)
    crc_bytes = struct.pack("<H", crc)  # little-endian CRC on wire
    return bytes([SYNC0, SYNC1]) + body + crc_bytes


def encode_packet(
    vehicle_id: int,
    seq: int,
    decoded: DecodedPayload,
) -> bytes:
    """Encode a typed payload dataclass into a full wire frame."""
    if isinstance(decoded, TelemetryFrame):
        return encode_frame(vehicle_id, TYPE_TELEMETRY, seq, encode_telemetry(decoded))
    if isinstance(decoded, GpsFrame):
        return encode_frame(vehicle_id, TYPE_GPS, seq, encode_gps(decoded))
    if isinstance(decoded, StatusFrame):
        return encode_frame(vehicle_id, TYPE_STATUS, seq, encode_status(decoded))
    if isinstance(decoded, EventFrame):
        return encode_frame(vehicle_id, TYPE_EVENT, seq, encode_event(decoded))
    raise ProtocolError(f"unknown payload type: {type(decoded)!r}")


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------
def decode_telemetry(payload: bytes) -> TelemetryFrame:
    if len(payload) != TELEMETRY_PAYLOAD_SIZE:
        raise ProtocolError(
            f"telemetry payload size {len(payload)} != {TELEMETRY_PAYLOAD_SIZE}"
        )
    fields = struct.unpack(_TELEMETRY_FMT, payload)
    return TelemetryFrame(
        timestamp_ms=fields[0],
        altitude_m=fields[1],
        pressure_hpa=fields[2],
        temperature_c=fields[3],
        accel_x=fields[4],
        accel_y=fields[5],
        accel_z=fields[6],
        gyro_x=fields[7],
        gyro_y=fields[8],
        gyro_z=fields[9],
        pitch=fields[10],
        yaw=fields[11],
        roll=fields[12],
        battery_v=fields[13],
    )


def decode_gps(payload: bytes) -> GpsFrame:
    if len(payload) != GPS_PAYLOAD_SIZE:
        raise ProtocolError(f"gps payload size {len(payload)} != {GPS_PAYLOAD_SIZE}")
    (
        gps_timestamp,
        lat,
        lon,
        alt_msl_m,
        num_sats,
        hdop,
        fix_type,
    ) = struct.unpack(_GPS_FMT, payload)
    return GpsFrame(
        gps_timestamp=gps_timestamp,
        lat=lat,
        lon=lon,
        alt_msl_m=alt_msl_m,
        num_sats=num_sats,
        hdop=hdop,
        fix_type=fix_type,
    )


def decode_status(payload: bytes) -> StatusFrame:
    if len(payload) != STATUS_PAYLOAD_SIZE:
        raise ProtocolError(
            f"status payload size {len(payload)} != {STATUS_PAYLOAD_SIZE}"
        )
    phase_hint, battery_v, error_flags = struct.unpack(_STATUS_FMT, payload)
    return StatusFrame(
        phase_hint=phase_hint,
        battery_v=battery_v,
        error_flags=error_flags,
    )


def decode_event(payload: bytes) -> EventFrame:
    try:
        message = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"event payload not valid UTF-8: {exc}") from exc
    return EventFrame(message=message)


def decode_payload(packet_type: int, payload: bytes) -> DecodedPayload:
    """Decode payload bytes into a typed frame (PRD C.3 protocol.py)."""
    if packet_type == TYPE_TELEMETRY:
        return decode_telemetry(payload)
    if packet_type == TYPE_GPS:
        return decode_gps(payload)
    if packet_type == TYPE_STATUS:
        return decode_status(payload)
    if packet_type == TYPE_EVENT:
        return decode_event(payload)
    raise ProtocolError(f"unknown packet_type: 0x{packet_type:02X}")


def vehicle_name(vehicle_id: int) -> str:
    if vehicle_id == VEHICLE_ROCKET:
        return "rocket"
    if vehicle_id == VEHICLE_SATELLITE:
        return "satellite"
    return f"unknown_{vehicle_id}"
