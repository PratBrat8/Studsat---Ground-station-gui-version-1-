import React from 'react';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { fmt } from '../../utils/format.js';

function Cell({ label, value, sub, warn, accent }) {
  return (
    <div className={`vg-cell ${warn ? 'warn' : ''} ${accent || ''}`}>
      <div className="vg-label">{label}</div>
      <div className="vg-value">{value}</div>
      {sub != null && <div className="vg-sub">{sub}</div>}
    </div>
  );
}

/**
 * Primary numeric telemetry grid (PRD A.6.2 / Phase 5).
 * Subscribes only to telemetry/gps/link slices for the given vehicle.
 */
export default function ValueGrid({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const t = useStore((s) => s.telemetry);
  const gps = useStore((s) => s.gps);
  const link = useStore((s) => s.link);
  const packets = useStore((s) => s.packets);

  const battWarn = t.battery_v != null && t.battery_v < 7.0;
  const linkWarn = link.state && link.state !== 'CONNECTED';
  const crcWarn = (packets.frames_crc_error ?? link.crc_error_count ?? 0) > 0;

  return (
    <div className="value-grid" aria-label={`${vehicle} value grid`}>
      <Cell label="Altitude" value={fmt(t.altitude_m, 1, 'm')} accent="hi" />
      <Cell label="V. Speed" value={fmt(t.speed_mps, 2, 'm/s')} />
      <Cell label="Pitch" value={fmt(t.pitch, 1, '°')} />
      <Cell label="Yaw" value={fmt(t.yaw, 1, '°')} />
      <Cell label="Roll" value={fmt(t.roll, 1, '°')} />
      <Cell
        label="Battery"
        value={fmt(t.battery_v, 2, 'V')}
        warn={battWarn}
        sub={battWarn ? 'low' : undefined}
      />
      <Cell label="Temp" value={fmt(t.temperature_c, 1, '°C')} />
      <Cell label="Pressure" value={fmt(t.pressure_hpa, 1, 'hPa')} />
      <Cell label="Latitude" value={fmt(gps.lat, 6)} />
      <Cell label="Longitude" value={fmt(gps.lon, 6)} />
      <Cell
        label="GPS"
        value={
          gps.sats != null
            ? `${gps.sats} sats`
            : '—'
        }
        sub={gps.hdop != null ? `HDOP ${fmt(gps.hdop, 2)}` : undefined}
      />
      <Cell
        label="Link"
        value={fmt(link.packet_rate_hz, 1, 'Hz')}
        warn={linkWarn || crcWarn}
        sub={link.state || 'DISCONNECTED'}
      />
    </div>
  );
}
