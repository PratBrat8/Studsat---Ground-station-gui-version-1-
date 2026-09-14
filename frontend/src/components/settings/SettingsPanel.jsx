import React, { useCallback, useEffect, useState } from 'react';
import PortSelector from './PortSelector.jsx';
import { useSettingsStore } from '../../state/settingsStore.js';
import {
  connectVehicleSerial,
  disconnectVehicleLink,
  refreshBackendStatus,
  refreshPorts,
  setVehicleSimulate,
} from '../../services/vehicleBridge.js';
import { fetchTilesInfo } from '../../services/tiles.js';

const BAUD_OPTIONS = [9600, 57600, 115200, 230400, 460800, 921600];

function VehicleSettingsCard({ vehicle, title, accentClass }) {
  const ports = useSettingsStore((s) => s.ports);
  const baud = useSettingsStore((s) => s.baud);
  const busy = useSettingsStore((s) => s.busy[vehicle]);
  const port = useSettingsStore((s) =>
    vehicle === 'rocket' ? s.rocketPort : s.satellitePort
  );
  const simulate = useSettingsStore((s) =>
    vehicle === 'rocket' ? s.rocketSimulate : s.satelliteSimulate
  );
  const mode = useSettingsStore((s) =>
    vehicle === 'rocket' ? s.rocketMode : s.satelliteMode
  );
  const setPort = useSettingsStore((s) =>
    vehicle === 'rocket' ? s.setRocketPort : s.setSatellitePort
  );
  const setActionError = useSettingsStore((s) => s.setActionError);
  const setBusy = useSettingsStore((s) => s.setBusy);

  const run = useCallback(
    async (fn) => {
      setBusy(vehicle, true);
      setActionError(null);
      try {
        await fn();
        await refreshBackendStatus().catch(() => {});
      } catch (err) {
        setActionError(`${title}: ${err.message || String(err)}`);
      } finally {
        setBusy(vehicle, false);
      }
    },
    [vehicle, title, setBusy, setActionError]
  );

  const onToggleSim = () => {
    run(() => setVehicleSimulate(vehicle, !simulate));
  };

  const onConnect = () => {
    if (!port) {
      setActionError(`${title}: choose a COM port first`);
      return;
    }
    run(() => connectVehicleSerial(vehicle, port, baud));
  };

  const onDisconnect = () => {
    run(() => disconnectVehicleLink(vehicle));
  };

  return (
    <section className={`settings-card ${accentClass}`}>
      <header className="settings-card-head">
        <h2>{title}</h2>
        <span className={`mode-pill ${mode || 'off'}`}>
          {mode === 'sim' ? 'SIM' : mode === 'serial' ? 'SERIAL' : 'OFF'}
        </span>
      </header>

      <div className="settings-row">
        <label className="toggle">
          <input
            type="checkbox"
            checked={simulate}
            disabled={busy}
            onChange={onToggleSim}
          />
          <span>Simulation mode</span>
        </label>
        <p className="hint">
          Streams synthetic frames through the real protocol parser (not a UI
          mock).
        </p>
      </div>

      <div className="settings-row serial-block" aria-disabled={simulate}>
        <PortSelector
          label="Serial port"
          ports={ports}
          value={port}
          onChange={setPort}
          disabled={busy || simulate}
        />
        <div className="btn-row">
          <button
            type="button"
            className="btn primary"
            disabled={busy || simulate || !port}
            onClick={onConnect}
          >
            Connect serial
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || (!mode && !simulate)}
            onClick={onDisconnect}
          >
            Disconnect
          </button>
        </div>
      </div>
    </section>
  );
}

export default function SettingsPanel() {
  const baud = useSettingsStore((s) => s.baud);
  const setBaud = useSettingsStore((s) => s.setBaud);
  const portsLoading = useSettingsStore((s) => s.portsLoading);
  const portsError = useSettingsStore((s) => s.portsError);
  const actionError = useSettingsStore((s) => s.actionError);
  const setPortsLoading = useSettingsStore((s) => s.setPortsLoading);
  const setPortsError = useSettingsStore((s) => s.setPortsError);
  const setActionError = useSettingsStore((s) => s.setActionError);
  const lastPortsRefresh = useSettingsStore((s) => s.lastPortsRefresh);
  const backendConnections = useSettingsStore((s) => s.backendConnections);
  const [localMsg, setLocalMsg] = useState('');
  const [tilesInfo, setTilesInfo] = useState(null);

  const doRefreshPorts = useCallback(async () => {
    setPortsLoading(true);
    setPortsError(null);
    try {
      const ports = await refreshPorts();
      setLocalMsg(`Found ${ports.length} port(s)`);
      await refreshBackendStatus().catch(() => {});
    } catch (err) {
      setPortsError(err.message || String(err));
    } finally {
      setPortsLoading(false);
    }
  }, [setPortsLoading, setPortsError]);

  useEffect(() => {
    doRefreshPorts();
    fetchTilesInfo()
      .then(setTilesInfo)
      .catch(() => setTilesInfo(null));
    const t = setInterval(() => {
      refreshPorts().catch(() => {});
      refreshBackendStatus().catch(() => {});
    }, 5000);
    return () => clearInterval(t);
  }, [doRefreshPorts]);

  return (
    <div className="settings-panel">
      <header className="settings-header">
        <div>
          <h1>Settings</h1>
          <p className="muted">
            Assign serial ports independently, or enable simulation per vehicle.
          </p>
        </div>
        <div className="settings-header-actions">
          <label className="field inline">
            <span className="field-label">Baud</span>
            <select
              value={baud}
              onChange={(e) => setBaud(Number(e.target.value))}
            >
              {BAUD_OPTIONS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn"
            onClick={doRefreshPorts}
            disabled={portsLoading}
          >
            {portsLoading ? 'Refreshing…' : 'Refresh ports'}
          </button>
        </div>
      </header>

      {(actionError || portsError) && (
        <div className="banner error" role="alert">
          {actionError || portsError}
          <button
            type="button"
            className="banner-dismiss"
            onClick={() => {
              setActionError(null);
              setPortsError(null);
            }}
          >
            ×
          </button>
        </div>
      )}
      {localMsg && !actionError && (
        <div className="banner info">
          {localMsg}
          {lastPortsRefresh
            ? ` · updated ${new Date(lastPortsRefresh).toLocaleTimeString()}`
            : ''}
        </div>
      )}

      <div className="settings-grid">
        <VehicleSettingsCard
          vehicle="rocket"
          title="Rocket"
          accentClass="accent-rocket"
        />
        <VehicleSettingsCard
          vehicle="satellite"
          title="Satellite"
          accentClass="accent-sat"
        />
      </div>

      {tilesInfo && (
        <div className="settings-card" style={{ marginTop: '1rem' }}>
          <header className="settings-card-head">
            <h2>Offline map tiles</h2>
            <span className={`mode-pill ${tilesInfo.using_placeholders ? 'off' : 'serial'}`}>
              {tilesInfo.using_placeholders ? 'PLACEHOLDERS' : 'FILES'}
            </span>
          </header>
          <p className="hint" style={{ margin: 0 }}>
            Dir: <code>{tilesInfo.tiles_dir}</code>
            <br />
            Files: {tilesInfo.tile_file_count} · URL:{' '}
            <code>{tilesInfo.url_template}</code>
            <br />
            {tilesInfo.note}
          </p>
        </div>
      )}

      {backendConnections && (
        <details className="status-details">
          <summary>Backend connection status</summary>
          <pre>{JSON.stringify(backendConnections, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
