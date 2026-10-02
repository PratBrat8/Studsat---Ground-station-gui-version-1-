"""Phase 10 — Packet Monitor RSSI/SNR + transport vs application errors."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import app
from app.protocol import FlightState, TelemetryRecord, format_telemetry_csv
from app.radio_transport import (
    MalformedRadioLine,
    ModuleErr,
    ModuleOk,
    RadioLineBuffer,
    format_rcv_line,
    parse_rcv_line,
)
from app.telemetry_hub import TelemetryHub


def _good_pkt(count=1, rssi=-72, snr=9.5):
    rec = TelemetryRecord(
        team_id="XXXX",
        timestamp="00:00:01",
        packet_count=count,
        altitude_m=100.5,
        pressure=980.0,
        temp_c=21.0,
        voltage=7.6,
        gnss_time="00:00:01",
        gnss_lat=12.9716,
        gnss_lon=77.5946,
        gnss_alt_m=932.5,
        gnss_sats=9,
        accel_x=0.0,
        accel_y=0.0,
        accel_z=9.8,
        gyro_x=0.0,
        gyro_y=0.0,
        gyro_z=0.0,
        flight_software_state=int(FlightState.LAUNCH_PAD),
    )
    return parse_rcv_line(format_rcv_line(1, format_telemetry_csv(rec), rssi, snr))


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_health_phase10(client: TestClient):
    body = client.get("/health").json()
    assert body["v2_phase"] >= 10


def test_good_rcv_exposes_rssi_snr_and_application_layer():
    hub = TelemetryHub()
    pkt = _good_pkt()
    assert pkt is not None
    hub.ingest_radio_packet(
        "rocket",
        pkt,
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    snap = hub.packets_snapshot("rocket")
    assert snap["frames_ok"] == 1
    assert snap["rssi"] == -72
    assert snap["snr"] == pytest.approx(9.5)
    assert snap["app_parse_error"] == 0
    assert snap["transport_malformed"] == 0
    rec = snap["recent"][0]
    assert rec["ok"] is True
    assert rec["layer"] == "application"
    assert rec["rssi"] == -72
    assert rec["snr"] == pytest.approx(9.5)
    assert rec["fields"]["altitude_m"] == pytest.approx(100.5, rel=1e-3)
    assert rec["hex"]
    ws = hub.latest_state("rocket")
    assert ws["packets"]["rssi"] == -72
    assert ws["packets"]["app_parse_error"] == 0


def test_malformed_rcv_is_transport_not_csv():
    hub = TelemetryHub()
    buf = RadioLineBuffer()
    items = buf.feed(b"+RCV=not-a-packet\r\n")
    assert len(items) == 1
    assert isinstance(items[0], MalformedRadioLine)
    hub.ingest_radio_event(
        "rocket",
        items[0],
        {
            "frames_ok": buf.stats.rcv_ok,
            "frames_crc_error": buf.stats.rcv_malformed,
            "frames_resynced": buf.oversize_resets,
            "transport_err": buf.stats.err_responses,
            "transport_unknown": buf.stats.unknown_lines,
        },
    )
    snap = hub.packets_snapshot("rocket")
    assert snap["transport_malformed"] == 1
    assert snap["frames_crc_error"] == 1
    assert snap["app_parse_error"] == 0
    rec = snap["recent"][0]
    assert rec["ok"] is False
    assert rec["layer"] == "transport"
    assert rec["type_name"] == "MALFORMED"


def test_csv_fail_is_application_not_transport():
    hub = TelemetryHub()
    pkt = parse_rcv_line(format_rcv_line(1, "too,few,fields", -60, 4.0))
    assert pkt is not None
    hub.ingest_radio_packet(
        "rocket",
        pkt,
        {"frames_ok": 1, "frames_crc_error": 0, "frames_resynced": 0},
    )
    snap = hub.packets_snapshot("rocket")
    assert snap["frames_ok"] == 1
    assert snap["transport_malformed"] == 0
    assert snap["frames_crc_error"] == 0
    assert snap["app_parse_error"] == 1
    assert snap["app_field_count_error"] == 1
    rec = snap["recent"][0]
    assert rec["ok"] is False
    assert rec["layer"] == "application"
    assert rec["error"] == "csv field count"
    assert rec["rssi"] == -60


def test_module_err_counts_as_transport():
    hub = TelemetryHub()
    hub.ingest_radio_event("rocket", ModuleErr(code="1", raw_line="+ERR=1"))
    hub.ingest_radio_event("rocket", ModuleOk(raw_line="+OK"))
    snap = hub.packets_snapshot("rocket")
    assert snap["transport_err"] == 1
    assert snap["transport_ok"] == 1
    assert snap["app_parse_error"] == 0
    kinds = [r["type_name"] for r in snap["recent"]]
    assert "+OK" in kinds
    assert "+ERR" in kinds
    err = next(r for r in snap["recent"] if r["type_name"] == "+ERR")
    assert err["layer"] == "transport"
    assert err["ok"] is False


def test_packets_http_has_layer_counters(client: TestClient):
    r = client.get("/packets/rocket")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "rssi",
        "snr",
        "transport_malformed",
        "transport_err",
        "app_parse_error",
        "app_field_count_error",
        "app_type_error",
    ):
        assert key in body
