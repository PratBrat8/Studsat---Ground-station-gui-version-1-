/**
 * Offline tile URL helpers (PRD Phase 6).
 * Never points at OpenStreetMap / MapTiler / any internet host.
 */

import { getApiBase } from './api.js';

/** Default map center — matches backend simulator launch site [ASSUMED]. */
export const DEFAULT_MAP_CENTER = {
  lat: 12.9716,
  lon: 77.5946,
};

export const DEFAULT_MAP_ZOOM = 14;

/**
 * Leaflet tile URL template for local backend XYZ tiles.
 * Vite dev: proxied /tiles → backend. Electron file://: absolute API base.
 */
export function getTileUrlTemplate() {
  const base = getApiBase(); // '' in Vite dev, 'http://127.0.0.1:8765' in Electron
  return `${base}/tiles/{z}/{x}/{y}.png`;
}

export async function fetchTilesInfo() {
  const base = getApiBase();
  const res = await fetch(`${base}/tiles/info`);
  if (!res.ok) throw new Error(`tiles/info ${res.status}`);
  return res.json();
}
