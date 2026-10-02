import React from 'react';
import HoldConfirmButton from './HoldConfirmButton.jsx';

const EJ_HOLD_MS = 2000;

/**
 * Manual CanSat ejection — Rocket/Avionics only (PRD A.5.1 / G15).
 * Hold ~2s; a single click never sends EJ.
 */
export default function EjectButton({ disabled, busy, onFire }) {
  return (
    <div className="command-ej">
      <HoldConfirmButton
        holdMs={EJ_HOLD_MS}
        disabled={disabled || busy}
        className="btn danger"
        ariaLabel="Hold two seconds to fire manual CanSat ejection"
        onConfirm={onFire}
      >
        {busy ? 'Sending EJ…' : 'Hold 2s to fire EJ'}
      </HoldConfirmButton>
      <p className="muted small command-ej-note">
        Rocket / Avionics only · CMD,&lt;TEAM_ID&gt;,EJ,R · hold-to-confirm, never a
        single click
      </p>
    </div>
  );
}
