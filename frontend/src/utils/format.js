/** Shared display helpers for telemetry UI. */

export function fmt(value, digits = 2, unit = '') {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  return `${n.toFixed(digits)}${unit ? ` ${unit}` : ''}`;
}

export function fmtSigned(value, digits = 1, unit = '°') {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)}${unit ? unit : ''}`;
}

/** Normalize degrees into [0, 360). */
export function wrap360(deg) {
  if (deg == null || Number.isNaN(Number(deg))) return 0;
  let d = Number(deg) % 360;
  if (d < 0) d += 360;
  return d;
}

/** Clamp value into [min, max]. */
export function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

/**
 * Build recharts-friendly series from a history number array.
 * Uses index as x so charts keep scrolling without wall-clock gaps.
 */
export function historyToSeries(values, maxPoints = 120) {
  if (!Array.isArray(values) || values.length === 0) return [];
  const slice =
    values.length > maxPoints ? values.slice(values.length - maxPoints) : values;
  const offset = values.length > maxPoints ? values.length - maxPoints : 0;
  return slice.map((v, i) => ({
    i: offset + i,
    v: typeof v === 'number' && !Number.isNaN(v) ? v : null,
  }));
}
