"""
Offline XYZ map tile serving (PRD B.2 / C.3 / Phase 6).

Serves pre-downloaded tiles from TILES_DIR as:
  GET /tiles/{z}/{x}/{y}.png

If a tile file is missing, returns a generated placeholder PNG so the map
still works fully offline without an internet tile provider. Replace the
tiles/ tree with a real OSM/MapTiler XYZ export for the launch site before
competition day.
"""
from __future__ import annotations

import struct
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.config import TILES_DIR

router = APIRouter(tags=["tiles"])

# ---------------------------------------------------------------------------
# Minimal PNG writer (no Pillow) — 256×256 RGB tiles
# ---------------------------------------------------------------------------
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_solid_png(
    rgb: Tuple[int, int, int],
    size: int = 256,
    grid: bool = True,
    label_hint: Optional[Tuple[int, int, int]] = None,
) -> bytes:
    """Build a small solid-color (optional grid) PNG tile."""
    r, g, b = rgb
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter=None
        for x in range(size):
            pr, pg, pb = r, g, b
            if grid and (x == 0 or y == 0 or x == size - 1 or y == size - 1):
                pr, pg, pb = min(255, r + 40), min(255, g + 40), min(255, b + 40)
            elif grid and (x % 64 == 0 or y % 64 == 0):
                pr, pg, pb = min(255, r + 18), min(255, g + 18), min(255, b + 18)
            row.extend((pr, pg, pb))
        rows.append(bytes(row))
    raw = b"".join(rows)
    # label_hint unused in pixel draw (kept for future text tiles)
    _ = label_hint
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 6))
        + _png_chunk(b"IEND", b"")
    )


@lru_cache(maxsize=64)
def _placeholder_tile(z: int, x: int, y: int) -> bytes:
    """
    Deterministic offline placeholder. Slight color variation by tile index
    so empty regions still read as a map grid, not a solid void.
    """
    # Earthy blue-gray palette, shift with z/x/y
    base_r = 28 + (x * 3 + z * 5) % 40
    base_g = 40 + (y * 2 + z * 3) % 35
    base_b = 52 + (x + y + z) % 45
    return make_solid_png((base_r, base_g, base_b), size=256, grid=True)


def resolve_tile_path(z: int, x: int, y: int) -> Optional[Path]:
    """Return path if a real tile file exists under TILES_DIR."""
    # Standard XYZ: tiles/{z}/{x}/{y}.png
    candidates = [
        TILES_DIR / str(z) / str(x) / f"{y}.png",
        TILES_DIR / str(z) / str(x) / f"{y}.PNG",
        TILES_DIR / str(z) / str(x) / f"{y}.jpg",
        TILES_DIR / str(z) / str(x) / f"{y}.jpeg",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def count_tiles(root: Path = TILES_DIR) -> int:
    if not root.is_dir():
        return 0
    n = 0
    for p in root.rglob("*"):
        if p.suffix.lower() in {".png", ".jpg", ".jpeg"} and p.is_file():
            n += 1
    return n


@router.get("/tiles/{z}/{x}/{y}.png")
def get_tile(z: int, x: int, y: int) -> Response:
    """Serve local tile or offline placeholder (never hits the internet)."""
    if z < 0 or z > 22 or x < 0 or y < 0:
        return Response(status_code=400, content=b"invalid tile coords")

    path = resolve_tile_path(z, x, y)
    if path is not None:
        media = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        return FileResponse(
            path,
            media_type=media,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    png = _placeholder_tile(z, x, y)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Studsat-Tile": "placeholder",
        },
    )


@router.get("/tiles/info")
def tiles_info() -> dict:
    """Diagnostics for Settings / ops — not required by leaflet."""
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    n = count_tiles()
    return {
        "tiles_dir": str(TILES_DIR.resolve()),
        "tile_file_count": n,
        "using_placeholders": n == 0,
        "url_template": "/tiles/{z}/{x}/{y}.png",
        "note": (
            "Drop an XYZ export into tiles/{z}/{x}/{y}.png for the launch site. "
            "Missing tiles fall back to offline placeholders."
        ),
    }
