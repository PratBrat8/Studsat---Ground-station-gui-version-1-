"""Reyax AT transport — +RCV / AT+SEND / +OK / +ERR (PRD v2 Phase 2)."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.radio_transport import (
    MalformedRadioLine,
    ModuleErr,
    ModuleOk,
    RadioLineBuffer,
    RadioPacket,
    build_send_command,
    classify_radio_line,
    format_rcv_line,
    parse_module_response,
    parse_rcv_line,
)

CSV = (
    "XXXX,00:00:01,1,12.50,1013.25,21.40,7.80,"
    "00:00:01,12.971600,77.594600,932.50,9,"
    "0.100,-0.200,9.810,1.000,2.000,0.500,2"
)


def test_parse_rcv_with_commas_in_payload():
    line = format_rcv_line(1, CSV, -72, 9.5)
    pkt = parse_rcv_line(line)
    assert pkt is not None
    assert pkt.address == 1
    assert pkt.data == CSV
    assert pkt.rssi == -72
    assert pkt.snr == 9.5
    assert CSV.count(",") == 18  # 19 fields


def test_parse_rcv_rejects_wrong_length():
    # Claim length 4 but payload is longer — remaining is not ,rssi,snr
    line = "+RCV=1,4,HELLO,-70,8.0\r\n"
    assert parse_rcv_line(line) is None


def test_parse_rcv_rejects_truncated():
    assert parse_rcv_line("+RCV=1,5,HEL") is None
    assert parse_rcv_line("junk") is None
    assert parse_rcv_line("") is None


def test_build_send_command_length_matches_payload():
    payload = "CMD,XXXX,TX,ON"
    wire = build_send_command(1, payload)
    assert wire.endswith(b"\r\n")
    text = wire.decode("utf-8").strip()
    assert text.startswith("AT+SEND=1,")
    # AT+SEND=<addr>,<len>,<data>
    body = text[len("AT+SEND=") :]
    addr_s, rest = body.split(",", 1)
    len_s, data = rest.split(",", 1)
    assert int(addr_s) == 1
    assert int(len_s) == len(payload.encode("utf-8"))
    assert data == payload


def test_module_ok_and_err():
    assert isinstance(parse_module_response("+OK\r\n"), ModuleOk)
    err = parse_module_response("+ERR=1\r\n")
    assert isinstance(err, ModuleErr)
    assert err.code == "1"
    assert parse_module_response("+RCV=1,1,A,-1,0") is None


def test_line_buffer_splits_across_feeds():
    line = format_rcv_line(3, CSV, -80, 4.25)
    raw = line.encode("utf-8")
    mid = len(raw) // 2
    buf = RadioLineBuffer()
    first = buf.feed(raw[:mid])
    assert first == []
    second = buf.feed(raw[mid:])
    assert len(second) == 1
    assert isinstance(second[0], RadioPacket)
    assert second[0].data == CSV
    assert second[0].address == 3
    assert buf.stats.rcv_ok == 1
    assert buf.stats.rcv_malformed == 0


def test_line_buffer_ok_and_bad_together():
    buf = RadioLineBuffer()
    blob = b"+OK\r\n+ERR=5\r\n+RCV=not-a-packet\r\n"
    items = buf.feed(blob)
    kinds = [type(x) for x in items]
    assert ModuleOk in kinds
    assert ModuleErr in kinds
    assert MalformedRadioLine in kinds
    assert RadioPacket not in kinds
    assert buf.stats.ok_responses == 1
    assert buf.stats.err_responses == 1
    assert buf.stats.rcv_malformed == 1


def test_classify_unknown():
    bad = classify_radio_line("+READY")
    assert isinstance(bad, MalformedRadioLine)
    assert bad.reason == "unknown"


def test_classify_malformed_rcv_emits_event():
    bad = classify_radio_line("+RCV=not-a-packet")
    assert isinstance(bad, MalformedRadioLine)
    assert bad.reason == "malformed_rcv"
