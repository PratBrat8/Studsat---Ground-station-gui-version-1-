/**
 * CDR 8-state flight software field (PRD v2 B.3 / A.5.6).
 * Order is the progress-strip sequence, index = FLIGHT_SOFTWARE_STATE.
 */
export const CDR_STATES = [
  { id: 'BOOT', label: 'BOOT', n: 0 },
  { id: 'TEST_MODE', label: 'TEST', n: 1 },
  { id: 'LAUNCH_PAD', label: 'PAD', n: 2 },
  { id: 'ASCENT', label: 'ASCENT', n: 3 },
  { id: 'PAYLOAD_SEP', label: 'SEP', n: 4 },
  { id: 'DESCENT', label: 'DESCENT', n: 5 },
  { id: 'AEROBREAK_RELEASE', label: 'AERO', n: 6 },
  { id: 'IMPACT', label: 'IMPACT', n: 7 },
];

export function cdrStateIndex(phase, flightSoftwareState) {
  const n = Number(flightSoftwareState);
  if (Number.isInteger(n) && n >= 0 && n <= 7) return n;
  if (phase === 'RECOVERED' || phase === 'LANDED') return 7;
  const i = CDR_STATES.findIndex((s) => s.id === phase);
  return i;
}
