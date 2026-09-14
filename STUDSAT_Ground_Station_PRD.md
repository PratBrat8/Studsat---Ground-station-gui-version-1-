# STUDSAT Dual Ground Station — Technical PRD, HLD & LLD

**Version:** 1.0
**Scope:** Offline desktop Ground Station application for Rocket + Satellite telemetry, built from an existing UI-only mockup into a fully functional, hardware-connected system.
**Author context:** Prepared for handoff to an AI coding agent (Grok / Grok Code in VS Code) for full-stack implementation.

---

## 0. How to use this document

This is a single source of truth. It is split into:
- **Part A — PRD**: what we're building and why.
- **Part B — HLD**: how the system is structured at the architecture level.
- **Part C — LLD**: concrete modules, classes, message schemas, algorithms, folder layout — detailed enough that an AI coding agent can implement it without guessing.
- **Part D — Build plan**: the order in which Grok should build this, phase by phase.
- **Appendix**: the actual prompt to paste into Grok, and open decisions the team still needs to confirm.

Anything marked **[ASSUMED]** is a reasonable default chosen because the real firmware/packet spec wasn't available at writing time. These are flagged so your firmware/embedded lead can correct them in one place before Grok starts building — the whole system is designed so that only `protocol.py` / `protocol.ts` need to change if the real packet format differs.

---

# PART A — PRODUCT REQUIREMENTS

## A.1 Background & hardware context

The team has two independent flight vehicles that both report telemetry to the same ground laptop:

| Vehicle | Onboard compute | Sensors observed | Notes |
|---|---|---|---|
| **Rocket** | Raspberry Pi Zero (2) W | MPU6050/MPU9250 IMU (accel+gyro, on breadboard), BME280/680 (temp/pressure/humidity/gas), GPS module with battery-backed RTC (u-blox-class module), Pi Camera module | Onboard antenna for RF downlink |
| **Satellite** | Raspberry Pi Zero (2) W | Same sensor set (IMU, BME, GPS, camera) | Same downlink chain |
| **Ground side** | Laptop (Windows, likely, at competition site) | USB RF telemetry receiver dongle (small board with SMA antenna, presents as a **virtual COM/serial port**) | Confirmed: telemetry arrives as a **raw serial byte stream** over USB, not over WiFi/TCP. |

Both vehicles use the **same sensor stack and the same downlink style** (per your confirmation), which is why one shared backend architecture with two parallel "vehicle pipelines" is the right design, rather than two unrelated codebases.

Deployment confirmed as an **Electron desktop app** — a single installable/double-clickable app, bundling the React UI and the Python backend together, with **zero internet dependency** at runtime (no CDN scripts, no online map tiles, no telemetry APIs).

Offline maps confirmed: the team will pre-download real map tiles (OSM/MapTiler export, e.g. MBTiles or an XYZ folder) for the launch site region ahead of the competition.

## A.2 Problem statement

The existing HTML mockups (`rocket_ground_station.html` → `v4`) are **UI-only**: telemetry is a `simData()` function generating fake sine-wave numbers, there's no serial connection, no packet framing, no data persistence, and no cross-vehicle tabbing. The team needs a **real, offline, dual-vehicle ground station** that:

1. Actually reads bytes off a serial port and turns them into validated telemetry.
2. Shows the same class of information the mockups show (attitude HUD, compass, map, graphs, video) but for **two independently-selectable vehicles in two tabs**.
3. Adds: a **packet visualizer**, **landing prediction**, **3D-style attitude/tilt animation driven by real gyro data**, and a **landing animation sequence**.
4. Works with **zero network connectivity**, is resilient to bad cables/dropped packets/USB re-enumeration, and logs every session so data isn't lost if the app crashes.

## A.3 Goals

- G1: Two top-level tabs — **Rocket** and **Satellite** — each an independent telemetry pipeline (own serial port, own state, own history), sharing one shell app.
- G2: Standard ground-station readouts: altitude, velocity/speed, attitude (pitch/roll/yaw), GPS fix (lat/lon/alt/sats/HDOP), battery voltage, temperature/pressure, mission timer, mission phase/status, signal/link health, packet rate & loss.
- G3: **Packet Monitor** panel — live raw hex + parsed field breakdown + valid/invalid frame counters, per vehicle.
- G4: **Landing prediction** — estimated touchdown lat/lon + ETA, shown as a marker on the map and updated continuously during descent.
- G5: **Graphs** — real-time scrolling charts for altitude, velocity, attitude, temperature, battery, pressure, with a scrub-back replay mode after landing.
- G6: **Attitude/tilt animation** — a 3D-style body model (rocket shape / satellite shape) that rotates live based on gyro/accelerometer-derived orientation, plus the existing 2D HUD ladder + compass.
- G7: **Landing animation** — a distinct on-screen sequence (parachute/touchdown visual + status banner) that triggers automatically when the mission phase transitions into "LANDED"/"RECOVERED".
- G8: **Fully offline** — no external tile servers, no CDNs, no cloud calls, anywhere in the runtime path.
- G9: Session logging (CSV, one file per vehicle per session) + **replay mode** so a landed flight can be scrubbed back through after the fact for debrief/reporting.
- G10: Resilient serial handling — auto-detect available COM ports, reconnect on drop, never crash the UI on a bad/corrupt frame.

## A.4 Non-goals (explicitly out of scope v1)

- Sending uplink commands to the vehicles (this is a **receive-only** ground station in v1, unless your team confirms a command uplink exists — flagged as an open question).
- Multi-ground-station networking / cloud sync.
- Full flight-dynamics simulation (the "landing prediction" is a lightweight kinematic estimator, not a 6-DOF simulator — see C.6).
- Video is treated as optional/best-effort (kept from the mockup as an MJPEG/local-stream panel) since it's not in scope of the sensor list confirmed — do not block the rest of the system on it.

## A.5 Users

- **Ground crew / mission control operator**: watches live telemetry, arms/monitors mission phase, needs the packet monitor and link-health indicators to diagnose RF issues on the spot.
- **Recovery team**: cares mainly about the **map + landing prediction** to go and physically retrieve the vehicle.
- **Judges/reviewers at the competition**: will look at the UI's polish, the graphs, and the replay — this is also a demo-quality product, not just internal tooling.

## A.6 Functional requirements detail

### A.6.1 Shared shell
- App opens to a top bar with **[ Rocket ] [ Satellite ] [ Replay ] [ Settings ]** tabs.
- Each of Rocket/Satellite is a fully independent screen (own connect button, own mission clock, own state) — switching tabs never disconnects the other vehicle; both can stream simultaneously if two dongles are plugged in.
- Settings tab: list available COM ports (auto-refresh), assign a port + baud rate to Rocket and to Satellite independently, choose the local map tile folder, view/change log directory, toggle simulation mode (for demos without hardware).

### A.6.2 Per-vehicle telemetry screen (Rocket tab / Satellite tab)
Must contain, at minimum (mirroring the mockup's panel set, now backed by real data):
- Attitude HUD (artificial horizon), compass/yaw dial, 3D tilt/body animation.
- Value grid: altitude, vertical speed, pitch/yaw/roll, temperature, pressure, battery voltage, GPS sats/HDOP.
- Map panel with live position marker, breadcrumb trail, and (during descent) the predicted landing marker + ETA.
- Graphs panel: altitude vs time, vertical speed vs time, attitude vs time, battery vs time, temperature/pressure vs time.
- Packet Monitor panel: live hex stream, parsed field table, packets/sec, invalid/CRC-failed count, last-packet-age ("link health").
- Mission phase badge (IDLE → ARMED → ASCENT → APOGEE → DESCENT → RECOVERY/LANDED) with the mission clock.
- Landing prediction card (predicted lat/lon, straight-line distance from last known GPS fix, ETA).
- Landing animation overlay, auto-triggered on phase → LANDED.

### A.6.3 Replay tab
- Load a previously logged CSV session (Rocket or Satellite) and scrub through it using the exact same visual components as live mode (HUD, map, graphs, packet monitor) — i.e. replay re-uses the live rendering pipeline, just fed from a file instead of a serial port.

### A.6.4 Settings / connection management
- COM port list + refresh, baud rate selector **[ASSUMED default 115200]**, per-vehicle assignment.
- "Simulation mode" toggle per vehicle: generates physics-plausible synthetic frames through the *same* parser/pipeline as real hardware, so the UI/demo works with zero hardware attached (this directly replaces the old `simData()` mock, but now flows through the real protocol layer instead of faking the UI state directly — important so that a bug in the real pipeline can't hide behind a fake data path).

## A.7 Non-functional requirements

- **Offline-first**: no runtime dependency on internet reachability. All fonts/libs bundled at build time. Map tiles served from a local folder.
- **Resilience**: a malformed/corrupt packet must never crash the app; it increments an error counter and is dropped.
- **Reconnect**: if a COM port is unplugged/re-enumerated, the backend must detect the disconnect, keep the UI alive (shows "LINK LOST"), and reconnect automatically once the port reappears.
- **Performance**: must handle telemetry at up to **20 Hz per vehicle** from the serial layer without UI jank; UI redraw is throttled to ~15–20 fps regardless of raw ingest rate (see C.4).
- **Data durability**: every connected session is logged to disk continuously (not just on disconnect), so a crash mid-flight doesn't lose data.
- **Packaging**: one installer/build artifact per platform (Windows primary target — competition laptops), fully self-contained, no "please `pip install`" step for end users.
- **Startup time**: app should be usable (tabs rendered, ports listed) within a few seconds of launch.

---

# PART B — HIGH-LEVEL DESIGN (HLD)

## B.1 Architecture overview

```
┌───────────────────────────────────────────────────────────────────────┐
│                          ELECTRON APP (desktop)                       │
│                                                                         │
│  ┌─────────────────────────┐        spawns/manages        ┌─────────┐│
│  │   Electron Main Process  │ ───────────────────────────▶ │ Python  ││
│  │   (Node.js)               │                              │ Backend ││
│  │  - creates BrowserWindow  │ ◀─────── stdout/health ─────│ (child  ││
│  │  - spawns backend.exe     │                              │ process)││
│  │  - restarts backend if it │                              └────┬────┘│
│  │    crashes                │                                   │     │
│  └─────────────┬─────────────┘                                   │     │
│                │ loads                                            │     │
│                ▼                                                  │     │
│  ┌─────────────────────────────────────┐   WebSocket (telemetry)  │     │
│  │   React Renderer (Chromium view)    │◀─────────────────────────┘     │
│  │   - Rocket tab / Satellite tab      │   REST (control: ports,        │
│  │   - Replay tab / Settings tab       │   connect, logs, replay list)  │
│  │   - react-leaflet map (local tiles) │─────────────────────────────▶ │
│  │   - react-three-fiber 3D attitude   │                                │
│  │   - recharts graphs                 │                                │
│  └─────────────────────────────────────┘                                │
└───────────────────────────────────────────────────────────────────────┘
         ▲                                        ▲
         │ USB                                    │ USB
   ┌─────┴──────┐                            ┌────┴───────┐
   │ RF Dongle  │◀── RF link ── Rocket Pi     │ RF Dongle  │◀── RF link ── Satellite Pi
   │ (COM port) │                              │ (COM port) │
   └────────────┘                              └────────────┘
```

Two serial ports can be open concurrently (one per vehicle) inside the **same Python backend process**, each with its own asyncio task, its own frame parser instance, its own WebSocket topic, and its own CSV log file. This is the key structural decision: **one backend process, two "vehicle pipelines" running in parallel**, not two separate apps.

## B.2 Why this stack

- **Electron** wraps both the React UI and the Python backend into one distributable, satisfying "fully offline, double-click app" — Node's `child_process` module manages the backend's lifecycle so the user never sees a terminal.
- **Python + PySerial** for the hardware-facing layer, per your requested tech stack — pyserial is the standard for exactly this (raw byte stream off a virtual COM port).
- **FastAPI + WebSocket** (or plain `websockets` lib) as the bridge between Python and React — WebSocket gives push-based low-latency streaming (better than polling REST for 10–20 Hz data), REST is used only for control actions (list ports, connect, load replay).
- **React + react-leaflet + recharts + react-three-fiber** for the frontend — matches your requested stack, and each maps cleanly onto one PRD requirement (map→react-leaflet, graphs→recharts, 3D tilt→react-three-fiber/Three.js).
- **Local tile serving**: the Python backend also serves the pre-downloaded map tiles as static files (`/tiles/{z}/{x}/{y}.png`) so react-leaflet points at `http://127.0.0.1:PORT/tiles/...` instead of any internet tile server — this is what actually makes the map "offline."

## B.3 Process/data flow (one vehicle pipeline)

```
Serial bytes ─▶ FrameParser (state machine) ─▶ validated Frame
   │                                                 │
   │ (bad CRC / bad sync → dropped, counters++)      ▼
   │                                          Decode → typed telemetry object
   │                                                 │
   │                                    ┌────────────┼─────────────┐
   │                                    ▼            ▼             ▼
   │                              TelemetryHub   CSV Logger   LandingPredictor
   │                              (ring buffer)  (append)     (recompute on new
   │                                    │                       descent sample)
   │                                    ▼
   │                          WebSocket broadcast (throttled)
   │                                    │
   ▼                                    ▼
Reconnect/                        React renderer updates:
watchdog logic                    HUD, map, graphs, packet monitor,
                                   phase badge, prediction card
```

## B.4 Mission phase state machine (shared logic, per vehicle)

```
IDLE ──(connect + first valid frame)──▶ ARMED
ARMED ──(altitude/accel exceeds launch threshold, or explicit EVENT packet)──▶ ASCENT
ASCENT ──(vertical speed changes sign, sustained)──▶ APOGEE
APOGEE ──(altitude decreasing, sustained)──▶ DESCENT
DESCENT ──(altitude ~ ground level AND speed ~ 0, sustained N samples)──▶ LANDED
LANDED ──(operator marks "Recovered" in UI)──▶ RECOVERED
```
Thresholds are configurable constants (see C.7) — **[ASSUMED]** since exact launch/land thresholds depend on real sensor scaling from your firmware; ship with conservative defaults and expose them in Settings so the team can tune on-site.

---

# PART C — LOW-LEVEL DESIGN (LLD)

## C.1 Repository layout

```
studsat-ground-station/
├── electron/
│   ├── main.js                 # Electron main process, spawns backend, window mgmt
│   ├── preload.js               # contextBridge, exposes safe IPC to renderer
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app entry, mounts routes + static tiles
│   │   ├── protocol.py           # frame constants, struct formats, CRC16, dataclasses
│   │   ├── serial_manager.py     # SerialReader per vehicle (thread/async)
│   │   ├── frame_parser.py       # byte-stream → validated Frame state machine
│   │   ├── telemetry_hub.py      # in-memory ring buffers + pub/sub to WS clients
│   │   ├── predictor.py          # LandingPredictor (dead-reckoning estimator)
│   │   ├── attitude.py           # gyro/accel → orientation fusion (Madgwick/comp. filter)
│   │   ├── phase_fsm.py          # mission phase state machine
│   │   ├── logger.py             # CSV session logger + replay file loader
│   │   ├── simulator.py          # synthetic frame generator (sim mode)
│   │   ├── ws_routes.py          # /ws/{vehicle} websocket endpoint
│   │   ├── rest_routes.py        # /ports /connect /disconnect /replay/* /settings
│   │   └── config.py             # constants, thresholds, default ports/baud
│   ├── requirements.txt
│   └── build_backend.spec        # PyInstaller spec → single backend executable
├── frontend/
│   ├── src/
│   │   ├── main.jsx / App.jsx
│   │   ├── state/
│   │   │   ├── vehicleStore.js   # zustand store, one instance per vehicle
│   │   │   └── settingsStore.js
│   │   ├── services/
│   │   │   ├── wsClient.js
│   │   │   └── api.js
│   │   └── components/
│   │       ├── shell/ (TopBar, TabNav, MissionClock, PhaseBadge)
│   │       ├── attitude/ (HorizonHUD.jsx, CompassDial.jsx, Body3D.jsx)
│   │       ├── map/ (MapPanel.jsx, LandingMarker.jsx, TrailLayer.jsx)
│   │       ├── graphs/ (GraphsPanel.jsx, LineChartCard.jsx)
│   │       ├── packets/ (PacketMonitor.jsx, HexView.jsx, FieldTable.jsx)
│   │       ├── prediction/ (LandingPredictionCard.jsx)
│   │       ├── landing/ (LandingAnimationOverlay.jsx)
│   │       ├── video/ (VideoPanel.jsx)          # optional/best-effort
│   │       ├── replay/ (ReplayControls.jsx)
│   │       └── settings/ (SettingsPanel.jsx, PortSelector.jsx)
│   ├── package.json
│   └── vite.config.js
├── tiles/                        # pre-downloaded offline map tiles go here
├── logs/                         # CSV session logs written here at runtime
└── docs/
    └── (this PRD + protocol spec)
```

## C.2 Wire protocol — `protocol.py` / mirrored `protocol.ts`

> **[ASSUMED — confirm against real firmware before final integration.]** This is the proposed frame format. It is deliberately simple (fixed-size fields, single CRC) so it's easy for your firmware/embedded lead to implement identically on the Pi side, or to tell Grok "change these field widths/order to X" with everything isolated to this one file.

**Frame layout (byte stream over serial):**

| Field | Size | Notes |
|---|---|---|
| SYNC0 | 1 B | `0xAA` |
| SYNC1 | 1 B | `0x55` |
| VEHICLE_ID | 1 B | `0x01` = Rocket, `0x02` = Satellite |
| PACKET_TYPE | 1 B | `0x01` TELEMETRY, `0x02` GPS, `0x03` STATUS/HEARTBEAT, `0x04` EVENT |
| SEQ | 1 B | rolling 0–255, used to detect packet loss |
| LEN | 1 B | payload length in bytes (N) |
| PAYLOAD | N B | little-endian packed fields, see below |
| CRC16 | 2 B | CRC-CCITT (0x1021 poly) over VEHICLE_ID..PAYLOAD |

**TELEMETRY payload (PACKET_TYPE=0x01), all little-endian:**
```
uint32  timestamp_ms
float32 altitude_m
float32 pressure_hpa
float32 temperature_c
float32 accel_x, accel_y, accel_z      // m/s^2
float32 gyro_x, gyro_y, gyro_z         // deg/s
float32 pitch, yaw, roll               // deg  (either computed onboard, or 0 and fused on ground — see attitude.py)
float32 battery_v
```

**GPS payload (PACKET_TYPE=0x02):**
```
uint32  gps_timestamp
float64 lat
float64 lon
float32 alt_msl_m
uint8   num_sats
float32 hdop
uint8   fix_type   // 0=no fix,1=2D,2=3D
```

**STATUS/HEARTBEAT payload (PACKET_TYPE=0x03):**
```
uint8   phase_hint     // optional: firmware's own phase opinion, 0 = "let ground station decide"
float32 battery_v
uint8   error_flags    // bitmask, sensor health
```

**EVENT payload (PACKET_TYPE=0x04):** free-form short string (e.g. `"LAUNCH_DETECT"`, `"CHUTE_DEPLOY"`), length-prefixed by LEN.

**Framing state machine (`frame_parser.py`):**
```
STATE_WAIT_SYNC0 → STATE_WAIT_SYNC1 → STATE_HEADER (read VEHICLE_ID,TYPE,SEQ,LEN)
   → STATE_PAYLOAD (accumulate LEN bytes) → STATE_CRC (read 2 bytes)
   → validate CRC:
        - match  → emit Frame(vehicle_id, type, seq, payload_bytes) → back to WAIT_SYNC0
        - mismatch → increment crc_error_count, resync by scanning forward for next SYNC0/SYNC1 pair
```
This must be implemented as an **incremental byte-feed** function (`feed(bytes) -> list[Frame]`), not a blocking read, so it works identically whether fed from a live serial port or from a replayed log file.

## C.3 Backend module contracts

### `protocol.py`
- Constants: `SYNC0, SYNC1, VEHICLE_ROCKET=0x01, VEHICLE_SATELLITE=0x02, TYPE_TELEMETRY, TYPE_GPS, TYPE_STATUS, TYPE_EVENT`.
- `crc16_ccitt(data: bytes) -> int`.
- Dataclasses: `TelemetryFrame`, `GpsFrame`, `StatusFrame`, `EventFrame` (typed fields matching C.2).
- `decode_payload(packet_type: int, payload: bytes) -> TelemetryFrame | GpsFrame | StatusFrame | EventFrame`.

### `frame_parser.py`
- `class FrameParser: def feed(self, data: bytes) -> list[RawFrame]` — pure function of state, no I/O. Unit-testable by feeding byte arrays.
- Tracks `frames_ok`, `frames_crc_error`, `frames_resynced` counters — surfaced to the Packet Monitor.

### `serial_manager.py`
- `class SerialVehicleLink`:
  - `__init__(vehicle_id, port, baud, on_frame_callback)`.
  - Runs a background thread (or asyncio + `pyserial-asyncio`) reading available bytes every ~20 ms, feeding `FrameParser`.
  - Emits connection state changes: `CONNECTED / LINK_LOST / RECONNECTING`.
  - Auto-reconnect: on `SerialException`, retries opening the port every 2 s (backoff to 5 s after 5 tries) without blocking the rest of the app.
- `list_available_ports() -> list[{device, description}]` (wraps `serial.tools.list_ports.comports()`).

### `telemetry_hub.py`
- Per vehicle: fixed-size ring buffers (numpy or `collections.deque(maxlen=N)`, **[ASSUMED N=3600 samples ≈ 3 min at 20 Hz]**) for altitude, speed, pitch/yaw/roll, battery, temperature, pressure, plus the raw GPS track (lat/lon list, capped separately e.g. 5000 points since GPS updates slower).
- `latest_state(vehicle_id) -> dict` — merged current snapshot for a new WS client that just connected.
- `subscribe(vehicle_id, ws_connection)` / `unsubscribe(...)` — simple pub/sub; broadcast is throttled (see C.4).

### `attitude.py`
- If firmware already sends fused pitch/yaw/roll → pass through.
- Else, `class AttitudeFuser` implementing a **complementary filter** (simple, no external deps) combining accelerometer-derived pitch/roll with gyro-integrated rates, output smoothed pitch/yaw/roll in degrees. Keep this isolated so it can later be swapped for a Madgwick/Mahony filter without touching anything else.

### `predictor.py` — Landing Prediction (v1 algorithm)
Deliberately simple and explainable rather than a full flight simulator:
1. Only runs once phase == DESCENT (or APOGEE, to start early).
2. Maintain a short rolling window (last ~10–20 GPS fixes) of lat/lon/alt/time.
3. Compute **vertical descent rate** `vz` from altitude samples (linear regression over the window).
4. Compute **horizontal drift vector** (d_lat/dt, d_lon/dt) from the same window (captures wind drift under the parachute).
5. `time_to_ground = current_altitude / abs(vz)` (guard against divide-by-zero / vz≈0 → mark prediction "low confidence").
6. `predicted_lat = current_lat + d_lat/dt * time_to_ground`, same for lon.
7. Confidence heuristic: based on window R² of the vertical fit and GPS HDOP — surfaced in the UI as High/Med/Low, not a bare number, so it's honest about being an estimate rather than a guarantee.
8. Recompute on every new GPS frame during DESCENT; expose `PredictionResult{lat, lon, eta_seconds, confidence}` via the WS telemetry message so the frontend just renders it, with no prediction math on the client.

### `phase_fsm.py`
- Pure function `next_phase(current_phase, recent_samples) -> phase` implementing the diagram in B.4, with thresholds from `config.py` (see C.7). Also accepts EVENT frames (e.g. `"LAUNCH_DETECT"`, `"CHUTE_DEPLOY"`) as authoritative overrides when present, since an explicit firmware event is more trustworthy than inferring from thresholds.

### `logger.py`
- One CSV per vehicle per connect session: `logs/{vehicle}_{YYYYMMDD_HHMMSS}.csv`, header = flattened telemetry+GPS fields + phase + wall-clock time; append-only, flushed periodically (not just at disconnect) so a crash doesn't lose the flight.
- `list_sessions() -> list[{filename, vehicle, start_time, duration, sample_count}]` for the Replay tab.
- `load_session(filename) -> iterator[frame-like rows]` used to feed the *same* TelemetryHub/prediction/phase pipeline in replay mode, at either real-time pace or a "fast scrub" speed controlled by the UI.

### `simulator.py`
- `class SimulatedVehicleLink` — same interface as `SerialVehicleLink` (drop-in replacement selected in Settings), but instead of opening a real port, it constructs a physics-plausible flight profile (launch → ascent → apogee → descent → landing, with realistic-ish noise) and calls the exact same `on_frame_callback` with **already-encoded byte frames matching protocol.py**, so it exercises the *entire* real pipeline (parser, CRC, phase FSM, predictor) — not a UI-only shortcut like the old mockup's `simData()`.

### `ws_routes.py`
- `GET /ws/{vehicle}` — on connect, immediately sends one `snapshot` message (full current state), then streams `update` messages.
- Message envelope (JSON):
```json
{ "type": "update", "vehicle": "rocket", "t": 1690000000123,
  "telemetry": { "altitude_m": 812.4, "speed_mps": 41.2, "pitch": 12.3, "yaw": 88.0, "roll": -4.1,
                 "temperature_c": 21.4, "pressure_hpa": 934.2, "battery_v": 7.62 },
  "gps": { "lat": 12.9716, "lon": 77.5946, "alt_m": 810.1, "sats": 9, "hdop": 0.9, "fix_type": 2 },
  "phase": "DESCENT",
  "link": { "state": "CONNECTED", "packet_rate_hz": 9.8, "crc_error_count": 2, "last_seq_gap": 0 },
  "prediction": { "lat": 12.9701, "lon": 77.5950, "eta_s": 46, "confidence": "MED" }
}
```
- Throttle: internal ingest can be up to 20 Hz, but the hub only **emits at most every 60 ms (~16 fps)** to WS clients — coalescing multiple ingested samples into one UI update to protect render performance (raw samples are still all logged to CSV and all fed into graphs' backing arrays, just not all individually pushed over the wire).

### `rest_routes.py`
- `GET /ports` → list of serial ports.
- `POST /connect {vehicle, port, baud}` / `POST /disconnect {vehicle}`.
- `POST /simulate {vehicle, enabled: bool}`.
- `GET /replay/sessions`, `POST /replay/load {filename, speed}`.
- `GET /tiles/{z}/{x}/{y}.png` → serves from local `tiles/` folder (static mount).
- `GET /health` → used by the Electron main process to know the backend is alive.

## C.4 Frontend state & rendering strategy

- One Zustand store instance per vehicle (`useRocketStore`, `useSatelliteStore`, or a factory `createVehicleStore('rocket')`), each holding: `latest telemetry/gps/phase/prediction`, `history arrays` (mirrored from what the hub sends, capped e.g. 600 points for on-screen graphs — the full-resolution data lives in the CSV, not in browser memory), `connection state`, `packet stats`.
- `wsClient.js` opens one socket per vehicle tab (only when that vehicle is connected/simulated), dispatches incoming `update` messages into the matching store — components subscribe to slices of the store, so a value update in the Satellite tab never re-renders the Rocket tab.
- Graphs (`recharts`) read directly from the store's capped history arrays; no separate polling.
- 3D body (`react-three-fiber`): a simple procedural mesh (cone+cylinder for rocket, box+solar-panel-planes for satellite — no need for detailed models) whose rotation quaternion is driven every frame from `pitch/yaw/roll` in the store, smoothed with a simple lerp to avoid visual jitter between WS updates.
- `LandingAnimationOverlay` watches `phase` in the store; on transition **into** `LANDED` (edge-triggered, not level-triggered, so it plays once) it mounts a short full-panel animation (e.g. parachute canopy settling + "TOUCHDOWN" banner + the final GPS pin drop-in on the map) and then auto-dismisses to the normal recovered-state view.

## C.5 Packet Monitor panel (LLD)

- Backend already exposes `frames_ok/frames_crc_error/frames_resynced` and last N raw frames (keep last ~50 raw frame byte arrays server-side per vehicle, small ring buffer, exposed either via the same WS stream under a `"packets"` field, or a lighter-weight `/packets/{vehicle}` polling endpoint since this doesn't need 20 Hz).
- Frontend renders: hex bytes (grouped 8/line) + a parsed field table (field name → value) for the most recent frame of each type, plus rolling counters and a sparkline of packet rate — this satisfies "visual for the packets" as a genuine protocol-level debug tool, not just a cosmetic widget.

## C.6 Config & thresholds (`config.py`) — all overridable from Settings UI

```python
DEFAULT_BAUD = 115200          # [ASSUMED]
RING_BUFFER_SAMPLES = 3600      # [ASSUMED] ~3 min at 20Hz
WS_BROADCAST_INTERVAL_MS = 60   # ~16 fps to renderer
LAUNCH_ACCEL_THRESHOLD_G = 2.0  # [ASSUMED] accel magnitude spike to flag ASCENT
APOGEE_VSPEED_EPS = 0.5         # m/s, near-zero vertical speed window to flag APOGEE
LANDED_ALT_EPS_M = 5.0          # [ASSUMED] altitude-above-ground-estimate tolerance
LANDED_SPEED_EPS = 1.0          # m/s
LANDED_CONFIRM_SAMPLES = 15     # sustained samples before committing to LANDED
PREDICTION_WINDOW_SAMPLES = 15
RECONNECT_BACKOFF_S = [2, 2, 3, 5, 5]
```

## C.7 Packaging & lifecycle

- Backend: `pyinstaller --onefile backend/app/main.py` (via the provided spec) → `backend.exe` placed in Electron's `resources/` (extraResources in electron-builder config).
- Electron `main.js`: on app start, `child_process.spawn(backendPath, [...])`, polls `GET /health` until ready, then loads the React build (`file://.../index.html`) pointed at `http://127.0.0.1:PORT`; on app quit, kills the backend child process; if the backend process exits unexpectedly, restart it once and surface a UI toast if it fails again.
- `electron-builder` → NSIS installer for Windows (primary target platform for the competition).
- Frontend build: Vite production build, no CDN `<script src>` tags anywhere (bundle react-leaflet/three/recharts locally) — this is the actual enforcement point for "fully offline."

---

# PART D — BUILD PLAN (phase order for Grok)

Build and get each phase *running end-to-end* (even if ugly) before moving to the next — this avoids Grok generating a huge amount of disconnected code at once.

1. **Repo scaffold**: folder layout from C.1, empty FastAPI app that returns `/health`, empty Vite+React app with the four tabs rendering placeholder text, Electron shell that spawns the (stub) backend and loads the React build. Confirm the whole chain launches as one process.
2. **Protocol + parser + simulator**: implement `protocol.py`, `frame_parser.py`, `simulator.py`. Prove correctness with unit tests that feed known byte sequences (including deliberately corrupted ones) into `FrameParser.feed()` and assert the right frames/counters come out.
3. **Serial layer + hub + WS**: implement `serial_manager.py`, `telemetry_hub.py`, `ws_routes.py`, `rest_routes.py` (`/ports`, `/connect`, `/simulate`). Verify with simulation mode: connect a vehicle in "sim mode" and see JSON `update` messages arrive over a raw WebSocket test client.
4. **React data layer**: `wsClient.js`, Zustand stores, wire Settings tab's simulate-toggle end-to-end so numbers change in a bare-bones Rocket tab.
5. **Core visual panels**: value grid, HUD/compass/3D body, graphs — all reading from the store.
6. **Map + offline tiles**: static tile mount, react-leaflet with local `TileLayer`, live marker + trail.
7. **Phase FSM + landing prediction**: `phase_fsm.py`, `predictor.py`, prediction card + map marker, wire the phase badge.
8. **Packet Monitor**: expose counters/raw frames, build the hex+field UI.
9. **Landing animation**: edge-triggered overlay on phase→LANDED.
10. **Logging + Replay tab**: `logger.py`, replay REST endpoints, `ReplayControls`, make sure replay reuses the exact same components as live mode.
11. **Resilience pass**: disconnect/reconnect behavior, bad-port handling, crash-recovery of the backend child process, verify nothing in the UI throws on malformed frames.
12. **Packaging**: PyInstaller backend build, electron-builder Windows installer, verify the packaged app runs with zero internet and zero Python/Node installed on the target machine.

---

# APPENDIX 1 — Open questions for your team (not blocking, but worth confirming)

1. **Is this receive-only?** Confirm there's no uplink/command channel to either vehicle — if there is (e.g. an arm/disarm command, or a "trigger chute" override), that's a meaningful addition (new REST endpoint + serial write path) and should be scoped explicitly.
2. **Real packet format**: does your firmware team already have a defined telemetry frame layout? If yes, replace Part C.2 with the real one before Grok starts Phase 2 — everything downstream only depends on that one file's contract.
3. **Baud rate & exact RF dongle**: confirm baud rate and whether the dongle does any of its own framing/escaping (e.g. HDLC/COBS) that would sit *underneath* the protocol in C.2.
4. **Is pitch/yaw/roll computed onboard the Pi, or should the ground station fuse raw accel+gyro itself?** Affects whether `attitude.py`'s complementary filter is load-bearing or just a fallback.
5. **Video**: is the Pi Camera module actually streamed live to the ground station, and if so how (MJPEG over the same RF link seems unlikely given bandwidth — more likely WiFi-only at the pad, or post-flight retrieval)? Kept as best-effort/optional per A.4.

---

# APPENDIX 2 — Full Grok build prompt

See the companion file **`GROK_BUILD_PROMPT.md`** — paste that directly into Grok/Grok Code. It references this PRD by section number so Grok builds against a fixed spec rather than improvising architecture.
