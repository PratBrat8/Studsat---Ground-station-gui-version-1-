"""Phase 6: converted CAD GLBs exist and look like binary glTF."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "assets" / "models"
PUBLIC = ROOT / "frontend" / "public" / "models"
GLB_MAGIC = b"glTF"


def test_rocket_and_cansat_glb_present():
    for name in ("rocket.glb", "cansat.glb"):
        src = MODELS / name
        pub = PUBLIC / name
        assert src.is_file(), f"missing {src}"
        assert pub.is_file(), f"missing {pub}"
        assert src.stat().st_size > 1000
        assert src.read_bytes()[:4] == GLB_MAGIC
        assert pub.read_bytes()[:4] == GLB_MAGIC
