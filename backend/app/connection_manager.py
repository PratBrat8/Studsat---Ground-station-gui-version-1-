"""
Owns per-vehicle serial/sim/replay links and feeds TelemetryHub.

One backend process, two independent vehicle pipelines (PRD B.1).
Phase 10: session CSV logging + replay player.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Union

from app.logger import ReplayPlayer, SessionLogger, list_sessions
from app.protocol import VEHICLE_ROCKET, VEHICLE_SATELLITE, RawFrame
from app.serial_manager import SerialVehicleLink, list_available_ports
from app.simulator import SimulatedVehicleLink
from app.telemetry_hub import VEHICLES, TelemetryHub

LinkType = Union[SerialVehicleLink, SimulatedVehicleLink]

_VEHICLE_IDS = {
    "rocket": VEHICLE_ROCKET,
    "satellite": VEHICLE_SATELLITE,
}


class ConnectionManager:
    def __init__(self, hub: TelemetryHub) -> None:
        self.hub = hub
        self._lock = threading.RLock()
        self._links: Dict[str, LinkType] = {}
        self._modes: Dict[str, Optional[str]] = {v: None for v in VEHICLES}
        self._loggers: Dict[str, Optional[SessionLogger]] = {v: None for v in VEHICLES}
        self.replay = ReplayPlayer(hub)

    def list_ports(self) -> list:
        return list_available_ports()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            out = {}
            for v in VEHICLES:
                link = self._links.get(v)
                logger = self._loggers.get(v)
                diag = {}
                if link is not None and hasattr(link, "diagnostics"):
                    try:
                        diag = link.diagnostics()
                    except Exception:
                        diag = {}
                out[v] = {
                    "mode": self._modes.get(v),
                    "running": bool(link and link.is_running),
                    "port": getattr(link, "port", None) if link else None,
                    "baud": getattr(link, "baud", None) if link else None,
                    "logging": bool(logger is not None),
                    "log_file": logger.filename if logger else None,
                    "log_samples": logger.sample_count if logger else 0,
                    "link_state": getattr(link, "link_state", None) if link else "DISCONNECTED",
                    "last_error": diag.get("last_error"),
                    "open_failures": diag.get("open_failures"),
                    "reconnect_count": diag.get("reconnect_count"),
                }
            out["replay"] = self.replay.get_status()
            return out

    def connect_serial(self, vehicle: str, port: str, baud: int) -> Dict[str, Any]:
        from app.serial_manager import port_exists, validate_port_arg

        vehicle = self._norm_vehicle(vehicle)
        port = validate_port_arg(port)
        present = port_exists(port)
        with self._lock:
            self._stop_unlocked(vehicle)
            # Stop replay if it owns this vehicle
            rs = self.replay.get_status()
            if rs.get("running") and rs.get("vehicle") == vehicle:
                self.replay.stop()
            self.hub.reset_vehicle(vehicle)
            self._start_logger(vehicle)
            try:
                link = SerialVehicleLink(
                    vehicle_id=_VEHICLE_IDS[vehicle],
                    port=port,
                    baud=baud,
                    on_frame_callback=self._on_frame,
                    on_link_state=self._on_link_state,
                )
                link.start()
            except Exception as exc:
                self._stop_logger(vehicle)
                raise ValueError(f"serial start failed: {exc}") from exc
            self._links[vehicle] = link
            self._modes[vehicle] = "serial"
            self.hub.set_link_state(vehicle, "RECONNECTING")
        return {
            "ok": True,
            "vehicle": vehicle,
            "mode": "serial",
            "port": port,
            "baud": baud,
            "port_present": present,
            "warning": None
            if present
            else f"Port {port} not in current COM list — will keep retrying",
            "log_file": self._loggers[vehicle].filename if self._loggers[vehicle] else None,
        }

    def start_simulate(self, vehicle: str, enabled: bool = True) -> Dict[str, Any]:
        vehicle = self._norm_vehicle(vehicle)
        with self._lock:
            if not enabled:
                return self._stop_unlocked(vehicle)

            self._stop_unlocked(vehicle)
            # Stop replay if it targets this vehicle
            rs = self.replay.get_status()
            if rs.get("running") and rs.get("vehicle") == vehicle:
                self.replay.stop()

            self.hub.reset_vehicle(vehicle)
            self._start_logger(vehicle)
            link = SimulatedVehicleLink(
                vehicle_id=_VEHICLE_IDS[vehicle],
                on_frame_callback=self._on_frame,
                on_link_state=self._on_link_state,
                hz=10.0,
            )
            self._links[vehicle] = link
            self._modes[vehicle] = "sim"
            link.start()
            self.hub.set_link_state(vehicle, "CONNECTED")
        return {
            "ok": True,
            "vehicle": vehicle,
            "mode": "sim",
            "enabled": True,
            "log_file": self._loggers[vehicle].filename if self._loggers[vehicle] else None,
        }

    def disconnect(self, vehicle: str) -> Dict[str, Any]:
        vehicle = self._norm_vehicle(vehicle)
        with self._lock:
            return self._stop_unlocked(vehicle)

    def stop_all(self) -> None:
        try:
            self.replay.stop()
        except Exception:
            pass
        with self._lock:
            for v in list(VEHICLES):
                self._stop_unlocked(v)

    # --- Replay (Phase 10) ---

    def list_replay_sessions(self) -> list:
        return list_sessions()

    def start_replay(
        self, filename: str, speed: float = 1.0, vehicle: Optional[str] = None
    ) -> Dict[str, Any]:
        # Stop live links that would fight the hub for the target vehicle
        # Peek vehicle from sessions if not provided
        sessions = list_sessions()
        meta = next((s for s in sessions if s["filename"] == filename), None)
        veh = vehicle or (meta["vehicle"] if meta else "rocket")
        veh = self._norm_vehicle(veh)

        with self._lock:
            self._stop_unlocked(veh)

        status = self.replay.start(filename, vehicle=veh, speed=speed)
        self._modes[veh] = "replay"
        return {"ok": True, **status}

    def stop_replay(self) -> Dict[str, Any]:
        st = self.replay.stop()
        with self._lock:
            for v in VEHICLES:
                if self._modes.get(v) == "replay":
                    self._modes[v] = None
        return {"ok": True, **st}

    def pause_replay(self, paused: bool = True) -> Dict[str, Any]:
        return {"ok": True, **self.replay.set_paused(paused)}

    def set_replay_speed(self, speed: float) -> Dict[str, Any]:
        return {"ok": True, **self.replay.set_speed(speed)}

    def replay_status(self) -> Dict[str, Any]:
        return self.replay.get_status()

    def _start_logger(self, vehicle: str) -> None:
        self._stop_logger(vehicle)
        try:
            logger = SessionLogger(vehicle)
            self._loggers[vehicle] = logger
            self.hub.set_session_logger(vehicle, logger)
        except Exception:
            self._loggers[vehicle] = None
            self.hub.set_session_logger(vehicle, None)

    def _stop_logger(self, vehicle: str) -> None:
        logger = self._loggers.get(vehicle)
        self._loggers[vehicle] = None
        self.hub.set_session_logger(vehicle, None)
        if logger is not None:
            try:
                logger.close()
            except Exception:
                pass

    def _stop_unlocked(self, vehicle: str) -> Dict[str, Any]:
        link = self._links.pop(vehicle, None)
        self._modes[vehicle] = None
        if link is not None:
            try:
                link.stop()
            except Exception:
                pass
        log_file = None
        samples = 0
        logger = self._loggers.get(vehicle)
        if logger:
            log_file = logger.filename
            samples = logger.sample_count
        self._stop_logger(vehicle)
        self.hub.set_link_state(vehicle, "DISCONNECTED")
        return {
            "ok": True,
            "vehicle": vehicle,
            "mode": None,
            "running": False,
            "log_file": log_file,
            "log_samples": samples,
        }

    def _norm_vehicle(self, vehicle: str) -> str:
        v = (vehicle or "").strip().lower()
        if v not in VEHICLES:
            raise ValueError(f"vehicle must be one of {VEHICLES}, got {vehicle!r}")
        return v

    def _on_frame(self, vehicle_key: str, frame: RawFrame) -> None:
        stats = None
        with self._lock:
            link = self._links.get(vehicle_key)
            if link is not None:
                p = link.parser
                stats = {
                    "frames_ok": p.frames_ok,
                    "frames_crc_error": p.frames_crc_error,
                    "frames_resynced": p.frames_resynced,
                }
        try:
            self.hub.ingest_raw_frame(vehicle_key, frame, stats, logging_enabled=True)
        except Exception:
            pass

    def _on_link_state(self, vehicle_key: str, state: str) -> None:
        try:
            self.hub.set_link_state(vehicle_key, state)
        except Exception:
            pass
