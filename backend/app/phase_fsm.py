"""
Mission phase state machine (PRD B.4 / C.3 phase_fsm.py).

  IDLE → ARMED → ASCENT → APOGEE → DESCENT → LANDED → RECOVERED

Thresholds from config.py. EVENT frames (LAUNCH_DETECT, CHUTE_DEPLOY, …)
are authoritative overrides when present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Deque, Iterable, List, Optional, Sequence

from app.config import (
    APOGEE_VSPEED_EPS,
    LANDED_ALT_EPS_M,
    LANDED_CONFIRM_SAMPLES,
    LANDED_SPEED_EPS,
    LAUNCH_ACCEL_THRESHOLD_G,
)

# Ordered phases for comparison helpers
PHASES = (
    "IDLE",
    "ARMED",
    "ASCENT",
    "APOGEE",
    "DESCENT",
    "LANDED",
    "RECOVERED",
)

G0 = 9.80665

# Event strings firmware may send (PRD C.2 EVENT payload)
EVENT_LAUNCH = "LAUNCH_DETECT"
EVENT_CHUTE = "CHUTE_DEPLOY"
EVENT_APOGEE = "APOGEE"
EVENT_LANDING = "LANDING_DETECT"
EVENT_TOUCHDOWN = "TOUCHDOWN"


@dataclass
class PhaseSample:
    """One fused sample for the FSM (recent telemetry + optional event)."""

    altitude_m: float  # AGL preferred
    speed_mps: float  # vertical speed (+up)
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 0.0
    event: Optional[str] = None
    t: float = 0.0


@dataclass
class PhaseFSM:
    """
    Stateful FSM per vehicle. Call step() with the latest sample (and optional
    event). Pure of I/O — unit-testable.
    """

    phase: str = "IDLE"
    # Sustained-condition counters
    apogee_near_zero_count: int = 0
    descent_count: int = 0
    landed_count: int = 0
    # Pad / ground reference (AGL ≈ 0 at arm)
    pad_altitude_m: Optional[float] = None
    max_altitude_m: float = 0.0
    # Hysteresis: samples after launch before allowing apogee
    ascent_samples: int = 0
    # Last event applied (debug)
    last_event: Optional[str] = None

    # Tunables (copied from config so tests can override)
    launch_accel_g: float = LAUNCH_ACCEL_THRESHOLD_G
    apogee_vspeed_eps: float = APOGEE_VSPEED_EPS
    landed_alt_eps_m: float = LANDED_ALT_EPS_M
    landed_speed_eps: float = LANDED_SPEED_EPS
    landed_confirm_samples: int = LANDED_CONFIRM_SAMPLES
    # Extra assumed thresholds
    launch_alt_delta_m: float = 15.0  # AGL rise to confirm launch without accel
    apogee_confirm_samples: int = 5
    descent_confirm_samples: int = 4
    min_ascent_samples: int = 8

    def reset(self) -> None:
        self.phase = "IDLE"
        self.apogee_near_zero_count = 0
        self.descent_count = 0
        self.landed_count = 0
        self.pad_altitude_m = None
        self.max_altitude_m = 0.0
        self.ascent_samples = 0
        self.last_event = None

    def mark_recovered(self) -> str:
        """Operator action from UI (PRD B.4)."""
        if self.phase == "LANDED":
            self.phase = "RECOVERED"
        return self.phase

    def on_connected(self) -> str:
        """First valid frame while IDLE → ARMED."""
        if self.phase == "IDLE":
            self.phase = "ARMED"
        return self.phase

    def step(self, sample: PhaseSample) -> str:
        """Advance FSM by one sample. Never raises."""
        try:
            return self._step(sample)
        except Exception:
            return self.phase

    def _step(self, sample: PhaseSample) -> str:
        alt = float(sample.altitude_m)
        vz = float(sample.speed_mps)
        ax, ay, az = float(sample.accel_x), float(sample.accel_y), float(sample.accel_z)
        accel_mag = (ax * ax + ay * ay + az * az) ** 0.5
        accel_g = accel_mag / G0

        if self.pad_altitude_m is None and self.phase in ("ARMED", "IDLE"):
            self.pad_altitude_m = alt
        if self.pad_altitude_m is None:
            self.pad_altitude_m = 0.0

        agl = alt - self.pad_altitude_m
        # Also treat absolute small alt as AGL if pad not set well
        if abs(self.pad_altitude_m) < 1.0:
            agl = alt

        self.max_altitude_m = max(self.max_altitude_m, agl)

        # --- Event overrides (authoritative) ---
        ev = (sample.event or "").strip().upper()
        if ev:
            self.last_event = ev
            self._apply_event(ev, agl, vz)

        phase = self.phase

        if phase == "IDLE":
            # Waiting for connection handler; sample alone can still arm
            self.phase = "ARMED"
            phase = self.phase

        if phase == "ARMED":
            launched = (
                accel_g >= self.launch_accel_g
                or agl >= self.launch_alt_delta_m
                or vz >= 8.0
            )
            if launched:
                self.phase = "ASCENT"
                self.ascent_samples = 0
                self.apogee_near_zero_count = 0

        elif phase == "ASCENT":
            self.ascent_samples += 1
            # Near-zero vertical speed after climbing → apogee window
            if (
                self.ascent_samples >= self.min_ascent_samples
                and self.max_altitude_m > self.launch_alt_delta_m
                and abs(vz) <= self.apogee_vspeed_eps
            ):
                self.apogee_near_zero_count += 1
            elif vz < -self.apogee_vspeed_eps and self.ascent_samples >= self.min_ascent_samples:
                # Already falling hard — skip straight toward apogee/descent
                self.apogee_near_zero_count += 2
            else:
                self.apogee_near_zero_count = max(0, self.apogee_near_zero_count - 1)

            if self.apogee_near_zero_count >= self.apogee_confirm_samples:
                self.phase = "APOGEE"
                self.descent_count = 0

        elif phase == "APOGEE":
            if vz < -self.apogee_vspeed_eps or agl < self.max_altitude_m - 5.0:
                self.descent_count += 1
            else:
                self.descent_count = max(0, self.descent_count - 1)
            if self.descent_count >= self.descent_confirm_samples:
                self.phase = "DESCENT"
                self.landed_count = 0

        elif phase == "DESCENT":
            near_ground = agl <= self.landed_alt_eps_m
            slow = abs(vz) <= self.landed_speed_eps
            if near_ground and slow:
                self.landed_count += 1
            else:
                self.landed_count = max(0, self.landed_count - 1)
            if self.landed_count >= self.landed_confirm_samples:
                self.phase = "LANDED"

        elif phase in ("LANDED", "RECOVERED"):
            pass

        return self.phase

    def _apply_event(self, ev: str, agl: float, vz: float) -> None:
        if ev in (EVENT_LAUNCH, "LAUNCH", "LIFTOFF"):
            if self.phase in ("IDLE", "ARMED"):
                self.phase = "ASCENT"
                self.ascent_samples = max(self.ascent_samples, self.min_ascent_samples)
        elif ev in (EVENT_APOGEE,):
            if self.phase in ("ARMED", "ASCENT"):
                self.phase = "APOGEE"
        elif ev in (EVENT_CHUTE, "CHUTE", "PARACHUTE"):
            if self.phase in ("ASCENT", "APOGEE"):
                self.phase = "DESCENT"
            elif self.phase == "ARMED":
                self.phase = "DESCENT"
        elif ev in (EVENT_LANDING, EVENT_TOUCHDOWN, "LANDED"):
            if self.phase not in ("RECOVERED",):
                self.phase = "LANDED"


def next_phase(
    current_phase: str,
    recent_samples: Sequence[PhaseSample],
    *,
    fsm: Optional[PhaseFSM] = None,
) -> str:
    """
    Functional API from PRD C.3: next_phase(current, recent_samples) -> phase.

    If *fsm* is provided it is used (stateful counters). Otherwise a temporary
    FSM starts at *current_phase* and only the last sample is applied (limited
    usefulness without sustained counters — prefer PhaseFSM.step in the hub).
    """
    if fsm is not None:
        for s in recent_samples:
            fsm.step(s)
        return fsm.phase

    tmp = PhaseFSM(phase=current_phase)
    for s in recent_samples:
        tmp.step(s)
    return tmp.phase
