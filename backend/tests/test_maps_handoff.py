"""Phase 7 — Google Maps handoff URL contract (PRD A.5.10)."""
from __future__ import annotations

import re

HANDOFF_RE = re.compile(
    r"^https://www\.google\.com/maps\?q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$"
)


def google_maps_handoff_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


def test_prd_url_shape():
    url = google_maps_handoff_url(12.9716, 77.5946)
    m = HANDOFF_RE.match(url)
    assert m is not None
    assert float(m.group(1)) == 12.9716
    assert float(m.group(2)) == 77.5946


def test_rejects_non_maps_hosts():
    assert HANDOFF_RE.match("https://evil.example/maps?q=1,2") is None
    assert HANDOFF_RE.match("http://www.google.com/maps?q=1,2") is None
    assert HANDOFF_RE.match("https://www.google.com/maps?q=1,2&extra=1") is None
