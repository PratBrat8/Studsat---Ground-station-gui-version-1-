"""Unit tests for FrameParser — valid, corrupt, split feeds, resync (PRD Phase 2)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.frame_parser import FrameParser
from app.protocol import (
    TYPE_EVENT,
    TYPE_GPS,
    TYPE_TELEMETRY,
    VEHICLE_ROCKET,
    VEHICLE_SATELLITE,
    EventFrame,
    GpsFrame,
    TelemetryFrame,
    crc16_ccitt,
    decode_payload,
    encode_frame,
    encode_packet,
)


def _telem(alt: float = 100.0, seq: int = 0, vehicle: int = VEHICLE_ROCKET) -> bytes:
    t = TelemetryFrame(
        timestamp_ms=1000,
        altitude_m=alt,
        pressure_hpa=1000.0,
        temperature_c=20.0,
        accel_x=0.0,
        accel_y=0.0,
        accel_z=9.8,
        gyro_x=0.0,
        gyro_y=0.0,
        gyro_z=0.0,
        pitch=1.0,
        yaw=2.0,
        roll=3.0,
        battery_v=7.4,
    )
    return encode_packet(vehicle, seq, t)


def test_single_valid_frame():
    parser = FrameParser()
    wire = _telem(alt=42.0, seq=5)
    frames = parser.feed(wire)
    assert len(frames) == 1
    assert parser.frames_ok == 1
    assert parser.frames_crc_error == 0
    fr = frames[0]
    assert fr.vehicle_id == VEHICLE_ROCKET
    assert fr.packet_type == TYPE_TELEMETRY
    assert fr.seq == 5
    assert fr.raw_bytes == wire
    decoded = decode_payload(fr.packet_type, fr.payload)
    assert decoded.altitude_m == pytest.approx(42.0)


def test_multiple_frames_in_one_chunk():
    parser = FrameParser()
    blob = _telem(seq=0) + _telem(seq=1) + _telem(seq=2, vehicle=VEHICLE_SATELLITE)
    frames = parser.feed(blob)
    assert len(frames) == 3
    assert parser.frames_ok == 3
    assert frames[0].seq == 0
    assert frames[1].seq == 1
    assert frames[2].vehicle_id == VEHICLE_SATELLITE


def test_split_across_feed_calls():
    """Incremental feed — critical for serial 20 ms reads."""
    parser = FrameParser()
    wire = _telem(seq=9)
    mid = len(wire) // 3
    assert parser.feed(wire[:mid]) == []
    assert parser.feed(wire[mid : mid * 2]) == []
    frames = parser.feed(wire[mid * 2 :])
    assert len(frames) == 1
    assert frames[0].seq == 9
    assert parser.frames_ok == 1


def test_byte_by_byte_feed():
    parser = FrameParser()
    wire = _telem(seq=3)
    got = []
    for b in wire:
        got.extend(parser.feed(bytes([b])))
    assert len(got) == 1
    assert got[0].seq == 3


def test_corrupt_crc_dropped_and_counted():
    parser = FrameParser()
    wire = bytearray(_telem(seq=1))
    # Flip last CRC byte
    wire[-1] ^= 0xFF
    frames = parser.feed(bytes(wire))
    assert frames == []
    assert parser.frames_ok == 0
    assert parser.frames_crc_error == 1
    assert parser.frames_resynced >= 1


def test_good_frame_after_corrupt_crc():
    parser = FrameParser()
    bad = bytearray(_telem(seq=1))
    bad[-1] ^= 0xAA
    good = _telem(seq=2, alt=77.0)
    frames = parser.feed(bytes(bad) + good)
    assert parser.frames_crc_error == 1
    assert len(frames) == 1
    assert frames[0].seq == 2
    decoded = decode_payload(frames[0].packet_type, frames[0].payload)
    assert decoded.altitude_m == pytest.approx(77.0)
    assert parser.frames_ok == 1


def test_noise_before_sync_then_valid():
    parser = FrameParser()
    noise = bytes([0x00, 0x11, 0x22, 0xAA, 0x00, 0x55, 0x99])  # false starts
    good = _telem(seq=4)
    frames = parser.feed(noise + good)
    assert len(frames) == 1
    assert frames[0].seq == 4
    assert parser.frames_ok == 1
    assert parser.frames_resynced >= 1


def test_garbage_stream_never_raises():
    parser = FrameParser()
    garbage = bytes(range(256)) * 20
    # Must not raise
    frames = parser.feed(garbage)
    assert isinstance(frames, list)
    # Follow with a real frame — parser still usable
    frames2 = parser.feed(_telem(seq=10))
    assert len(frames2) == 1
    assert frames2[0].seq == 10


def test_empty_and_none_like_feed():
    parser = FrameParser()
    assert parser.feed(b"") == []
    assert parser.feed(bytearray()) == []


def test_event_and_gps_types():
    parser = FrameParser()
    e = encode_packet(VEHICLE_ROCKET, 1, EventFrame("CHUTE_DEPLOY"))
    g = encode_packet(
        VEHICLE_ROCKET,
        2,
        GpsFrame(
            gps_timestamp=1,
            lat=1.0,
            lon=2.0,
            alt_msl_m=3.0,
            num_sats=5,
            hdop=1.1,
            fix_type=2,
        ),
    )
    frames = parser.feed(e + g)
    assert len(frames) == 2
    assert frames[0].packet_type == TYPE_EVENT
    assert decode_payload(TYPE_EVENT, frames[0].payload).message == "CHUTE_DEPLOY"
    assert frames[1].packet_type == TYPE_GPS
    assert decode_payload(TYPE_GPS, frames[1].payload).lat == pytest.approx(1.0)


def test_manual_bad_crc_construction():
    """Build frame with wrong CRC explicitly via encode_frame parts."""
    payload = b"\x01\x02\x03"
    header = bytes([VEHICLE_ROCKET, TYPE_EVENT, 0, len(payload)])
    body = header + payload
    wrong_crc = (crc16_ccitt(body) ^ 0x1111) & 0xFFFF
    wire = bytes([0xAA, 0x55]) + body + struct.pack("<H", wrong_crc)
    # Sanity: encode_frame would have correct CRC
    good = encode_frame(VEHICLE_ROCKET, TYPE_EVENT, 0, payload)
    assert good != wire

    parser = FrameParser()
    assert parser.feed(wire) == []
    assert parser.frames_crc_error == 1


def test_two_valid_with_noise_between():
    parser = FrameParser()
    a = _telem(seq=1)
    b = _telem(seq=2)
    frames = parser.feed(a + b"\xDE\xAD\xBE\xEF" + b)
    assert len(frames) == 2
    assert [f.seq for f in frames] == [1, 2]
