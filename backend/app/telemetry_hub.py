"""
In-memory telemetry hub — ring buffers + throttled pub/sub (PRD C.3 / C.4).

Thread-safe ingest from serial/sim threads; asyncio queues notify WS clients.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set

from app.config import (
    GPS_TRACK_MAX_POINTS,
    PACKET_RING_SIZE,
    PREDICTION_WINDOW_SAMPLES,
    RING_BUFFER_SAMPLES,
    WS_BROADCAST_INTERVAL_MS,
)
from app.phase_fsm import PhaseFSM, PhaseSample
from app.predictor import LandingPredictor
from app.protocol import (
    TYPE_EVENT,
    TYPE_GPS,
    TYPE_STATUS,
    TYPE_TELEMETRY,
    EventFrame,
    GpsFrame,
    ProtocolError,
    RawFrame,
    StatusFrame,
    TelemetryFrame,
    decode_payload,
)

VEHICLES = ("rocket", "satellite")

_PACKET_TYPE_NAMES = {
    TYPE_TELEMETRY: "TELEMETRY",
    TYPE_GPS: "GPS",
    TYPE_STATUS: "STATUS",
    TYPE_EVENT: "EVENT",
}


def _fields_from_decoded(decoded: Any) -> Dict[str, Any]:
    """Flatten decoded dataclass to JSON-safe field map for Packet Monitor."""
    if decoded is None:
        return {}
    try:
        if isinstance(decoded, TelemetryFrame):
            return {
                "timestamp_ms": decoded.timestamp_ms,
                "altitude_m": round(decoded.altitude_m, 3),
                "pressure_hpa": round(decoded.pressure_hpa, 3),
                "temperature_c": round(decoded.temperature_c, 3),
                "accel_x": round(decoded.accel_x, 3),
                "accel_y": round(decoded.accel_y, 3),
                "accel_z": round(decoded.accel_z, 3),
                "gyro_x": round(decoded.gyro_x, 3),
                "gyro_y": round(decoded.gyro_y, 3),
                "gyro_z": round(decoded.gyro_z, 3),
                "pitch": round(decoded.pitch, 3),
                "yaw": round(decoded.yaw, 3),
                "roll": round(decoded.roll, 3),
                "battery_v": round(decoded.battery_v, 3),
            }
        if isinstance(decoded, GpsFrame):
            return {
                "gps_timestamp": decoded.gps_timestamp,
                "lat": decoded.lat,
                "lon": decoded.lon,
                "alt_msl_m": round(decoded.alt_msl_m, 3),
                "num_sats": decoded.num_sats,
                "hdop": round(decoded.hdop, 3),
                "fix_type": decoded.fix_type,
            }
        if isinstance(decoded, StatusFrame):
            return {
                "phase_hint": decoded.phase_hint,
                "battery_v": round(decoded.battery_v, 3),
                "error_flags": decoded.error_flags,
            }
        if isinstance(decoded, EventFrame):
            return {"message": decoded.message}
        # Generic fallback
        if hasattr(decoded, "__dict__"):
            return {k: getattr(decoded, k) for k in vars(decoded)}
    except Exception:
        return {}
    return {}


def _empty_telemetry() -> Dict[str, Any]:
    return {
        "altitude_m": None,
        "speed_mps": None,
        "pitch": None,
        "yaw": None,
        "roll": None,
        "temperature_c": None,
        "pressure_hpa": None,
        "battery_v": None,
        "accel_x": None,
        "accel_y": None,
        "accel_z": None,
        "gyro_x": None,
        "gyro_y": None,
        "gyro_z": None,
        "timestamp_ms": None,
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

    # Packet monitor
    recent_packets: Deque[Dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=PACKET_RING_SIZE)
    )
    frames_ok: int = 0
    frames_crc_error: int = 0
    frames_resynced: int = 0
    last_seq: Optional[int] = None
    last_seq_gap: int = 0
    total_seq_gaps: int = 0
    packet_times: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    packet_rate_history: Deque[float] = field(
        default_factory=lambda: deque(maxlen=60)
    )
    last_packet_age_s: float = 9999.0
    last_frame_wall: float = 0.0
    # Latest decoded frame per type (for Packet Monitor field table)
    last_by_type: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # Phase 7 — FSM + landing predictor (per vehicle)
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

    def ingest_raw_frame(
        self,
        vehicle: str,
        frame: RawFrame,
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
            if parser_stats:
                st.frames_ok = int(parser_stats.get("frames_ok", st.frames_ok))
                st.frames_crc_error = int(
                    parser_stats.get("frames_crc_error", st.frames_crc_error)
                )
                st.frames_resynced = int(
                    parser_stats.get("frames_resynced", st.frames_resynced)
                )

            # Seq gap detection
            if st.last_seq is not None:
                expected = (st.last_seq + 1) & 0xFF
                if frame.seq != expected:
                    gap = (frame.seq - expected) & 0xFF
                    st.last_seq_gap = gap
                    st.total_seq_gaps += 1
                else:
                    st.last_seq_gap = 0
            st.last_seq = frame.seq
            st.packet_times.append(now)
            st.last_frame_wall = now
            st.last_packet_age_s = 0.0
            st.link_state = "CONNECTED"
            rate = self._packet_rate_hz(st)
            st.packet_rate_history.append(round(rate, 2))

            if not st._got_first_frame:
                st._got_first_frame = True
                st.prev_phase = st.phase
                st.phase_fsm.on_connected()
                st.phase = st.phase_fsm.phase

            # Decode payload defensively
            decoded = None
            decode_err = None
            try:
                decoded = decode_payload(frame.packet_type, frame.payload)
            except ProtocolError as exc:
                decode_err = str(exc)
            except Exception as exc:
                decode_err = str(exc)

            fields = _fields_from_decoded(decoded) if decoded is not None else {}
            type_name = _PACKET_TYPE_NAMES.get(
                frame.packet_type, f"0x{frame.packet_type:02X}"
            )
            pkt_rec = {
                "t": wall_ms,
                "seq": frame.seq,
                "type": frame.packet_type,
                "type_name": type_name,
                "vehicle_id": frame.vehicle_id,
                "len": len(frame.payload),
                "hex": frame.raw_bytes.hex(" "),
                "payload_hex": frame.payload.hex(" "),
                "ok": decode_err is None,
                "error": decode_err,
                "fields": fields,
            }
            st.recent_packets.appendleft(pkt_rec)
            if decoded is not None:
                st.last_by_type[frame.packet_type] = pkt_rec

            if decoded is None:
                self._pending_notify[vehicle] = True
            else:
                self._apply_decoded(st, frame.packet_type, decoded, now)
                self._pending_notify[vehicle] = True

            # Continuous CSV log (Phase 10) — after phase/prediction update
            if logging_enabled:
                logger = self._session_loggers.get(vehicle)
                if logger is not None:
                    try:
                        from app.logger import build_log_row_from_state

                        logger.log_row(
                            build_log_row_from_state(
                                vehicle, frame, st, wall_ms, type_name=type_name
                            )
                        )
                    except Exception:
                        pass

        self._schedule_notify(vehicle)

    def _apply_decoded(
        self, st: VehicleState, packet_type: int, decoded: Any, now: float
    ) -> None:
        event_for_fsm: Optional[str] = None

        if packet_type == TYPE_TELEMETRY:
            t = decoded
            speed = self._estimate_vspeed(st, float(t.altitude_m), now)
            st.telemetry = {
                "altitude_m": float(t.altitude_m),
                "speed_mps": speed,
                "pitch": float(t.pitch),
                "yaw": float(t.yaw),
                "roll": float(t.roll),
                "temperature_c": float(t.temperature_c),
                "pressure_hpa": float(t.pressure_hpa),
                "battery_v": float(t.battery_v),
                "accel_x": float(t.accel_x),
                "accel_y": float(t.accel_y),
                "accel_z": float(t.accel_z),
                "gyro_x": float(t.gyro_x),
                "gyro_y": float(t.gyro_y),
                "gyro_z": float(t.gyro_z),
                "timestamp_ms": int(t.timestamp_ms),
            }
            st.hist_t.append(now)
            st.hist_altitude.append(float(t.altitude_m))
            st.hist_speed.append(speed if speed is not None else 0.0)
            st.hist_pitch.append(float(t.pitch))
            st.hist_yaw.append(float(t.yaw))
            st.hist_roll.append(float(t.roll))
            st.hist_battery.append(float(t.battery_v))
            st.hist_temperature.append(float(t.temperature_c))
            st.hist_pressure.append(float(t.pressure_hpa))
            st._last_alt = float(t.altitude_m)
            st._last_alt_t = now

            # Feed altitude into predictor between GPS fixes
            try:
                st.predictor.push_altitude(now, float(t.altitude_m))
            except Exception:
                pass

            event_for_fsm = st._pending_event
            st._pending_event = None
            self._run_phase_and_prediction(st, now, event=event_for_fsm)

        elif packet_type == TYPE_GPS:
            g = decoded
            st.gps = {
                "lat": float(g.lat),
                "lon": float(g.lon),
                "alt_m": float(g.alt_msl_m),
                "sats": int(g.num_sats),
                "hdop": float(g.hdop),
                "fix_type": int(g.fix_type),
                "gps_timestamp": int(g.gps_timestamp),
            }
            if g.fix_type > 0:
                st.trail.append(
                    {"lat": float(g.lat), "lon": float(g.lon), "t": now}
                )
                # Prefer AGL from last telemetry for vertical fit
                alt_for_pred = (
                    float(st.telemetry["altitude_m"])
                    if st.telemetry.get("altitude_m") is not None
                    else float(g.alt_msl_m)
                )
                try:
                    st.predictor.push_gps(
                        now,
                        float(g.lat),
                        float(g.lon),
                        alt_for_pred,
                        hdop=float(g.hdop),
                    )
                except Exception:
                    pass
            # Recompute prediction on GPS (descent tracking)
            self._update_prediction_only(st)

        elif packet_type == TYPE_STATUS:
            s = decoded
            st.telemetry["battery_v"] = float(s.battery_v)
            # phase_hint 0 = let ground station decide (PRD)

        elif packet_type == TYPE_EVENT:
            msg = str(decoded.message)
            st.events.appendleft(msg)
            # Apply on next telemetry sample so we have altitude context;
            # also step immediately with last known kinematics.
            st._pending_event = msg
            self._run_phase_and_prediction(st, now, event=msg)

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
            "prev_phase": st.prev_phase,
            "events": list(st.events)[:5],
            "packets": {
                "frames_ok": st.frames_ok,
                "frames_crc_error": st.frames_crc_error,
                "frames_resynced": st.frames_resynced,
                "packet_rate_hz": round(self._packet_rate_hz(st), 2),
                "last_seq": st.last_seq,
                "last_seq_gap": st.last_seq_gap,
                "total_seq_gaps": st.total_seq_gaps,
                "rate_history": list(st.packet_rate_history)[-40:],
                "recent": list(st.recent_packets)[:pkt_n],
                "last_by_type": {
                    str(k): v for k, v in st.last_by_type.items()
                },
            },
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
        return msg

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

    def packets_snapshot(self, vehicle: str, limit: int = 50) -> Dict[str, Any]:
        """Full packet monitor payload for GET /packets/{vehicle} (PRD C.5)."""
        vehicle = vehicle.lower()
        if vehicle not in self._states:
            raise KeyError(vehicle)
        with self._lock:
            st = self._states[vehicle]
            now = time.monotonic()
            age = (now - st.last_frame_wall) if st.last_frame_wall else 9999.0
            lim = max(1, min(int(limit), PACKET_RING_SIZE))
            return {
                "vehicle": vehicle,
                "frames_ok": st.frames_ok,
                "frames_crc_error": st.frames_crc_error,
                "frames_resynced": st.frames_resynced,
                "packet_rate_hz": round(self._packet_rate_hz(st), 2),
                "last_seq": st.last_seq,
                "last_seq_gap": st.last_seq_gap,
                "total_seq_gaps": st.total_seq_gaps,
                "last_packet_age_s": round(age, 3),
                "rate_history": list(st.packet_rate_history),
                "recent": list(st.recent_packets)[:lim],
                "last_by_type": {str(k): v for k, v in st.last_by_type.items()},
            }
