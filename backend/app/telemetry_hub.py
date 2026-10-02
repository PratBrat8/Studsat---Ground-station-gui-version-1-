"""
In-memory telemetry hub — ring buffers + throttled pub/sub (PRD C.3 / C.4).

Thread-safe ingest from serial/sim threads; asyncio queues notify WS clients.
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set

from app.config import (
    ALTITUDE_DISAGREEMENT_THRESHOLD_M,
    GPS_TRACK_MAX_POINTS,
    PACKET_RING_SIZE,
    PREDICTION_WINDOW_SAMPLES,
    RING_BUFFER_SAMPLES,
    WS_BROADCAST_INTERVAL_MS,
)
from app.phase_fsm import PhaseFSM, PhaseSample
from app.predictor import LandingPredictor
from app.power import voltage_to_percent
from app.protocol import (
    FLIGHT_STATE_NAMES,
    CsvParseStats,
    FlightState,
    TelemetryRecord,
    parse_telemetry_csv,
)
from app.radio_transport import (
    MalformedRadioLine,
    ModuleErr,
    ModuleOk,
    RadioPacket,
)
from app.trajectory import ascent_trend, climb_angle_deg, haversine_m

VEHICLES = ("rocket", "satellite")


def json_safe(value: Any) -> Any:
    """Replace NaN/Inf so WS json.dumps(..., allow_nan=False) cannot crash."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


def _fields_from_record(rec: Optional[TelemetryRecord]) -> Dict[str, Any]:
    if rec is None:
        return {}
    return {
        "team_id": rec.team_id,
        "timestamp": rec.timestamp,
        "packet_count": rec.packet_count,
        "altitude_m": round(rec.altitude_m, 3),
        "pressure": round(rec.pressure, 3),
        "temp_c": round(rec.temp_c, 3),
        "voltage": round(rec.voltage, 3),
        "gnss_time": rec.gnss_time,
        "gnss_lat": rec.gnss_lat,
        "gnss_lon": rec.gnss_lon,
        "gnss_alt_m": round(rec.gnss_alt_m, 3),
        "gnss_sats": rec.gnss_sats,
        "accel_x": round(rec.accel_x, 3),
        "accel_y": round(rec.accel_y, 3),
        "accel_z": round(rec.accel_z, 3),
        "gyro_x": round(rec.gyro_x, 3),
        "gyro_y": round(rec.gyro_y, 3),
        "gyro_z": round(rec.gyro_z, 3),
        "flight_software_state": rec.flight_software_state,
    }


def _cdr_phase_name(state: int) -> str:
    try:
        return FLIGHT_STATE_NAMES.get(FlightState(state), f"STATE_{state}")
    except ValueError:
        return f"STATE_{state}"


def _predictor_phase(cdr_name: str) -> str:
    """Map CDR 8-state names onto the v1 predictor's expected labels."""
    # After PAYLOAD_SEP the vehicles descend independently — both get a
    # landing estimate (PRD A.5.6 / Phase 8).
    if cdr_name in ("PAYLOAD_SEP", "DESCENT", "AEROBREAK_RELEASE", "APOGEE"):
        return "DESCENT"
    if cdr_name in ("IMPACT", "LANDED"):
        return "LANDED"
    if cdr_name == "ASCENT":
        return "ASCENT"
    return "IDLE"


def _empty_telemetry() -> Dict[str, Any]:
    return {
        "altitude_m": None,
        "altitude_gnss_m": None,
        "altitude_delta_m": None,
        "altitude_disagreement": False,
        "speed_mps": None,
        "pitch": None,
        "yaw": None,
        "roll": None,
        "temperature_c": None,
        "pressure_hpa": None,
        "battery_v": None,
        "battery_pct": None,
        "battery_pct_assumed": True,
        "current_a": None,
        "power_w": None,
        "accel_x": None,
        "accel_y": None,
        "accel_z": None,
        "gyro_x": None,
        "gyro_y": None,
        "gyro_z": None,
        "timestamp_ms": None,
        "packet_count": None,
        "rssi": None,
        "snr": None,
        "flight_software_state": None,
    }


def _empty_gps() -> Dict[str, Any]:
    return {
        "lat": None,
        "lon": None,
        "alt_m": None,
        "sats": None,
        "hdop": None,
        "fix_type": 0,
        "gps_timestamp": None,
    }


@dataclass
class VehicleState:
    vehicle: str
    phase: str = "IDLE"
    link_state: str = "DISCONNECTED"
    telemetry: Dict[str, Any] = field(default_factory=_empty_telemetry)
    gps: Dict[str, Any] = field(default_factory=_empty_gps)
    prediction: Optional[Dict[str, Any]] = None
    events: Deque[str] = field(default_factory=lambda: deque(maxlen=20))

    # Histories (for graphs / rate / vspeed)
    hist_t: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_altitude: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_speed: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_pitch: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_yaw: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_roll: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_battery: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_temperature: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    hist_pressure: Deque[float] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SAMPLES)
    )
    trail: Deque[Dict[str, float]] = field(
        default_factory=lambda: deque(maxlen=GPS_TRACK_MAX_POINTS)
    )
    hist_traj: Deque[Dict[str, float]] = field(
        default_factory=lambda: deque(maxlen=GPS_TRACK_MAX_POINTS)
    )
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None

    # Packet monitor
    recent_packets: Deque[Dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=PACKET_RING_SIZE)
    )
    frames_ok: int = 0
    frames_crc_error: int = 0  # transport malformed +RCV / oversize (not CSV)
    frames_resynced: int = 0
    transport_ok: int = 0
    transport_err: int = 0
    transport_unknown: int = 0
    last_seq: Optional[int] = None
    last_seq_gap: int = 0
    total_seq_gaps: int = 0
    packet_times: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    packet_rate_history: Deque[float] = field(
        default_factory=lambda: deque(maxlen=60)
    )
    last_packet_age_s: float = 9999.0
    last_frame_wall: float = 0.0
    last_by_type: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    csv_stats: CsvParseStats = field(default_factory=CsvParseStats)
    hist_rssi: Deque[float] = field(default_factory=lambda: deque(maxlen=60))
    hist_snr: Deque[float] = field(default_factory=lambda: deque(maxlen=60))
    last_rssi: Optional[int] = None
    last_snr: Optional[float] = None

    # Predictor still used; display phase is CDR FLIGHT_SOFTWARE_STATE.
    phase_fsm: PhaseFSM = field(default_factory=PhaseFSM)
    predictor: LandingPredictor = field(
        default_factory=lambda: LandingPredictor(window=PREDICTION_WINDOW_SAMPLES)
    )
    prev_phase: str = "IDLE"
    _got_first_frame: bool = False
    _last_alt: Optional[float] = None
    _last_alt_t: Optional[float] = None
    _pending_event: Optional[str] = None


class TelemetryHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: Dict[str, VehicleState] = {
            v: VehicleState(vehicle=v) for v in VEHICLES
        }
        # asyncio.Queue subscribers per vehicle (set from event loop thread)
        self._subs: Dict[str, Set[asyncio.Queue]] = {v: set() for v in VEHICLES}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_broadcast: Dict[str, float] = {v: 0.0 for v in VEHICLES}
        self._pending_notify: Dict[str, bool] = {v: False for v in VEHICLES}
        self._throttle_s = WS_BROADCAST_INTERVAL_MS / 1000.0
        self._broadcaster_task: Optional[asyncio.Task] = None
        # Phase 10 — per-vehicle SessionLogger (or None)
        self._session_loggers: Dict[str, Any] = {v: None for v in VEHICLES}
        # Mission-level: Rocket PAYLOAD_SEP (PRD A.5.6).
        self._cansat_separated = False

    def set_session_logger(self, vehicle: str, logger: Any) -> None:
        vehicle = vehicle.lower()
        with self._lock:
            if vehicle in self._session_loggers:
                self._session_loggers[vehicle] = logger

    def get_session_logger(self, vehicle: str) -> Any:
        return self._session_loggers.get(vehicle.lower())

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def start_broadcaster(self) -> None:
        """Coalesce dirty vehicles and push at most ~16 fps (PRD C.4)."""
        while True:
            await asyncio.sleep(self._throttle_s)
            now = time.monotonic()
            with self._lock:
                dirty = [v for v, d in self._pending_notify.items() if d]
                for v in dirty:
                    self._pending_notify[v] = False
                    self._last_broadcast[v] = now
            for v in dirty:
                self._push_queues(v)

    def _push_queues(self, vehicle: str) -> None:
        queues = list(self._subs.get(vehicle, set()))
        for q in queues:
            try:
                q.put_nowait("update")
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait("update")
                except Exception:
                    pass
            except Exception:
                pass

    def subscribe(self, vehicle: str, queue: asyncio.Queue) -> None:
        vehicle = vehicle.lower()
        if vehicle not in self._subs:
            raise KeyError(vehicle)
        self._subs[vehicle].add(queue)

    def unsubscribe(self, vehicle: str, queue: asyncio.Queue) -> None:
        vehicle = vehicle.lower()
        self._subs.get(vehicle, set()).discard(queue)

    def set_link_state(self, vehicle: str, state: str) -> None:
        vehicle = vehicle.lower()
        with self._lock:
            st = self._states[vehicle]
            st.link_state = state
            if state in ("DISCONNECTED",):
                if not st._got_first_frame:
                    st.phase = "IDLE"
            self._pending_notify[vehicle] = True
        self._schedule_notify(vehicle)

    def reset_vehicle(self, vehicle: str) -> None:
        vehicle = vehicle.lower()
        with self._lock:
            self._states[vehicle] = VehicleState(vehicle=vehicle)
            if vehicle == "rocket":
                self._cansat_separated = False
            self._pending_notify[vehicle] = True
        self._schedule_notify(vehicle)

    def mark_recovered(self, vehicle: str) -> Dict[str, Any]:
        """Operator marks vehicle recovered (LANDED → RECOVERED)."""
        vehicle = vehicle.lower()
        with self._lock:
            st = self._states[vehicle]
            st.prev_phase = st.phase
            st.phase = st.phase_fsm.mark_recovered()
            self._pending_notify[vehicle] = True
            phase = st.phase
        self._schedule_notify(vehicle)
        return {"ok": True, "vehicle": vehicle, "phase": phase}

    def _apply_parser_stats(
        self, st: VehicleState, parser_stats: Optional[Dict[str, int]]
    ) -> None:
        if not parser_stats:
            return
        st.frames_ok = int(
            parser_stats.get("frames_ok", parser_stats.get("transport_rcv_ok", st.frames_ok))
        )
        st.frames_crc_error = int(
            parser_stats.get(
                "frames_crc_error",
                parser_stats.get("transport_malformed", st.frames_crc_error),
            )
        )
        st.frames_resynced = int(
            parser_stats.get("frames_resynced", st.frames_resynced)
        )
        if "transport_ok" in parser_stats:
            st.transport_ok = int(parser_stats["transport_ok"])
        if "transport_err" in parser_stats:
            st.transport_err = int(parser_stats["transport_err"])
        if "transport_unknown" in parser_stats:
            st.transport_unknown = int(parser_stats["transport_unknown"])

    def ingest_radio_event(
        self,
        vehicle: str,
        item: Any,
        parser_stats: Optional[Dict[str, int]] = None,
    ) -> None:
        """Record a transport-layer +OK / +ERR / malformed line in the packet ring."""
        if isinstance(item, RadioPacket):
            self.ingest_radio_packet(vehicle, item, parser_stats)
            return
        vehicle = vehicle.lower()
        if vehicle not in self._states:
            return
        wall_ms = int(time.time() * 1000)
        with self._lock:
            st = self._states[vehicle]
            if parser_stats:
                self._apply_parser_stats(st, parser_stats)
            elif isinstance(item, ModuleErr):
                st.transport_err += 1
            elif isinstance(item, ModuleOk):
                st.transport_ok += 1
            elif isinstance(item, MalformedRadioLine):
                if item.reason == "unknown":
                    st.transport_unknown += 1
                else:
                    st.frames_crc_error += 1
                    if item.reason == "oversize":
                        st.frames_resynced += 1

            raw = getattr(item, "raw_line", "") or ""
            if isinstance(item, ModuleOk):
                type_name = "+OK"
                ok = True
                error = None
                fields: Dict[str, Any] = {"response": "+OK"}
            elif isinstance(item, ModuleErr):
                type_name = "+ERR"
                ok = False
                error = f"+ERR={item.code}"
                fields = {"code": item.code}
            elif isinstance(item, MalformedRadioLine):
                type_name = "MALFORMED"
                ok = False
                error = f"transport {item.reason}"
                fields = {"reason": item.reason}
            else:
                type_name = type(item).__name__
                ok = False
                error = "unknown radio event"
                fields = {}

            pkt_rec = {
                "t": wall_ms,
                "seq": None,
                "type": type_name,
                "type_name": type_name,
                "layer": "transport",
                "address": None,
                "rssi": None,
                "snr": None,
                "len": len(raw),
                "csv": None,
                "ascii": raw,
                "hex": raw.encode("utf-8", errors="replace").hex(" "),
                "ok": ok,
                "error": error,
                "fields": fields,
            }
            st.recent_packets.appendleft(pkt_rec)
            self._pending_notify[vehicle] = True
        self._schedule_notify(vehicle)

    def ingest_radio_packet(
        self,
        vehicle: str,
        packet: RadioPacket,
        parser_stats: Optional[Dict[str, int]] = None,
        logging_enabled: bool = True,
    ) -> None:
        """Thread-safe: called from serial/sim/replay reader threads."""
        vehicle = vehicle.lower()
        if vehicle not in self._states:
            return
        now = time.monotonic()
        wall_ms = int(time.time() * 1000)

        with self._lock:
            st = self._states[vehicle]
            self._apply_parser_stats(st, parser_stats)

            fc_before = st.csv_stats.field_count_error
            ty_before = st.csv_stats.type_error
            rec = parse_telemetry_csv(packet.data, st.csv_stats)
            decode_err = None
            if rec is None:
                if st.csv_stats.field_count_error > fc_before:
                    decode_err = "csv field count"
                elif st.csv_stats.type_error > ty_before:
                    decode_err = "csv type error"
                else:
                    decode_err = "csv parse failed"

            seq = rec.packet_count if rec is not None else st.last_seq
            if rec is not None:
                if st.last_seq is not None:
                    expected = st.last_seq + 1
                    if rec.packet_count != expected:
                        st.last_seq_gap = rec.packet_count - expected
                        st.total_seq_gaps += 1
                    else:
                        st.last_seq_gap = 0
                st.last_seq = rec.packet_count

            st.packet_times.append(now)
            st.last_frame_wall = now
            st.last_packet_age_s = 0.0
            st.link_state = "CONNECTED"
            st.last_rssi = int(packet.rssi)
            st.last_snr = float(packet.snr)
            st.hist_rssi.append(float(packet.rssi))
            st.hist_snr.append(float(packet.snr))
            rate = self._packet_rate_hz(st)
            st.packet_rate_history.append(round(rate, 2))

            if not st._got_first_frame:
                st._got_first_frame = True
                st.prev_phase = st.phase

            fields = _fields_from_record(rec)
            raw = packet.raw_line or packet.data
            pkt_rec = {
                "t": wall_ms,
                "seq": seq,
                "type": "TELEMETRY",
                "type_name": "TELEMETRY",
                "layer": "application",
                "address": packet.address,
                "rssi": packet.rssi,
                "snr": packet.snr,
                "len": len(packet.data),
                "csv": packet.data,
                "ascii": raw,
                "hex": raw.encode("utf-8", errors="replace").hex(" "),
                "ok": rec is not None,
                "error": decode_err,
                "fields": fields,
            }
            st.recent_packets.appendleft(pkt_rec)
            if rec is not None:
                st.last_by_type["TELEMETRY"] = pkt_rec
                self._apply_record(st, rec, packet, now)
            self._pending_notify[vehicle] = True

            if logging_enabled:
                logger = self._session_loggers.get(vehicle)
                if logger is not None:
                    try:
                        from app.logger import build_log_row_from_state

                        logger.log_row(
                            build_log_row_from_state(
                                vehicle, packet, st, wall_ms, type_name="TELEMETRY"
                            )
                        )
                    except Exception:
                        pass

        self._schedule_notify(vehicle)
        if vehicle == "rocket":
            with self._lock:
                sat_pending = bool(self._pending_notify.get("satellite"))
            if sat_pending:
                self._schedule_notify("satellite")

    def _apply_record(
        self,
        st: VehicleState,
        rec: TelemetryRecord,
        packet: RadioPacket,
        now: float,
    ) -> None:
        speed = self._estimate_vspeed(st, float(rec.altitude_m), now)
        delta = abs(float(rec.altitude_m) - float(rec.gnss_alt_m))
        disagree = delta > ALTITUDE_DISAGREEMENT_THRESHOLD_M
        st.telemetry = {
            "altitude_m": float(rec.altitude_m),
            "altitude_gnss_m": float(rec.gnss_alt_m),
            "altitude_delta_m": round(delta, 2),
            "altitude_disagreement": disagree,
            "speed_mps": speed,
            "pitch": None,
            "yaw": None,
            "roll": None,
            "temperature_c": float(rec.temp_c),
            "pressure_hpa": float(rec.pressure),
            "battery_v": float(rec.voltage),
            # TEMPORARY/UNCONFIRMED 2S Li-ion curve (Appendix 1.4).
            "battery_pct": round(voltage_to_percent(float(rec.voltage)), 1),
            "battery_pct_assumed": True,
            # INA219 current is not in the 19-field CSV yet.
            "current_a": None,
            "power_w": None,
            "accel_x": float(rec.accel_x),
            "accel_y": float(rec.accel_y),
            "accel_z": float(rec.accel_z),
            "gyro_x": float(rec.gyro_x),
            "gyro_y": float(rec.gyro_y),
            "gyro_z": float(rec.gyro_z),
            "timestamp_ms": None,
            "packet_count": int(rec.packet_count),
            "rssi": int(packet.rssi),
            "snr": float(packet.snr),
            "flight_software_state": int(rec.flight_software_state),
        }
        st.hist_t.append(now)
        st.hist_altitude.append(float(rec.altitude_m))
        st.hist_speed.append(speed if speed is not None else 0.0)
        st.hist_battery.append(float(rec.voltage))
        st.hist_temperature.append(float(rec.temp_c))
        st.hist_pressure.append(float(rec.pressure))
        st._last_alt = float(rec.altitude_m)
        st._last_alt_t = now

        st.gps = {
            "lat": float(rec.gnss_lat),
            "lon": float(rec.gnss_lon),
            "alt_m": float(rec.gnss_alt_m),
            "sats": int(rec.gnss_sats),
            "hdop": None,
            "fix_type": 2 if rec.gnss_sats else 0,
            "gps_timestamp": rec.gnss_time,
        }
        if rec.gnss_sats > 0:
            st.trail.append(
                {"lat": float(rec.gnss_lat), "lon": float(rec.gnss_lon), "t": now}
            )
            if st.origin_lat is None:
                st.origin_lat = float(rec.gnss_lat)
                st.origin_lon = float(rec.gnss_lon)
            range_m = haversine_m(
                st.origin_lat,
                st.origin_lon,
                float(rec.gnss_lat),
                float(rec.gnss_lon),
            )
            st.hist_traj.append(
                {
                    "range_m": round(range_m, 2),
                    "alt_m": float(rec.altitude_m),
                    "t": now,
                }
            )
            try:
                st.predictor.push_gps(
                    now,
                    float(rec.gnss_lat),
                    float(rec.gnss_lon),
                    float(rec.altitude_m),
                    hdop=1.0,
                )
            except Exception:
                pass

        try:
            st.predictor.push_altitude(now, float(rec.altitude_m))
        except Exception:
            pass

        cdr_name = _cdr_phase_name(int(rec.flight_software_state))
        st.prev_phase = st.phase
        st.phase = cdr_name
        if (
            st.vehicle == "rocket"
            and st.prev_phase != cdr_name
            and cdr_name == "PAYLOAD_SEP"
        ):
            self._cansat_separated = True
            st.events.appendleft("CanSat Separated")
            self._states["satellite"].events.appendleft("CanSat Separated")
            self._pending_notify["satellite"] = True

        pred_phase = _predictor_phase(cdr_name)
        try:
            result = st.predictor.compute(
                phase=pred_phase,
                current_lat=st.gps.get("lat"),
                current_lon=st.gps.get("lon"),
                current_alt_m=st.telemetry.get("altitude_m"),
                current_hdop=st.gps.get("hdop"),
            )
            st.prediction = result.as_dict() if result is not None else (
                st.prediction if pred_phase == "LANDED" else None
            )
        except Exception:
            pass

    def _run_phase_and_prediction(
        self,
        st: VehicleState,
        now: float,
        event: Optional[str] = None,
    ) -> None:
        t = st.telemetry
        alt = t.get("altitude_m")
        if alt is None:
            if event:
                # Event-only step with zeros
                st.prev_phase = st.phase
                st.phase = st.phase_fsm.step(
                    PhaseSample(
                        altitude_m=0.0,
                        speed_mps=0.0,
                        event=event,
                        t=now,
                    )
                )
            return

        sample = PhaseSample(
            altitude_m=float(alt),
            speed_mps=float(t.get("speed_mps") or 0.0),
            accel_x=float(t.get("accel_x") or 0.0),
            accel_y=float(t.get("accel_y") or 0.0),
            accel_z=float(t.get("accel_z") or 0.0),
            event=event,
            t=now,
        )
        st.prev_phase = st.phase
        st.phase = st.phase_fsm.step(sample)
        self._update_prediction_only(st)

    def _update_prediction_only(self, st: VehicleState) -> None:
        try:
            result = st.predictor.compute(
                phase=st.phase,
                current_lat=st.gps.get("lat"),
                current_lon=st.gps.get("lon"),
                current_alt_m=st.telemetry.get("altitude_m"),
                current_hdop=st.gps.get("hdop"),
            )
            st.prediction = result.as_dict() if result is not None else (
                st.prediction if st.phase == "LANDED" else None
            )
        except Exception:
            # Prediction must never break the live pipeline
            pass

    def _estimate_vspeed(
        self, st: VehicleState, alt: float, now: float
    ) -> Optional[float]:
        if st._last_alt is None or st._last_alt_t is None:
            return 0.0
        dt = now - st._last_alt_t
        dalt = alt - st._last_alt
        # Same-tick ingest (tests / burst): altitude unchanged → zero rate,
        # not a frozen previous huge value that would block LANDED forever.
        if dt <= 1e-4:
            if abs(dalt) < 1e-6:
                return 0.0
            # Tiny dt with real altitude change — clamp using min dt
            dt = 1e-3
        return dalt / dt

    def _packet_rate_hz(self, st: VehicleState) -> float:
        times = list(st.packet_times)
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        if span <= 0:
            return 0.0
        return (len(times) - 1) / span

    def _schedule_notify(self, vehicle: str) -> None:
        """Throttle: mark dirty; broadcaster or immediate if past interval."""
        loop = self._loop
        if loop is None:
            return
        now = time.monotonic()
        with self._lock:
            last = self._last_broadcast.get(vehicle, 0.0)
            if now - last >= self._throttle_s:
                self._pending_notify[vehicle] = False
                self._last_broadcast[vehicle] = now
                immediate = True
            else:
                self._pending_notify[vehicle] = True
                immediate = False
        if immediate:
            try:
                loop.call_soon_threadsafe(self._push_queues, vehicle)
            except Exception:
                pass

    def latest_state(
        self, vehicle: str, *, msg_type: str = "snapshot", full_history: bool = True
    ) -> Dict[str, Any]:
        """Snapshot/update envelope for WS clients (PRD C.3)."""
        vehicle = vehicle.lower()
        with self._lock:
            return self._snapshot_unlocked(
                self._states[vehicle],
                msg_type=msg_type,
                full_history=full_history,
            )

    def _trajectory_payload(
        self, st: VehicleState, *, full_history: bool
    ) -> Dict[str, Any]:
        path = list(st.hist_traj)
        last = path[-1] if path else None
        hspeed = None
        if len(path) >= 2:
            dt = float(path[-1]["t"]) - float(path[-2]["t"])
            if dt > 1e-3:
                hspeed = (
                    float(path[-1]["range_m"]) - float(path[-2]["range_m"])
                ) / dt
        climb, src = climb_angle_deg(
            st.telemetry.get("pitch"),
            st.telemetry.get("speed_mps"),
            hspeed,
        )
        trend_active = st.phase == "ASCENT"
        trend = ascent_trend(path) if trend_active else []
        blob: Dict[str, Any] = {
            "origin": (
                {"lat": st.origin_lat, "lon": st.origin_lon}
                if st.origin_lat is not None and st.origin_lon is not None
                else None
            ),
            "range_m": last["range_m"] if last else None,
            "climb_deg": round(float(climb), 1) if climb is not None else None,
            "climb_source": src,
            "trend_active": trend_active,
            "trend": trend,
        }
        if full_history:
            blob["path"] = [
                {"range_m": p["range_m"], "alt_m": p["alt_m"]} for p in path[-300:]
            ]
        else:
            blob["path_point"] = (
                [{"range_m": last["range_m"], "alt_m": last["alt_m"]}]
                if last
                else []
            )
        return blob

    def _snapshot_unlocked(
        self,
        st: VehicleState,
        msg_type: str = "update",
        full_history: bool = True,
    ) -> Dict[str, Any]:
        now = time.monotonic()
        age = (now - st.last_frame_wall) if st.last_frame_wall else 9999.0
        hist_n = 300 if full_history else 0
        trail_n = 500 if full_history else 1
        pkt_n = 20 if full_history else 5
        msg: Dict[str, Any] = {
            "type": msg_type,
            "vehicle": st.vehicle,
            "t": int(time.time() * 1000),
            "telemetry": dict(st.telemetry),
            "gps": dict(st.gps),
            "phase": st.phase,
            "link": {
                "state": st.link_state,
                "packet_rate_hz": round(self._packet_rate_hz(st), 2),
                "crc_error_count": st.frames_crc_error,
                "frames_ok": st.frames_ok,
                "frames_resynced": st.frames_resynced,
                "last_seq_gap": st.last_seq_gap,
                "last_packet_age_s": round(age, 3),
            },
            "prediction": st.prediction,
            "trajectory": self._trajectory_payload(st, full_history=full_history),
            "prev_phase": st.prev_phase,
            "events": list(st.events)[:5],
            "cansat_separated": self._cansat_separated,
            "signal": {
                "rssi": st.last_rssi,
                "snr": st.last_snr,
                "rssi_history": list(st.hist_rssi)[-40:],
                "snr_history": list(st.hist_snr)[-40:],
            },
            "packets": self._packets_counters(st, recent_n=pkt_n),
        }
        if full_history:
            msg["history"] = {
                "altitude": list(st.hist_altitude)[-hist_n:],
                "speed": list(st.hist_speed)[-hist_n:],
                "pitch": list(st.hist_pitch)[-hist_n:],
                "yaw": list(st.hist_yaw)[-hist_n:],
                "roll": list(st.hist_roll)[-hist_n:],
                "battery": list(st.hist_battery)[-hist_n:],
                "temperature": list(st.hist_temperature)[-hist_n:],
                "pressure": list(st.hist_pressure)[-hist_n:],
            }
            msg["trail"] = list(st.trail)[-trail_n:]
        else:
            # Lightweight live update — client appends to its own history
            msg["trail_point"] = list(st.trail)[-1:] if st.trail else []
        return json_safe(msg)

    def connection_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                v: {
                    "link_state": self._states[v].link_state,
                    "phase": self._states[v].phase,
                    "frames_ok": self._states[v].frames_ok,
                }
                for v in VEHICLES
            }

    def _packets_counters(
        self, st: VehicleState, recent_n: Optional[int] = None
    ) -> Dict[str, Any]:
        now = time.monotonic()
        age = (now - st.last_frame_wall) if st.last_frame_wall else 9999.0
        blob: Dict[str, Any] = {
            "frames_ok": st.frames_ok,
            "frames_crc_error": st.frames_crc_error,
            "frames_resynced": st.frames_resynced,
            "transport_malformed": st.frames_crc_error,
            "transport_ok": st.transport_ok,
            "transport_err": st.transport_err,
            "transport_unknown": st.transport_unknown,
            "app_parse_error": st.csv_stats.errors,
            "app_field_count_error": st.csv_stats.field_count_error,
            "app_type_error": st.csv_stats.type_error,
            "rssi": st.last_rssi,
            "snr": st.last_snr,
            "packet_rate_hz": round(self._packet_rate_hz(st), 2),
            "last_seq": st.last_seq,
            "last_seq_gap": st.last_seq_gap,
            "total_seq_gaps": st.total_seq_gaps,
            "last_packet_age_s": round(age, 3),
            "rate_history": list(st.packet_rate_history)[-40:],
            "last_by_type": {str(k): v for k, v in st.last_by_type.items()},
        }
        if recent_n is not None:
            blob["recent"] = list(st.recent_packets)[:recent_n]
        return blob

    def packets_snapshot(self, vehicle: str, limit: int = 50) -> Dict[str, Any]:
        """Full packet monitor payload for GET /packets/{vehicle} (PRD C.5)."""
        vehicle = vehicle.lower()
        if vehicle not in self._states:
            raise KeyError(vehicle)
        with self._lock:
            st = self._states[vehicle]
            lim = max(1, min(int(limit), PACKET_RING_SIZE))
            blob = self._packets_counters(st, recent_n=lim)
            blob["vehicle"] = vehicle
            blob["rate_history"] = list(st.packet_rate_history)
            return json_safe(blob)
