"""
Battery voltage → percentage (PRD v2 C.5).

TEMPORARY/UNCONFIRMED (Appendix 1.4): both vehicles use a generic
2S Li-ion 6.0 V – 8.4 V placeholder curve until the firmware/hardware
team confirms chemistry and pack voltage range.

A wrong curve produces a confidently wrong number on screen. Phase 5
wires this into the battery cards as an assumed percentage, labeled
TEMPORARY — never treat it as measured state of charge.
"""
from __future__ import annotations

from typing import Sequence, Tuple

# TEMPORARY/UNCONFIRMED — 2S Li-ion placeholder (6.0–8.4 V).
# Linear interpolation between these points. Replace with a real
# discharge table before competition.
PLACEHOLDER_2S_LION_CURVE: Sequence[Tuple[float, float]] = (
    (6.00, 0.0),
    (6.40, 5.0),
    (6.80, 15.0),
    (7.20, 40.0),
    (7.40, 55.0),
    (7.60, 70.0),
    (7.80, 82.0),
    (8.00, 92.0),
    (8.20, 97.0),
    (8.40, 100.0),
)

ROCKET_BATTERY_CURVE = PLACEHOLDER_2S_LION_CURVE
CANSAT_BATTERY_CURVE = PLACEHOLDER_2S_LION_CURVE


def voltage_to_percent(
    voltage: float,
    curve: Sequence[Tuple[float, float]] = PLACEHOLDER_2S_LION_CURVE,
) -> float:
    """Piecewise-linear interpolation. Clamped to 0–100. Never raises."""
    if not curve:
        return 0.0
    points = sorted(curve, key=lambda p: p[0])
    v = float(voltage)
    if v <= points[0][0]:
        return float(points[0][1])
    if v >= points[-1][0]:
        return float(points[-1][1])
    for i in range(1, len(points)):
        v0, p0 = points[i - 1]
        v1, p1 = points[i]
        if v <= v1:
            if v1 == v0:
                return float(p1)
            t = (v - v0) / (v1 - v0)
            return float(p0 + t * (p1 - p0))
    return float(points[-1][1])


def electrical_power_w(voltage: float, current_a: float) -> float:
    return float(voltage) * float(current_a)
