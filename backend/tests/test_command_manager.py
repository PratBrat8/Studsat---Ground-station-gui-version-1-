"""Uplink command manager unit tests (PRD v2 Phase 3)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.command_manager import CommandManager, STATUS_NO_RESPONSE, STATUS_TRANSMITTED
from app.radio_transport import ModuleOk, build_send_command


def test_sent_then_ok_is_transmitted(tmp_path):
    written = []

    def writer(data: bytes) -> bool:
        written.append(data)
        return True

    mgr = CommandManager(logs_dir=tmp_path, timeout_s=1.0, rate_limit_s=0.0)
    mgr.set_writer("rocket", writer)
    rec = mgr.send_command("rocket", "TX", on=True)
    assert rec["status"] == "SENT"
    assert written and written[0].startswith(b"AT+SEND=")
    mgr.on_module_response("rocket", ModuleOk())
    got = mgr.get_command(rec["id"])
    assert got["status"] == STATUS_TRANSMITTED
    assert got["note"] == "transmitted, not confirmed by vehicle"
    mgr.close()


def test_fail_inflight_marks_no_response(tmp_path):
    mgr = CommandManager(logs_dir=tmp_path, timeout_s=30.0, rate_limit_s=0.0)
    mgr.set_writer("rocket", lambda _b: True)
    rec = mgr.send_command("rocket", "TX", on=True)
    assert rec["status"] == "SENT"
    mgr.fail_inflight("rocket", "link lost")
    got = mgr.get_command(rec["id"])
    assert got["status"] == STATUS_NO_RESPONSE
    assert "link lost" in (got["error"] or "")
    mgr.fail_inflight("rocket", "again")
    assert mgr.get_command(rec["id"])["status"] == STATUS_NO_RESPONSE
    mgr.close()


def test_timeout_is_no_response(tmp_path):
    mgr = CommandManager(logs_dir=tmp_path, timeout_s=0.15, rate_limit_s=0.0)
    mgr.set_writer("rocket", lambda _b: True)
    rec = mgr.send_command("rocket", "CG")
    time.sleep(0.35)
    got = mgr.get_command(rec["id"])
    assert got["status"] == STATUS_NO_RESPONSE
    mgr.close()


def test_rate_limit(tmp_path):
    mgr = CommandManager(logs_dir=tmp_path, timeout_s=2.0, rate_limit_s=3.0)
    mgr.set_writer("rocket", lambda _b: True)
    mgr.send_command("rocket", "CA")
    mgr.on_module_response("rocket", ModuleOk())
    with pytest.raises(RuntimeError, match="rate limited"):
        mgr.send_command("rocket", "CA")
    mgr.close()


def test_tx_off_requires_confirm(tmp_path):
    mgr = CommandManager(logs_dir=tmp_path, rate_limit_s=0.0)
    mgr.set_writer("rocket", lambda _b: True)
    with pytest.raises(PermissionError, match="TX OFF"):
        mgr.send_command("rocket", "TX", on=False, confirmed=False)
    rec = mgr.send_command("rocket", "TX", on=False, confirmed=True)
    assert rec["command"] == "CMD,XXXX,TX,OFF"
    mgr.close()


def test_set_time_uses_supplied_utc(tmp_path):
    mgr = CommandManager(logs_dir=tmp_path, rate_limit_s=0.0)
    mgr.set_writer("rocket", lambda _b: True)
    rec = mgr.send_command("rocket", "ST", utc_time="12:34:56")
    assert rec["command"] == "CMD,XXXX,ST,12:34:56"
    mgr.close()


def test_ej_gates(tmp_path):
    mgr = CommandManager(logs_dir=tmp_path, rate_limit_s=0.0)
    mgr.set_writer("rocket", lambda _b: True)
    mgr.set_writer("satellite", lambda _b: True)
    with pytest.raises(PermissionError):
        mgr.send_command("rocket", "EJ", confirmed=False)
    with pytest.raises(ValueError, match="Rocket"):
        mgr.send_command("satellite", "EJ", confirmed=True)
    rec = mgr.send_command("rocket", "EJ", confirmed=True)
    assert rec["command"] == "CMD,XXXX,EJ,R"
    mgr.close()


def test_build_send_wraps_cmd():
    wire = build_send_command(1, "CMD,XXXX,TX,ON")
    assert b"AT+SEND=1," in wire
    assert b"CMD,XXXX,TX,ON" in wire
