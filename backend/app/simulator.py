"""
Simulation mode — synthetic vehicle link that emits *real* protocol frames
through the real FrameParser (PRD C.3 simulator.py).

Drop-in replacement for SerialVehicleLink: same callback shape
  on_frame_callback(vehicle_key, raw_frame: RawFrame)
and connection-state callback
  on_link_state(vehicle_key, state: str)

Not a UI-only mock: every sample is encode_frame → FrameParser.feed → callback.
"""
from __future__ import annotations

import math
import random
import threading
import time
from typing import Callable, Optional

from app.frame_parser import FrameParser
from app.protocol import (
    VEHICLE_ROCKET,
    VEHICLE_SATELLITE,
    EventFrame,
    GpsFrame,
    RawFrame,
    StatusFrame,
    TelemetryFrame,
    encode_packet,
    vehicle_name,
)

LinkStateCallback = Callable[[str, str], None]
FrameCallback = Callable[[str, RawFrame], None]

# Rough launch-site default (Bengaluru area) — [ASSUMED] for sim only.
_SIM_LAT0 = 12.9716
_SIM_LON0 = 77.5946
_SIM_GROUND_ALT_M = 920.0


class SimulatedVehicleLink:
    """
    Background-thread flight simulator for one vehicle.

    Interface mirrors SerialVehicleLink (Phase 3):
      start() / stop() / is_running
    """

    def __init__(
        self,
        vehicle_id: int,
        on_frame_callback: FrameCallback,
        on_link_state: Optional[LinkStateCallback] = None,
        hz: float = 10.0,
        seed: Optional[int] = None,
    ) -> None:
        if vehicle_id not in (VEHICLE_ROCKET, VEHICLE_SATELLITE):
            raise ValueError(f"unsupported vehicle_id: {vehicle_id}")
        self.vehicle_id = vehicle_id
        self.vehicle_key = vehicle_name(vehicle_id)
        self._on_frame = on_frame_callback
        self._on_link_state = on_link_state
        self._hz = max(1.0, float(hz))
        self._rng = random.Random(seed if seed is not None else vehicle_id)
        self._parser = FrameParser()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._seq = 0
        self._running = False

        # Flight timeline (seconds since "arm")
        self._t0_wall: float = 0.0
        self._mission_t: float = 0.0
        # Profile parameters (slightly different per vehicle)
        self._apogee_m = 850.0 if vehicle_id == VEHICLE_ROCKET else 420.0
        self._ascent_s = 12.0 if vehicle_id == VEHICLE_ROCKET else 18.0
        self._descent_s = 45.0 if vehicle_id == VEHICLE_ROCKET else 90.0
        self._prelaunch_s = 3.0
        self._drift_east_m_s = 1.2 if vehicle_id == VEHICLE_ROCKET else 0.6
        self._drift_north_m_s = 0.4 if vehicle_id == VEHICLE_ROCKET else -0.3

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def parser(self) -> FrameParser:
        """Expose parser so Packet Monitor counters can be read."""
        return self._parser

    def start(self) -> None:
        if self._running:
            return
        self._stop.clear()
        self._parser.reset()
        self._parser.reset_counters()
        self._seq = 0
        self._mission_t = 0.0
        self._t0_wall = time.monotonic()
        self._running = True
        self._emit_link("CONNECTED")
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"sim-{self.vehicle_key}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        was = self._running
        self._running = False
        if was:
            self._emit_link("DISCONNECTED")

    def _emit_link(self, state: str) -> None:
        if self._on_link_state:
            try:
                self._on_link_state(self.vehicle_key, state)
            except Exception:
                pass

    def _next_seq(self) -> int:
        s = self._seq & 0xFF
        self._seq = (self._seq + 1) & 0xFF
        return s

    def _push_wire(self, wire: bytes) -> None:
        """Encode path → real parser → callback (PRD non-negotiable #3)."""
        try:
            frames = self._parser.feed(wire)
            for fr in frames:
                try:
                    self._on_frame(self.vehicle_key, fr)
                except Exception:
                    # Callback errors must not kill the sim thread.
                    pass
        except Exception:
            pass

    def _run_loop(self) -> None:
        period = 1.0 / self._hz
        gps_every_n = max(1, int(round(self._hz / 2.0)))  # ~2 Hz GPS
        status_every_n = max(1, int(round(self._hz)))  # ~1 Hz status
        tick = 0
        # Fire LAUNCH_DETECT once when leaving pad
        launch_event_sent = False
        chute_event_sent = False

        while not self._stop.is_set():
            loop_start = time.monotonic()
            self._mission_t = loop_start - self._t0_wall
            sample = self._sample_physics(self._mission_t)

            if sample["phase_name"] == "ASCENT" and not launch_event_sent:
                self._push_wire(
                    encode_packet(
                        self.vehicle_id,
                        self._next_seq(),
                        EventFrame(message="LAUNCH_DETECT"),
                    )
                )
                launch_event_sent = True

            if sample["phase_name"] == "DESCENT" and not chute_event_sent:
                self._push_wire(
                    encode_packet(
                        self.vehicle_id,
                        self._next_seq(),
                        EventFrame(message="CHUTE_DEPLOY"),
                    )
                )
                chute_event_sent = True

            telem = TelemetryFrame(
                timestamp_ms=int(self._mission_t * 1000) & 0xFFFFFFFF,
                altitude_m=sample["alt_agl"],
                pressure_hpa=sample["pressure_hpa"],
                temperature_c=sample["temp_c"],
                accel_x=sample["accel_x"],
                accel_y=sample["accel_y"],
                accel_z=sample["accel_z"],
                gyro_x=sample["gyro_x"],
                gyro_y=sample["gyro_y"],
                gyro_z=sample["gyro_z"],
                pitch=sample["pitch"],
                yaw=sample["yaw"],
                roll=sample["roll"],
                battery_v=sample["battery_v"],
            )
            self._push_wire(
                encode_packet(self.vehicle_id, self._next_seq(), telem)
            )

            if tick % gps_every_n == 0:
                gps = GpsFrame(
                    gps_timestamp=int(self._mission_t * 1000) & 0xFFFFFFFF,
                    lat=sample["lat"],
                    lon=sample["lon"],
                    alt_msl_m=sample["alt_msl"],
                    num_sats=sample["sats"],
                    hdop=sample["hdop"],
                    fix_type=2,
                )
                self._push_wire(
                    encode_packet(self.vehicle_id, self._next_seq(), gps)
                )

            if tick % status_every_n == 0:
                status = StatusFrame(
                    phase_hint=0,  # let GS decide
                    battery_v=sample["battery_v"],
                    error_flags=0,
                )
                self._push_wire(
                    encode_packet(self.vehicle_id, self._next_seq(), status)
                )

            tick += 1
            elapsed = time.monotonic() - loop_start
            sleep_for = period - elapsed
            if sleep_for > 0:
                self._stop.wait(sleep_for)

        self._running = False

    def _sample_physics(self, t: float) -> dict:
        """Piecewise flight profile with light noise — plausible, not 6-DOF."""
        rng = self._rng
        pre = self._prelaunch_s
        asc = self._ascent_s
        des = self._descent_s
        ap = self._apogee_m
        t_launch = pre
        t_apogee = pre + asc
        t_land = pre + asc + des

        n = lambda s: rng.gauss(0.0, s)  # noqa: E731

        if t < t_launch:
            phase = "ARMED"
            alt_agl = max(0.0, 0.2 + n(0.05))
            vz = 0.0
            ax, ay, az = n(0.05), n(0.05), 9.81 + n(0.05)
            pitch, yaw, roll = n(0.3), (t * 2.0) % 360.0, n(0.3)
        elif t < t_apogee:
            phase = "ASCENT"
            u = (t - t_launch) / asc  # 0..1
            # Smooth ease-out altitude
            alt_agl = ap * math.sin(u * math.pi / 2.0) + n(0.8)
            vz = (ap * math.pi / 2.0 / asc) * math.cos(u * math.pi / 2.0)
            ax, ay, az = n(0.5), n(0.5), 9.81 + 25.0 * (1.0 - u) + n(1.0)
            pitch = 5.0 + 8.0 * u + n(0.5)
            yaw = (t * 40.0) % 360.0
            roll = n(1.5)
        elif t < t_land:
            phase = "DESCENT"
            u = (t - t_apogee) / des
            # Exponential-ish parachute descent
            alt_agl = ap * (1.0 - u) ** 1.15 + n(0.5)
            alt_agl = max(0.0, alt_agl)
            vz = -ap * 1.15 / des * (1.0 - u) ** 0.15
            ax, ay, az = n(0.3), n(0.3), 9.81 + n(0.2)
            pitch = 10.0 + 15.0 * math.sin(t * 1.7) + n(1.0)
            yaw = (t * 25.0) % 360.0
            roll = 5.0 * math.sin(t * 2.3) + n(1.0)
        else:
            phase = "LANDED"
            alt_agl = max(0.0, 0.5 + n(0.1))
            vz = 0.0
            ax, ay, az = n(0.05), n(0.05), 9.81 + n(0.05)
            pitch, yaw, roll = n(1.0), (t * 1.0) % 360.0, n(1.0)

        # Horizontal drift after launch
        flight_t = max(0.0, t - t_launch)
        # metres → rough degrees (lat fixed scale; lon cos-corrected)
        north_m = self._drift_north_m_s * flight_t + n(0.3)
        east_m = self._drift_east_m_s * flight_t + n(0.3)
        dlat = north_m / 111_320.0
        dlon = east_m / (111_320.0 * math.cos(math.radians(_SIM_LAT0)))
        lat = _SIM_LAT0 + dlat
        lon = _SIM_LON0 + dlon
        alt_msl = _SIM_GROUND_ALT_M + alt_agl

        # ISA-ish pressure from MSL altitude
        pressure = 1013.25 * (1.0 - 2.25577e-5 * alt_msl) ** 5.25588
        temp = 22.0 - alt_agl * 0.0065 + n(0.05)
        battery = max(6.5, 8.2 - 0.0008 * t + n(0.01))

        return {
            "phase_name": phase,
            "alt_agl": float(alt_agl),
            "alt_msl": float(alt_msl),
            "vz": float(vz),
            "lat": float(lat),
            "lon": float(lon),
            "pressure_hpa": float(pressure + n(0.05)),
            "temp_c": float(temp),
            "accel_x": float(ax),
            "accel_y": float(ay),
            "accel_z": float(az),
            "gyro_x": float(n(2.0) if phase == "ASCENT" else n(0.5)),
            "gyro_y": float(n(2.0) if phase == "ASCENT" else n(0.5)),
            "gyro_z": float(n(1.0)),
            "pitch": float(pitch),
            "yaw": float(yaw % 360.0),
            "roll": float(roll),
            "battery_v": float(battery),
            "sats": 8 + int(rng.random() * 4),
            "hdop": float(0.8 + abs(n(0.15))),
        }


def generate_flight_bytes(
    vehicle_id: int = VEHICLE_ROCKET,
    duration_s: float = 5.0,
    hz: float = 10.0,
    seed: int = 1,
) -> bytes:
    """
    Offline helper: build a concatenated byte stream of a short simulated flight
    without starting a thread. Useful for unit tests and replay-style feeds.
    """
    rng = random.Random(seed)
    link = SimulatedVehicleLink(
        vehicle_id=vehicle_id,
        on_frame_callback=lambda *_: None,
        hz=hz,
        seed=seed,
    )
    # Reuse physics only — encode without threading
    chunks = bytearray()
    steps = max(1, int(duration_s * hz))
    seq = 0
    for i in range(steps):
        t = i / hz
        sample = link._sample_physics(t)
        telem = TelemetryFrame(
            timestamp_ms=int(t * 1000),
            altitude_m=sample["alt_agl"],
            pressure_hpa=sample["pressure_hpa"],
            temperature_c=sample["temp_c"],
            accel_x=sample["accel_x"],
            accel_y=sample["accel_y"],
            accel_z=sample["accel_z"],
            gyro_x=sample["gyro_x"],
            gyro_y=sample["gyro_y"],
            gyro_z=sample["gyro_z"],
            pitch=sample["pitch"],
            yaw=sample["yaw"],
            roll=sample["roll"],
            battery_v=sample["battery_v"],
        )
        chunks.extend(encode_packet(vehicle_id, seq & 0xFF, telem))
        seq += 1
        if i % 5 == 0:
            gps = GpsFrame(
                gps_timestamp=int(t * 1000),
                lat=sample["lat"],
                lon=sample["lon"],
                alt_msl_m=sample["alt_msl"],
                num_sats=sample["sats"],
                hdop=sample["hdop"],
                fix_type=2,
            )
            chunks.extend(encode_packet(vehicle_id, seq & 0xFF, gps))
            seq += 1
        # Suppress unused rng warning by touching it
        _ = rng.random()
    return bytes(chunks)
