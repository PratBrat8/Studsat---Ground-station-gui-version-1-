/**
 * Per-vehicle Zustand store (PRD C.4).
 * One instance per vehicle — Satellite updates never re-render Rocket subscribers
 * that only select rocket slices.
 */
import { create } from 'zustand';
import { capHistory } from '../services/wsClient.js';
import { isValidGps } from '../utils/mapsHandoff.js';

const HISTORY_CAP = 600;

const emptyTelemetry = {
  altitude_m: null,
  altitude_gnss_m: null,
  altitude_delta_m: null,
  altitude_disagreement: false,
  speed_mps: null,
  pitch: null,
  yaw: null,
  roll: null,
  temperature_c: null,
  pressure_hpa: null,
  battery_v: null,
  battery_pct: null,
  battery_pct_assumed: true,
  current_a: null,
  power_w: null,
  accel_x: null,
  accel_y: null,
  accel_z: null,
  gyro_x: null,
  gyro_y: null,
  gyro_z: null,
  timestamp_ms: null,
  packet_count: null,
  rssi: null,
  snr: null,
  flight_software_state: null,
};

const emptySignal = {
  rssi: null,
  snr: null,
  rssi_history: [],
  snr_history: [],
};

const emptyGps = {
  lat: null,
  lon: null,
  alt_m: null,
  sats: null,
  hdop: null,
  fix_type: 0,
  gps_timestamp: null,
};

const emptyTrajectory = () => ({
  origin: null,
  range_m: null,
  climb_deg: null,
  climb_source: 'none',
  trend_active: false,
  trend: [],
  path: [],
});

const emptyLink = {
  state: 'DISCONNECTED',
  packet_rate_hz: 0,
  crc_error_count: 0,
  frames_ok: 0,
  frames_resynced: 0,
  last_seq_gap: 0,
  last_packet_age_s: null,
};

const emptyHistory = () => ({
  altitude: [],
  speed: [],
  pitch: [],
  yaw: [],
  roll: [],
  battery: [],
  temperature: [],
  pressure: [],
});

function appendHistory(history, telemetry) {
  if (!telemetry || telemetry.altitude_m == null) return history;
  return {
    altitude: capHistory([...history.altitude, telemetry.altitude_m], HISTORY_CAP),
    speed: capHistory(
      [...history.speed, telemetry.speed_mps ?? 0],
      HISTORY_CAP
    ),
    pitch: capHistory([...history.pitch, telemetry.pitch ?? 0], HISTORY_CAP),
    yaw: capHistory([...history.yaw, telemetry.yaw ?? 0], HISTORY_CAP),
    roll: capHistory([...history.roll, telemetry.roll ?? 0], HISTORY_CAP),
    battery: capHistory(
      [...history.battery, telemetry.battery_v ?? 0],
      HISTORY_CAP
    ),
    temperature: capHistory(
      [...history.temperature, telemetry.temperature_c ?? 0],
      HISTORY_CAP
    ),
    pressure: capHistory(
      [...history.pressure, telemetry.pressure_hpa ?? 0],
      HISTORY_CAP
    ),
  };
}

function mergeHistoryFromSnapshot(msgHistory) {
  if (!msgHistory) return emptyHistory();
  return {
    altitude: capHistory(msgHistory.altitude || [], HISTORY_CAP),
    speed: capHistory(msgHistory.speed || [], HISTORY_CAP),
    pitch: capHistory(msgHistory.pitch || [], HISTORY_CAP),
    yaw: capHistory(msgHistory.yaw || [], HISTORY_CAP),
    roll: capHistory(msgHistory.roll || [], HISTORY_CAP),
    battery: capHistory(msgHistory.battery || [], HISTORY_CAP),
    temperature: capHistory(msgHistory.temperature || [], HISTORY_CAP),
    pressure: capHistory(msgHistory.pressure || [], HISTORY_CAP),
  };
}

export function createVehicleStore(vehicleId) {
  return create((set, get) => ({
    vehicleId,
    phase: 'IDLE',
    prev_phase: 'IDLE',
    wsConnected: false,
    lastUpdateT: null,
    link: { ...emptyLink },
    telemetry: { ...emptyTelemetry },
    gps: { ...emptyGps },
    lastGps: { lat: null, lon: null, t: null },
    signal: { ...emptySignal },
    lastCommand: null,
    commands: [],
    prediction: null,
    trajectory: emptyTrajectory(),
    events: [],
    cansat_separated: false,
    history: emptyHistory(),
    trail: [],
    packets: {
      frames_ok: 0,
      frames_crc_error: 0,
      frames_resynced: 0,
      transport_malformed: 0,
      transport_ok: 0,
      transport_err: 0,
      transport_unknown: 0,
      app_parse_error: 0,
      app_field_count_error: 0,
      app_type_error: 0,
      rssi: null,
      snr: null,
      packet_rate_hz: 0,
      last_seq: null,
      last_seq_gap: 0,
      total_seq_gaps: 0,
      last_packet_age_s: null,
      rate_history: [],
      recent: [],
      last_by_type: {},
    },

    setWsConnected: (wsConnected) => set({ wsConnected }),

    setLastCommand: (lastCommand) => set({ lastCommand }),

    setCommands: (commands) =>
      set({ commands: Array.isArray(commands) ? commands : [] }),

    applyUpdate: (msg) => {
      // Phase 11: never throw — bad WS payloads are dropped
      try {
        if (!msg || typeof msg !== 'object') return;
        if (msg.vehicle && msg.vehicle !== vehicleId) return;

        set((state) => {
          try {
            const telemetry = msg.telemetry
              ? { ...state.telemetry, ...msg.telemetry }
              : state.telemetry;
            const gps = msg.gps ? { ...state.gps, ...msg.gps } : state.gps;
            const lastGps = isValidGps(gps.lat, gps.lon)
              ? {
                  lat: Number(gps.lat),
                  lon: Number(gps.lon),
                  t: msg.t ?? state.lastUpdateT,
                }
              : state.lastGps;
            const link = msg.link ? { ...state.link, ...msg.link } : state.link;
            const nextPhase = msg.phase ?? state.phase;
            const prev_phase =
              msg.prev_phase !== undefined
                ? msg.prev_phase
                : nextPhase !== state.phase
                  ? state.phase
                  : state.prev_phase;

            let history = state.history;
            let trail = state.trail;

            if (msg.type === 'snapshot' && msg.history) {
              history = mergeHistoryFromSnapshot(msg.history);
            } else if (
              msg.telemetry &&
              msg.telemetry.altitude_m != null &&
              !Number.isNaN(Number(msg.telemetry.altitude_m))
            ) {
              history = appendHistory(state.history, telemetry);
            }

            if (msg.type === 'snapshot' && Array.isArray(msg.trail)) {
              trail = msg.trail.slice(-2000);
            } else if (Array.isArray(msg.trail_point) && msg.trail_point.length) {
              trail = capHistory([...state.trail, ...msg.trail_point], 2000);
            }

            let trajectory = state.trajectory || emptyTrajectory();
            if (msg.trajectory && typeof msg.trajectory === 'object') {
              const tmsg = msg.trajectory;
              let path = trajectory.path || [];
              if (Array.isArray(tmsg.path)) {
                path = tmsg.path.slice(-2000);
              } else if (Array.isArray(tmsg.path_point) && tmsg.path_point.length) {
                path = capHistory([...path, ...tmsg.path_point], 2000);
              }
              trajectory = {
                origin: tmsg.origin !== undefined ? tmsg.origin : trajectory.origin,
                range_m:
                  tmsg.range_m !== undefined ? tmsg.range_m : trajectory.range_m,
                climb_deg:
                  tmsg.climb_deg !== undefined
                    ? tmsg.climb_deg
                    : trajectory.climb_deg,
                climb_source: tmsg.climb_source || trajectory.climb_source,
                trend_active: Boolean(tmsg.trend_active),
                trend: Array.isArray(tmsg.trend) ? tmsg.trend : [],
                path,
              };
            }

            const signal = msg.signal
              ? {
                  rssi: msg.signal.rssi ?? state.signal.rssi,
                  snr: msg.signal.snr ?? state.signal.snr,
                  rssi_history: Array.isArray(msg.signal.rssi_history)
                    ? msg.signal.rssi_history
                    : state.signal.rssi_history,
                  snr_history: Array.isArray(msg.signal.snr_history)
                    ? msg.signal.snr_history
                    : state.signal.snr_history,
                }
              : state.signal;

            const packets = msg.packets
              ? {
                  frames_ok: msg.packets.frames_ok ?? state.packets.frames_ok,
                  frames_crc_error:
                    msg.packets.frames_crc_error ??
                    state.packets.frames_crc_error,
                  frames_resynced:
                    msg.packets.frames_resynced ?? state.packets.frames_resynced,
                  transport_malformed:
                    msg.packets.transport_malformed ??
                    msg.packets.frames_crc_error ??
                    state.packets.transport_malformed,
                  transport_ok:
                    msg.packets.transport_ok ?? state.packets.transport_ok,
                  transport_err:
                    msg.packets.transport_err ?? state.packets.transport_err,
                  transport_unknown:
                    msg.packets.transport_unknown ??
                    state.packets.transport_unknown,
                  app_parse_error:
                    msg.packets.app_parse_error ??
                    state.packets.app_parse_error,
                  app_field_count_error:
                    msg.packets.app_field_count_error ??
                    state.packets.app_field_count_error,
                  app_type_error:
                    msg.packets.app_type_error ??
                    state.packets.app_type_error,
                  rssi:
                    msg.packets.rssi !== undefined
                      ? msg.packets.rssi
                      : state.packets.rssi,
                  snr:
                    msg.packets.snr !== undefined
                      ? msg.packets.snr
                      : state.packets.snr,
                  packet_rate_hz:
                    msg.packets.packet_rate_hz ?? state.packets.packet_rate_hz,
                  last_seq:
                    msg.packets.last_seq !== undefined
                      ? msg.packets.last_seq
                      : state.packets.last_seq,
                  last_seq_gap:
                    msg.packets.last_seq_gap ?? state.packets.last_seq_gap,
                  total_seq_gaps:
                    msg.packets.total_seq_gaps ?? state.packets.total_seq_gaps,
                  last_packet_age_s:
                    msg.packets.last_packet_age_s ??
                    state.packets.last_packet_age_s,
                  rate_history: Array.isArray(msg.packets.rate_history)
                    ? msg.packets.rate_history
                    : state.packets.rate_history,
                  recent: Array.isArray(msg.packets.recent)
                    ? msg.packets.recent
                    : state.packets.recent,
                  last_by_type:
                    msg.packets.last_by_type &&
                    typeof msg.packets.last_by_type === 'object'
                      ? msg.packets.last_by_type
                      : state.packets.last_by_type,
                }
              : state.packets;

            return {
              phase: nextPhase,
              prev_phase,
              link,
              telemetry,
              gps,
              lastGps,
              signal,
              prediction:
                msg.prediction !== undefined
                  ? msg.prediction
                  : state.prediction,
              trajectory,
              events: Array.isArray(msg.events) ? msg.events : state.events,
              cansat_separated:
                msg.cansat_separated !== undefined
                  ? Boolean(msg.cansat_separated)
                  : state.cansat_separated,
              history,
              trail,
              packets,
              lastUpdateT: msg.t ?? state.lastUpdateT,
            };
          } catch {
            return state;
          }
        });
      } catch (err) {
        console.error(`[store:${vehicleId}] applyUpdate failed`, err);
      }
    },

    reset: () =>
      set({
        phase: 'IDLE',
        prev_phase: 'IDLE',
        wsConnected: get().wsConnected,
        lastUpdateT: null,
        link: { ...emptyLink },
        telemetry: { ...emptyTelemetry },
        gps: { ...emptyGps },
        signal: { ...emptySignal },
        lastCommand: null,
        commands: [],
        prediction: null,
        trajectory: emptyTrajectory(),
        events: [],
        cansat_separated: false,
        history: emptyHistory(),
        trail: [],
        packets: {
          frames_ok: 0,
          frames_crc_error: 0,
          frames_resynced: 0,
          transport_malformed: 0,
          transport_ok: 0,
          transport_err: 0,
          transport_unknown: 0,
          app_parse_error: 0,
          app_field_count_error: 0,
          app_type_error: 0,
          rssi: null,
          snr: null,
          packet_rate_hz: 0,
          last_seq: null,
          last_seq_gap: 0,
          total_seq_gaps: 0,
          last_packet_age_s: null,
          rate_history: [],
          recent: [],
          last_by_type: {},
        },
      }),
  }));
}

export const useRocketStore = createVehicleStore('rocket');
export const useSatelliteStore = createVehicleStore('satellite');

export function useVehicleStore(vehicleId) {
  return vehicleId === 'satellite' ? useSatelliteStore : useRocketStore;
}
