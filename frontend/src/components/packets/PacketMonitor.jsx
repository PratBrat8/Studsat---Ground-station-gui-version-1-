import React, { useEffect, useMemo, useState } from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { getApiBase } from '../../services/api.js';
import HexView from './HexView.jsx';
import FieldTable from './FieldTable.jsx';
import { fmt } from '../../utils/format.js';

/** Mini SVG sparkline for packet rate history. */
function RateSparkline({ values, width = 160, height = 36 }) {
  const pts = useMemo(() => {
    if (!Array.isArray(values) || values.length < 2) return '';
    const max = Math.max(...values, 1e-3);
    const min = Math.min(...values, 0);
    const span = max - min || 1;
    return values
      .map((v, i) => {
        const x = (i / (values.length - 1)) * (width - 2) + 1;
        const y = height - 2 - ((v - min) / span) * (height - 4);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [values, width, height]);

  if (!pts) {
    return <div className="rate-spark empty muted small">rate —</div>;
  }

  return (
    <svg
      className="rate-spark"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label="Packet rate sparkline"
    >
      <polyline
        fill="none"
        stroke="#3d9cf0"
        strokeWidth="1.5"
        points={pts}
      />
    </svg>
  );
}

/**
 * Protocol-level Packet Monitor (PRD v2 Phase 10 / C.5).
 * RSSI/SNR plus transport-layer errors alongside application CSV parse errors.
 */
export default function PacketMonitor({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const packets = useStore((s) => s.packets);
  const link = useStore((s) => s.link);
  const signal = useStore((s) => s.signal);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [pollExtra, setPollExtra] = useState(null);

  // Optional REST poll for fuller ring (PRD C.5 alternative path)
  useEffect(() => {
    let cancelled = false;
    let timer;

    async function poll() {
      try {
        const res = await fetch(
          `${getApiBase()}/packets/${vehicle}?limit=40`
        );
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setPollExtra(data);
        }
      } catch {
        /* offline / backend down — WS path still works */
      }
      timer = setTimeout(poll, 1500);
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [vehicle]);

  // Prefer richer REST snapshot when available; fall back to WS packets
  const recent = useMemo(() => {
    const fromPoll = pollExtra?.recent;
    const fromWs = packets?.recent;
    if (Array.isArray(fromPoll) && fromPoll.length) return fromPoll;
    return Array.isArray(fromWs) ? fromWs : [];
  }, [pollExtra, packets]);

  const lastByType = pollExtra?.last_by_type || packets?.last_by_type || {};
  const rateHistory =
    pollExtra?.rate_history || packets?.rate_history || [];

  const framesOk = pollExtra?.frames_ok ?? packets?.frames_ok ?? link.frames_ok ?? 0;
  const transportBad =
    pollExtra?.transport_malformed ??
    packets?.transport_malformed ??
    pollExtra?.frames_crc_error ??
    packets?.frames_crc_error ??
    link.crc_error_count ??
    0;
  const transportErr =
    pollExtra?.transport_err ?? packets?.transport_err ?? 0;
  const appErr =
    pollExtra?.app_parse_error ?? packets?.app_parse_error ?? 0;
  const appField =
    pollExtra?.app_field_count_error ?? packets?.app_field_count_error ?? 0;
  const appType =
    pollExtra?.app_type_error ?? packets?.app_type_error ?? 0;
  const resync =
    pollExtra?.frames_resynced ?? packets?.frames_resynced ?? 0;
  const rate =
    pollExtra?.packet_rate_hz ??
    packets?.packet_rate_hz ??
    link.packet_rate_hz ??
    0;
  const seqGap =
    pollExtra?.last_seq_gap ?? packets?.last_seq_gap ?? link.last_seq_gap ?? 0;
  const age =
    pollExtra?.last_packet_age_s ??
    packets?.last_packet_age_s ??
    link.last_packet_age_s ??
    null;
  const rssi = pollExtra?.rssi ?? packets?.rssi ?? signal?.rssi ?? null;
  const snr = pollExtra?.snr ?? packets?.snr ?? signal?.snr ?? null;

  // Clamp selection
  const safeIdx = recent.length
    ? Math.min(selectedIdx, recent.length - 1)
    : 0;
  const selected = recent[safeIdx] || null;

  useEffect(() => {
    // Always show newest when stream is hot
    setSelectedIdx(0);
  }, [recent[0]?.t, recent[0]?.seq]);

  return (
    <div className="packet-monitor" aria-label="Packet monitor">
      <div className="packet-monitor-head">
        <div>
          <h2 className="section-title">Packet monitor</h2>
          <p className="muted small" style={{ margin: '0.15rem 0 0' }}>
            Reyax AT + CSV · transport errors vs application parse errors
          </p>
        </div>
        <RateSparkline values={rateHistory} />
      </div>

      <div className="packet-counters">
        <div className="pkt-stat">
          <div className="vg-label">Rate</div>
          <div className="vg-value">{fmt(rate, 1, 'Hz')}</div>
        </div>
        <div className="pkt-stat">
          <div className="vg-label">RX OK</div>
          <div className="vg-value">{framesOk}</div>
        </div>
        <div className="pkt-stat">
          <div className="vg-label">RSSI</div>
          <div className="vg-value">
            {rssi == null ? '—' : `${fmt(rssi, 0)} dBm`}
          </div>
        </div>
        <div className="pkt-stat">
          <div className="vg-label">SNR</div>
          <div className="vg-value">{snr == null ? '—' : fmt(snr, 1)}</div>
        </div>
        <div className={`pkt-stat ${transportBad > 0 ? 'warn' : ''}`}>
          <div className="vg-label">RX malformed</div>
          <div className="vg-value">{transportBad}</div>
        </div>
        <div className={`pkt-stat ${transportErr > 0 ? 'warn' : ''}`}>
          <div className="vg-label">TX +ERR</div>
          <div className="vg-value">{transportErr}</div>
        </div>
        <div className={`pkt-stat ${appErr > 0 ? 'warn' : ''}`}>
          <div className="vg-label">CSV err</div>
          <div className="vg-value">{appErr}</div>
          {(appField > 0 || appType > 0) && (
            <div className="vg-sub">
              {appField} field · {appType} type
            </div>
          )}
        </div>
        <div className={`pkt-stat ${resync > 0 ? 'warn' : ''}`}>
          <div className="vg-label">Oversize</div>
          <div className="vg-value">{resync}</div>
        </div>
        <div className="pkt-stat">
          <div className="vg-label">Seq gap</div>
          <div className="vg-value">{seqGap}</div>
        </div>
        <div className="pkt-stat">
          <div className="vg-label">Age</div>
          <div className="vg-value">
            {age == null ? '—' : `${fmt(age, 2)} s`}
          </div>
        </div>
      </div>

      <div className="packet-body">
        <div className="packet-list-col">
          <div className="vg-label">Recent frames</div>
          <div className="packet-list" role="listbox" aria-label="Recent frames">
            {recent.length === 0 && (
              <div className="muted small" style={{ padding: '0.5rem' }}>
                No frames yet — start simulation or connect serial
              </div>
            )}
            {recent.map((pkt, i) => (
              <button
                key={`${pkt.t}-${pkt.seq}-${i}`}
                type="button"
                role="option"
                aria-selected={i === safeIdx}
                className={`packet-list-item ${i === safeIdx ? 'active' : ''} ${
                  pkt.ok === false ? 'bad' : ''
                } ${pkt.layer === 'transport' ? 'transport' : ''}`}
                onClick={() => setSelectedIdx(i)}
              >
                <span className="pkt-type">
                  {pkt.type_name || pkt.type || 'frame'}
                </span>
                <span className="pkt-rssi">
                  {pkt.rssi == null ? '—' : `${pkt.rssi}`}
                </span>
                <span className="pkt-seq">
                  {pkt.layer === 'transport'
                    ? 'AT'
                    : pkt.seq == null
                      ? '—'
                      : `#${pkt.seq}`}
                </span>
                <span className="pkt-flag">{pkt.ok === false ? 'ERR' : 'OK'}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="packet-detail-col">
          <div className="vg-label">Hex (AT ASCII line)</div>
          <HexView hex={selected?.hex || ''} highlightCrc={false} mode="at" />
          <div className="vg-label" style={{ marginTop: '0.65rem' }}>
            Parsed fields
          </div>
          <FieldTable packet={selected} lastByType={lastByType} />
        </div>
      </div>
    </div>
  );
}
