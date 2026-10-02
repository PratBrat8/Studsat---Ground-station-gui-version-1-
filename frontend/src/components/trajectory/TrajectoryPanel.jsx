import React, { useMemo } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { fmt } from '../../utils/format.js';

const TOOLTIP_STYLE = {
  contentStyle: {
    background: '#121820',
    border: '1px solid #1e2a38',
    borderRadius: 6,
    fontSize: 12,
  },
  labelStyle: { color: '#8b9bb0' },
  itemStyle: { color: '#e6edf5' },
};

function climbSourceLabel(source) {
  if (source === 'imu_pitch') return 'IMU pitch';
  if (source === 'atan2') return 'atan2(vz, vh) — IMU pitch not in CSV';
  return 'no climb source yet';
}

/**
 * Altitude vs horizontal range + ASCENT trend estimate (PRD A.5.5 / C.7).
 * One instance per vehicle — rocket and CanSat never share a path.
 */
export default function TrajectoryPanel({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const traj = useStore((s) => s.trajectory);
  const phase = useStore((s) => s.phase);
  const accent = vehicle === 'satellite' ? '#3dd6a5' : '#f0733d';

  const { flown, trend } = useMemo(() => {
    const path = Array.isArray(traj?.path) ? traj.path : [];
    const flownPts = path
      .filter((p) => p && p.range_m != null && p.alt_m != null)
      .map((p) => ({
        range_m: Number(p.range_m),
        flown: Number(p.alt_m),
      }));
    const trendPts = Array.isArray(traj?.trend)
      ? traj.trend
          .filter((p) => p && p.range_m != null && p.alt_m != null)
          .map((p) => ({
            range_m: Number(p.range_m),
            estimate: Number(p.alt_m),
          }))
      : [];
    return { flown: flownPts, trend: trendPts };
  }, [traj]);

  const chartData = useMemo(() => {
    const byX = new Map();
    flown.forEach((p) => {
      byX.set(p.range_m, { range_m: p.range_m, flown: p.flown });
    });
    trend.forEach((p) => {
      const prev = byX.get(p.range_m) || { range_m: p.range_m };
      prev.estimate = p.estimate;
      byX.set(p.range_m, prev);
    });
    return [...byX.values()].sort((a, b) => a.range_m - b.range_m);
  }, [flown, trend]);

  const showTrend = Boolean(traj?.trend_active) && trend.length > 1;
  const hasPath = flown.length >= 2;

  return (
    <article className="trajectory-panel" aria-label="Trajectory">
      <header className="trajectory-head">
        <div>
          <div className="panel-title">Trajectory</div>
          <p className="muted small" style={{ margin: 0 }}>
            Altitude vs distance from launch origin · {phase}
          </p>
        </div>
        <div className="trajectory-readouts">
          <div>
            <div className="vg-label">Range</div>
            <div className="vg-value">{fmt(traj?.range_m, 0, 'm')}</div>
          </div>
          <div>
            <div className="vg-label">Climb</div>
            <div className="vg-value">{fmt(traj?.climb_deg, 1, '°')}</div>
          </div>
        </div>
      </header>

      <div className="trajectory-chart">
        {!hasPath ? (
          <div className="chart-empty muted small">
            Waiting for GPS trail — start simulation to plot the path.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 8, right: 12, left: 0, bottom: 4 }}
            >
              <CartesianGrid stroke="#1e2a38" strokeDasharray="3 3" />
              <XAxis
                dataKey="range_m"
                type="number"
                tick={{ fill: '#8b9bb0', fontSize: 10 }}
                stroke="#1e2a38"
                tickLine={false}
                unit=" m"
              />
              <YAxis
                tick={{ fill: '#8b9bb0', fontSize: 10 }}
                stroke="#1e2a38"
                tickLine={false}
                width={46}
                unit=" m"
              />
              <Tooltip
                {...TOOLTIP_STYLE}
                formatter={(v, name) => [
                  v == null ? '—' : `${Number(v).toFixed(1)} m`,
                  name === 'estimate' ? 'Estimate' : 'Flown',
                ]}
                labelFormatter={(l) => `Range ${Number(l).toFixed(0)} m`}
              />
              <Legend
                wrapperStyle={{ fontSize: 11, color: '#8b9bb0' }}
              />
              <Line
                type="monotone"
                dataKey="flown"
                name="Flown"
                stroke={accent}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              {showTrend && (
                <Line
                  type="monotone"
                  dataKey="estimate"
                  name="Ascent estimate"
                  stroke={accent}
                  strokeWidth={1.6}
                  strokeDasharray="6 4"
                  strokeOpacity={0.55}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <p className="muted small trajectory-note">
        Climb from {climbSourceLabel(traj?.climb_source)}. The dashed line is a
        linear trend of the last samples during ASCENT — an estimate, not a
        certainty. Each vehicle has its own origin and path.
      </p>
    </article>
  );
}
