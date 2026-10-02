/**
 * Preload — exposes a minimal, safe API to the renderer (PRD C.1 / Phase 11).
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('studsat', {
  apiBase: 'http://127.0.0.1:8765',
  wsBase: 'ws://127.0.0.1:8765',
  platform: process.platform,
  isElectron: true,
  restartBackend: () => ipcRenderer.invoke('studsat:restart-backend'),
  openExternal: (url) => ipcRenderer.invoke('studsat:open-external', url),
  onBackendStatus: (handler) => {
    if (typeof handler !== 'function') return () => {};
    const listener = (_event, payload) => {
      try {
        handler(payload);
      } catch (_) {
        /* never throw into main */
      }
    };
    ipcRenderer.on('studsat:backend-status', listener);
    return () => ipcRenderer.removeListener('studsat:backend-status', listener);
  },
});
