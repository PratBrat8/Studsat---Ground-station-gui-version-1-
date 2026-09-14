"""Phase 7 — landing predictor unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.predictor import LandingPredictor, _confidence, _haversine_m


def test_no_prediction_outside_descent():
    p = LandingPredictor(window=10)
    for i in range(10):
        p.push_gps(i, 12.97, 77.59, 100 - i * 5, hdop=1.0)
    assert p.compute(
        phase="ASCENT",
        current_lat=12.97,
        current_lon=77.59,
        current_alt_m=50,
    ) is None


def test_descent_prediction_drifts_with_wind():
    p = LandingPredictor(window=15)
    # Descending while drifting east
    lat0, lon0 = 12.9716, 77.5946
    for i in range(15):
        t = float(i)
        alt = 200.0 - i * 10.0  # vz ≈ -10 m/s
        lat = lat0 + i * 0.00005
        lon = lon0 + i * 0.00008
        p.push_gps(t, lat, lon, alt, hdop=0.9)

    result = p.compute(
        phase="DESCENT",
        current_lat=lat0 + 14 * 0.00005,
        current_lon=lon0 + 14 * 0.00008,
        current_alt_m=60.0,
        current_hdop=0.9,
    )
    assert result is not None
    assert result.eta_s > 0
    assert result.eta_s < 30  # ~6 s at 10 m/s from 60 m, allow margin
    assert result.confidence in ("HIGH", "MED", "LOW")
    # Should drift further east of current
    assert result.lon >= lon0 + 14 * 0.00008 - 1e-9
    assert result.distance_m >= 0


def test_low_confidence_when_vz_near_zero():
    p = LandingPredictor(window=10)
    for i in range(10):
        p.push_gps(float(i), 12.0, 77.0, 100.0, hdop=5.0)
    result = p.compute(
        phase="DESCENT",
        current_lat=12.0,
        current_lon=77.0,
        current_alt_m=100.0,
        current_hdop=5.0,
    )
    assert result is not None
    assert result.confidence == "LOW"


def test_confidence_heuristic():
    assert _confidence(0.95, 0.8, 15, 5.0) == "HIGH"
    assert _confidence(0.2, 5.0, 3, 0.5) == "LOW"


def test_haversine_zero():
    assert _haversine_m(0, 0, 0, 0) == pytest.approx(0.0)


def test_landed_keeps_last():
    p = LandingPredictor(window=10)
    for i in range(12):
        p.push_gps(float(i), 12.97, 77.59 + i * 1e-5, 120 - i * 8, hdop=1.0)
    mid = p.compute(
        phase="DESCENT",
        current_lat=12.97,
        current_lon=77.59 + 11e-5,
        current_alt_m=24,
        current_hdop=1.0,
    )
    assert mid is not None
    kept = p.compute(
        phase="LANDED",
        current_lat=12.97,
        current_lon=77.59,
        current_alt_m=1,
    )
    assert kept is mid
