/**
 * Settings store — COM ports, baud, sim toggles, connection modes (Phase 4).
 */
import { create } from 'zustand';

export const useSettingsStore = create((set) => ({
  ports: [],
  portsLoading: false,
  portsError: null,
  lastPortsRefresh: null,

  rocketPort: '',
  satellitePort: '',
  baud: 115200,

  rocketSimulate: false,
  satelliteSimulate: false,

  /** null | 'sim' | 'serial' */
  rocketMode: null,
  satelliteMode: null,

  backendConnections: null,
  busy: {
    rocket: false,
    satellite: false,
  },
  actionError: null,

  tilesPath: null,
  logsPath: null,

  setPorts: (ports) =>
    set({
      ports: ports || [],
      lastPortsRefresh: Date.now(),
      portsError: null,
    }),
  setPortsLoading: (portsLoading) => set({ portsLoading }),
  setPortsError: (portsError) => set({ portsError }),

  setRocketPort: (rocketPort) => set({ rocketPort }),
  setSatellitePort: (satellitePort) => set({ satellitePort }),
  setBaud: (baud) => set({ baud: Number(baud) || 115200 }),

  setRocketSimulate: (rocketSimulate) => set({ rocketSimulate }),
  setSatelliteSimulate: (satelliteSimulate) => set({ satelliteSimulate }),

  setConnectionMode: (vehicle, mode) =>
    set(
      vehicle === 'satellite'
        ? { satelliteMode: mode }
        : { rocketMode: mode }
    ),

  setBackendConnections: (backendConnections) => set({ backendConnections }),

  setBusy: (vehicle, busy) =>
    set((s) => ({
      busy: { ...s.busy, [vehicle]: busy },
    })),

  setActionError: (actionError) => set({ actionError }),
}));
