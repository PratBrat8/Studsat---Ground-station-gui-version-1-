import React, { useEffect, useState } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';

/**
 * Mission elapsed clock — counts up while link is CONNECTED and phase != IDLE.
 */
export default function MissionClock({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const phase = useStore((s) => s.phase);
  const linkState = useStore((s) => s.link.state);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [t0, setT0] = useState(null);

  useEffect(() => {
    const live =
      linkState === 'CONNECTED' && phase && phase !== 'IDLE';
    if (live && t0 == null) {
      setT0(Date.now() - elapsedMs);
    }
    if (!live && phase === 'IDLE') {
      setT0(null);
      setElapsedMs(0);
    }
  }, [linkState, phase, t0, elapsedMs]);

  useEffect(() => {
    if (t0 == null) return undefined;
    const id = setInterval(() => {
      setElapsedMs(Date.now() - t0);
    }, 200);
    return () => clearInterval(id);
  }, [t0]);

  const totalSec = Math.floor(elapsedMs / 1000);
  const m = String(Math.floor(totalSec / 60)).padStart(2, '0');
  const s = String(totalSec % 60).padStart(2, '0');
  const cs = String(Math.floor((elapsedMs % 1000) / 10)).padStart(2, '0');

  return (
    <span className="mission-clock" title="Mission elapsed">
      T+{m}:{s}.{cs}
    </span>
  );
}
