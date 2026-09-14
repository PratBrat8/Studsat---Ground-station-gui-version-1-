"""Phase 7 — mission phase FSM unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase_fsm import PhaseFSM, PhaseSample, EVENT_LAUNCH, EVENT_CHUTE


def test_idle_to_armed_on_connect():
    fsm = PhaseFSM()
    assert fsm.phase == "IDLE"
    fsm.on_connected()
    assert fsm.phase == "ARMED"


def test_launch_detect_event():
    fsm = PhaseFSM(phase="ARMED")
    fsm.step(PhaseSample(altitude_m=0, speed_mps=0, event=EVENT_LAUNCH))
    assert fsm.phase == "ASCENT"


def test_ascent_apogee_descent_landed_profile():
    fsm = PhaseFSM(phase="ARMED")
    # Pad
    for i in range(3):
        fsm.step(PhaseSample(altitude_m=0.5, speed_mps=0.0, accel_z=9.8, t=i))
    assert fsm.phase == "ARMED"

    # Launch accel spike
    fsm.step(
        PhaseSample(
            altitude_m=2.0,
            speed_mps=20.0,
            accel_x=0,
            accel_y=0,
            accel_z=40.0,
            t=3,
        )
    )
    assert fsm.phase == "ASCENT"

    # Climb
    for i in range(20):
        fsm.step(
            PhaseSample(
                altitude_m=10 + i * 40,
                speed_mps=35.0,
                accel_z=12.0,
                t=4 + i,
            )
        )
    assert fsm.phase == "ASCENT"
    assert fsm.max_altitude_m > 50

    # Coast / apogee (near-zero vspeed)
    for i in range(10):
        fsm.step(
            PhaseSample(
                altitude_m=800 + i * 0.1,
                speed_mps=0.1,
                accel_z=9.8,
                t=30 + i,
            )
        )
    assert fsm.phase in ("APOGEE", "DESCENT", "ASCENT")
    # Force more near-zero if still ascent
    for i in range(10):
        fsm.step(
            PhaseSample(altitude_m=805, speed_mps=0.0, accel_z=9.8, t=40 + i)
        )
    assert fsm.phase in ("APOGEE", "DESCENT")

    # Descent
    for i in range(15):
        alt = 800 - i * 50
        fsm.step(
            PhaseSample(
                altitude_m=max(0, alt),
                speed_mps=-15.0,
                accel_z=9.8,
                t=50 + i,
            )
        )
    assert fsm.phase in ("DESCENT", "LANDED")

    # Touchdown sustained
    for i in range(20):
        fsm.step(
            PhaseSample(
                altitude_m=1.0,
                speed_mps=0.1,
                accel_z=9.8,
                t=70 + i,
            )
        )
    assert fsm.phase == "LANDED"

    fsm.mark_recovered()
    assert fsm.phase == "RECOVERED"


def test_chute_event_forces_descent():
    fsm = PhaseFSM(phase="ASCENT")
    fsm.ascent_samples = 20
    fsm.max_altitude_m = 500
    fsm.step(PhaseSample(altitude_m=500, speed_mps=5, event=EVENT_CHUTE))
    assert fsm.phase == "DESCENT"


def test_never_raises_on_garbage():
    fsm = PhaseFSM()
    # Should not throw
    fsm.step(PhaseSample(altitude_m=float("nan"), speed_mps=0))
    assert fsm.phase in (
        "IDLE",
        "ARMED",
        "ASCENT",
        "APOGEE",
        "DESCENT",
        "LANDED",
        "RECOVERED",
    )
