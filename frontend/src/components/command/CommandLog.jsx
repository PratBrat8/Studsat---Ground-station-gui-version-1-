import React from 'react';

function statusClass(status) {
  if (status === 'TRANSMITTED') return 'ok';
  if (status === 'TX_ERROR' || status === 'NO_RESPONSE') return 'bad';
  if (status === 'SENT') return 'mode';
  return '';
}

function formatTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toISOString().slice(11, 23) + 'Z';
}

/**
 * Timestamped uplink command log (PRD A.5.1 / Phase 11).
 */
export default function CommandLog({
  commands,
  heading = 'Command log',
  emptyLabel = 'No commands sent this session.',
}) {
  const rows = Array.isArray(commands) ? commands : [];

  return (
    <div className="command-log" aria-label={heading}>
      <div className="vg-label">{heading}</div>
      {rows.length === 0 ? (
        <p className="muted small">{emptyLabel}</p>
      ) : (
        <div className="command-log-table-wrap">
          <table className="command-log-table">
            <thead>
              <tr>
                <th>UTC</th>
                <th>Type</th>
                <th>Command</th>
                <th>Status</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id || `${c.sent_at}-${c.command}`}>
                  <td className="muted">{formatTime(c.sent_at)}</td>
                  <td>{c.type}</td>
                  <td>
                    <code>{c.command}</code>
                  </td>
                  <td>
                    <span className={`link-pill ${statusClass(c.status)}`}>
                      {c.status}
                    </span>
                  </td>
                  <td className="muted small">
                    {c.error || c.note || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
