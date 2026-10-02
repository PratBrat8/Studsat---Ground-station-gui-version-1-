import React from 'react';

const PHASE_CLASS = {
  IDLE: 'phase-idle',
  BOOT: 'phase-idle',
  TEST_MODE: 'phase-armed',
  LAUNCH_PAD: 'phase-armed',
  ARMED: 'phase-armed',
  ASCENT: 'phase-ascent',
  PAYLOAD_SEP: 'phase-apogee',
  APOGEE: 'phase-apogee',
  DESCENT: 'phase-descent',
  AEROBREAK_RELEASE: 'phase-descent',
  IMPACT: 'phase-landed',
  LANDED: 'phase-landed',
  RECOVERED: 'phase-recovered',
};

export default function PhaseBadge({ phase = 'IDLE' }) {
  const cls = PHASE_CLASS[phase] || 'phase-idle';
  return <span className={`phase-badge ${cls}`}>{phase}</span>;
}
