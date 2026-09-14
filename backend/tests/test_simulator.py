"""Simulator emits real protocol frames through FrameParser (PRD Phase 2)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.frame_parser import FrameParser
from app.protocol import (
    TYPE_TELEMETRY,
    VEHICLE_ROCKET,
    VEHICLE_SATELLITE,
    decode_payload,
)
from app.simulator import SimulatedVehicleLink, generate_flight_bytes


def test_generate_flight_bytes_parses_cleanly():
    blob = generate_flight_bytes(
        vehicle_id=VEHICLE_ROCKET, duration_s=2.0, hz=10.0, seed=42
    )
    assert len(blob) > 100
    parser = FrameParser()
    frames = parser.feed(blob)
    assert parser.frames_crc_error == 0
    assert parser.frames_ok == len(frames)
    assert len(frames) >= 20  # 2s * 10 Hz telem + some GPS
    telem = [f for f in frames if f.packet_type == TYPE_TELEMETRY]
    assert len(telem) >= 15
    decoded = decode_payload(telem[0].packet_type, telem[0].payload)
    assert decoded.battery_v > 0


def test_sim_link_thread_emits_parsed_frames():
    received = []

    def on_frame(vehicle_key, frame):
        received.append((vehicle_key, frame))

    link = SimulatedVehicleLink(
        vehicle_id=VEHICLE_SATELLITE,
        on_frame_callback=on_frame,
        hz=20.0,
        seed=7,
    )
    link.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and len(received) < 10:
            time.sleep(0.05)
    finally:
        link.stop()

    assert len(received) >= 10
    assert all(vk == "satellite" for vk, _ in received)
    assert link.parser.frames_ok >= 10
    assert link.parser.frames_crc_error == 0
    # At least one telemetry sample with sensible altitude field
    alts = []
    for _, fr in received:
        if fr.packet_type == TYPE_TELEMETRY:
            alts.append(decode_payload(fr.packet_type, fr.payload).altitude_m)
    assert alts
    assert min(alts) >= -5.0  # AGL near pad can be ~0


def test_sim_stop_is_idempotent():
    link = SimulatedVehicleLink(
        vehicle_id=VEHICLE_ROCKET,
        on_frame_callback=lambda *_: None,
        hz=5.0,
    )
    link.start()
    time.sleep(0.2)
    link.stop()
    link.stop()
    assert not link.is_running
