import React, { useCallback, useEffect, useState } from 'react';
import * as api from '../../services/api.js';
import {
  startReplaySession,
  stopReplaySession,
} from '../../services/vehicleBridge.js';

const SPEEDS = [0.25, 0.5, 1, 2, 5, 10];

/**
 * Session list + play/pause/speed for CSV replay (PRD A.6.3 / Phase 10).
 */
export default function ReplayControls({ onVehicleChange }) {
  const [sessions, setSessions] = useState([]);
  const [selected, setSelected] = useState('');
  const [speed, setSpeed] = useState(2);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refreshSessions = useCallback(async () => {
    try {
      const data = await api.listReplaySessions();
      setSessions(data.sessions || []);
    } catch (err) {
      setError(err.message || String(err));
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const st = await api.fetchReplayStatus();
      setStatus(st);
      if (st?.vehicle && onVehicleChange) {
        onVehicleChange(st.vehicle);
      }
    } catch {
      /* ignore */
    }
  }, [onVehicleChange]);

  useEffect(() => {
    refreshSessions();
    refreshStatus();
    const t = setInterval(refreshStatus, 500);
    return () => clearInterval(t);
  }, [refreshSessions, refreshStatus]);

  const onPlay = async () => {
    if (!selected) {
      setError('Select a session CSV first');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await startReplaySession(selected, speed);
      setStatus(data);
      if (data.vehicle && onVehicleChange) onVehicleChange(data.vehicle);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const onStop = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await stopReplaySession();
      setStatus(data);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const onPauseToggle = async () => {
    if (!status?.running) return;
    setBusy(true);
    try {
      const data = await api.pauseReplay(!status.paused);
      setStatus(data);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const onSpeedChange = async (v) => {
    const s = Number(v);
    setSpeed(s);
    if (status?.running) {
      try {
        const data = await api.setReplaySpeed(s);
        setStatus(data);
      } catch {
        /* ignore */
      }
    }
  };

  const running = Boolean(status?.running);
  const progressPct = Math.round((status?.progress || 0) * 100);

  return (
    <div className="replay-controls">
      <header className="replay-controls-head">
        <div>
          <h1>Replay</h1>
          <p className="muted">
            Load a logged CSV and scrub through the <strong>same</strong> live
            panels (HUD, map, graphs, packet monitor). Backend re-feeds the real
            protocol parser — not a UI-only mock.
          </p>
        </div>
        <button
          type="button"
          className="btn"
          onClick={refreshSessions}
          disabled={busy}
        >
          Refresh list
        </button>
      </header>

      {error && (
        <div className="banner error" role="alert">
          {error}
          <button
            type="button"
            className="banner-dismiss"
            onClick={() => setError(null)}
          >
            ×
          </button>
        </div>
      )}

      <div className="replay-toolbar">
        <label className="field">
          <span className="field-label">Session</span>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            disabled={busy || running}
          >
            <option value="">— choose log —</option>
            {sessions.map((s) => (
              <option key={s.filename} value={s.filename}>
                {s.filename} · {s.vehicle} · {s.sample_count} samples ·{' '}
                {s.duration_s}s
              </option>
            ))}
          </select>
        </label>

        <label className="field inline">
          <span className="field-label">Speed</span>
          <select
            value={speed}
            onChange={(e) => onSpeedChange(e.target.value)}
            disabled={busy}
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>

        <div className="btn-row" style={{ marginTop: 0 }}>
          {!running ? (
            <button
              type="button"
              className="btn primary"
              disabled={busy || !selected}
              onClick={onPlay}
            >
              Play
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={onPauseToggle}
              >
                {status?.paused ? 'Resume' : 'Pause'}
              </button>
              <button
                type="button"
                className="btn danger"
                disabled={busy}
                onClick={onStop}
              >
                Stop
              </button>
            </>
          )}
        </div>
      </div>

      {running && (
        <div className="replay-progress">
          <div className="replay-progress-bar">
            <div
              className="replay-progress-fill"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="muted small">
            {status.filename} · {status.vehicle} · {status.index}/{status.total}{' '}
            ({progressPct}%) · {status.speed}×
            {status.paused ? ' · PAUSED' : ''}
          </div>
        </div>
      )}

      {!sessions.length && (
        <div className="banner info">
          No session logs yet. Run <strong>Start simulation</strong> on Rocket or
          Satellite — CSV is written continuously to <code>logs/</code>.
        </div>
      )}
    </div>
  );
}
