"""
Incremental byte-stream → validated RawFrame parser (PRD C.2 / C.3).

Pure state machine: feed(bytes) -> list[RawFrame]. No I/O.
Malformed frames never raise — they increment counters and resync.
"""
from __future__ import annotations

import struct
from collections import deque
from enum import Enum, auto
from typing import Deque, List, Optional

from app.protocol import (
    CRC_SIZE,
    HEADER_SIZE,
    MAX_PAYLOAD_LEN,
    SYNC0,
    SYNC1,
    RawFrame,
    crc16_ccitt,
)


class _State(Enum):
    WAIT_SYNC0 = auto()
    WAIT_SYNC1 = auto()
    HEADER = auto()
    PAYLOAD = auto()
    CRC = auto()


class FrameParser:
    """
    Streaming frame framer.

    Counters (surfaced to Packet Monitor in Phase 8):
      frames_ok, frames_crc_error, frames_resynced
    """

    def __init__(self) -> None:
        self._state = _State.WAIT_SYNC0
        self._crc_buf = bytearray()
        self._vehicle_id = 0
        self._packet_type = 0
        self._seq = 0
        self._payload_len = 0
        self._payload = bytearray()
        self._header = bytearray()
        self._frame_prefix = bytearray()  # sync + header + payload
        # Extra bytes to process after a resync (iterative, not recursive)
        self._inject: Deque[int] = deque()

        self.frames_ok = 0
        self.frames_crc_error = 0
        self.frames_resynced = 0

    def reset(self) -> None:
        """Clear parser state (not counters, not inject queue)."""
        self._state = _State.WAIT_SYNC0
        self._crc_buf.clear()
        self._payload.clear()
        self._header.clear()
        self._frame_prefix.clear()
        self._payload_len = 0

    def reset_counters(self) -> None:
        self.frames_ok = 0
        self.frames_crc_error = 0
        self.frames_resynced = 0

    def feed(self, data: bytes | bytearray | memoryview) -> List[RawFrame]:
        """
        Consume available bytes; return zero or more validated frames.
        Safe against corrupt input — never raises on bad serial data.
        """
        out: List[RawFrame] = []
        if not data and not self._inject:
            return out

        try:
            # Merge injected resync bytes with new data into one walk.
            stream: Deque[int] = self._inject
            self._inject = deque()
            for byte in data:
                stream.append(byte & 0xFF)

            while stream:
                b = stream.popleft()
                frame = self._step(b, stream)
                if frame is not None:
                    out.append(frame)
        except Exception:
            self.frames_resynced += 1
            self.reset()
            self._inject.clear()
        return out

    def _step(self, b: int, stream: Deque[int]) -> Optional[RawFrame]:
        """Advance one byte. May prepend leftover bytes onto *stream* on resync."""
        if self._state == _State.WAIT_SYNC0:
            if b == SYNC0:
                self._frame_prefix = bytearray([SYNC0])
                self._state = _State.WAIT_SYNC1
            return None

        if self._state == _State.WAIT_SYNC1:
            if b == SYNC1:
                self._frame_prefix.append(SYNC1)
                self._header.clear()
                self._state = _State.HEADER
            elif b == SYNC0:
                self._frame_prefix = bytearray([SYNC0])
                self.frames_resynced += 1
            else:
                self._frame_prefix.clear()
                self._state = _State.WAIT_SYNC0
                self.frames_resynced += 1
            return None

        if self._state == _State.HEADER:
            self._header.append(b)
            self._frame_prefix.append(b)
            if len(self._header) < HEADER_SIZE:
                return None
            self._vehicle_id = self._header[0]
            self._packet_type = self._header[1]
            self._seq = self._header[2]
            self._payload_len = self._header[3]
            if self._payload_len > MAX_PAYLOAD_LEN:
                # Should be impossible (u8 max 255 == MAX), keep defensive path.
                self.frames_resynced += 1
                leftover = list(self._frame_prefix[1:])
                self.reset()
                for lb in reversed(leftover):
                    stream.appendleft(lb)
                return None
            self._payload.clear()
            if self._payload_len == 0:
                self._crc_buf.clear()
                self._state = _State.CRC
            else:
                self._state = _State.PAYLOAD
            return None

        if self._state == _State.PAYLOAD:
            self._payload.append(b)
            self._frame_prefix.append(b)
            if len(self._payload) < self._payload_len:
                return None
            self._crc_buf.clear()
            self._state = _State.CRC
            return None

        if self._state == _State.CRC:
            self._crc_buf.append(b)
            if len(self._crc_buf) < CRC_SIZE:
                return None

            received_crc = struct.unpack("<H", bytes(self._crc_buf))[0]
            body = bytes(self._header) + bytes(self._payload)
            expected_crc = crc16_ccitt(body)
            full_raw = bytes(self._frame_prefix) + bytes(self._crc_buf)

            if received_crc == expected_crc:
                self.frames_ok += 1
                frame = RawFrame(
                    vehicle_id=self._vehicle_id,
                    packet_type=self._packet_type,
                    seq=self._seq,
                    payload=bytes(self._payload),
                    raw_bytes=full_raw,
                )
                self.reset()
                return frame

            # CRC mismatch: drop frame, rescan from byte after initial SYNC0
            self.frames_crc_error += 1
            self.frames_resynced += 1
            leftover = list(full_raw[1:])
            self.reset()
            for lb in reversed(leftover):
                stream.appendleft(lb)
            return None

        self.reset()
        return None
