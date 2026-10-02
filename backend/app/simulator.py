"""
Simulation mode — synthetic Reyax +RCV lines wrapping competition CSV
(PRD v2 Phase 2).

Every sample is:
  TelemetryRecord → format_telemetry_csv → format_rcv_line
  → RadioLineBuffer.feed → callback(RadioPacket)

Not a UI mock: the two-layer stack is exercised for real.
"""
from __future__ import annotations

import math
import random
import threading
import time
from typing import Callable, List, Optional

from app.config import (
    CANSAT_VEHICLE_ADDR,
    ROCKET_VEHICLE_ADDR,
    TEAM_ID,
)
from app.protocol import (
    VEHICLE_ROCKET,
    VEHICLE_SATELLITE,
    CsvParseStats,
    FlightState,
    TelemetryRecord,
    format_telemetry_csv,
    parse_telemetry_csv,
    vehicle_name,
)
from app.radio_transport import (
    RadioLine,
    RadioLineBuffer,
    RadioPacket,
    format_rcv_line,
)

LinkStateCallback = Callable[[str, str], None]
PacketCallback = Callable[[str, RadioPacket], None]
RadioCallback = Callable[[str, RadioLine], None]

# Rough launch-site default (Bengaluru area) — sim only.
_SIM_LAT0 = 12.9716
_SIM_LON0 = 77.5946
_SIM_GROUND_ALT_M = 920.0


def _hms(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


class SimulatedVehicleLink:
    """
    Background-thread flight simulator for one vehicle.

    Callback: on_packet_callback(vehicle_key, radio_packet)
    `on_frame_callback` is accepted as an alias (v1 name).
    """

    def __init__(
        self,
        vehicle_id: int,
        on_packet_callback: Optional[PacketCallback] = None,
        on_frame_callback: Optional[PacketCallback] = None,
        on_radio_callback: Optional[RadioCallback] = None,
        on_link_state: Optional[LinkStateCallback] = None,
        hz: float = 10.0,
        seed: Optional[int] = None,
        team_id: str = TEAM_ID,
    ) -> None:
        if vehicle_id not in (VEHICLE_ROCKET, VEHICLE_SATELLITE):
            raise ValueError(f"unsupported vehicle_id: {vehicle_id}")
        cb = on_packet_callback or on_frame_callback
        self.vehicle_id = vehicle_id
        self.vehicle_key = vehicle_name(vehicle_id)
        self._on_packet = cb
        self._on_radio = on_radio_callback
        if self._on_packet is None and self._on_radio is None:
            raise ValueError("on_packet_callback or on_radio_callback is required")
        self._on_link_state = on_link_state
        self._io_lock = threading.Lock()
        self._hz = max(1.0, float(hz))
        self._rng = random.Random(seed if seed is not None else vehicle_id)
        self._buf = RadioLineBuffer()
        self.csv_stats = CsvParseStats()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._seq = 0
        self._running = False
        self._team_id = team_id
        self._sender_addr = (
            ROCKET_VEHICLE_ADDR
            if vehicle_id == VEHICLE_ROCKET
            else CANSAT_VEHICLE_ADDR
        )

        self._apogee_m = 850.0 if vehicle_id == VEHICLE_ROCKET else 420.0
        self._ascent_s = 12.0 if vehicle_id == VEHICLE_ROCKET else 18.0
        self._descent_s = 45.0 if vehicle_id == VEHICLE_ROCKET else 90.0
        self._prelaunch_s = 3.0
        self._boot_s = 0.4
        self._test_s = 0.8
        self._sep_s = 1.2 if vehicle_id == VEHICLE_ROCKET else 0.0
        self._drift_east_m_s = 1.2 if vehicle_id == VEHICLE_ROCKET else 0.6
        self._drift_north_m_s = 0.4 if vehicle_id == VEHICLE_ROCKET else -0.3

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def parser(self) -> RadioLineBuffer:
        return self._buf

    def start(self) -> None:
        if self._running:
            return
        self._stop.clear()
        self._buf.reset()
        self._buf.reset_counters()
        self.csv_stats.reset()
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
        s = self._seq
        self._seq += 1
        return s

    def write(self, data: bytes) -> bool:
        """
        Simulate Reyax UART write. AT+SEND is accepted and the module
        replies with +OK (transport ack only — no vehicle ACKED).
        """
        if not self._running:
            return False
        if not data:
            return False
        text = data.decode("utf-8", errors="replace").strip()
        if text.startswith("AT+SEND="):
            self._inject(b"+OK\r\n")
            return True
        self._inject(b"+ERR=1\r\n")
        return True

    def _inject(self, wire: bytes) -> None:
        try:
            with self._io_lock:
                items = self._buf.feed(wire)
            self._dispatch(items)
        except Exception:
            pass

    def _dispatch(self, items: List[RadioLine]) -> None:
        for item in items:
            if self._on_radio:
                try:
                    self._on_radio(self.vehicle_key, item)
                except Exception:
                    pass
            if isinstance(item, RadioPacket) and self._on_packet:
                try:
                    self._on_packet(self.vehicle_key, item)
                except Exception:
                    pass

    def _push_rcv(self, csv_line: str, rssi: int, snr: float) -> None:
        wire = format_rcv_line(self._sender_addr, csv_line, rssi, snr).encode(
            "utf-8"
        )
        self._inject(wire)

    def _run_loop(self) -> None:
        period = 1.0 / self._hz
        while not self._stop.is_set():
            loop_start = time.monotonic()
            self._mission_t = loop_start - self._t0_wall
            record, rssi, snr = self._make_record(self._mission_t)
            self._push_rcv(format_telemetry_csv(record), rssi, snr)
            elapsed = time.monotonic() - loop_start
            sleep_for = period - elapsed
            if sleep_for > 0:
                self._stop.wait(sleep_for)
        self._running = False

    def _flight_state(self, t: float) -> int:
        pre = self._prelaunch_s
        boot_end = self._boot_s
        test_end = boot_end + self._test_s
        t_launch = pre
        t_apogee = pre + self._ascent_s
        t_sep_end = t_apogee + self._sep_s
        t_aero = t_apogee + self._descent_s * 0.65
        t_land = pre + self._ascent_s + self._descent_s
        if t < boot_end:
            return int(FlightState.BOOT)
        if t < test_end:
            return int(FlightState.TEST_MODE)
        if t < t_launch:
            return int(FlightState.LAUNCH_PAD)
        if t < t_apogee:
            return int(FlightState.ASCENT)
        if self._sep_s > 0 and t < t_sep_end:
            return int(FlightState.PAYLOAD_SEP)
        if t < t_aero:
            return int(FlightState.DESCENT)
        if t < t_land:
            return int(FlightState.AEROBREAK_RELEASE)
        return int(FlightState.IMPACT)

    def _make_record(self, t: float) -> tuple[TelemetryRecord, int, float]:
        sample = self._sample_physics(t)
        state = self._flight_state(t)
        rssi = int(-55 + self._rng.gauss(0.0, 3.0) - 0.05 * t)
        rssi = max(-120, min(-40, rssi))
        snr = max(0.0, 10.0 + self._rng.gauss(0.0, 1.2) - 0.02 * t)
        rec = TelemetryRecord(
            team_id=self._team_id,
            timestamp=_hms(t),
            packet_count=self._next_seq(),
            altitude_m=sample["alt_agl"],
            pressure=sample["pressure_hpa"],
            temp_c=sample["temp_c"],
            voltage=sample["battery_v"],
            gnss_time=_hms(t),
            gnss_lat=sample["lat"],
            gnss_lon=sample["lon"],
            gnss_alt_m=sample["alt_msl"],
            gnss_sats=sample["sats"],
            accel_x=sample["accel_x"],
            accel_y=sample["accel_y"],
            accel_z=sample["accel_z"],
            gyro_x=sample["gyro_x"],
            gyro_y=sample["gyro_y"],
            gyro_z=sample["gyro_z"],
            flight_software_state=state,
        )
        return rec, rssi, snr

    def _sample_physics(self, t: float) -> dict:
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
            alt_agl = max(0.0, 0.2 + n(0.05))
            ax, ay, az = n(0.05), n(0.05), 9.81 + n(0.05)
            phase = "PAD"
        elif t < t_apogee:
            u = (t - t_launch) / asc
            alt_agl = ap * math.sin(u * math.pi / 2.0) + n(0.8)
            ax, ay, az = n(0.5), n(0.5), 9.81 + 25.0 * (1.0 - u) + n(1.0)
            phase = "ASCENT"
        elif t < t_land:
            u = (t - t_apogee) / des
            alt_agl = max(0.0, ap * (1.0 - u) ** 1.15 + n(0.5))
            ax, ay, az = n(0.3), n(0.3), 9.81 + n(0.2)
            phase = "DESCENT"
        else:
            alt_agl = max(0.0, 0.5 + n(0.1))
            ax, ay, az = n(0.05), n(0.05), 9.81 + n(0.05)
            phase = "LANDED"

        flight_t = max(0.0, t - t_launch)
        north_m = self._drift_north_m_s * flight_t + n(0.3)
        east_m = self._drift_east_m_s * flight_t + n(0.3)
        dlat = north_m / 111_320.0
        dlon = east_m / (111_320.0 * math.cos(math.radians(_SIM_LAT0)))
        lat = _SIM_LAT0 + dlat
        lon = _SIM_LON0 + dlon
        alt_msl = _SIM_GROUND_ALT_M + alt_agl
        pressure = 1013.25 * (1.0 - 2.25577e-5 * alt_msl) ** 5.25588
        temp = 22.0 - alt_agl * 0.0065 + n(0.05)
        battery = max(6.5, 8.2 - 0.0008 * t + n(0.01))

        return {
            "alt_agl": float(alt_agl),
            "alt_msl": float(alt_msl),
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
            "battery_v": float(battery),
            "sats": 8 + int(rng.random() * 4),
        }


def generate_flight_bytes(
    vehicle_id: int = VEHICLE_ROCKET,
    duration_s: float = 5.0,
    hz: float = 10.0,
    seed: int = 1,
    team_id: str = TEAM_ID,
) -> bytes:
    """
    Offline helper: concatenated +RCV lines of a short simulated flight.
    """
    link = SimulatedVehicleLink(
        vehicle_id=vehicle_id,
        on_packet_callback=lambda *_: None,
        hz=hz,
        seed=seed,
        team_id=team_id,
    )
    chunks = bytearray()
    steps = max(1, int(duration_s * hz))
    for i in range(steps):
        t = i / hz
        record, rssi, snr = link._make_record(t)
        csv_line = format_telemetry_csv(record)
        chunks.extend(
            format_rcv_line(link._sender_addr, csv_line, rssi, snr).encode(
                "utf-8"
            )
        )
    return bytes(chunks)


def decode_sim_stream(
    blob: bytes,
) -> List[tuple[RadioPacket, Optional[TelemetryRecord]]]:
    """Parse a generate_flight_bytes blob through both layers."""
    buf = RadioLineBuffer()
    stats = CsvParseStats()
    out: List[tuple[RadioPacket, Optional[TelemetryRecord]]] = []
    for item in buf.feed(blob):
        if isinstance(item, RadioPacket):
            rec = parse_telemetry_csv(item.data, stats)
            out.append((item, rec))
    return out
