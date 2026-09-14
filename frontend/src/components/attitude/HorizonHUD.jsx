import React, { useMemo } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { clamp, fmt, fmtSigned } from '../../utils/format.js';

/**
 * Artificial horizon — pitch ladder + roll bank (PRD G6 / Phase 5).
 * Pure SVG/CSS; driven by store pitch/roll.
 */
export default function HorizonHUD({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const pitch = useStore((s) => s.telemetry.pitch) ?? 0;
  const roll = useStore((s) => s.telemetry.roll) ?? 0;
  const speed = useStore((s) => s.telemetry.speed_mps);
  const alt = useStore((s) => s.telemetry.altitude_m);

  // Visual scale: ~2.2 px per degree of pitch, clamp extreme attitudes
  const pitchPx = clamp(pitch, -40, 40) * 2.4;
  const rollDeg = clamp(roll, -60, 60);

  const ladder = useMemo(() => {
    const marks = [];
    for (let p = -30; p <= 30; p += 10) {
      if (p === 0) continue;
      marks.push(p);
    }
    return marks;
  }, []);

  return (
    <div className="hud-panel" aria-label="Artificial horizon">
      <div className="panel-title">Attitude HUD</div>
      <div className="hud-viewport">
        <div
          className="hud-sky-ground"
          style={{
            transform: `rotate(${-rollDeg}deg) translateY(${pitchPx}px)`,
          }}
        >
          <div className="hud-sky" />
          <div className="hud-horizon-line" />
          <div className="hud-ground" />
          <div className="hud-ladder">
            {ladder.map((p) => (
              <div
                key={p}
                className="hud-ladder-mark"
                style={{ top: `calc(50% - ${p * 2.4}px)` }}
              >
                <span className="hud-ladder-line" />
                <span className="hud-ladder-text">{p}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Fixed aircraft symbol */}
        <svg className="hud-aircraft" viewBox="0 0 120 40" aria-hidden>
          <line x1="10" y1="20" x2="45" y2="20" stroke="#f0c14d" strokeWidth="2.5" />
          <line x1="75" y1="20" x2="110" y2="20" stroke="#f0c14d" strokeWidth="2.5" />
          <circle cx="60" cy="20" r="3" fill="none" stroke="#f0c14d" strokeWidth="2" />
          <line x1="60" y1="20" x2="60" y2="28" stroke="#f0c14d" strokeWidth="2" />
        </svg>

        {/* Roll scale ticks at top */}
        <div className="hud-roll-scale">
          <div
            className="hud-roll-pointer"
            style={{ transform: `rotate(${rollDeg}deg)` }}
          />
        </div>
      </div>

      <div className="hud-readouts">
        <span>P {fmtSigned(pitch, 1)}</span>
        <span>R {fmtSigned(roll, 1)}</span>
        <span>VS {fmt(speed, 1, 'm/s')}</span>
        <span>ALT {fmt(alt, 0, 'm')}</span>
      </div>
    </div>
  );
}
