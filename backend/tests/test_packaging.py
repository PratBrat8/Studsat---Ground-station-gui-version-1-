"""Phase 14 — packaging spec, scripts, and version contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import APP_VERSION, app

REQUIRED_HIDDEN = (
    "app.trajectory",
    "app.radio_transport",
    "app.command_manager",
    "app.power",
    "app.protocol",
    "app.simulator",
    "app.telemetry_hub",
    "app.serial_manager",
    "serial.tools.list_ports",
)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_health_phase14(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["prd_version"] == 2
    assert body["v2_phase"] == 14
    assert body["version"] == "2.0.0-phase14"
    assert APP_VERSION == "2.0.0-phase14"
    assert "frozen" in body
    assert isinstance(body["frozen"], bool)


def test_pyinstaller_spec_lists_v2_modules():
    spec = (_BACKEND / "build_backend.spec").read_text(encoding="utf-8")
    for name in REQUIRED_HIDDEN:
        assert name in spec, f"missing hiddenimport {name}"
    assert "cadquery" in spec
    assert "excludes" in spec
    assert "studsat-backend" in spec
    assert "console=True" in spec or "console = True" in spec


def test_package_scripts_exist():
    assert (_BACKEND / "scripts" / "build_backend.ps1").is_file()
    assert (_REPO / "scripts" / "package-windows.ps1").is_file()
    assert (_REPO / "docs" / "PACKAGING.md").is_file()


def test_electron_builder_config_v2():
    pkg = json.loads((_REPO / "electron" / "package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == "2.0.0"
    extra = pkg["build"]["extraResources"]
    froms = [item["from"] for item in extra]
    tos = [item["to"] for item in extra]
    assert "../backend/dist/studsat-backend.exe" in froms
    assert "backend/studsat-backend.exe" in tos
    assert "../frontend/dist" in froms
    assert "frontend" in tos
    assert "../tiles" in froms
    assert "tiles" in tos
    nsis = pkg["build"]["nsis"]["artifactName"]
    assert "${version}" in nsis
    assert "Setup" in nsis
