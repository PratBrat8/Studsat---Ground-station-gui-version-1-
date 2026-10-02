import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import { useVehicleStore } from '../../state/vehicleStore.js';
import {
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  fetchTilesInfo,
  getTileUrlTemplate,
} from '../../services/tiles.js';
import TrailLayer from './TrailLayer.jsx';
import LandingMarker from './LandingMarker.jsx';
import { fmt } from '../../utils/format.js';
import { openGoogleMapsHandoff } from '../../utils/mapsHandoff.js';

/** DivIcon — no CDN marker images (offline hard requirement). */
function makeVehicleIcon(vehicle, isLive) {
  const cls = vehicle === 'satellite' ? 'sat' : 'rocket';
  return L.divIcon({
    className: `gs-vehicle-marker ${cls} ${isLive ? 'live' : ''}`,
    html: `<div class="gs-vehicle-marker-inner"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

/** Recenter map when GPS moves far from current view (smooth follow). */
function FollowPosition({ lat, lon, enabled }) {
  const map = useMap();
  const last = useRef(null);

  useEffect(() => {
    if (!enabled || lat == null || lon == null) return;
    const pos = [lat, lon];
    if (!last.current) {
      map.setView(pos, map.getZoom(), { animate: false });
      last.current = pos;
      return;
    }
    const bounds = map.getBounds();
    // Recenter if near edge or first fix
    if (!bounds.pad(-0.25).contains(pos)) {
      map.panTo(pos, { animate: true, duration: 0.4 });
    }
    last.current = pos;
  }, [lat, lon, enabled, map]);

  return null;
}

/** Invalidate size when panel becomes visible / resizes. */
function ResizeInvalidator() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const ro = new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
    });
    ro.observe(el);
    // Leaflet often mounts at 0 height in flex layouts
    const t = setTimeout(() => map.invalidateSize(), 100);
    return () => {
      ro.disconnect();
      clearTimeout(t);
    };
  }, [map]);
  return null;
}

/**
 * Offline map panel + Google Maps handoff (PRD G8 / A.5.10 / Phase 7).
 */
export default function MapPanel({ vehicle }) {
  const useStore = useVehicleStore(vehicle);
  const gps = useStore((s) => s.gps);
  const lastGps = useStore((s) => s.lastGps);
  const trail = useStore((s) => s.trail);
  const prediction = useStore((s) => s.prediction);
  const phase = useStore((s) => s.phase);
  const linkState = useStore((s) => s.link.state);
  const [tileInfo, setTileInfo] = useState(null);
  const [handoffError, setHandoffError] = useState(null);
  const [handoffBusy, setHandoffBusy] = useState(false);

  const hasFix =
    gps.lat != null &&
    gps.lon != null &&
    !Number.isNaN(Number(gps.lat)) &&
    !Number.isNaN(Number(gps.lon)) &&
    (gps.fix_type == null || gps.fix_type > 0);

  const lat = hasFix ? Number(gps.lat) : DEFAULT_MAP_CENTER.lat;
  const lon = hasFix ? Number(gps.lon) : DEFAULT_MAP_CENTER.lon;

  const tileUrl = useMemo(() => getTileUrlTemplate(), []);
  const accent = vehicle === 'satellite' ? '#3dd6a5' : '#f0733d';
  const icon = useMemo(
    () => makeVehicleIcon(vehicle, hasFix && linkState === 'CONNECTED'),
    [vehicle, hasFix, linkState]
  );

  const showLanding =
    prediction &&
    prediction.lat != null &&
    (phase === 'DESCENT' ||
      phase === 'APOGEE' ||
      phase === 'PAYLOAD_SEP' ||
      phase === 'AEROBREAK_RELEASE' ||
      phase === 'IMPACT' ||
      phase === 'LANDED');

  const handoffLat = lastGps?.lat;
  const handoffLon = lastGps?.lon;
  const canHandoff = handoffLat != null && handoffLon != null;

  useEffect(() => {
    let cancelled = false;
    fetchTilesInfo()
      .then((info) => {
        if (!cancelled) setTileInfo(info);
      })
      .catch(() => {
        if (!cancelled) setTileInfo(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onHandoff = async () => {
    if (!canHandoff || handoffBusy) return;
    setHandoffError(null);
    setHandoffBusy(true);
    try {
      await openGoogleMapsHandoff(handoffLat, handoffLon);
    } catch (err) {
      setHandoffError(err.message || String(err));
    } finally {
      setHandoffBusy(false);
    }
  };

  return (
    <div className="map-panel" aria-label={`${vehicle} map`}>
      <div className="map-panel-head">
        <div>
          <div className="panel-title">Map · offline tiles</div>
          <div className="map-coords muted small">
            {hasFix ? (
              <>
                {fmt(lat, 6)}, {fmt(lon, 6)}
                {gps.sats != null ? ` · ${gps.sats} sats` : ''}
                {gps.hdop != null ? ` · HDOP ${fmt(gps.hdop, 1)}` : ''}
              </>
            ) : (
              <>No GPS fix · showing default pad ({DEFAULT_MAP_CENTER.lat}, {DEFAULT_MAP_CENTER.lon})</>
            )}
          </div>
        </div>
        <div className="map-badges">
          <span className="link-pill mode">
            {tileInfo?.using_placeholders ? 'PLACEHOLDER TILES' : 'LOCAL TILES'}
          </span>
          {!hasFix && <span className="link-pill">NO FIX</span>}
          <button
            type="button"
            className="btn"
            disabled={!canHandoff || handoffBusy}
            onClick={onHandoff}
            title={
              canHandoff
                ? `Opens ${handoffLat.toFixed(6)}, ${handoffLon.toFixed(6)} in the system browser. Needs internet.`
                : 'Waiting for a GPS fix'
            }
          >
            Google Maps
          </button>
        </div>
      </div>

      <div className="map-canvas-wrap">
        <MapContainer
          center={[lat, lon]}
          zoom={DEFAULT_MAP_ZOOM}
          className="map-canvas"
          zoomControl
          attributionControl={false}
          preferCanvas
        >
          <TileLayer
            url={tileUrl}
            maxZoom={18}
            minZoom={3}
            // No crossOrigin CDN; same-origin / proxied backend only
            errorTileUrl=""
          />
          <ResizeInvalidator />
          <FollowPosition lat={hasFix ? lat : null} lon={hasFix ? lon : null} enabled={hasFix} />
          <TrailLayer trail={trail} color={accent} />
          {hasFix && (
            <Marker position={[lat, lon]} icon={icon}>
              <Popup>
                <strong>{vehicle === 'satellite' ? 'Satellite' : 'Rocket'}</strong>
                <br />
                {lat.toFixed(6)}, {lon.toFixed(6)}
                <br />
                Alt MSL {fmt(gps.alt_m, 1, 'm')} · phase {phase}
              </Popup>
            </Marker>
          )}
          {showLanding && <LandingMarker prediction={prediction} />}
        </MapContainer>
      </div>

      <div className="map-footer muted small">
        Tiles: <code>{tileUrl}</code>
        {tileInfo?.tile_file_count != null
          ? ` · ${tileInfo.tile_file_count} local files`
          : ''}
        {' · '}
        Drop XYZ files into <code>tiles/z/x/y.png</code> for a real basemap.
        {' · '}
        <strong>Google Maps</strong> opens the last known fix in the system
        browser and needs internet at click time.
        {canHandoff
          ? ` Last known ${handoffLat.toFixed(6)}, ${handoffLon.toFixed(6)}.`
          : ' Button stays disabled until a GPS fix arrives.'}
        {handoffError ? ` · ${handoffError}` : ''}
      </div>
    </div>
  );
}
