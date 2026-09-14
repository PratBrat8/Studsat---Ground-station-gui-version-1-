/**
 * Orchestrates REST connect/sim + WebSocket lifecycle per vehicle (Phase 4).
 * Keeps Rocket and Satellite fully independent.
 */

import * as api from './api.js';
import { createWsClient } from './wsClient.js';
import { useRocketStore, useSatelliteStore } from '../state/vehicleStore.js';
import { useSettingsStore } from '../state/settingsStore.js';

const clients = {
  rocket: null,
  satellite: null,
};

function storeFor(vehicle) {
  return vehicle === 'satellite' ? useSatelliteStore : useRocketStore;
}

function ensureClient(vehicle) {
  if (clients[vehicle]) return clients[vehicle];
  const store = storeFor(vehicle);
  const client = createWsClient(vehicle, {
    applyUpdate: (msg) => store.getState().applyUpdate(msg),
    setWsConnected: (ok) => store.getState().setWsConnected(ok),
  });
  clients[vehicle] = client;
  return client;
}

export function openVehicleStream(vehicle) {
  const client = ensureClient(vehicle);
  client.connect();
}

export function closeVehicleStream(vehicle) {
  const client = clients[vehicle];
  if (client) {
    client.disconnect();
  }
}

/**
 * Toggle simulation mode end-to-end: REST /simulate + WS stream.
 */
export async function setVehicleSimulate(vehicle, enabled) {
  const settings = useSettingsStore.getState();
  const store = storeFor(vehicle);

  if (enabled) {
    // Sim replaces any serial link for this vehicle
    await api.setSimulate(vehicle, true);
    if (vehicle === 'rocket') {
      settings.setRocketSimulate(true);
      settings.setConnectionMode('rocket', 'sim');
    } else {
      settings.setSatelliteSimulate(true);
      settings.setConnectionMode('satellite', 'sim');
    }
    store.getState().reset();
    openVehicleStream(vehicle);
  } else {
    await api.setSimulate(vehicle, false);
    closeVehicleStream(vehicle);
    if (vehicle === 'rocket') {
      settings.setRocketSimulate(false);
      settings.setConnectionMode('rocket', null);
    } else {
      settings.setSatelliteSimulate(false);
      settings.setConnectionMode('satellite', null);
    }
    store.getState().reset();
  }
}

/**
 * Connect a real serial port for a vehicle.
 */
export async function connectVehicleSerial(vehicle, port, baud) {
  const settings = useSettingsStore.getState();
  const store = storeFor(vehicle);

  // Clear sim flag if switching to hardware
  if (vehicle === 'rocket' && settings.rocketSimulate) {
    settings.setRocketSimulate(false);
  }
  if (vehicle === 'satellite' && settings.satelliteSimulate) {
    settings.setSatelliteSimulate(false);
  }

  await api.connectVehicle(vehicle, port, baud);
  settings.setConnectionMode(vehicle, 'serial');
  if (vehicle === 'rocket') {
    settings.setRocketPort(port);
  } else {
    settings.setSatellitePort(port);
  }
  settings.setBaud(baud);
  store.getState().reset();
  openVehicleStream(vehicle);
}

export async function disconnectVehicleLink(vehicle) {
  const settings = useSettingsStore.getState();
  closeVehicleStream(vehicle);
  try {
    await api.disconnectVehicle(vehicle);
  } catch {
    /* backend may already be idle */
  }
  if (vehicle === 'rocket') {
    settings.setRocketSimulate(false);
    settings.setConnectionMode('rocket', null);
  } else {
    settings.setSatelliteSimulate(false);
    settings.setConnectionMode('satellite', null);
  }
  storeFor(vehicle).getState().reset();
}

export async function refreshPorts() {
  const data = await api.fetchPorts();
  const ports = data.ports || [];
  useSettingsStore.getState().setPorts(ports);
  return ports;
}

export async function refreshBackendStatus() {
  const data = await api.fetchStatus();
  useSettingsStore.getState().setBackendConnections(data);
  return data;
}

/**
 * Start CSV replay into a vehicle pipeline (real parser path on backend).
 * Opens WS so live panels update.
 */
export async function startReplaySession(filename, speed = 1, vehicle = null) {
  // Stop any live sim/serial first via backend load; also close local streams
  const data = await api.loadReplay(filename, speed, vehicle);
  const veh = data.vehicle || vehicle || 'rocket';
  // Close both then open target (replay owns hub for that vehicle)
  closeVehicleStream('rocket');
  closeVehicleStream('satellite');
  storeFor(veh).getState().reset();
  openVehicleStream(veh);
  useSettingsStore.getState().setConnectionMode(veh, 'replay');
  return data;
}

export async function stopReplaySession() {
  const data = await api.stopReplay();
  closeVehicleStream('rocket');
  closeVehicleStream('satellite');
  useSettingsStore.getState().setConnectionMode('rocket', null);
  useSettingsStore.getState().setConnectionMode('satellite', null);
  return data;
}
