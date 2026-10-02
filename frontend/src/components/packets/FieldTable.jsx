import React, { useMemo } from 'react';

const TYPE_LABELS = {
  1: 'TELEMETRY',
  2: 'GPS',
  3: 'STATUS',
  4: 'EVENT',
};

function formatValue(v) {
  if (v == null) return '—';
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(4).replace(/\.?0+$/, (m) => (m.includes('.') ? m.replace(/0+$/, '').replace(/\.$/, '') : m));
  }
  return String(v);
}

/**
 * Parsed field table for the selected / latest frame (PRD C.5).
 */
export default function FieldTable({ packet, lastByType }) {
  const rows = useMemo(() => {
    if (packet?.fields && Object.keys(packet.fields).length) {
      return Object.entries(packet.fields).map(([k, v]) => ({
        name: k,
        value: formatValue(v),
      }));
    }
    return [];
  }, [packet]);

  const typeSummary = useMemo(() => {
    if (!lastByType || typeof lastByType !== 'object') return [];
    return Object.entries(lastByType).map(([typeId, rec]) => ({
      typeId: Number(typeId),
      name: rec?.type_name || TYPE_LABELS[Number(typeId)] || typeId,
      seq: rec?.seq,
      t: rec?.t,
      ok: rec?.ok,
    }));
  }, [lastByType]);

  if (!packet && typeSummary.length === 0) {
    return (
      <div className="field-table empty muted small">No parsed fields yet</div>
    );
  }

  return (
    <div className="field-table-wrap">
      {packet && (
        <div className="field-meta muted small">
          <span>
            {packet.type_name || TYPE_LABELS[packet.type] || `type ${packet.type}`}
          </span>
          <span>{packet.layer === 'transport' ? 'transport' : 'application'}</span>
          <span>seq {packet.seq ?? '—'}</span>
          <span>len {packet.len ?? '—'}</span>
          {packet.rssi != null && <span>RSSI {packet.rssi} dBm</span>}
          {packet.snr != null && <span>SNR {packet.snr}</span>}
          <span className={packet.ok === false ? 'bad' : 'ok'}>
            {packet.ok === false
              ? `ERR ${packet.error || ''}`
              : packet.layer === 'transport'
                ? 'AT OK'
                : 'CSV OK'}
          </span>
        </div>
      )}

      {packet?.error && (
        <div className="banner error" style={{ margin: '0.35rem 0' }}>
          {packet.layer === 'transport' ? 'Transport' : 'Application'}: {packet.error}
        </div>
      )}

      <table className="field-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={2} className="muted">
                No payload fields
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr key={r.name}>
                <td className="field-name">{r.name}</td>
                <td className="field-value">{r.value}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      {typeSummary.length > 0 && (
        <div className="last-by-type">
          <div className="vg-label" style={{ marginTop: '0.65rem' }}>
            Last frame per type
          </div>
          <ul className="type-list">
            {typeSummary.map((t) => (
              <li key={t.typeId}>
                <strong>{t.name}</strong>
                <span className="muted"> seq {t.seq}</span>
                {t.ok === false && <span className="bad"> bad</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
