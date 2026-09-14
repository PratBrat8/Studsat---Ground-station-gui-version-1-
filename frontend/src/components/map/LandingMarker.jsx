import React, { useMemo } from 'react';
import { Marker, Popup, Circle } from 'react-leaflet';
import L from 'leaflet';

function makeLandingIcon() {
  return L.divIcon({
    className: 'gs-landing-marker',
    html: `<div class="gs-landing-marker-inner" title="Predicted landing">
      <div class="gs-landing-x"></div>
    </div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

/**
 * Predicted landing marker (PRD G4 / Phase 6 shell).
 * Phase 7 fills real prediction; until then shows when store has prediction.
 */
export default function LandingMarker({ prediction }) {
  const icon = useMemo(() => makeLandingIcon(), []);

  if (
    !prediction ||
    prediction.lat == null ||
    prediction.lon == null ||
    Number.isNaN(Number(prediction.lat))
  ) {
    return null;
  }

  const lat = Number(prediction.lat);
  const lon = Number(prediction.lon);
  const conf = prediction.confidence || '—';
  const eta =
    prediction.eta_s != null ? `${Math.round(prediction.eta_s)} s` : '—';

  return (
    <>
      <Circle
        center={[lat, lon]}
        radius={40}
        pathOptions={{
          color: '#f0c14d',
          fillColor: '#f0c14d',
          fillOpacity: 0.12,
          weight: 1,
          dashArray: '4 4',
        }}
      />
      <Marker position={[lat, lon]} icon={icon}>
        <Popup>
          <strong>Predicted landing</strong>
          <br />
          {lat.toFixed(6)}, {lon.toFixed(6)}
          <br />
          ETA: {eta} · conf: {conf}
        </Popup>
      </Marker>
    </>
  );
}
