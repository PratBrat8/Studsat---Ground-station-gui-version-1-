import React from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { CDR_STATES, cdrStateIndex } from '../../utils/cdrPhases.js';

/**
 * Labeled 8-state CDR progress indicator (PRD A.5.6 / Phase 9).
 */
export default function CdrPhaseStrip({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const phase = useStore((s) => s.phase);
  const fs = useStore((s) => s.telemetry.flight_software_state);
  const idx = cdrStateIndex(phase, fs);

  return (
    <nav
      className="cdr-strip"
      aria-label="CDR flight states"
    >
      <ol className="cdr-strip-list">
        {CDR_STATES.map((st) => {
          let kind = 'upcoming';
          if (idx < 0) kind = 'upcoming';
          else if (st.n < idx) kind = 'done';
          else if (st.n === idx) kind = 'current';
          return (
            <li
              key={st.id}
              className={`cdr-step ${kind}`}
              aria-current={kind === 'current' ? 'step' : undefined}
              title={`${st.n} ${st.id}`}
            >
              <span className="cdr-step-n">{st.n}</span>
              <span className="cdr-step-label">{st.label}</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
