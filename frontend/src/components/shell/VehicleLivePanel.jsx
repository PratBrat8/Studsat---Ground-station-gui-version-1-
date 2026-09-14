import React, { Component } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { useSettingsStore } from '../../state/settingsStore.js';
import {
  disconnectVehicleLink,
  setVehicleSimulate,
} from '../../services/vehicleBridge.js';
import PhaseBadge from './PhaseBadge.jsx';
import MissionClock from './MissionClock.jsx';
import ValueGrid from '../telemetry/ValueGrid.jsx';
import HorizonHUD from '../attitude/HorizonHUD.jsx';
import CompassDial from '../attitude/CompassDial.jsx';
import Body3D from '../attitude/Body3D.jsx';
import GraphsPanel from '../graphs/GraphsPanel.jsx';
import MapPanel from '../map/MapPanel.jsx';
import LandingPredictionCard from '../prediction/LandingPredictionCard.jsx';
import PacketMonitor from '../packets/PacketMonitor.jsx';
import LandingAnimationOverlay from '../landing/LandingAnimationOverlay.jsx';
import { fmt } from '../../utils/format.js';

/** Catch WebGL / map / chart errors so one panel cannot blank the whole tab. */
class PanelErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel-error">
          <div className="panel-title">{this.props.label || 'Panel'}</div>
          <p className="muted small">
            Failed to render: {this.state.error.message || String(this.state.error)}
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * Per-vehicle live screen (Phases 5–6):
 * value grid, HUD, compass, 3D, offline map, graphs.
 */
export default function VehicleLivePanel({ vehicle, compactToolbar = false }) {
  const useStore = useVehicleStore(vehicle);
  const phase = useStore((s) => s.phase);
  const link = useStore((s) => s.link);
  const wsConnected = useStore((s) => s.wsConnected);
  const packets = useStore((s) => s.packets);
  const historyLen = useStore((s) => s.history.altitude.length);
  const trailLen = useStore((s) => s.trail.length);

  const mode = useSettingsStore((s) =>
    vehicle === 'rocket' ? s.rocketMode : s.satelliteMode
  );
  const simulate = useSettingsStore((s) =>
    vehicle === 'rocket' ? s.rocketSimulate : s.satelliteSimulate
  );
  const busy = useSettingsStore((s) => s.busy[vehicle]);
  const setActionError = useSettingsStore((s) => s.setActionError);
  const setBusy = useSettingsStore((s) => s.setBusy);

  const accent = vehicle === 'rocket' ? 'rocket' : 'satellite';
  const title = vehicle === 'rocket' ? 'Rocket' : 'Satellite';
  const linkOk = link.state === 'CONNECTED';
  const isLive = mode != null || wsConnected;
  const isReplay = mode === 'replay';

  const onQuickSim = async () => {
    setBusy(vehicle, true);
    setActionError(null);
    try {
      await setVehicleSimulate(vehicle, !simulate);
    } catch (err) {
      setActionError(err.message || String(err));
    } finally {
      setBusy(vehicle, false);
    }
  };

  const onDisconnect = async () => {
    setBusy(vehicle, true);
    try {
      await disconnectVehicleLink(vehicle);
    } catch (err) {
      setActionError(err.message || String(err));
    } finally {
      setBusy(vehicle, false);
    }
  };

  return (
    <section className="live-panel live-panel-v5">
      <LandingAnimationOverlay vehicle={vehicle} />

      <header className="live-header">
        <div>
          <span className={`vehicle-badge ${accent}`}>{title}</span>
          <h1>{title} telemetry</h1>
        </div>
        <div className="live-header-meta">
          <MissionClock vehicle={vehicle} />
          <PhaseBadge phase={phase} />
          <span className={`link-pill ${linkOk ? 'ok' : 'bad'}`}>
            {link.state || 'DISCONNECTED'}
          </span>
          <span className={`link-pill ${wsConnected ? 'ok' : ''}`}>
            WS {wsConnected ? 'open' : 'closed'}
          </span>
          {mode && <span className="link-pill mode">{mode.toUpperCase()}</span>}
        </div>
      </header>

      <div className="live-toolbar">
        {!compactToolbar && !isReplay && (
          <>
            <button
              type="button"
              className={`btn ${simulate ? 'danger' : 'primary'}`}
              disabled={busy}
              onClick={onQuickSim}
            >
              {simulate ? 'Stop simulation' : 'Start simulation'}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy || !isLive}
              onClick={onDisconnect}
            >
              Disconnect
            </button>
          </>
        )}
        {isReplay && (
          <span className="link-pill mode">REPLAY</span>
        )}
        <span className="muted small">
          Rate {fmt(link.packet_rate_hz, 1, 'Hz')} · frames{' '}
          {packets.frames_ok ?? 0} · hist {historyLen} · trail {trailLen}
        </span>
      </div>

      {!isLive && !isReplay && (
        <div className="banner info">
          Not connected. Click <strong>Start simulation</strong> to drive HUD,
          3D body, map trail, and graphs through the real backend pipeline.
          Sessions are logged continuously to <code>logs/</code>.
        </div>
      )}

      <ValueGrid vehicle={vehicle} />

      <div className="attitude-row">
        <PanelErrorBoundary label="Attitude HUD">
          <HorizonHUD vehicle={vehicle} />
        </PanelErrorBoundary>
        <PanelErrorBoundary label="Compass">
          <CompassDial vehicle={vehicle} />
        </PanelErrorBoundary>
        <PanelErrorBoundary label="3D body">
          <Body3D vehicle={vehicle} />
        </PanelErrorBoundary>
      </div>

      <div className="map-prediction-row">
        <PanelErrorBoundary label="Map">
          <MapPanel vehicle={vehicle} />
        </PanelErrorBoundary>
        <PanelErrorBoundary label="Landing prediction">
          <LandingPredictionCard vehicle={vehicle} />
        </PanelErrorBoundary>
      </div>

      <PanelErrorBoundary label="Packet monitor">
        <PacketMonitor vehicle={vehicle} />
      </PanelErrorBoundary>

      <PanelErrorBoundary label="Graphs">
        <GraphsPanel vehicle={vehicle} />
      </PanelErrorBoundary>

      <p className="muted small footer-note">
        Phase 10 · continuous CSV logging + replay · resilience pass Phase 11 ·
        packaging Phase 12
      </p>
    </section>
  );
}
