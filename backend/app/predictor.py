"""
Landing prediction — simple kinematic dead-reckoning (PRD C.6).

Not a 6-DOF flight simulator:
  1. Active in APOGEE / DESCENT
  2. Rolling window of GPS lat/lon/alt/time
  3. Vertical descent rate vz via linear regression
  4. Horizontal drift rates dlat/dt, dlon/dt
  5. time_to_ground = alt_agl / abs(vz)  (guarded)
  6. predicted lat/lon = current + rate * t_go
  7. Confidence HIGH / MED / LOW from fit R² + HDOP
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from app.config import PREDICTION_WINDOW_SAMPLES


@dataclass(frozen=True)
class PredictionResult:
    lat: float
    lon: float
    eta_s: float
    confidence: str  # HIGH | MED | LOW
    distance_m: float
    vz_mps: float
    r2_vertical: float
    samples: int

    def as_dict(self) -> Dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "eta_s": round(self.eta_s, 1),
            "confidence": self.confidence,
            "distance_m": round(self.distance_m, 1),
            "vz_mps": round(self.vz_mps, 2),
            "r2_vertical": round(self.r2_vertical, 3),
            "samples": self.samples,
        }


@dataclass
class _GpsPoint:
    t: float
    lat: float
    lon: float
    alt_m: float  # AGL preferred
    hdop: float = 1.0


@dataclass
class LandingPredictor:
    window: int = PREDICTION_WINDOW_SAMPLES
    _points: Deque[_GpsPoint] = field(default_factory=deque)
    _last: Optional[PredictionResult] = None

    def __post_init__(self) -> None:
        self._points = deque(maxlen=max(5, int(self.window)))

    def reset(self) -> None:
        self._points.clear()
        self._last = None

    def push_gps(
        self,
        t: float,
        lat: float,
        lon: float,
        alt_m: float,
        hdop: float = 1.0,
    ) -> None:
        if lat is None or lon is None:
            return
        try:
            self._points.append(
                _GpsPoint(
                    t=float(t),
                    lat=float(lat),
                    lon=float(lon),
                    alt_m=float(alt_m),
                    hdop=float(hdop) if hdop is not None else 1.0,
                )
            )
        except (TypeError, ValueError):
            return

    def push_altitude(self, t: float, alt_m: float) -> None:
        """If GPS is sparse, still feed altitude onto last lat/lon."""
        if not self._points:
            return
        last = self._points[-1]
        self._points.append(
            _GpsPoint(
                t=float(t),
                lat=last.lat,
                lon=last.lon,
                alt_m=float(alt_m),
                hdop=last.hdop,
            )
        )

    def compute(
        self,
        *,
        phase: str,
        current_lat: Optional[float],
        current_lon: Optional[float],
        current_alt_m: Optional[float],
        current_hdop: Optional[float] = None,
    ) -> Optional[PredictionResult]:
        """
        Recompute prediction. Returns None if not in descent window or
        insufficient data. On failure modes returns LOW confidence when possible.
        """
        phase = (phase or "").upper()
        if phase not in ("APOGEE", "DESCENT"):
            # Keep last prediction frozen on LANDED for recovery team
            if phase == "LANDED":
                return self._last
            return None

        if current_lat is None or current_lon is None or current_alt_m is None:
            return self._last

        pts = list(self._points)
        if len(pts) < 3:
            # Degenerate: drop straight down, no drift
            alt = max(0.0, float(current_alt_m))
            if alt < 0.5:
                result = PredictionResult(
                    lat=float(current_lat),
                    lon=float(current_lon),
                    eta_s=0.0,
                    confidence="LOW",
                    distance_m=0.0,
                    vz_mps=0.0,
                    r2_vertical=0.0,
                    samples=len(pts),
                )
                self._last = result
                return result
            result = PredictionResult(
                lat=float(current_lat),
                lon=float(current_lon),
                eta_s=999.0,
                confidence="LOW",
                distance_m=0.0,
                vz_mps=0.0,
                r2_vertical=0.0,
                samples=len(pts),
            )
            self._last = result
            return result

        times = [p.t for p in pts]
        alts = [p.alt_m for p in pts]
        lats = [p.lat for p in pts]
        lons = [p.lon for p in pts]
        hdop = float(current_hdop if current_hdop is not None else pts[-1].hdop)

        vz, r2_v = _linreg_slope_r2(times, alts)
        dlat_dt, r2_lat = _linreg_slope_r2(times, lats)
        dlon_dt, r2_lon = _linreg_slope_r2(times, lons)

        alt = max(0.0, float(current_alt_m))
        # vz is d(alt)/dt; descent means vz < 0
        if vz >= -0.15:
            # Not clearly descending — low confidence / long ETA
            confidence = "LOW"
            eta = 999.0 if alt > 1.0 else 0.0
            pred_lat = float(current_lat)
            pred_lon = float(current_lon)
        else:
            eta = alt / abs(vz)
            # Cap absurd ETAs
            eta = min(eta, 900.0)
            pred_lat = float(current_lat) + dlat_dt * eta
            pred_lon = float(current_lon) + dlon_dt * eta
            confidence = _confidence(r2_v, hdop, len(pts), abs(vz))

        dist = _haversine_m(
            float(current_lat), float(current_lon), pred_lat, pred_lon
        )
        result = PredictionResult(
            lat=pred_lat,
            lon=pred_lon,
            eta_s=eta,
            confidence=confidence,
            distance_m=dist,
            vz_mps=vz,
            r2_vertical=r2_v,
            samples=len(pts),
        )
        self._last = result
        return result


def _linreg_slope_r2(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Return (slope, R²) for y ≈ a + b x. Degenerate → (0, 0)."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = 0.0
    den = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        num += dx * (y - mean_y)
        den += dx * dx
    if den < 1e-12:
        return 0.0, 0.0
    slope = num / den
    # R²
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    if ss_tot < 1e-12:
        return slope, 1.0
    ss_res = 0.0
    intercept = mean_y - slope * mean_x
    for x, y in zip(xs, ys):
        err = y - (intercept + slope * x)
        ss_res += err * err
    r2 = max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    return slope, r2


def _confidence(r2_v: float, hdop: float, n: int, abs_vz: float) -> str:
    """Heuristic High/Med/Low (PRD C.6)."""
    score = 0
    if r2_v >= 0.85:
        score += 2
    elif r2_v >= 0.55:
        score += 1
    if hdop <= 1.2:
        score += 2
    elif hdop <= 2.5:
        score += 1
    if n >= 12:
        score += 1
    if abs_vz >= 2.0:
        score += 1
    if score >= 5:
        return "HIGH"
    if score >= 3:
        return "MED"
    return "LOW"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))
