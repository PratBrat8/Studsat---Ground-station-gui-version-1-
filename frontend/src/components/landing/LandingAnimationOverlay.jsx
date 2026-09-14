import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { fmt } from '../../utils/format.js';

const AUTO_DISMISS_MS = 5500;

/**
 * Landing animation overlay (PRD C.4 / Phase 9, non-negotiable #7).
 *
 * Edge-triggered: fires exactly once when phase transitions **into** LANDED.
 * Level-triggered re-renders while phase stays LANDED do NOT replay.
 * Flag resets when phase returns to pre-landed mission states (new flight).
 */
export default function LandingAnimationOverlay({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const phase = useStore((s) => s.phase);
  const gps = useStore((s) => s.gps);
  const prediction = useStore((s) => s.prediction);
  const telemetry = useStore((s) => s.telemetry);

  const [visible, setVisible] = useState(false)
  const [exiting, setExiting] = useState(false);
  // Session key so React StrictMode double-mount doesn't double-fire incorrectly
  // after a real edge — we key by transition identity.
  const lastPhaseRef = useRef(phase);
  const playedEdgeRef = useRef(false);
  const dismissTimerRef = useRef(null);
  const exitTimerRef = useRef(null);

  const clearTimers = useCallback(() => {
    if (dismissTimerRef.current) {
      clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = null;
    }
    if (exitTimerRef.current) {
      clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }
  }, []);

  const startDismiss = useCallback(() => {
    setExiting(true);
    exitTimerRef.current = setTimeout(() => {
      setVisible(false);
      setExiting(false);
    }, 400);
  }, []);

  const dismiss = useCallback(() => {
    clearTimers();
    startDismiss();
  }, [clearTimers, startDismiss]);

  useEffect(() => {
    const prev = lastPhaseRef.current;
    lastPhaseRef.current = phase;

    // Reset edge latch when a new flight arm/ascent cycle begins
    if (
      phase === 'IDLE' ||
      phase === 'ARMED' ||
      phase === 'ASCENT' ||
      phase === 'APOGEE' ||
      phase === 'DESCENT'
    ) {
      // Only clear latch once we've left the landed/recovered terminal states
      if (prev === 'LANDED' || prev === 'RECOVERED' || phase === 'IDLE' || phase === 'ARMED') {
        if (phase !== 'LANDED' && phase !== 'RECOVERED') {
          playedEdgeRef.current = false;
        }
      }
      if (phase === 'IDLE' || phase === 'ARMED' || phase === 'ASCENT') {
        playedEdgeRef.current = false;
      }
    }

    // Rising edge into LANDED
    const enteringLanded = phase === 'LANDED' && prev !== 'LANDED';
    if (enteringLanded && !playedEdgeRef.current) {
      playedEdgeRef.current = true;
      setExiting(false);
      setVisible(true);
      clearTimers();
      dismissTimerRef.current = setTimeout(() => {
        startDismiss();
      }, AUTO_DISMISS_MS);
    }
  }, [phase, clearTimers, startDismiss]);

  useEffect(() => () => clearTimers(), [clearTimers]);

  if (!visible) return null;

  const lat = gps?.lat ?? prediction?.lat;
  const lon = gps?.lon ?? prediction?.lon;
  const alt = telemetry?.altitude_m;
  const title = vehicle === 'satellite' ? 'Satellite' : 'Rocket';

  return (
    <div
      className={`landing-overlay ${exiting ? 'exiting' : ''}`}
      role="dialog"
      aria-modal="true"
      aria-label="Touchdown"
    >
      <div className="landing-overlay-backdrop" onClick={dismiss} />

      <div className="landing-overlay-card">
        <div className="landing-sky">
          <div className="landing-chute" aria-hidden>
            <div className="chute-canopy" />
            <div className="chute-lines">
              <span />
              <span />
              <span />
              <span />
            </div>
            <div className={`chute-payload ${vehicle}`} />
          </div>
          <div className="landing-ground" aria-hidden>
            <div className="landing-dust" />
            <div className="landing-pin" />
          </div>
        </div>

        <div className="landing-banner">
          <div className="landing-banner-kicker">Mission event</div>
          <h2 className="landing-banner-title">TOUCHDOWN</h2>
          <p className="landing-banner-sub">
            {title} phase → <strong>LANDED</strong>
          </p>
        </div>

        <div className="landing-coords">
          <div>
            <div className="vg-label">Touchdown fix</div>
            <div className="landing-coord-value">
              {lat != null && lon != null
                ? `${fmt(lat, 6)}, ${fmt(lon, 6)}`
                : 'GPS pending'}
            </div>
          </div>
          <div>
            <div className="vg-label">Altitude AGL</div>
            <div className="landing-coord-value">{fmt(alt, 1, 'm')}</div>
          </div>
          {prediction?.lat != null && (
            <div>
              <div className="vg-label">Predicted</div>
              <div className="landing-coord-value">
                {fmt(prediction.lat, 5)}, {fmt(prediction.lon, 5)}
                {prediction.confidence
                  ? ` · ${prediction.confidence}`
                  : ''}
              </div>
            </div>
          )}
        </div>

        <div className="landing-actions">
          <button type="button" className="btn primary" onClick={dismiss}>
            Continue
          </button>
          <span className="muted small">
            Auto-dismiss in a few seconds · plays once per landing
          </span>
        </div>
      </div>
    </div>
  );
}
