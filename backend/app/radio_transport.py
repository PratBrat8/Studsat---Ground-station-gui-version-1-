"""
Reyax RYLR993 AT transport layer (PRD v2 C.2).

This module is the radio envelope only. It does not know about competition
CSV telemetry or CMD strings — those live in protocol.py.

Receiving:
  +RCV=<address>,<length>,<data>,<rssi>,<snr>\\r\\n

Sending:
  AT+SEND=<address>,<length>,<data>\\r\\n

Module responses:
  +OK\\r\\n
  +ERR=<code>\\r\\n

<length> is the byte length of <data>. Data may itself contain commas
(the competition CSV), so parsers MUST slice by length, never split the
whole line on commas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Union


RCV_PREFIX = "+RCV="
SEND_PREFIX = "AT+SEND="
OK_LINE = "+OK"
ERR_PREFIX = "+ERR="


@dataclass(frozen=True, slots=True)
class RadioPacket:
    """One successfully parsed +RCV= downlink."""

    address: int
    data: str
    rssi: int
    snr: float
    raw_line: str = ""


@dataclass(frozen=True, slots=True)
class ModuleOk:
    raw_line: str = OK_LINE


@dataclass(frozen=True, slots=True)
class ModuleErr:
    code: str
    raw_line: str = ""


@dataclass(frozen=True, slots=True)
class MalformedRadioLine:
    """Transport-layer line that did not parse as +RCV / +OK / +ERR."""

    raw_line: str
    reason: str  # malformed_rcv | unknown | oversize


RadioLine = Union[RadioPacket, ModuleOk, ModuleErr, MalformedRadioLine]


@dataclass
class TransportStats:
    rcv_ok: int = 0
    rcv_malformed: int = 0
    ok_responses: int = 0
    err_responses: int = 0
    unknown_lines: int = 0

    def reset(self) -> None:
        self.rcv_ok = 0
        self.rcv_malformed = 0
        self.ok_responses = 0
        self.err_responses = 0
        self.unknown_lines = 0


def _as_bytes(line: Union[str, bytes]) -> bytes:
    if isinstance(line, bytes):
        return line
    return line.encode("utf-8")


def _as_text(line: Union[str, bytes]) -> str:
    if isinstance(line, str):
        return line
    return line.decode("utf-8", errors="replace")


def format_rcv_line(
    address: int,
    data: str,
    rssi: int,
    snr: float,
) -> str:
    """Build a +RCV= line (used by the simulator and unit tests)."""
    payload = data.encode("utf-8")
    # SNR printed without trailing junk; int-like floats stay readable.
    snr_s = f"{snr:g}"
    return f"{RCV_PREFIX}{int(address)},{len(payload)},{data},{int(rssi)},{snr_s}\r\n"


def build_send_command(address: int, payload: str) -> bytes:
    """Wrap an application-layer string in AT+SEND= for the Reyax UART."""
    encoded = payload.encode("utf-8")
    line = f"{SEND_PREFIX}{int(address)},{len(encoded)},{payload}\r\n"
    return line.encode("utf-8")


def parse_rcv_line(line: Union[str, bytes]) -> Optional[RadioPacket]:
    """
    Parse one +RCV= line. Returns None on mismatch (never raises).

    Length-based slice so CSV commas inside <data> are not field separators.
    """
    raw_text = _as_text(line).strip("\r\n")
    raw = _as_bytes(raw_text)
    prefix = RCV_PREFIX.encode("ascii")
    if not raw.startswith(prefix):
        return None
    body = raw[len(prefix) :]
    p1 = body.find(b",")
    if p1 <= 0:
        return None
    p2 = body.find(b",", p1 + 1)
    if p2 < 0:
        return None
    try:
        address = int(body[:p1])
        length = int(body[p1 + 1 : p2])
    except ValueError:
        return None
    if length < 0 or length > 4096:
        return None
    data_start = p2 + 1
    data = body[data_start : data_start + length]
    if len(data) != length:
        return None
    rest = body[data_start + length :]
    if not rest.startswith(b","):
        return None
    rest = rest[1:]
    split = rest.rfind(b",")
    if split < 0:
        return None
    try:
        rssi = int(rest[:split].strip())
        snr = float(rest[split + 1 :].strip())
    except ValueError:
        return None
    try:
        data_str = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return RadioPacket(
        address=address,
        data=data_str,
        rssi=rssi,
        snr=snr,
        raw_line=raw_text,
    )


def parse_module_response(line: Union[str, bytes]) -> Optional[Union[ModuleOk, ModuleErr]]:
    """Parse +OK / +ERR=<code>. Returns None if the line is neither."""
    text = _as_text(line).strip("\r\n")
    if text == OK_LINE:
        return ModuleOk(raw_line=text)
    if text.startswith(ERR_PREFIX):
        return ModuleErr(code=text[len(ERR_PREFIX) :], raw_line=text)
    return None


def classify_radio_line(
    line: Union[str, bytes],
    stats: Optional[TransportStats] = None,
) -> Optional[RadioLine]:
    """Dispatch one stripped radio line to packet / OK / ERR / malformed."""
    text = _as_text(line).strip("\r\n")
    if not text:
        return None
    if text.startswith(RCV_PREFIX):
        pkt = parse_rcv_line(text)
        if pkt is None:
            if stats is not None:
                stats.rcv_malformed += 1
            return MalformedRadioLine(raw_line=text, reason="malformed_rcv")
        if stats is not None:
            stats.rcv_ok += 1
        return pkt
    resp = parse_module_response(text)
    if resp is None:
        if stats is not None:
            stats.unknown_lines += 1
        return MalformedRadioLine(raw_line=text, reason="unknown")
    if stats is not None:
        if isinstance(resp, ModuleOk):
            stats.ok_responses += 1
        else:
            stats.err_responses += 1
    return resp


class RadioLineBuffer:
    """
    Incremental UART → complete lines.

    feed(bytes) -> list of decoded line strings (without CR/LF).
    Partial lines stay buffered. Malformed bytes never raise.
    """

    def __init__(self, max_line_bytes: int = 4096) -> None:
        self._buf = bytearray()
        self._max = max_line_bytes
        self.stats = TransportStats()
        self.oversize_resets = 0

    def reset(self) -> None:
        self._buf.clear()

    def reset_counters(self) -> None:
        self.stats.reset()
        self.oversize_resets = 0

    def feed(self, chunk: bytes) -> List[RadioLine]:
        if not chunk:
            return []
        self._buf.extend(chunk)
        out: List[RadioLine] = []
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                if len(self._buf) > self._max:
                    snippet = bytes(self._buf[:80]).decode("utf-8", errors="replace")
                    self._buf.clear()
                    self.oversize_resets += 1
                    self.stats.rcv_malformed += 1
                    out.append(
                        MalformedRadioLine(raw_line=snippet, reason="oversize")
                    )
                break
            raw_line = bytes(self._buf[: nl + 1])
            del self._buf[: nl + 1]
            try:
                classified = classify_radio_line(raw_line, self.stats)
            except Exception:
                snippet = raw_line.decode("utf-8", errors="replace").strip("\r\n")
                self.stats.unknown_lines += 1
                classified = MalformedRadioLine(raw_line=snippet, reason="unknown")
            if classified is not None:
                out.append(classified)
        return out
