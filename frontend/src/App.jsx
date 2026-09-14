import React, { useEffect, useState } from 'react';
import TopBar from './components/shell/TopBar.jsx';
import RocketTab from './components/shell/RocketTab.jsx';
import SatelliteTab from './components/shell/SatelliteTab.jsx';
import ReplayTab from './components/shell/ReplayTab.jsx';
import SettingsTab from './components/shell/SettingsTab.jsx';
import AppErrorBoundary from './components/shell/AppErrorBoundary.jsx';
import { fetchHealth } from './services/api.js';

const TABS = ['rocket', 'satellite', 'replay', 'settings'];

export default function App() {
  const [activeTab, setActiveTab] = useState('rocket');
  const [backendStatus, setBackendStatus] = useState({
    state: 'checking',
    version: null,
    error: null,
  });
  const [toast, setToast] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer;

    async function poll() {
      try {
        const data = await fetchHealth();
        if (!cancelled) {
          setBackendStatus({
            state: 'ok',
            version: data.version ?? 'unknown',
            error: null,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setBackendStatus({
            state: 'err',
            version: null,
            error: err?.message || 'unreachable',
          });
        }
      }
      timer = setTimeout(poll, 3000);
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  // Electron backend crash/recovery toasts (Phase 11)
  useEffect(() => {
    const unsub = window.studsat?.onBackendStatus?.((payload) => {
      if (!payload) return;
      setToast({
        kind: payload.state === 'ok' ? 'info' : 'error',
        text: payload.message || payload.state,
      });
      if (payload.state === 'ok') {
        setBackendStatus((s) => ({ ...s, state: 'ok', error: null }));
      } else if (payload.state === 'err') {
        setBackendStatus((s) => ({
          ...s,
          state: 'err',
          error: payload.message,
        }));
      } else if (payload.state === 'restarting') {
        setBackendStatus((s) => ({
          ...s,
          state: 'checking',
          error: payload.message,
        }));
      }
    });
    return () => {
      if (typeof unsub === 'function') unsub();
    };
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <AppErrorBoundary>
      <div className="app">
        <TopBar
          tabs={TABS}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          backendStatus={backendStatus}
        />
        {toast && (
          <div
            className={`banner ${toast.kind === 'error' ? 'error' : 'info'}`}
            style={{ margin: '0.5rem 1.25rem 0' }}
            role="status"
          >
            {toast.text}
            <button
              type="button"
              className="banner-dismiss"
              onClick={() => setToast(null)}
            >
              ×
            </button>
          </div>
        )}
        {backendStatus.state === 'err' && (
          <div className="banner error" style={{ margin: '0.5rem 1.25rem 0' }}>
            Backend offline — telemetry will resume when it reconnects.
            {window.studsat?.restartBackend && (
              <button
                type="button"
                className="btn"
                style={{ marginLeft: '0.75rem' }}
                onClick={async () => {
                  try {
                    const r = await window.studsat.restartBackend();
                    setToast({
                      kind: r?.ok ? 'info' : 'error',
                      text: r?.ok
                        ? 'Backend restart requested'
                        : r?.error || 'Restart failed',
                    });
                  } catch (err) {
                    setToast({
                      kind: 'error',
                      text: err?.message || 'Restart failed',
                    });
                  }
                }}
              >
                Restart backend
              </button>
            )}
          </div>
        )}
        <main className="main">
          <AppErrorBoundary>
            {activeTab === 'rocket' && <RocketTab />}
            {activeTab === 'satellite' && <SatelliteTab />}
            {activeTab === 'replay' && <ReplayTab />}
            {activeTab === 'settings' && <SettingsTab />}
          </AppErrorBoundary>
        </main>
      </div>
    </AppErrorBoundary>
  );
}
