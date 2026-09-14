import React, { useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { historyToSeries } from '../../utils/format.js';

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

/**
 * Single scrolling line chart backed by a history number array.
 */
export default function LineChartCard({
  title,
  values,
  color = '#3d9cf0',
  unit = '',
  maxPoints = 120,
  height = 140,
}) {
  const data = useMemo(
    () => historyToSeries(values, maxPoints),
    [values, maxPoints]
  );

  const hasData = data.some((d) => d.v != null);

  return (
    <div className="chart-card">
      <div className="chart-card-head">
        <span className="panel-title">{title}</span>
        {hasData && unit ? <span className="chart-unit">{unit}</span> : null}
      </div>
      <div className="chart-body" style={{ height }}>
        {!hasData ? (
          <div className="chart-empty muted small">No samples yet</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#1e2a38" strokeDasharray="3 3" />
              <XAxis
                dataKey="i"
                tick={{ fill: '#8b9bb0', fontSize: 10 }}
                stroke="#1e2a38"
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tick={{ fill: '#8b9bb0', fontSize: 10 }}
                stroke="#1e2a38"
                tickLine={false}
                width={42}
                domain={['auto', 'auto']}
              />
              <Tooltip
                {...TOOLTIP_STYLE}
                formatter={(v) => [
                  v == null ? '—' : `${Number(v).toFixed(2)}${unit ? ` ${unit}` : ''}`,
                  title,
                ]}
                labelFormatter={(l) => `sample #${l}`}
              />
              <Line
                type="monotone"
                dataKey="v"
                stroke={color}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
