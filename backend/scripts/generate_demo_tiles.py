"""
Generate a small set of offline placeholder tiles around the sim launch site
(Bengaluru area — matches simulator.py defaults).

Usage (from backend/):
  python scripts/generate_demo_tiles.py

Real competition maps: replace tiles/ with a proper OSM/MapTiler XYZ export.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import TILES_DIR  # noqa: E402
from app.tile_server import make_solid_png  # noqa: E402

# Sim defaults (protocol/simulator)
LAT0 = 12.9716
LON0 = 77.5946
ZOOMS = (12, 13, 14, 15)


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat_deg)
    n = 2.0**zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def main() -> None:
    written = 0
    for z in ZOOMS:
        cx, cy = deg2num(LAT0, LON0, z)
        # 5×5 neighborhood around pad
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                x, y = cx + dx, cy + dy
                out = TILES_DIR / str(z) / str(x) / f"{y}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                # Slightly greener near center
                dist = abs(dx) + abs(dy)
                rgb = (34 + dist * 8, 72 - dist * 4, 48 + dist * 6)
                out.write_bytes(make_solid_png(rgb, size=256, grid=True))
                written += 1
    print(f"Wrote {written} demo tiles under {TILES_DIR}")


if __name__ == "__main__":
    main()
