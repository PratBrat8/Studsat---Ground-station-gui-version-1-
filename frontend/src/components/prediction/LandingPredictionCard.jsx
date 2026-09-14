import React from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { useSettingsStore } from '../../state/settingsStore.js';
import { markRecovered } from '../../services/api.js';
import { fmt } from '../../utils/format.js';

const CONF_CLASS = {
  HIGH: 'conf-high',
  MED: 'conf-med',
  LOW: 'conf-low',
};

/**
 * Landing prediction card — lat/lon, ETA, distance, High/Med/Low confidence.
 * PRD G4 / C.6 / Phase 7. Math is server-side; this only renders.
 */
export default function LandingPredictionCard({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const prediction = useStore((s) => s.prediction);
  const phase = useStore((s) => s.phase);
  const gps = useStore((s) => s.gps);
  const setActionError = useSettingsStore((s) => s.setActionError);
  const setBusy = useSettingsStore((s) => s.setBusy);
  const busy = useSettingsStore((s) => s.busy[vehicle]);

  const active =
    prediction &&
    (phase === 'APOGEE' || phase === 'DESCENT' || phase === 'LANDED');

  const conf = (prediction?.confidence || 'LOW').toUpperCase();
  const confCls = CONF_CLASS[conf] || CONF_CLASS.LOW;

  const onRecover = async () => {
    setBusy(vehicle, true);
    setActionError(null);
    try {
      await markRecovered(vehicle);
    } catch (err) {
      setActionError(err.message || String(err));
    } finally {
      setBusy(vehicle, false);
    }
  };

  return (
    <div className={`prediction-card ${active ? 'active' : ''}`}>
      <div className="prediction-card-head">
        <div className="panel-title">Landing prediction</div>
        {active ? (
          <span className={`conf-pill ${confCls}`}>{conf}</span>
        ) : (
          <span className="conf-pill conf-idle">—</span>
        )}
      </div>

      {!active && (
        <p className="muted small prediction-idle">
          Estimate runs during <strong>APOGEE / DESCENT</strong> (kinematic
          dead-reckoning — not a full flight sim). Confidence is High / Med /
          Low, never a bare guarantee.
        </p>
      )}

      {active && (
        <>
          <div className="prediction-grid">
            <div>
              <div className="vg-label">Predicted lat</div>
              <div className="vg-value">{fmt(prediction.lat, 6)}</div>
            </div>
            <div>
              <div className="vg-label">Predicted lon</div>
              <div className="vg-value">{fmt(prediction.lon, 6)}</div>
            </div>
            <div>
              <div className="vg-label">ETA</div>
              <div className="vg-value">
                {prediction.eta_s != null && prediction.eta_s < 900
                  ? `${Math.round(prediction.eta_s)} s`
                  : '—'}
              </div>
            </div>
            <div>
              <div className="vg-label">Distance</div>
              <div className="vg-value">
                {prediction.distance_m != null
                  ? fmt(prediction.distance_m, 0, 'm')
                  : '—'}
              </div>
            </div>
            <div>
              <div className="vg-label">Descent rate</div>
              <div className="vg-value">
                {prediction.vz_mps != null
                  ? fmt(prediction.vz_mps, 1, 'm/s')
                  : '—'}
              </div>
            </div>
            <div>
              <div className="vg-label">Fit R²</div>
              <div className="vg-value">
                {prediction.r2_vertical != null
                  ? fmt(prediction.r2_vertical, 2)
                  : '—'}
              </div>
            </div>
          </div>
          {gps.lat != null && (
            <p className="muted small" style={{ margin: '0.5rem 0 0' }}>
              Last fix {fmt(gps.lat, 5)}, {fmt(gps.lon, 5)} · marker on map
            </p>
          )}
        </>
      )}

      {phase === 'LANDED' && (
        <div className="prediction-actions">
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={onRecover}
          >
            Mark recovered
          </button>
        </div>
      )}
      {phase === 'RECOVERED' && (
        <p className="muted small" style={{ marginTop: '0.5rem' }}>
          Status: <strong>RECOVERED</strong>
        </p>
      )}
    </div>
  );
}
