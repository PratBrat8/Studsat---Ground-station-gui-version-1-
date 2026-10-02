import React from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { fmt } from '../../utils/format.js';

function fillColor(pct) {
  if (pct == null) return 'var(--muted)';
  if (pct <= 15) return 'var(--danger)';
  if (pct <= 35) return 'var(--warn)';
  return 'var(--ok)';
}

function BatteryIcon({ pct }) {
  const fill = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  const color = fillColor(pct);
  return (
    <svg
      className="battery-icon"
      viewBox="0 0 48 24"
      width="56"
      height="28"
      aria-hidden="true"
    >
      <rect
        x="1"
        y="4"
        width="42"
        height="16"
        rx="3"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
      <rect x="43" y="9" width="4" height="6" rx="1" fill="currentColor" />
      <rect
        x="4"
        y="7"
        width={(34 * fill) / 100}
        height="10"
        rx="1.5"
        fill={color}
      />
    </svg>
  );
}

function PctNote() {
  return (
    <p className="muted small">
      % is a TEMPORARY 2S Li-ion 6.0–8.4 V placeholder — not a measured state
      of charge.
    </p>
  );
}

/** Rocket/Avionics: INA219 voltage + current + power + % (PRD A.5.3). */
export function RocketBatteryCard() {
  const t = useVehicleStore('rocket')((s) => s.telemetry);
  const pct = t.battery_pct;
  const currentMissing = t.current_a == null;

  return (
    <article className="status-card battery-card rocket-batt" aria-label="Rocket battery">
      <header className="status-card-head">
        <h2>Battery · Rocket</h2>
        <BatteryIcon pct={pct} />
      </header>
      <div className="batt-grid rocket">
        <div>
          <div className="vg-label">Voltage</div>
          <div className="vg-value">{fmt(t.battery_v, 2, 'V')}</div>
        </div>
        <div>
          <div className="vg-label">Current</div>
          <div className="vg-value">{fmt(t.current_a, 2, 'A')}</div>
        </div>
        <div>
          <div className="vg-label">Power</div>
          <div className="vg-value">{fmt(t.power_w, 1, 'W')}</div>
        </div>
        <div>
          <div className="vg-label">Est. %</div>
          <div className="vg-value" style={{ color: fillColor(pct) }}>
            {pct == null ? '—' : `${Math.round(pct)}%`}
          </div>
        </div>
      </div>
      {currentMissing && (
        <p className="muted small">
          INA219 current/power are not in the 19-field CSV yet — shown as —
          until firmware adds them.
        </p>
      )}
      <PctNote />
    </article>
  );
}

/** CanSat: voltage + % only (no INA219). Separate layout from rocket. */
export function CansatBatteryCard() {
  const t = useVehicleStore('satellite')((s) => s.telemetry);
  const pct = t.battery_pct;

  return (
    <article className="status-card battery-card cansat-batt" aria-label="CanSat battery">
      <header className="status-card-head">
        <h2>Battery · CanSat</h2>
        <BatteryIcon pct={pct} />
      </header>
      <div className="batt-grid cansat">
        <div>
          <div className="vg-label">Voltage</div>
          <div className="vg-value">{fmt(t.battery_v, 2, 'V')}</div>
        </div>
        <div>
          <div className="vg-label">Est. %</div>
          <div className="vg-value" style={{ color: fillColor(pct) }}>
            {pct == null ? '—' : `${Math.round(pct)}%`}
          </div>
        </div>
      </div>
      <PctNote />
    </article>
  );
}

export default function BatteryCard({ vehicle }) {
  return vehicle === 'rocket' ? <RocketBatteryCard /> : <CansatBatteryCard />;
}
