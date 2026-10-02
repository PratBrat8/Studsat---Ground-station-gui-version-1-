import React, { useState } from 'react';
import ReplayControls from '../replay/ReplayControls.jsx';
import VehicleLivePanel from './VehicleLivePanel.jsx';

/**
 * Replay tab — same live visual pipeline, fed from a logged CSV (Phase 12).
 */
export default function ReplayTab() {
  const [vehicle, setVehicle] = useState('rocket');

  return (
    <div className="replay-tab">
      <ReplayControls onVehicleChange={setVehicle} />
      <div className="replay-live-wrap">
        <div className="banner info" style={{ marginBottom: '0.75rem' }}>
          Live components below · vehicle <strong>{vehicle}</strong> · data path
          is session CSV → +RCV → RadioLineBuffer → hub → WebSocket (same as
          sim/serial after the radio layer). Command log is from the sibling
          session file.
        </div>
        <VehicleLivePanel vehicle={vehicle} compactToolbar />
      </div>
    </div>
  );
}
