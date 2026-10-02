/**
 * Google Maps recovery handoff (PRD v2 A.5.10 / G21).
 * Builds the exact URL the Electron main process allowlists.
 * This is the one explicitly-online action in an otherwise offline app.
 */

export function isValidGps(lat, lon) {
  const la = Number(lat);
  const lo = Number(lon);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return false;
  if (la === 0 && lo === 0) return false;
  return Math.abs(la) <= 90 && Math.abs(lo) <= 180;
}

export function googleMapsHandoffUrl(lat, lon) {
  if (!isValidGps(lat, lon)) return null;
  const la = Number(lat).toFixed(6);
  const lo = Number(lon).toFixed(6);
  return `https://www.google.com/maps?q=${la},${lo}`;
}

/**
 * Open the last known fix in the OS default browser.
 * Electron: preload IPC → shell.openExternal (never inside the GS window).
 * Vite/browser: window.open as a fallback.
 */
export async function openGoogleMapsHandoff(lat, lon) {
  const url = googleMapsHandoffUrl(lat, lon);
  if (!url) {
    throw new Error('No valid GPS fix to hand off');
  }
  if (typeof window !== 'undefined' && window.studsat?.openExternal) {
    const result = await window.studsat.openExternal(url);
    if (result && result.ok === false) {
      throw new Error(result.error || 'Failed to open system browser');
    }
    return url;
  }
  const opened = window.open(url, '_blank', 'noopener,noreferrer');
  if (!opened) {
    throw new Error('Popup blocked — allow popups or run inside Electron');
  }
  return url;
}
