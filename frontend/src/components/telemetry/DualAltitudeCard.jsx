import React from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { fmt } from '../../utils/format.js';

/**
 * Baro vs GNSS altitude failsafe (PRD v2 A.5.2).
 * Threshold comes from the backend (default 30 m, TEMPORARY).
 */
export default function DualAltitudeCard({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const t = useStore((s) => s.telemetry);
  const gps = useStore((s) => s.gps);
  const baro = t.altitude_m;
  const gnss = t.altitude_gnss_m ?? gps.alt_m;
  const delta = t.altitude_delta_m;
  const warn = Boolean(t.altitude_disagreement);
  const baroLabel =
    vehicle === 'rocket' ? 'Baro (BMP388)' : 'Baro (BME680)';
  const warnCls = warn ? 'warn-text' : '';

  return (
    <article
      className={`status-card dual-alt ${warn ? 'warn' : ''}`}
      aria-label="Dual altitude"
    >
      <header className="status-card-head">
        <h2>Dual altitude</h2>
        {warn && <span className="link-pill bad">sensor disagreement</span>}
      </header>
      <div className="dual-alt-grid">
        <div>
          <div className="vg-label">{baroLabel}</div>
          <div className={`vg-value ${warnCls}`}>{fmt(baro, 1, 'm')}</div>
        </div>
        <div>
          <div className="vg-label">GNSS</div>
          <div className={`vg-value ${warnCls}`}>{fmt(gnss, 1, 'm')}</div>
        </div>
        <div>
          <div className="vg-label">|Δ|</div>
          <div className={`vg-value ${warnCls}`}>
            {fmt(delta, 1, 'm')}
          </div>
        </div>
      </div>
      {warn && (
        <p className="muted small">
          Baro and GNSS differ by more than the failsafe threshold. Treat both
          as untrusted until they reconverge.
        </p>
      )}
    </article>
  );
}
