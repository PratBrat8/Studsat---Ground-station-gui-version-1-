/**
 * Per-vehicle Zustand store (PRD C.4).
 * One instance per vehicle — Satellite updates never re-render Rocket subscribers
 * that only select rocket slices.
 */
import { create } from 'zustand';
import { capHistory } from '../services/wsClient.js';

const HISTORY_CAP = 600;

const emptyTelemetry = {
  altitude_m: null,
  speed_mps: null,
  pitch: null,
  yaw: null,
  roll: null,
  temperature_c: null,
  pressure_hpa: null,
  battery_v: null,
  accel_x: null,
  accel_y: null,
  accel_z: null,
  gyro_x: null,
  gyro_y: null,
  gyro_z: null,
  timestamp_ms: null,
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
    prediction: null,
    events: [],
    history: emptyHistory(),
    trail: [],
    packets: {
      frames_ok: 0,
      frames_crc_error: 0,
      frames_resynced: 0,
      packet_rate_hz: 0,
      last_seq: null,
      last_seq_gap: 0,
      total_seq_gaps: 0,
      rate_history: [],
      recent: [],
      last_by_type: {},
    },

    setWsConnected: (wsConnected) => set({ wsConnected }),

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

            const packets = msg.packets
              ? {
                  frames_ok: msg.packets.frames_ok ?? state.packets.frames_ok,
                  frames_crc_error:
                    msg.packets.frames_crc_error ??
                    state.packets.frames_crc_error,
                  frames_resynced:
                    msg.packets.frames_resynced ?? state.packets.frames_resynced,
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
              prediction:
                msg.prediction !== undefined
                  ? msg.prediction
                  : state.prediction,
              events: Array.isArray(msg.events) ? msg.events : state.events,
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
        prediction: null,
        events: [],
        history: emptyHistory(),
        trail: [],
        packets: {
          frames_ok: 0,
          frames_crc_error: 0,
          frames_resynced: 0,
          packet_rate_hz: 0,
          last_seq: null,
          last_seq_gap: 0,
          total_seq_gaps: 0,
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
