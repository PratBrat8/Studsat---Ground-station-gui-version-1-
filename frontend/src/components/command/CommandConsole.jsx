import React, { useCallback, useEffect, useState } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { useSettingsStore } from '../../state/settingsStore.js';
import {
  refreshCommands,
  sendVehicleCommand,
} from '../../services/vehicleBridge.js';
import CommandLog from './CommandLog.jsx';
import EjectButton from './EjectButton.jsx';
import HoldConfirmButton from './HoldConfirmButton.jsx';

function utcHms() {
  return new Date().toISOString().slice(11, 19);
}

function statusClass(status) {
  if (status === 'TRANSMITTED') return 'ok';
  if (status === 'TX_ERROR' || status === 'NO_RESPONSE') return 'bad';
  return '';
}

/**
 * Command Console (PRD A.5.1 / A.5.7 / Phase 11).
 * TX ON/OFF, set time, calibration, hold-to-confirm EJ, command log.
 * Status is transport-only: SENT → TRANSMITTED on +OK; never ACKED.
 */
export default function CommandConsole({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const lastCommand = useStore((s) => s.lastCommand);
  const commands = useStore((s) => s.commands);
  const setLastCommand = useStore((s) => s.setLastCommand);
  const mode = useSettingsStore((s) =>
    vehicle === 'rocket' ? s.rocketMode : s.satelliteMode
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [utcTime, setUtcTime] = useState(utcHms);
  const [timeDirty, setTimeDirty] = useState(false);

  const linked = mode === 'sim' || mode === 'serial';
  const isRocket = vehicle === 'rocket';

  useEffect(() => {
    if (!linked) return undefined;
    refreshCommands(vehicle).catch(() => {});
    const t = setInterval(() => {
      refreshCommands(vehicle).catch(() => {});
    }, 1000);
    return () => clearInterval(t);
  }, [vehicle, linked]);

  useEffect(() => {
    if (timeDirty) return undefined;
    const t = setInterval(() => setUtcTime(utcHms()), 1000);
    return () => clearInterval(t);
  }, [timeDirty]);

  const run = useCallback(
    async (type, extra = {}) => {
      setBusy(true);
      setError(null);
      try {
        const rec = await sendVehicleCommand(vehicle, type, extra);
        setLastCommand(rec);
        return rec;
      } catch (err) {
        setError(err.message || String(err));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [vehicle, setLastCommand]
  );

  const sendTxOn = () => run('TX', { on: true }).catch(() => {});
  const sendTxOff = () =>
    run('TX', { on: false, confirmed: true }).catch(() => {});
  const sendCal = (kind) => run(kind).catch(() => {});
  const sendTime = () => {
    const t = (utcTime || '').trim();
    if (!/^\d{2}:\d{2}:\d{2}$/.test(t)) {
      setError('Set time needs UTC HH:MM:SS');
      return;
    }
    run('ST', { utc_time: t }).catch(() => {});
  };
  const sendEj = () => run('EJ', { confirmed: true }).catch(() => {});

  return (
    <section className="command-console" aria-label={`${vehicle} command console`}>
      <header className="command-console-head">
        <h2>Command console</h2>
        <span className="muted small">
          Transport ack only — SENT → TRANSMITTED on +OK, never ACKED
        </span>
      </header>

      {!linked && (
        <p className="muted small">
          Start simulation (or connect serial) before sending commands.
        </p>
      )}

      <div className="command-group">
        <div className="vg-label">Vehicle power (TX)</div>
        <div className="command-row">
          <button
            type="button"
            className="btn primary"
            disabled={busy || !linked}
            onClick={sendTxOn}
          >
            TX ON
          </button>
          <HoldConfirmButton
            holdMs={1000}
            disabled={busy || !linked}
            className="btn danger"
            ariaLabel="Hold one second to send telemetry TX OFF"
            onConfirm={sendTxOff}
          >
            Hold 1s TX OFF
          </HoldConfirmButton>
          <span className="muted small">
            CMD,&lt;TEAM_ID&gt;,TX,ON|OFF — OFF is hold-gated
          </span>
        </div>
      </div>

      <div className="command-group">
        <div className="vg-label">Set time (UTC)</div>
        <div className="command-row">
          <input
            className="command-time-input"
            type="text"
            spellCheck={false}
            value={utcTime}
            aria-label="UTC time HH:MM:SS"
            disabled={busy || !linked}
            onChange={(e) => {
              setTimeDirty(true);
              setUtcTime(e.target.value);
            }}
          />
          <button
            type="button"
            className="btn"
            disabled={busy || !linked}
            onClick={() => {
              setUtcTime(utcHms());
              setTimeDirty(false);
            }}
          >
            Use clock
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || !linked}
            onClick={sendTime}
          >
            Set time
          </button>
        </div>
      </div>

      <div className="command-group">
        <div className="vg-label">Calibrate</div>
        <div className="command-row">
          <button
            type="button"
            className="btn"
            disabled={busy || !linked}
            onClick={() => sendCal('CG')}
          >
            Cal gyro (CG)
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || !linked}
            onClick={() => sendCal('CB')}
          >
            Cal baro (CB)
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || !linked}
            onClick={() => sendCal('CA')}
          >
            Cal accel (CA)
          </button>
        </div>
      </div>

      {isRocket && (
        <div className="command-group">
          <div className="vg-label">Manual CanSat ejection</div>
          <EjectButton disabled={!linked} busy={busy} onFire={sendEj} />
        </div>
      )}

      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      {lastCommand && (
        <div className={`command-status ${statusClass(lastCommand.status)}`}>
          <strong>{lastCommand.type}</strong> {lastCommand.command}
          <span className={`link-pill ${statusClass(lastCommand.status)}`}>
            {lastCommand.status}
          </span>
          {lastCommand.status === 'SENT' && (
            <span className="muted small">
              waiting for +OK · 3s timeout → NO_RESPONSE
            </span>
          )}
          {lastCommand.note && (
            <span className="muted small">{lastCommand.note}</span>
          )}
        </div>
      )}

      <CommandLog commands={commands} />
    </section>
  );
}
