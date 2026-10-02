"""
CSV session logger + replay file loader (PRD C.3 / Phase 12).

- Continuous append during live/sim sessions (flushed often — not only on disconnect).
- Per-session command log written next to the telemetry CSV.
- list_sessions() for Replay tab (skips commands.csv / *_commands.csv).
- load_session() yields rows; ReplayPlayer feeds the real hub via +RCV parse path.
"""
from __future__ import annotations

import csv
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from app.command_manager import COMMAND_LOG_FIELDS, STATUS_TRANSMITTED
from app.config import CANSAT_VEHICLE_ADDR, LOGS_DIR, ROCKET_VEHICLE_ADDR, TEAM_ID
from app.protocol import (
    VEHICLE_ROCKET,
    VEHICLE_SATELLITE,
    FlightState,
    TelemetryRecord,
    format_telemetry_csv,
)
from app.radio_transport import RadioLineBuffer, RadioPacket, format_rcv_line

GLOBAL_COMMANDS_FILENAME = "commands.csv"

CSV_FIELDS = [
    "wall_time_iso",
    "wall_ms",
    "vehicle",
    "phase",
    "seq",
    "packet_type",
    "packet_type_name",
    "raw_hex",
    "altitude_m",
    "speed_mps",
    "pitch",
    "yaw",
    "roll",
    "temperature_c",
    "pressure_hpa",
    "battery_v",
    "accel_x",
    "accel_y",
    "accel_z",
    "gyro_x",
    "gyro_y",
    "gyro_z",
    "timestamp_ms",
    "gps_lat",
    "gps_lon",
    "gps_alt_m",
    "gps_sats",
    "gps_hdop",
    "gps_fix_type",
    "event",
    "prediction_lat",
    "prediction_lon",
    "prediction_eta_s",
    "prediction_confidence",
    "link_state",
    "frames_ok",
    "frames_crc_error",
    "csv",
    "rssi",
    "snr",
    "flight_software_state",
]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")

_VEHICLE_IDS = {
    "rocket": VEHICLE_ROCKET,
    "satellite": VEHICLE_SATELLITE,
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _session_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class SessionLogger:
    """Append-only CSV logger for one vehicle session."""

    def __init__(self, vehicle: str, logs_dir: Optional[Path] = None) -> None:
        self.vehicle = vehicle.lower()
        self.logs_dir = Path(logs_dir or LOGS_DIR)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = _session_stamp()
        self.filename = f"{self.vehicle}_{stamp}.csv"
        self.command_filename = f"{self.vehicle}_{stamp}_commands.csv"
        self.path = self.logs_dir / self.filename
        self.command_path = self.logs_dir / self.command_filename
        self._lock = threading.Lock()
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        self._writer.writeheader()
        self._file.flush()
        self._cmd_file = self.command_path.open("w", newline="", encoding="utf-8")
        self._cmd_writer = csv.DictWriter(
            self._cmd_file, fieldnames=COMMAND_LOG_FIELDS, extrasaction="ignore"
        )
        self._cmd_writer.writeheader()
        self._cmd_file.flush()
        self.sample_count = 0
        self.command_count = 0
        self.started_at = time.time()
        self._closed = False

    def log_row(self, row: Dict[str, Any]) -> None:
        if self._closed:
            return
        out = {k: row.get(k, "") for k in CSV_FIELDS}
        with self._lock:
            try:
                self._writer.writerow(out)
                self.sample_count += 1
                # Continuous durability: flush every sample (sessions aren't huge)
                self._file.flush()
            except Exception:
                pass

    def log_command(self, row: Dict[str, Any]) -> None:
        if self._closed:
            return
        out = {k: row.get(k, "") for k in COMMAND_LOG_FIELDS}
        with self._lock:
            try:
                self._cmd_writer.writerow(out)
                self.command_count += 1
                self._cmd_file.flush()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
            try:
                self._cmd_file.flush()
                self._cmd_file.close()
            except Exception:
                pass


def is_command_log_filename(name: str) -> bool:
    n = Path(name).name.lower()
    return n == GLOBAL_COMMANDS_FILENAME or n.endswith("_commands.csv")


def command_log_name_for(telemetry_filename: str) -> str:
    stem = Path(telemetry_filename).stem
    return f"{stem}_commands.csv"


def list_sessions(logs_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan logs/ for telemetry session CSVs (PRD C.3 / Phase 12)."""
    root = Path(logs_dir or LOGS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    sessions: List[Dict[str, Any]] = []
    for path in sorted(root.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        if is_command_log_filename(path.name):
            continue
        info = _inspect_session(path)
        if info:
            sessions.append(info)
    return sessions


def _inspect_session(path: Path) -> Optional[Dict[str, Any]]:
    try:
        name = path.name
        vehicle = "unknown"
        if name.startswith("rocket_"):
            vehicle = "rocket"
        elif name.startswith("satellite_"):
            vehicle = "satellite"
        else:
            # try first data row
            pass

        sample_count = 0
        start_iso = None
        end_iso = None
        first_ms = None
        last_ms = None
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sample_count += 1
                if sample_count == 1:
                    start_iso = row.get("wall_time_iso") or ""
                    first_ms = _to_int(row.get("wall_ms"))
                    if row.get("vehicle"):
                        vehicle = row["vehicle"].strip().lower() or vehicle
                end_iso = row.get("wall_time_iso") or end_iso
                last_ms = _to_int(row.get("wall_ms")) or last_ms

        duration_s = 0.0
        if first_ms is not None and last_ms is not None and last_ms >= first_ms:
            duration_s = (last_ms - first_ms) / 1000.0
        elif sample_count > 1:
            duration_s = float(sample_count) / 10.0  # rough

        mtime = path.stat().st_mtime
        cmd_name = command_log_name_for(path.name)
        cmd_path = path.with_name(cmd_name)
        command_count = 0
        command_log = None
        if cmd_path.is_file():
            command_log = cmd_name
            try:
                with cmd_path.open("r", newline="", encoding="utf-8") as cf:
                    ids = {
                        (r.get("command_id") or "").strip()
                        for r in csv.DictReader(cf)
                    }
                    command_count = len({i for i in ids if i})
            except Exception:
                command_count = 0
        return {
            "filename": path.name,
            "vehicle": vehicle,
            "start_time": start_iso or datetime.fromtimestamp(mtime).isoformat(),
            "end_time": end_iso,
            "duration_s": round(duration_s, 2),
            "sample_count": sample_count,
            "command_count": command_count,
            "command_log": command_log,
            "size_bytes": path.stat().st_size,
            "path": str(path.resolve()),
        }
    except Exception:
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_log_path(filename: str, logs_dir: Optional[Path] = None) -> Path:
    root = Path(logs_dir or LOGS_DIR).resolve()
    safe = _SAFE_NAME.sub("", Path(filename).name)
    path = (root / safe).resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        raise FileNotFoundError(f"session not found: {filename}")
    return path


def load_session(filename: str, logs_dir: Optional[Path] = None) -> Iterator[Dict[str, Any]]:
    """Yield CSV rows as dicts (safe path under logs_dir only)."""
    path = _safe_log_path(filename, logs_dir=logs_dir)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield dict(row)


def load_session_commands(
    filename: str, logs_dir: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Last status per command id from the sibling session command CSV.
    `filename` is the telemetry session name (rocket_….csv).
    """
    if is_command_log_filename(filename):
        cmd_name = Path(filename).name
    else:
        cmd_name = command_log_name_for(filename)
    root = Path(logs_dir or LOGS_DIR).resolve()
    path = (root / _SAFE_NAME.sub("", cmd_name)).resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        return []
    latest: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = (row.get("command_id") or "").strip() or f"row-{len(order)}"
            status = (row.get("status") or "").strip()
            mapped = {
                "id": cid,
                "vehicle": row.get("vehicle") or "",
                "type": row.get("cmd_type") or "",
                "command": row.get("command_str") or "",
                "status": status,
                "error": row.get("error") or None,
                "confirmed": str(row.get("confirmed", "")).lower() in ("1", "true"),
                "dest_addr": row.get("dest_addr"),
                "sent_at": row.get("wall_time_iso") or "",
                "note": (
                    "transmitted, not confirmed by vehicle"
                    if status == STATUS_TRANSMITTED
                    else None
                ),
            }
            if cid not in latest:
                order.append(cid)
            latest[cid] = mapped
    return [latest[cid] for cid in order]


def row_to_wire_bytes(row: Dict[str, Any], vehicle_id: int, seq: int) -> Optional[bytes]:
    """Rebuild a +RCV line from a log row (v2 ASCII path)."""
    if row.get("cmd_type") and not row.get("csv") and not row.get("raw_hex"):
        return None
    raw = (row.get("raw_hex") or "").strip()
    if raw:
        try:
            blob = bytes.fromhex(raw.replace(" ", ""))
            if blob.startswith(b"+RCV="):
                if not blob.endswith(b"\n"):
                    blob += b"\r\n"
                return blob
        except ValueError:
            pass
        csv_inline = (row.get("csv") or "").strip()
        if csv_inline:
            addr = (
                ROCKET_VEHICLE_ADDR
                if vehicle_id == VEHICLE_ROCKET
                else CANSAT_VEHICLE_ADDR
            )
            rssi = _to_int(row.get("rssi")) or -70
            snr = _to_float(row.get("snr")) or 8.0
            return format_rcv_line(addr, csv_inline, rssi, snr).encode("utf-8")

    if row.get("altitude_m") in (None, "") and not row.get("csv"):
        return None
    try:
        rec = TelemetryRecord(
            team_id=str(row.get("team_id") or TEAM_ID),
            timestamp=str(row.get("timestamp") or "00:00:00"),
            packet_count=_to_int(row.get("seq")) or seq,
            altitude_m=_to_float(row.get("altitude_m")) or 0.0,
            pressure=_to_float(row.get("pressure_hpa")) or 0.0,
            temp_c=_to_float(row.get("temperature_c")) or 0.0,
            voltage=_to_float(row.get("battery_v")) or 0.0,
            gnss_time=str(row.get("timestamp") or "00:00:00"),
            gnss_lat=_to_float(row.get("gps_lat")) or 0.0,
            gnss_lon=_to_float(row.get("gps_lon")) or 0.0,
            gnss_alt_m=_to_float(row.get("gps_alt_m")) or 0.0,
            gnss_sats=_to_int(row.get("gps_sats")) or 0,
            accel_x=_to_float(row.get("accel_x")) or 0.0,
            accel_y=_to_float(row.get("accel_y")) or 0.0,
            accel_z=_to_float(row.get("accel_z")) or 9.8,
            gyro_x=_to_float(row.get("gyro_x")) or 0.0,
            gyro_y=_to_float(row.get("gyro_y")) or 0.0,
            gyro_z=_to_float(row.get("gyro_z")) or 0.0,
            flight_software_state=_to_int(row.get("flight_software_state"))
            or int(FlightState.LAUNCH_PAD),
        )
        addr = (
            ROCKET_VEHICLE_ADDR
            if vehicle_id == VEHICLE_ROCKET
            else CANSAT_VEHICLE_ADDR
        )
        rssi = _to_int(row.get("rssi")) or -70
        snr = _to_float(row.get("snr")) or 8.0
        return format_rcv_line(addr, format_telemetry_csv(rec), rssi, snr).encode(
            "utf-8"
        )
    except Exception:
        return None


@dataclass
class ReplayStatus:
    running: bool = False
    filename: Optional[str] = None
    vehicle: Optional[str] = None
    speed: float = 1.0
    index: int = 0
    total: int = 0
    paused: bool = False


class ReplayPlayer:
    """
    Plays a CSV session into TelemetryHub through the real encode→parser path
    (or raw_hex → parser), so UI reuses live WebSocket pipeline.
    """

    def __init__(
        self,
        hub: Any,
        on_status: Optional[Callable[[ReplayStatus], None]] = None,
    ) -> None:
        self.hub = hub
        self._on_status = on_status
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # not paused when set
        self.status = ReplayStatus()
        self._lock = threading.Lock()

    def start(
        self,
        filename: str,
        vehicle: Optional[str] = None,
        speed: float = 1.0,
        logs_dir: Optional[Path] = None,
    ) -> ReplayStatus:
        self.stop()
        if is_command_log_filename(filename):
            raise ValueError("that file is a command log — pick the telemetry session CSV")
        rows = list(load_session(filename, logs_dir=logs_dir))
        if not rows:
            raise ValueError("session has no samples")

        veh = (vehicle or rows[0].get("vehicle") or "rocket").strip().lower()
        if veh not in ("rocket", "satellite"):
            veh = "rocket"
        speed = max(0.1, min(float(speed), 50.0))

        self.hub.reset_vehicle(veh)
        self.hub.set_link_state(veh, "CONNECTED")

        with self._lock:
            self.status = ReplayStatus(
                running=True,
                filename=Path(filename).name,
                vehicle=veh,
                speed=speed,
                index=0,
                total=len(rows),
                paused=False,
            )
        self._stop.clear()
        self._pause.set()
        self._thread = threading.Thread(
            target=self._run,
            args=(rows, veh, speed),
            name=f"replay-{veh}",
            daemon=True,
        )
        self._thread.start()
        self._emit_status()
        return self.get_status()

    def stop(self) -> ReplayStatus:
        self._stop.set()
        self._pause.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        with self._lock:
            veh = self.status.vehicle
            self.status.running = False
            self.status.paused = False
        if veh:
            try:
                self.hub.set_link_state(veh, "DISCONNECTED")
            except Exception:
                pass
        self._emit_status()
        return self.get_status()

    def set_paused(self, paused: bool) -> ReplayStatus:
        if paused:
            self._pause.clear()
        else:
            self._pause.set()
        with self._lock:
            self.status.paused = bool(paused)
        self._emit_status()
        return self.get_status()

    def set_speed(self, speed: float) -> ReplayStatus:
        with self._lock:
            self.status.speed = max(0.1, min(float(speed), 50.0))
        self._emit_status()
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            s = self.status
            return {
                "running": s.running,
                "filename": s.filename,
                "vehicle": s.vehicle,
                "speed": s.speed,
                "index": s.index,
                "total": s.total,
                "paused": s.paused,
                "progress": (s.index / s.total) if s.total else 0.0,
            }

    def _emit_status(self) -> None:
        if self._on_status:
            try:
                self._on_status(self.status)
            except Exception:
                pass

    def _run(self, rows: List[Dict[str, Any]], vehicle: str, speed: float) -> None:
        parser = RadioLineBuffer()
        vehicle_id = _VEHICLE_IDS.get(vehicle, VEHICLE_ROCKET)
        prev_ms: Optional[int] = None
        seq_fallback = 0

        try:
            for i, row in enumerate(rows):
                if self._stop.is_set():
                    break
                # Pause support
                while not self._pause.is_set() and not self._stop.is_set():
                    time.sleep(0.05)

                with self._lock:
                    cur_speed = self.status.speed or speed
                    self.status.index = i

                wall_ms = _to_int(row.get("wall_ms"))
                if prev_ms is not None and wall_ms is not None and wall_ms >= prev_ms:
                    dt = (wall_ms - prev_ms) / 1000.0 / max(cur_speed, 0.1)
                    # Cap sleep so scrub stays responsive
                    dt = min(max(dt, 0.0), 2.0)
                    if dt > 0:
                        self._stop.wait(dt)
                elif prev_ms is not None:
                    self._stop.wait(0.05 / max(cur_speed, 0.1))
                prev_ms = wall_ms if wall_ms is not None else prev_ms

                if self._stop.is_set():
                    break

                seq = _to_int(row.get("seq"))
                if seq is None:
                    seq = seq_fallback
                seq_fallback = (seq + 1) & 0xFF

                wire = row_to_wire_bytes(row, vehicle_id, seq)
                if not wire:
                    continue
                try:
                    items = parser.feed(wire)
                    for item in items:
                        if not isinstance(item, RadioPacket):
                            continue
                        self.hub.ingest_radio_packet(
                            vehicle,
                            item,
                            {
                                "frames_ok": parser.stats.rcv_ok,
                                "frames_crc_error": parser.stats.rcv_malformed,
                                "frames_resynced": parser.oversize_resets,
                            },
                            logging_enabled=False,
                        )
                except Exception:
                    pass

                if i % 10 == 0:
                    self._emit_status()
        finally:
            with self._lock:
                self.status.running = False
                self.status.index = self.status.total
            try:
                self.hub.set_link_state(vehicle, "DISCONNECTED")
            except Exception:
                pass
            self._emit_status()


def build_log_row_from_state(
    vehicle: str,
    packet: RadioPacket,
    state: Any,
    wall_ms: int,
    type_name: str = "",
) -> Dict[str, Any]:
    """Flatten hub vehicle state + radio packet into a CSV row."""
    t = getattr(state, "telemetry", {}) or {}
    g = getattr(state, "gps", {}) or {}
    pred = getattr(state, "prediction", None) or {}
    events = list(getattr(state, "events", []) or [])
    event = events[0] if events else ""
    seq = t.get("packet_count", "")
    raw = (packet.raw_line or "").encode("utf-8", errors="replace")

    return {
        "wall_time_iso": _iso_now(),
        "wall_ms": wall_ms,
        "vehicle": vehicle,
        "phase": getattr(state, "phase", ""),
        "seq": seq,
        "packet_type": 1,
        "packet_type_name": type_name or "TELEMETRY",
        "raw_hex": raw.hex(" "),
        "csv": packet.data,
        "rssi": packet.rssi,
        "snr": packet.snr,
        "altitude_m": t.get("altitude_m", ""),
        "speed_mps": t.get("speed_mps", ""),
        "pitch": t.get("pitch", ""),
        "yaw": t.get("yaw", ""),
        "roll": t.get("roll", ""),
        "temperature_c": t.get("temperature_c", ""),
        "pressure_hpa": t.get("pressure_hpa", ""),
        "battery_v": t.get("battery_v", ""),
        "accel_x": t.get("accel_x", ""),
        "accel_y": t.get("accel_y", ""),
        "accel_z": t.get("accel_z", ""),
        "gyro_x": t.get("gyro_x", ""),
        "gyro_y": t.get("gyro_y", ""),
        "gyro_z": t.get("gyro_z", ""),
        "timestamp_ms": t.get("timestamp_ms", ""),
        "gps_lat": g.get("lat", ""),
        "gps_lon": g.get("lon", ""),
        "gps_alt_m": g.get("alt_m", ""),
        "gps_sats": g.get("sats", ""),
        "gps_hdop": g.get("hdop", ""),
        "gps_fix_type": g.get("fix_type", ""),
        "event": event,
        "prediction_lat": pred.get("lat", "") if pred else "",
        "prediction_lon": pred.get("lon", "") if pred else "",
        "prediction_eta_s": pred.get("eta_s", "") if pred else "",
        "prediction_confidence": pred.get("confidence", "") if pred else "",
        "link_state": getattr(state, "link_state", ""),
        "frames_ok": getattr(state, "frames_ok", ""),
        "frames_crc_error": getattr(state, "frames_crc_error", ""),
        "flight_software_state": t.get("flight_software_state", ""),
    }
