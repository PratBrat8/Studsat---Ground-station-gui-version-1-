"""
Uplink command queue (PRD v2 C.4).

Status lifecycle (Appendix 1.3 TEMPORARY/UNCONFIRMED):
  SENT → TRANSMITTED   (Reyax +OK)
  SENT → NO_RESPONSE   (timeout, no +OK)
  SENT → TX_ERROR      (Reyax +ERR)

Never promote to ACKED — firmware is assumed not to send an application-level
"command executed" reply. The UI must show "transmitted, not confirmed by
vehicle", not a fake executed state.

EJ requires confirmed=True and is routed to the Rocket/Avionics line only.
"""
from __future__ import annotations

import csv
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.config import (
    CANSAT_VEHICLE_ADDR,
    COMMAND_ACK_TIMEOUT_S,
    COMMAND_RATE_LIMIT_S,
    EJECTION_VEHICLE,
    LOGS_DIR,
    ROCKET_VEHICLE_ADDR,
    TEAM_ID,
)
from app.protocol import (
    cmd_calibrate,
    cmd_manual_ejection,
    cmd_set_time,
    cmd_telemetry_power,
)
from app.radio_transport import ModuleErr, ModuleOk, build_send_command

WriteFn = Callable[[bytes], bool]

STATUS_SENT = "SENT"
STATUS_TRANSMITTED = "TRANSMITTED"
STATUS_NO_RESPONSE = "NO_RESPONSE"
STATUS_TX_ERROR = "TX_ERROR"
# ACKED is intentionally unused (COMMAND_APP_ACK_ENABLED is False).

CALIBRATE_TYPES = {"CG", "CB", "CA"}
COMMAND_TYPES = {"TX", "ST", "CG", "CB", "CA", "EJ"}

COMMAND_LOG_FIELDS = [
    "wall_time_iso",
    "command_id",
    "vehicle",
    "cmd_type",
    "command_str",
    "status",
    "error",
    "confirmed",
    "dest_addr",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class CommandRecord:
    id: str
    vehicle: str
    cmd_type: str
    command_str: str
    status: str
    dest_addr: int
    confirmed: bool = False
    error: Optional[str] = None
    sent_at: float = field(default_factory=time.monotonic)
    sent_wall_iso: str = field(default_factory=_iso_now)
    transmitted_at: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        note = None
        if self.status == STATUS_TRANSMITTED:
            note = "transmitted, not confirmed by vehicle"
        return {
            "id": self.id,
            "vehicle": self.vehicle,
            "type": self.cmd_type,
            "command": self.command_str,
            "status": self.status,
            "error": self.error,
            "confirmed": self.confirmed,
            "dest_addr": self.dest_addr,
            "sent_at": self.sent_wall_iso,
            "note": note,
        }


class CommandManager:
    def __init__(
        self,
        logs_dir: Optional[Path] = None,
        timeout_s: float = COMMAND_ACK_TIMEOUT_S,
        rate_limit_s: float = COMMAND_RATE_LIMIT_S,
        team_id: str = TEAM_ID,
    ) -> None:
        self._lock = threading.RLock()
        self._history: List[CommandRecord] = []
        self._inflight: Dict[str, CommandRecord] = {}
        self._last_sent: Dict[tuple[str, str], float] = {}
        self._timers: Dict[str, threading.Timer] = {}
        self._writers: Dict[str, WriteFn] = {}
        self._session_sinks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self._timeout_s = float(timeout_s)
        self._rate_limit_s = float(rate_limit_s)
        self._team_id = team_id
        self.logs_dir = Path(logs_dir or LOGS_DIR)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.logs_dir / "commands.csv"
        self._init_log()

    def _init_log(self) -> None:
        new = not self.log_path.exists()
        self._log_file = self.log_path.open("a", newline="", encoding="utf-8")
        self._log_writer = csv.DictWriter(
            self._log_file, fieldnames=COMMAND_LOG_FIELDS, extrasaction="ignore"
        )
        if new:
            self._log_writer.writeheader()
            self._log_file.flush()

    def set_writer(self, vehicle: str, writer: Optional[WriteFn]) -> None:
        vehicle = vehicle.lower()
        with self._lock:
            if writer is None:
                self._writers.pop(vehicle, None)
            else:
                self._writers[vehicle] = writer

    def set_session_sink(
        self, vehicle: str, sink: Optional[Callable[[Dict[str, Any]], None]]
    ) -> None:
        """Per-session command CSV (Phase 12) alongside the process-wide log."""
        vehicle = vehicle.lower()
        with self._lock:
            if sink is None:
                self._session_sinks.pop(vehicle, None)
            else:
                self._session_sinks[vehicle] = sink

    def close(self) -> None:
        with self._lock:
            for t in list(self._timers.values()):
                try:
                    t.cancel()
                except Exception:
                    pass
            self._timers.clear()
            try:
                self._log_file.close()
            except Exception:
                pass

    def list_commands(self, vehicle: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = list(self._history)
        if vehicle:
            v = vehicle.lower()
            rows = [r for r in rows if r.vehicle == v]
        rows = rows[-max(1, min(int(limit), 200)) :]
        return [r.as_dict() for r in reversed(rows)]

    def get_command(self, command_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for r in self._history:
                if r.id == command_id:
                    return r.as_dict()
        return None

    def send_command(
        self,
        vehicle: str,
        cmd_type: str,
        *,
        on: Optional[bool] = None,
        utc_time: Optional[str] = None,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        vehicle = (vehicle or "").strip().lower()
        if vehicle not in ("rocket", "satellite"):
            raise ValueError("vehicle must be rocket or satellite")
        kind = (cmd_type or "").strip().upper()
        if kind not in COMMAND_TYPES:
            raise ValueError(f"unknown command type {cmd_type!r}")

        if kind == "EJ":
            if vehicle != EJECTION_VEHICLE:
                raise ValueError(
                    "EJ is Rocket/Avionics only (TEMPORARY/UNCONFIRMED Appendix 1.7)"
                )
            if not confirmed:
                raise PermissionError(
                    "EJ requires confirmed=true (hold-to-confirm / arm-fire)"
                )
        if kind == "TX" and on is False and not confirmed:
            raise PermissionError(
                "TX OFF requires confirmed=true (hold-to-confirm)"
            )

        command_str = self._build(kind, on=on, utc_time=utc_time)
        dest = ROCKET_VEHICLE_ADDR if vehicle == "rocket" else CANSAT_VEHICLE_ADDR
        now = time.monotonic()

        with self._lock:
            inflight = self._inflight.get(vehicle)
            if inflight is not None and inflight.status == STATUS_SENT:
                raise RuntimeError(
                    f"command {inflight.id} still waiting for +OK on {vehicle}"
                )
            last = self._last_sent.get((vehicle, kind), 0.0)
            if now - last < self._rate_limit_s:
                wait = self._rate_limit_s - (now - last)
                raise RuntimeError(
                    f"rate limited: wait {wait:.1f}s before sending {kind} again"
                )
            writer = self._writers.get(vehicle)
            if writer is None:
                raise RuntimeError(f"no radio link for {vehicle}")

            rec = CommandRecord(
                id=uuid.uuid4().hex[:12],
                vehicle=vehicle,
                cmd_type=kind,
                command_str=command_str,
                status=STATUS_SENT,
                dest_addr=dest,
                confirmed=bool(confirmed),
            )
            # Register inflight BEFORE write so a synchronous +OK can match.
            self._history.append(rec)
            self._inflight[vehicle] = rec
            self._last_sent[(vehicle, kind)] = now
            timer = threading.Timer(
                self._timeout_s, self._on_timeout, args=(rec.id, vehicle)
            )
            timer.daemon = True
            self._timers[rec.id] = timer
            timer.start()
            self._append_log(rec)

            wire = build_send_command(dest, command_str)
            try:
                ok = bool(writer(wire))
            except Exception as exc:
                rec.status = STATUS_TX_ERROR
                rec.error = f"write failed: {exc}"
                self._inflight.pop(vehicle, None)
                t = self._timers.pop(rec.id, None)
                if t:
                    t.cancel()
                self._append_log(rec)
                return rec.as_dict()
            if not ok:
                rec.status = STATUS_TX_ERROR
                rec.error = "write failed (link not open)"
                self._inflight.pop(vehicle, None)
                t = self._timers.pop(rec.id, None)
                if t:
                    t.cancel()
                self._append_log(rec)
                return rec.as_dict()
            return rec.as_dict()

    def on_module_response(self, vehicle: str, resp: Any) -> None:
        vehicle = vehicle.lower()
        with self._lock:
            rec = self._inflight.get(vehicle)
            if rec is None or rec.status != STATUS_SENT:
                return
            if isinstance(resp, ModuleOk):
                rec.status = STATUS_TRANSMITTED
                rec.transmitted_at = time.monotonic()
                rec.error = None
            elif isinstance(resp, ModuleErr):
                rec.status = STATUS_TX_ERROR
                rec.error = f"+ERR={resp.code}"
            else:
                return
            self._inflight.pop(vehicle, None)
            t = self._timers.pop(rec.id, None)
            if t:
                t.cancel()
            self._append_log(rec)

    def fail_inflight(self, vehicle: str, reason: str = "link lost") -> None:
        """Drop SENT commands when the radio link dies (Phase 13)."""
        vehicle = (vehicle or "").strip().lower()
        with self._lock:
            rec = self._inflight.get(vehicle)
            if rec is None or rec.status != STATUS_SENT:
                return
            rec.status = STATUS_NO_RESPONSE
            rec.error = reason
            self._inflight.pop(vehicle, None)
            t = self._timers.pop(rec.id, None)
            if t:
                t.cancel()
            self._append_log(rec)

    def _on_timeout(self, command_id: str, vehicle: str) -> None:
        with self._lock:
            rec = self._inflight.get(vehicle)
            if rec is None or rec.id != command_id:
                return
            if rec.status != STATUS_SENT:
                return
            rec.status = STATUS_NO_RESPONSE
            rec.error = f"no +OK within {self._timeout_s:.1f}s"
            self._inflight.pop(vehicle, None)
            self._timers.pop(command_id, None)
            self._append_log(rec)

    def _build(self, kind: str, *, on: Optional[bool], utc_time: Optional[str]) -> str:
        tid = self._team_id
        if kind == "TX":
            if on is None:
                raise ValueError("TX requires on=true|false")
            return cmd_telemetry_power(tid, bool(on))
        if kind == "ST":
            ts = utc_time or datetime.now(timezone.utc).strftime("%H:%M:%S")
            return cmd_set_time(tid, ts)
        if kind in CALIBRATE_TYPES:
            return cmd_calibrate(tid, kind)
        if kind == "EJ":
            return cmd_manual_ejection(tid)
        raise ValueError(kind)

    def _append_log(self, rec: CommandRecord) -> None:
        row = {
            "wall_time_iso": _iso_now(),
            "command_id": rec.id,
            "vehicle": rec.vehicle,
            "cmd_type": rec.cmd_type,
            "command_str": rec.command_str,
            "status": rec.status,
            "error": rec.error or "",
            "confirmed": rec.confirmed,
            "dest_addr": rec.dest_addr,
        }
        try:
            self._log_writer.writerow(row)
            self._log_file.flush()
        except Exception:
            pass
        sink = self._session_sinks.get(rec.vehicle)
        if sink is not None:
            try:
                sink(row)
            except Exception:
                pass
