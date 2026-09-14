"""
Serial vehicle link — PySerial reader + FrameParser (PRD C.3 / Phase 11).

One SerialVehicleLink per vehicle. Auto-reconnect with backoff from config.
Malformed serial data never crashes the process. Bad ports keep retrying
without taking down the backend.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from app.config import DEFAULT_BAUD, RECONNECT_BACKOFF_S
from app.frame_parser import FrameParser
from app.protocol import RawFrame, vehicle_name

try:
    import serial
    from serial import SerialException
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    serial = None  # type: ignore
    SerialException = OSError  # type: ignore
    list_ports = None  # type: ignore

LinkStateCallback = Callable[[str, str], None]
FrameCallback = Callable[[str, RawFrame], None]

LINK_CONNECTED = "CONNECTED"
LINK_LOST = "LINK_LOST"
LINK_RECONNECTING = "RECONNECTING"
LINK_DISCONNECTED = "DISCONNECTED"


def list_available_ports() -> List[Dict[str, str]]:
    """Return [{device, description}, ...] for Settings / REST GET /ports."""
    if list_ports is None:
        return []
    out: List[Dict[str, str]] = []
    try:
        for p in list_ports.comports():
            out.append(
                {
                    "device": p.device or "",
                    "description": p.description or p.device or "",
                    "hwid": getattr(p, "hwid", "") or "",
                }
            )
    except Exception:
        return []
    return out


def port_exists(device: str) -> bool:
    """True if *device* appears in the current COM list (best-effort)."""
    if not device:
        return False
    try:
        for p in list_available_ports():
            if p.get("device") == device:
                return True
    except Exception:
        return False
    return False


def validate_port_arg(port: str) -> str:
    """Normalize/validate port string. Raises ValueError if unusable."""
    if port is None:
        raise ValueError("port is required")
    p = str(port).strip()
    if not p:
        raise ValueError("port is required")
    if len(p) > 128:
        raise ValueError("port name too long")
    if any(c in p for c in ("\x00", "\n", "\r")):
        raise ValueError("invalid port name")
    return p


class SerialVehicleLink:
    """
    Background-thread serial reader for one vehicle.

    Interface mirrors SimulatedVehicleLink:
      start() / stop() / is_running / parser
    """

    def __init__(
        self,
        vehicle_id: int,
        port: str,
        baud: int = DEFAULT_BAUD,
        on_frame_callback: Optional[FrameCallback] = None,
        on_link_state: Optional[LinkStateCallback] = None,
        read_interval_s: float = 0.02,
    ) -> None:
        self.vehicle_id = vehicle_id
        self.vehicle_key = vehicle_name(vehicle_id)
        self.port = validate_port_arg(port)
        try:
            self.baud = int(baud)
        except (TypeError, ValueError):
            self.baud = DEFAULT_BAUD
        if self.baud <= 0 or self.baud > 10_000_000:
            self.baud = DEFAULT_BAUD
        self._on_frame = on_frame_callback
        self._on_link_state = on_link_state
        self._read_interval_s = max(0.005, float(read_interval_s))
        self._parser = FrameParser()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = False
        self._ser: Any = None
        self._link_state = LINK_DISCONNECTED
        self.last_error: Optional[str] = None
        self.open_failures = 0
        self.reconnect_count = 0
        self.bytes_read = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def parser(self) -> FrameParser:
        return self._parser

    @property
    def link_state(self) -> str:
        return self._link_state

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "port": self.port,
            "baud": self.baud,
            "link_state": self._link_state,
            "last_error": self.last_error,
            "open_failures": self.open_failures,
            "reconnect_count": self.reconnect_count,
            "bytes_read": self.bytes_read,
            "frames_ok": self._parser.frames_ok,
            "frames_crc_error": self._parser.frames_crc_error,
            "frames_resynced": self._parser.frames_resynced,
            "port_present": port_exists(self.port),
        }

    def start(self) -> None:
        if self._running:
            return
        if serial is None:
            self.last_error = "pyserial is not installed"
            raise RuntimeError(self.last_error)
        self._stop.clear()
        self._parser.reset()
        # Keep CRC counters across reconnects so Packet Monitor stays honest,
        # but reset stream state.
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"serial-{self.vehicle_key}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._close_port()
        was = self._running
        self._running = False
        if was:
            self._set_link(LINK_DISCONNECTED)

    def _set_link(self, state: str) -> None:
        if self._link_state == state:
            # Still notify RECONNECTING periodically? skip duplicate
            if state != LINK_RECONNECTING:
                return
        self._link_state = state
        if self._on_link_state:
            try:
                self._on_link_state(self.vehicle_key, state)
            except Exception:
                pass

    def _close_port(self) -> None:
        ser = self._ser
        self._ser = None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def _open_port(self) -> bool:
        self._close_port()
        try:
            if serial is None:
                self.last_error = "pyserial is not installed"
                self.open_failures += 1
                return False
            self._ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=0.05,
                write_timeout=0.05,
            )
            try:
                self._ser.reset_input_buffer()
            except Exception:
                pass
            # Only reset framing state, keep global CRC counters
            self._parser.reset()
            self.last_error = None
            if self.reconnect_count > 0 or self.open_failures > 0:
                self.reconnect_count += 1
            self._set_link(LINK_CONNECTED)
            return True
        except Exception as exc:
            self._ser = None
            self.open_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def _run_loop(self) -> None:
        backoff_idx = 0
        try:
            while not self._stop.is_set():
                if self._ser is None or not getattr(self._ser, "is_open", False):
                    self._set_link(LINK_RECONNECTING)
                    if self._open_port():
                        backoff_idx = 0
                    else:
                        # Bad / missing port: stay alive, back off, never crash
                        delay = RECONNECT_BACKOFF_S[
                            min(backoff_idx, len(RECONNECT_BACKOFF_S) - 1)
                        ]
                        backoff_idx += 1
                        self._stop.wait(delay)
                    continue

                try:
                    n = getattr(self._ser, "in_waiting", 0) or 0
                    # Cap read size so a flood cannot balloon memory
                    if n > 0:
                        chunk = self._ser.read(min(int(n), 8192))
                    else:
                        chunk = self._ser.read(256)
                    if chunk:
                        self.bytes_read += len(chunk)
                        self._handle_bytes(chunk)
                except SerialException as exc:
                    self.last_error = f"SerialException: {exc}"
                    self._close_port()
                    self._set_link(LINK_LOST)
                    backoff_idx = 0
                    self._stop.wait(RECONNECT_BACKOFF_S[0])
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self._close_port()
                    self._set_link(LINK_LOST)
                    self._stop.wait(RECONNECT_BACKOFF_S[0])

                self._stop.wait(self._read_interval_s)
        except Exception as exc:
            # Absolute last resort — thread must not kill the process
            self.last_error = f"run_loop: {type(exc).__name__}: {exc}"
        finally:
            self._close_port()
            self._running = False
            if not self._stop.is_set():
                self._set_link(LINK_LOST)
            else:
                self._set_link(LINK_DISCONNECTED)

    def _handle_bytes(self, data: bytes) -> None:
        try:
            frames = self._parser.feed(data)
        except Exception:
            # Parser must never raise; if it does, reset framing only
            try:
                self._parser.reset()
            except Exception:
                pass
            return
        if not self._on_frame:
            return
        for fr in frames:
            try:
                self._on_frame(self.vehicle_key, fr)
            except Exception:
                pass
