/**
 * REST client for the Python backend (PRD C.3 / Phase 4).
 * Vite dev: same-origin + proxy. Electron file://: 127.0.0.1:8765.
 */

const DEFAULT_BASE =
  typeof window !== 'undefined' && window.location?.protocol === 'file:'
    ? 'http://127.0.0.1:8765'
    : '';

export function getApiBase() {
  if (typeof window !== 'undefined' && window.studsat?.apiBase) {
    return window.studsat.apiBase;
  }
  return DEFAULT_BASE;
}

async function request(path, options = {}) {
  const res = await fetch(`${getApiBase()}${path}`, {
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
    ...options,
  });
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }
  if (!res.ok) {
    const detail = data?.detail || data?.raw || res.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

export async function fetchHealth() {
  return request('/health');
}

export async function fetchPorts() {
  return request('/ports');
}

export async function fetchStatus() {
  return request('/status');
}

export async function connectVehicle(vehicle, port, baud = 115200) {
  return request('/connect', {
    method: 'POST',
    body: JSON.stringify({ vehicle, port, baud: Number(baud) }),
  });
}

export async function disconnectVehicle(vehicle) {
  return request('/disconnect', {
    method: 'POST',
    body: JSON.stringify({ vehicle }),
  });
}

export async function setSimulate(vehicle, enabled) {
  return request('/simulate', {
    method: 'POST',
    body: JSON.stringify({ vehicle, enabled: Boolean(enabled) }),
  });
}

/** Operator: LANDED → RECOVERED (PRD B.4). */
export async function markRecovered(vehicle) {
  return request('/recover', {
    method: 'POST',
    body: JSON.stringify({ vehicle }),
  });
}

// --- Replay / logs (Phase 10) ---

export async function listReplaySessions() {
  return request('/replay/sessions');
}

export async function loadReplay(filename, speed = 1, vehicle = null) {
  const body = { filename, speed: Number(speed) };
  if (vehicle) body.vehicle = vehicle;
  return request('/replay/load', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function stopReplay() {
  return request('/replay/stop', { method: 'POST', body: '{}' });
}

export async function pauseReplay(paused = true) {
  return request('/replay/pause', {
    method: 'POST',
    body: JSON.stringify({ paused: Boolean(paused) }),
  });
}

export async function setReplaySpeed(speed) {
  return request('/replay/speed', {
    method: 'POST',
    body: JSON.stringify({ speed: Number(speed) }),
  });
}

export async function fetchReplayStatus() {
  return request('/replay/status');
}
