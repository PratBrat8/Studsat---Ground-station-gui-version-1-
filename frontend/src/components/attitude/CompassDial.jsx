import React, { useMemo } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { fmt, wrap360 } from '../../utils/format.js';

const CARDINALS = [
  { deg: 0, label: 'N' },
  { deg: 45, label: 'NE' },
  { deg: 90, label: 'E' },
  { deg: 135, label: 'SE' },
  { deg: 180, label: 'S' },
  { deg: 225, label: 'SW' },
  { deg: 270, label: 'W' },
  { deg: 315, label: 'NW' },
];

/**
 * Yaw / heading compass dial (PRD A.6.2 / Phase 5).
 */
export default function CompassDial({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const yaw = wrap360(useStore((s) => s.telemetry.yaw) ?? 0);

  const ticks = useMemo(() => {
    const out = [];
    for (let d = 0; d < 360; d += 15) {
      out.push(d);
    }
    return out;
  }, []);

  return (
    <div className="compass-panel" aria-label="Compass">
      <div className="panel-title">Compass / Yaw</div>
      <div className="compass-wrap">
        <div
          className="compass-rose"
          style={{ transform: `rotate(${-yaw}deg)` }}
        >
          {ticks.map((d) => (
            <div
              key={d}
              className={`compass-tick ${d % 90 === 0 ? 'major' : ''}`}
              style={{ transform: `rotate(${d}deg)` }}
            >
              <span className="compass-tick-mark" />
            </div>
          ))}
          {CARDINALS.map((c) => (
            <div
              key={c.label}
              className={`compass-cardinal ${c.label === 'N' ? 'north' : ''}`}
              style={{ transform: `rotate(${c.deg}deg)` }}
            >
              <span style={{ transform: `rotate(${-c.deg}deg)` }}>{c.label}</span>
            </div>
          ))}
        </div>
        <div className="compass-lubber" aria-hidden />
        <div className="compass-center">
          <div className="compass-heading">{fmt(yaw, 0)}°</div>
        </div>
      </div>
    </div>
  );
}
