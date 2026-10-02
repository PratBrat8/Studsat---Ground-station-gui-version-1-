import React from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { fmt } from '../../utils/format.js';

function Sparkline({ values, min = -120, max = -40, label }) {
  const pts = (values || []).filter((v) => typeof v === 'number' && !Number.isNaN(v));
  if (pts.length < 2) {
    return <div className="sparkline empty muted small">No RSSI history yet</div>;
  }
  const w = 180;
  const h = 40;
  const span = max - min || 1;
  const d = pts
    .map((v, i) => {
      const x = (i / (pts.length - 1)) * w;
      const y = h - ((v - min) / span) * h;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height="40"
      role="img"
      aria-label={label}
    >
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="1.8" />
    </svg>
  );
}

/**
 * Downlink RSSI/SNR from Reyax +RCV= (PRD v2 A.5.4).
 * Downlink only — uplink RSSI is not in telemetry (Appendix 1.5).
 */
export default function SignalStrengthCard({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const signal = useStore((s) => s.signal);
  const t = useStore((s) => s.telemetry);
  const rssi = signal.rssi ?? t.rssi;
  const snr = signal.snr ?? t.snr;
  const hist = signal.rssi_history || [];

  return (
    <article className="status-card signal-card" aria-label="Signal strength">
      <header className="status-card-head">
        <h2>Signal (downlink)</h2>
        <span className="muted small">Reyax +RCV RSSI/SNR</span>
      </header>
      <div className="signal-nums">
        <div>
          <div className="vg-label">RSSI</div>
          <div className="vg-value">
            {rssi == null ? '—' : `${rssi} dBm`}
          </div>
        </div>
        <div>
          <div className="vg-label">SNR</div>
          <div className="vg-value">{fmt(snr, 1, 'dB')}</div>
        </div>
      </div>
      <Sparkline values={hist} label="RSSI sparkline" />
    </article>
  );
}
