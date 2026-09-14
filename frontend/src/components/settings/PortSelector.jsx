import React from 'react';

export default function PortSelector({
  label,
  ports,
  value,
  onChange,
  disabled,
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        <option value="">— select COM port —</option>
        {ports.map((p) => (
          <option key={p.device} value={p.device}>
            {p.device}
            {p.description ? ` — ${p.description}` : ''}
          </option>
        ))}
      </select>
    </label>
  );
}
