"""
Ascent trajectory helpers (PRD v2 A.5.5 / C.7).

Path is (horizontal range from launch origin, baro altitude).
During ASCENT a linear fit of the last N samples is projected forward as a
dashed estimate — not a physics simulation.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence, Tuple

from app.config import TRAJECTORY_TREND_WINDOW_SAMPLES
from app.predictor import _haversine_m as haversine_m


def climb_angle_deg(
    pitch: Optional[float],
    vspeed_mps: Optional[float],
    hspeed_mps: Optional[float],
) -> Tuple[Optional[float], str]:
    """Prefer IMU pitch (PRD C.7). Fall back to atan2(vz, vh)."""
    if pitch is not None:
        try:
            p = float(pitch)
        except (TypeError, ValueError):
            p = None
        else:
            if math.isfinite(p):
                return p, "imu_pitch"
    if vspeed_mps is None or hspeed_mps is None:
        return None, "none"
    try:
        vz = float(vspeed_mps)
        vh = abs(float(hspeed_mps))
    except (TypeError, ValueError):
        return None, "none"
    if not math.isfinite(vz) or not math.isfinite(vh):
        return None, "none"
    return math.degrees(math.atan2(vz, max(vh, 0.05))), "atan2"


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float]:
    """Least-squares y = intercept + slope * x. Pure Python (no numpy)."""
    n = len(xs)
    if n < 2:
        return (float(ys[0]) if ys else 0.0), 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x < 1e-12:
        return mean_y, 0.0
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return intercept, slope


def ascent_trend(
    path: Iterable[dict],
    *,
    window: int = TRAJECTORY_TREND_WINDOW_SAMPLES,
    extra_range_m: Optional[float] = None,
    steps: int = 8,
) -> List[dict]:
    """
    Project the last `window` (range, alt) points forward.
    Returns an empty list when there is not enough geometry.
    """
    pts = [
        p
        for p in path
        if isinstance(p, dict)
        and p.get("range_m") is not None
        and p.get("alt_m") is not None
    ]
    pts = pts[-max(3, int(window)) :]
    if len(pts) < 3:
        return []
    xs = [float(p["range_m"]) for p in pts]
    ys = [float(p["alt_m"]) for p in pts]
    intercept, slope = linear_fit(xs, ys)
    x_last = xs[-1]
    span = max(xs) - min(xs)
    extra = extra_range_m if extra_range_m is not None else max(40.0, 0.35 * max(span, 1.0))
    out: List[dict] = [
        {"range_m": round(x_last, 2), "alt_m": round(ys[-1], 2), "estimate": True}
    ]
    for i in range(1, steps + 1):
        x = x_last + extra * (i / steps)
        y = intercept + slope * x
        out.append(
            {"range_m": round(x, 2), "alt_m": round(y, 2), "estimate": True}
        )
    return out
