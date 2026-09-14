/**
 * Per-vehicle WebSocket client (PRD C.4).
 * Opens /ws/{vehicle}, dispatches snapshot/update into the matching Zustand store.
 */

import { getApiBase } from './api.js';

const HISTORY_CAP = 600;

function wsUrl(vehicle) {
  // Electron preload may expose wsBase
  if (typeof window !== 'undefined' && window.studsat?.wsBase) {
    return `${window.studsat.wsBase}/ws/${vehicle}`;
  }
  const base = getApiBase();
  if (base) {
    // http(s)://host:port → ws(s)://host:port
    const wsBase = base.replace(/^http/, 'ws');
    return `${wsBase}/ws/${vehicle}`;
  }
  // Vite dev: same host, proxied
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/${vehicle}`;
}

/**
 * @param {string} vehicle 'rocket' | 'satellite'
 * @param {{ applyUpdate: Function, setWsConnected?: Function }} storeApi
 *   Zustand store getState()-like handlers
 */
export function createWsClient(vehicle, storeApi) {
  let socket = null;
  let intentionalClose = false;
  let reconnectTimer = null;
  let pingTimer = null;
  let reconnectAttempt = 0;

  function clearTimers() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  function handleMessage(event) {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === 'pong') return;

    try {
      storeApi.applyUpdate(msg);
    } catch (err) {
      console.error(`[ws:${vehicle}] applyUpdate failed`, err);
    }
  }

  function scheduleReconnect() {
    if (intentionalClose) return;
    const delay = Math.min(5000, 500 * 2 ** reconnectAttempt);
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => {
      connect();
    }, delay);
  }

  function connect() {
    intentionalClose = false;
    clearTimers();

    if (socket) {
      try {
        socket.onclose = null;
        socket.close();
      } catch {
        /* ignore */
      }
      socket = null;
    }

    const url = wsUrl(vehicle);
    let ws;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      console.error(`[ws:${vehicle}] open failed`, err);
      scheduleReconnect();
      return;
    }
    socket = ws;

    ws.onopen = () => {
      reconnectAttempt = 0;
      storeApi.setWsConnected?.(true);
      pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({ type: 'ping' }));
          } catch {
            /* ignore */
          }
        }
      }, 15000);
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      // onclose will follow
    };

    ws.onclose = () => {
      storeApi.setWsConnected?.(false);
      clearTimers();
      socket = null;
      if (!intentionalClose) {
        scheduleReconnect();
      }
    };
  }

  function disconnect() {
    intentionalClose = true;
    clearTimers();
    if (socket) {
      try {
        socket.close();
      } catch {
        /* ignore */
      }
      socket = null;
    }
    storeApi.setWsConnected?.(false);
  }

  function isConnected() {
    return socket != null && socket.readyState === WebSocket.OPEN;
  }

  return { connect, disconnect, isConnected, HISTORY_CAP };
}

/** Shared helpers for history capping used by vehicle stores. */
export function capHistory(arr, max = HISTORY_CAP) {
  if (!Array.isArray(arr)) return [];
  if (arr.length <= max) return arr;
  return arr.slice(arr.length - max);
}
