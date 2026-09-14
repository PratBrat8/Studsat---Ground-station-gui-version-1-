import React, { useMemo } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import LineChartCard from './LineChartCard.jsx';

/**
 * Real-time scrolling charts from store history (PRD G5 / Phase 5).
 * Caps on-screen points for render performance; full log is CSV (Phase 10).
 */
export default function GraphsPanel({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const history = useStore((s) => s.history);

  // Slice once so child memos stay stable when only older points shift
  const series = useMemo(
    () => ({
      altitude: history.altitude,
      speed: history.speed,
      pitch: history.pitch,
      yaw: history.yaw,
      roll: history.roll,
      battery: history.battery,
      temperature: history.temperature,
      pressure: history.pressure,
    }),
    [history]
  );

  const accent = vehicle === 'satellite' ? '#3dd6a5' : '#f0733d';

  return (
    <div className="graphs-panel" aria-label="Telemetry graphs">
      <div className="graphs-panel-head">
        <h2 className="section-title">Graphs</h2>
        <span className="muted small">
          {series.altitude?.length || 0} samples · live scroll
        </span>
      </div>
      <div className="graphs-grid">
        <LineChartCard
          title="Altitude"
          values={series.altitude}
          color={accent}
          unit="m"
        />
        <LineChartCard
          title="Vertical speed"
          values={series.speed}
          color="#3d9cf0"
          unit="m/s"
        />
        <LineChartCard
          title="Pitch"
          values={series.pitch}
          color="#f0c14d"
          unit="°"
        />
        <LineChartCard
          title="Yaw"
          values={series.yaw}
          color="#9b7bff"
          unit="°"
        />
        <LineChartCard
          title="Roll"
          values={series.roll}
          color="#e35d6a"
          unit="°"
        />
        <LineChartCard
          title="Battery"
          values={series.battery}
          color="#7dffb3"
          unit="V"
        />
        <LineChartCard
          title="Temperature"
          values={series.temperature}
          color="#f0733d"
          unit="°C"
        />
        <LineChartCard
          title="Pressure"
          values={series.pressure}
          color="#8b9bb0"
          unit="hPa"
        />
      </div>
    </div>
  );
}
