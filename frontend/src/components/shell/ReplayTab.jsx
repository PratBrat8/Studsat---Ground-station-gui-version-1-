import React, { useState } from 'react';
import ReplayControls from '../replay/ReplayControls.jsx';
import VehicleLivePanel from './VehicleLivePanel.jsx';

/**
 * Replay tab — same live visual pipeline, fed from a logged CSV (Phase 10).
 */
export default function ReplayTab() {
  const [vehicle, setVehicle] = useState('rocket');

  return (
    <div className="replay-tab">
      <ReplayControls onVehicleChange={setVehicle} />
      <div className="replay-live-wrap">
        <div className="banner info" style={{ marginBottom: '0.75rem' }}>
          Live components below · vehicle <strong>{vehicle}</strong> · data path
          is CSV → encode/raw hex → FrameParser → hub → WebSocket (identical to
          sim/serial after the parser).
        </div>
        <VehicleLivePanel vehicle={vehicle} compactToolbar />
      </div>
    </div>
  );
}
