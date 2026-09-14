import React, { useMemo } from 'react';
import { Polyline, CircleMarker } from 'react-leaflet';

/**
 * GPS breadcrumb trail (PRD A.6.2 / Phase 6).
 * @param {{ trail: Array<{lat:number, lon:number}>, color?: string }} props
 */
export default function TrailLayer({ trail, color = '#3d9cf0' }) {
  const positions = useMemo(() => {
    if (!Array.isArray(trail) || trail.length < 1) return [];
    return trail
      .filter((p) => p && p.lat != null && p.lon != null)
      .map((p) => [p.lat, p.lon]);
  }, [trail]);

  if (positions.length === 0) return null;

  return (
    <>
      {positions.length >= 2 && (
        <Polyline
          positions={positions}
          pathOptions={{
            color,
            weight: 3,
            opacity: 0.85,
            lineJoin: 'round',
            lineCap: 'round',
          }}
        />
      )}
      {/* Start pin */}
      <CircleMarker
        center={positions[0]}
        radius={5}
        pathOptions={{
          color: '#8b9bb0',
          fillColor: '#8b9bb0',
          fillOpacity: 0.9,
          weight: 1,
        }}
      />
    </>
  );
}
