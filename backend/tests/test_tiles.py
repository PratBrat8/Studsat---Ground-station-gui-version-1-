"""Phase 6 — offline tile server tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient

from app.main import app
from app.tile_server import make_solid_png, resolve_tile_path
from app.config import TILES_DIR


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_tiles_info(client: TestClient):
    r = client.get("/tiles/info")
    assert r.status_code == 200
    body = r.json()
    assert "tiles_dir" in body
    assert body["url_template"] == "/tiles/{z}/{x}/{y}.png"
    assert "tile_file_count" in body


def test_placeholder_tile_png(client: TestClient):
    # High z unlikely to have real files → placeholder path
    r = client.get("/tiles/18/1/1.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert r.headers.get("x-studsat-tile") == "placeholder"
    assert len(r.content) > 100


def test_make_solid_png_header():
    png = make_solid_png((30, 40, 50), size=16, grid=False)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in png
    assert b"IEND" in png


def test_real_file_served_when_present(client: TestClient, tmp_path, monkeypatch):
    # Write a tiny real tile into TILES_DIR
    z, x, y = 10, 500, 300
    dest = TILES_DIR / str(z) / str(x)
    dest.mkdir(parents=True, exist_ok=True)
    png = make_solid_png((10, 20, 30), size=8, grid=False)
    path = dest / f"{y}.png"
    path.write_bytes(png)
    try:
        assert resolve_tile_path(z, x, y) == path
        r = client.get(f"/tiles/{z}/{x}/{y}.png")
        assert r.status_code == 200
        assert r.content == png
        # Real file — not marked placeholder
        assert r.headers.get("x-studsat-tile") != "placeholder"
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def test_health_phase6(client: TestClient):
    body = client.get("/health").json()
    assert body["phase"] >= 6
