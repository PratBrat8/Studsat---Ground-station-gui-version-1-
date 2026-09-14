import React from 'react';

const PHASE_CLASS = {
  IDLE: 'phase-idle',
  ARMED: 'phase-armed',
  ASCENT: 'phase-ascent',
  APOGEE: 'phase-apogee',
  DESCENT: 'phase-descent',
  LANDED: 'phase-landed',
  RECOVERED: 'phase-recovered',
};

export default function PhaseBadge({ phase = 'IDLE' }) {
  const cls = PHASE_CLASS[phase] || 'phase-idle';
  return <span className={`phase-badge ${cls}`}>{phase}</span>;
}
