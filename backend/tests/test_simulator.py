"""Simulator emits +RCV wrapping CSV through both layers (PRD v2 Phase 2)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.protocol import (
    CSV_FIELD_COUNT,
    VEHICLE_ROCKET,
    VEHICLE_SATELLITE,
    parse_telemetry_csv,
)
from app.radio_transport import RadioLineBuffer, RadioPacket
from app.simulator import (
    SimulatedVehicleLink,
    decode_sim_stream,
    generate_flight_bytes,
)


def test_generate_flight_bytes_parses_both_layers():
    blob = generate_flight_bytes(
        vehicle_id=VEHICLE_ROCKET, duration_s=2.0, hz=10.0, seed=42
    )
    assert len(blob) > 100
    pairs = decode_sim_stream(blob)
    assert len(pairs) >= 15
    for pkt, rec in pairs:
        assert isinstance(pkt, RadioPacket)
        assert pkt.address == 1  # ROCKET_VEHICLE_ADDR placeholder
        assert pkt.rssi < 0
        assert rec is not None
        assert rec.voltage > 0
        assert 0 <= rec.flight_software_state <= 7
        assert len(pkt.data.split(",")) == CSV_FIELD_COUNT


def test_sim_link_thread_emits_radio_packets():
    received = []

    def on_packet(vehicle_key, packet):
        received.append((vehicle_key, packet))

    link = SimulatedVehicleLink(
        vehicle_id=VEHICLE_SATELLITE,
        on_packet_callback=on_packet,
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
    assert link.parser.stats.rcv_ok >= 10
    assert link.parser.stats.rcv_malformed == 0
    recs = [parse_telemetry_csv(pkt.data) for _, pkt in received]
    assert all(r is not None for r in recs)
    alts = [r.altitude_m for r in recs if r is not None]
    assert alts
    assert min(alts) >= -5.0


def test_sim_stop_is_idempotent():
    link = SimulatedVehicleLink(
        vehicle_id=VEHICLE_ROCKET,
        on_packet_callback=lambda *_: None,
        hz=5.0,
    )
    link.start()
    time.sleep(0.2)
    link.stop()
    link.stop()
    assert not link.is_running


def test_line_buffer_on_sim_blob():
    blob = generate_flight_bytes(duration_s=1.0, hz=10.0, seed=1)
    buf = RadioLineBuffer()
    items = buf.feed(blob)
    assert buf.stats.rcv_malformed == 0
    assert len(items) >= 8
    assert all(isinstance(i, RadioPacket) for i in items)
