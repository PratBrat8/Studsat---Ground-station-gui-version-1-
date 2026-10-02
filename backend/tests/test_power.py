"""Placeholder 2S Li-ion curve (TEMPORARY/UNCONFIRMED)."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.power import electrical_power_w, voltage_to_percent


def test_placeholder_curve_clamps():
    assert voltage_to_percent(5.0) == 0.0
    assert voltage_to_percent(8.4) == 100.0
    assert voltage_to_percent(9.0) == 100.0


def test_placeholder_mid_range():
    pct = voltage_to_percent(7.4)
    assert 50.0 <= pct <= 60.0


def test_power_product():
    assert electrical_power_w(7.4, 0.5) == 3.7
