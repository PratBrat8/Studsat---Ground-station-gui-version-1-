"""Phase 11 — Command Console REST: TX OFF confirm, ST clock, command log."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_health_phase11(client: TestClient):
    body = client.get("/health").json()
    assert body["v2_phase"] >= 11


def test_tx_off_requires_confirmed(client: TestClient):
    client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    r = client.post("/command", json={"vehicle": "rocket", "type": "TX", "on": False})
    assert r.status_code == 403
    r2 = client.post(
        "/command",
        json={"vehicle": "rocket", "type": "TX", "on": False, "confirmed": True},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["command"] == "CMD,XXXX,TX,OFF"
    assert body["status"] in ("SENT", "TRANSMITTED")
    assert body.get("note") != "ACKED"
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})


def test_set_time_and_calibrate_in_log(client: TestClient):
    client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    st = client.post(
        "/command",
        json={"vehicle": "rocket", "type": "ST", "utc_time": "08:15:30"},
    )
    assert st.status_code == 200
    assert st.json()["command"] == "CMD,XXXX,ST,08:15:30"
    cg = client.post("/command", json={"vehicle": "rocket", "type": "CG"})
    assert cg.status_code == 200
    assert cg.json()["command"] == "CMD,XXXX,CG,R"
    listed = client.get("/commands?vehicle=rocket&limit=20").json()["commands"]
    kinds = [c["type"] for c in listed]
    assert "ST" in kinds
    assert "CG" in kinds
    assert all(c["status"] != "ACKED" for c in listed)
    assert all("sent_at" in c for c in listed)
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})


def test_ej_still_forbidden_without_confirm(client: TestClient):
    client.post("/simulate", json={"vehicle": "rocket", "enabled": True})
    r = client.post("/command", json={"vehicle": "rocket", "type": "EJ"})
    assert r.status_code == 403
    client.post("/simulate", json={"vehicle": "rocket", "enabled": False})
