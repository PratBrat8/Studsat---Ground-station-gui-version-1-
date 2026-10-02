import React, { useEffect, useState } from 'react';
import { useRocketStore, useVehicleStore } from '../../state/vehicleStore.js';

/**
 * Mission banner when Rocket hits PAYLOAD_SEP (PRD A.5.6).
 * Reads the rocket store plus this vehicle's snapshot flag so it still
 * appears if only one tab's WebSocket is open.
 */
export default function SeparationBanner({ vehicle }) {
  const rocketSep = useRocketStore((s) => s.cansat_separated);
  const localSep = useVehicleStore(vehicle)((s) => s.cansat_separated);
  const separated = Boolean(rocketSep || localSep);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!separated) setDismissed(false);
  }, [separated]);

  if (!separated || dismissed) return null;

  return (
    <div className="banner sep-banner" role="alert">
      <div>
        <strong>CanSat Separated</strong>
        <span className="sep-banner-body">
          {' '}
          Vehicles descend independently. Treat the CanSat landing prediction as
          the primary recovery track.
        </span>
      </div>
      <button
        type="button"
        className="banner-dismiss"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss separation banner"
      >
        ×
      </button>
    </div>
  );
}
