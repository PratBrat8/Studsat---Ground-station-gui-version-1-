# STUDSAT Ground Station — PRD, HLD & LLD (v2)

**Supersedes:** `STUDSAT_Ground_Station_PRD.md` (v1)
**What changed and why:** v1 was written before the team's CDR (Critical Design Review) document and hardware were finalized, so it invented a binary packet protocol and a receive-only architecture as reasonable placeholders. This version replaces those placeholders with the **actual competition-mandated telemetry format, the actual command/uplink specification, and the actual radio hardware (Reyax RYLR993 LoRa, dual-band)**, and adds the full v2 feature set: uplink, battery/signal indicators, manual ejection failsafe, real CAD models, trajectory/prediction views, and more.

Anything still marked **[OPEN]** is a real unanswered question — listed together in Appendix 1 — that should be resolved with your hardware/firmware lead before or during the build, since it affects a specific, isolated part of the system rather than the whole architecture.

---

# PART A — PRODUCT REQUIREMENTS (v2)

## A.1 What changed from v1, at a glance

| Area | v1 (guessed) | v2 (confirmed from CDR + team) |
|---|---|---|
| Telemetry format | Custom binary frame + CRC16 | **ASCII CSV line**, exact fields per CDR §8.4 |
| Uplink | Not in scope | **Mandatory**, exact command set per CDR §8.6, plus a custom ejection command |
| Radio | Assumed generic USB dongle | **Reyax RYLR993 LoRa**, two independent units: one for CanSat, one for Rocket/Avionics (main band + redundant band per competition rules) |
| Architecture | One-way, ground listens only | **Two-way**: ground station sends commands, vehicles send telemetry + command acknowledgements |
| 3D models | Generic procedural shapes | **Real CAD** — rocket and CanSat STEP files provided, converted to web-friendly 3D models |
| Video | In scope (deferred design) | **Removed from scope** — no video hardware finalized yet |
| Flight phases | Informal (IDLE/ARMED/ASCENT/...) | **Exact 8 states from CDR**: `0 BOOT, 1 TEST_MODE, 2 LAUNCH_PAD, 3 ASCENT, 4 PAYLOAD_SEP, 5 DESCENT, 6 AEROBREAK_RELEASE, 7 IMPACT` |

## A.2 Hardware (confirmed)

| Vehicle | Compute | Sensors | Radio |
|---|---|---|---|
| **Rocket / Avionics Bay** | Teensy 4.1 | INA219 (power), BMP388 (baro pressure + altitude), MPU9250 (9-axis IMU), Bharat Pi GNSS, SD card (onboard backup log) | Reyax RYLR993 — **redundant band** |
| **CanSat payload** | Raspberry Pi Zero 2W | BME680 (pressure/temp/humidity/gas), MPU9250, GNSS, SD card | Reyax RYLR993 — **main/CanSat band** |
| **Ground station** | Laptop | — | Two Reyax RYLR993 units on USB-to-serial adapters (one per band), each a separate COM port |

CanSat power reading is assumed to be a **raw battery voltage read** (no INA219-equivalent on the payload side, per team confirmation) — this means the CanSat's battery indicator shows voltage only, not current/power draw like the rocket's does. **[OPEN — confirm exact voltage sensing method: direct ADC pin, voltage divider, etc., since that affects the calibration constant in firmware, not the ground station.]**

## A.3 Goals (v2, full list)

Carried over from v1 where unchanged, with new/updated goals below:

- **G1–G9 from v1** still apply: dual-vehicle tabs, standard readouts, packet visualizer, graphs, attitude animation, landing prediction, session logging/replay, offline-first, resilient serial handling — all now built against the **real** protocol instead of a guessed one.
- **G11 (new): Uplink command channel.** The ground station can send the competition-mandated commands (telemetry on/off, set time, calibrate gyro/baro/accel) to either vehicle independently, plus a custom manual-ejection command, with acknowledgement tracking and confirm-before-send safety gating on destructive commands.
- **G12 (new): Dual independent altitude cross-check.** GNSS altitude and barometric altitude are always shown side by side, with a visible warning if they diverge beyond a threshold — this is the sensor-level failsafe requirement.
- **G13 (new): Battery/power indicators.** Rocket: voltage + current + percentage + a visual battery icon (from INA219). CanSat: voltage + percentage + visual battery icon (voltage-only).
- **G14 (new): Signal strength display.** RSSI/SNR of the downlink (what the ground station receives from each vehicle), read directly from the Reyax module's own reporting — no estimation needed, the hardware already provides this.
- **G15 (new): Manual CanSat ejection failsafe.** A dedicated, confirm-gated control that sends a custom uplink command to trigger CanSat separation manually, independent of the automatic flight-software-driven separation.
- **G16 (new): Real CAD-based 3D models.** The rocket and CanSat 3D views use the team's actual STEP-file geometry (converted to a web format), not generic placeholder shapes, animated by live IMU orientation.
- **G17 (new): Trajectory & path prediction views.** A dedicated trajectory panel showing the flight path (altitude vs. distance / 3D path), climb angle, and a live-updating projected trend-line during ascent (visual extrapolation, not a physics simulation) — distinct from the existing post-apogee landing prediction.
- **G18 (new): Vehicle power on/off + telemetry on/off controls.** UI-level buttons mapping directly onto the CDR's `CMD,TEAM_ID,TX,ON/OFF` command, exposed clearly for each vehicle.
- **G19 (new): Communication link staging.** The UI shows not just "connected/disconnected" but the actual staged link state (port opened → TX command sent → telemetry active → link stable/degraded/lost), plus live data rate (packets/sec and bytes/sec).
- **G20 (new): Separation event indicator.** A clear, unmissable on-screen event/banner the moment the rocket's telemetry reports flight state `4 = PAYLOAD_SEP`, marking the CanSat's independent descent tracking as now active.
- **G21 (new): Google Maps handoff.** A button that opens the last known GPS position in Google Maps in the default browser, for the recovery team — explicitly best-effort/optional since it requires internet at the moment it's clicked (does not compromise the rest of the app's offline-first design).

## A.4 Non-goals (v2)

- **Video/GoPro is explicitly out of scope for this version** — hardware not finalized. Designed to be addable later as an independent panel without touching the rest of the system.
- Full 6-DOF flight simulation for ascent path prediction — v2 uses a lightweight visual trend-line extrapolation, matching the same "honest estimate" philosophy as the landing predictor.
- Automatic determination of the *vehicle's* received signal strength of the ground's uplink (i.e., true bidirectional signal quality) — the Reyax module only reports RSSI/SNR of what *it* received, so the ground station can only natively show downlink quality unless the firmware is changed to report uplink RSSI back inside telemetry. **[OPEN — flagged in Appendix 1.]**

## A.5 Functional requirements — new/changed items in detail

### A.5.1 Uplink command panel (per vehicle)
Each vehicle tab gets a **Command Console** section with:
- **Telemetry ON/OFF** toggle → sends `CMD,<TEAM_ID>,TX,ON` / `CMD,<TEAM_ID>,TX,OFF`.
- **Set Time** → sends `CMD,<TEAM_ID>,ST,<UTC_TIME>` (auto-filled from system clock, editable).
- **Calibrate Gyro / Baro / Accel** buttons → send `CMD,<TEAM_ID>,CG,R` / `CB,R` / `CA,R` respectively.
- **Manual CanSat Ejection** (Rocket tab only, since the separation mechanism lives in the Avionics Bay) → sends a custom `CMD,<TEAM_ID>,EJ,R` command. **Requires a hold-to-confirm interaction (press and hold ~2 seconds, or a two-step "Arm → Fire" pattern)** — this is the highest-consequence command in the system and must never be a single accidental click.
- Every sent command shows a status chip: `SENT` → `ACKED` (if/when the vehicle confirms) → or `NO RESPONSE` after a timeout, so the operator always knows whether a command actually landed, not just that it was transmitted.
- A **command log**, timestamped, of every command sent and its outcome, for post-flight review and competition compliance records.

### A.5.2 Dual altitude & sensor failsafe display
- Rocket tab shows **Baro Altitude (BMP388)** and **GNSS Altitude** side by side, plus their delta. If the delta exceeds a configurable threshold, both values highlight visually (e.g. amber/red) as a "sensor disagreement" warning — this is your failsafe against trusting a single bad sensor mid-flight.

### A.5.3 Battery & power panel
- Rocket: voltage, current, computed power, and an estimated percentage (from INA219, using a configurable voltage-to-percentage curve for your specific battery chemistry), shown as both a number and an aesthetic battery-level icon (fill proportional to percentage, color-graded green→amber→red).
- CanSat: voltage and estimated percentage only (no current/power, per confirmed hardware), same visual battery icon style for consistency.

### A.5.4 Signal strength panel
- Shows **RSSI and SNR** for the most recently received packet on each vehicle's link, read directly from the Reyax module's `+RCV=` response fields (see C.2) — plus a short rolling sparkline so a degrading link is visible as a trend, not just a single number.

### A.5.5 Trajectory & path prediction panel
- A dedicated view (separate from the map) showing the flight path as altitude vs. horizontal distance (or a 3D path plot), current climb angle (from IMU pitch), and — during ASCENT — a dashed projected trend-line extrapolating the current trajectory forward, clearly styled as a projection/estimate (e.g. dashed line, lower opacity), not a certainty.

### A.5.6 Separation & phase events
- When the Rocket's flight state transitions to `4 = PAYLOAD_SEP`, the UI fires a clear banner/event ("CanSat Separated") and the CanSat's own landing-prediction tracking is flagged as now the primary thing to watch (since the two vehicles descend independently from this point).
- All 8 CDR flight states are shown as a labeled progress indicator per vehicle, not just an internal variable.

### A.5.7 Vehicle power controls
- Explicit **ON/OFF** buttons per vehicle in the Command Console, wired to the same `TX ON/OFF` uplink command as A.5.1 — surfaced prominently (not buried in Settings) since this is a primary operational control, not a configuration option.

### A.5.8 Communication link staging & data rate
- Link status is shown as one of: `DISCONNECTED → PORT OPEN → TX COMMAND SENT → TELEMETRY ACTIVE → LINK STABLE → LINK DEGRADED → LINK LOST`, driven by real signal (first valid line received, rolling packet-loss rate, time since last packet).
- Live **data rate**: packets/sec and bytes/sec, rolling average.

### A.5.9 3D CAD models
- Rocket and CanSat 3D views use the team-provided STEP files (`rocket_150.step`, CanSat STEP), converted once at build time into a web-friendly format (GLTF/GLB), and animated live using IMU-derived orientation (pitch/yaw/roll), matching v1's animation approach but with real geometry instead of procedural shapes.

### A.5.10 Google Maps handoff
- A button on the map panel, using the last known GPS fix, opens `https://www.google.com/maps?q=<lat>,<lon>` in the system's default browser — clearly labeled as requiring internet at the moment it's used (this is the one explicitly-online-if-clicked feature in an otherwise offline-first app).

---

# PART B — HIGH-LEVEL DESIGN (v2)

## B.1 Two-layer protocol — this is the key technical change from v1

Because the radio hardware is now confirmed as **Reyax RYLR993**, the wire format is not just "the competition's CSV telemetry" — the CSV/command data is actually **wrapped inside the Reyax module's own AT-command protocol**. This is a two-layer design:

```
┌─────────────────────────────────────────────────────────┐
│  APPLICATION LAYER  (competition-defined, CDR §8.4/8.6)  │
│  - Telemetry: CSV line (team id, timestamp, altitude...) │
│  - Commands: CMD,<TEAM_ID>,<TYPE>,<VALUE>                │
└─────────────────────────────────────────────────────────┘
                          ▲  carried as payload inside  ▼
┌─────────────────────────────────────────────────────────┐
│  TRANSPORT LAYER  (Reyax RYLR993 AT protocol, over UART) │
│  - Receiving:  +RCV=<addr>,<len>,<data>,<rssi>,<snr>\r\n │
│  - Sending:    AT+SEND=<addr>,<len>,<data>\r\n           │
│  - Responses:  +OK\r\n  or  +ERR=<code>\r\n              │
└─────────────────────────────────────────────────────────┘
```

This matters practically because:
- **RSSI/SNR come for free** from the transport layer's `+RCV=` line — this is exactly what powers the Signal Strength panel (A.5.4), no separate measurement needed.
- Sending a command means the ground station backend must first wrap the application-layer command string in an `AT+SEND=` transport command, then wait for the module's own `+OK`/`+ERR` response (transport-level ack, i.e. "the module transmitted it") — which is a **separate, earlier** acknowledgement than the vehicle's own command-received acknowledgement (application-level ack, i.e. "the Teensy/Pi actually got and executed it"). The UI's `SENT → ACKED` status chip (A.5.1) should ideally distinguish these two if the team wants full clarity, though a single combined status is also acceptable for v2.
- Corruption handling is now **line/field-based**, not CRC-based: a valid application-layer CSV telemetry line must have the expected number of comma-separated fields, each parseable as its expected type (number, timestamp, etc.); a line failing either check is dropped and counted as an error, same philosophy as v1's CRC failures, just a different validation mechanism appropriate to ASCII data.

## B.2 Architecture overview (updated)

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          ELECTRON APP (desktop)                            │
│  Electron Main ──spawns──▶ Python Backend ◀──WebSocket/REST──▶ React UI    │
└───────────────────────────────────────────────────────────────────────────┘
        ▲ USB                                          ▲ USB
 ┌──────┴───────┐                                ┌──────┴───────┐
 │ Reyax RYLR993 │◀── LoRa (CanSat band) ── CanSat Pi Zero 2W    │
 │ (COM port A)  │                                                │
 └───────────────┘                                                │
 ┌───────────────┐                                                │
 │ Reyax RYLR993 │◀── LoRa (Redundant/Rocket band) ── Teensy 4.1  │
 │ (COM port B)  │                                                │
 └───────────────┘                                                │
```

Two Reyax modules, two COM ports, two independent vehicle pipelines inside one backend process — this is structurally identical to v1's design, just now with the correct radio and protocol underneath. **Uplink flows the same path in reverse**: React → REST call → backend command queue → `AT+SEND=` on the correct COM port → Reyax module → vehicle.

## B.3 Mission phase mapping (replaces v1's informal FSM)

The phase state machine is no longer inferred from thresholds — it's simply **read directly** from the `<FLIGHT SOFTWARE STATE>` field already present in every telemetry line:

```
0 BOOT → 1 TEST_MODE → 2 LAUNCH_PAD → 3 ASCENT → 4 PAYLOAD_SEP → 5 DESCENT → 6 AEROBREAK_RELEASE → 7 IMPACT
```

This is simpler and more trustworthy than v1's threshold-guessing approach, since the vehicle's own flight software is the authority on its state — the ground station just displays it clearly and triggers UI events (like the PAYLOAD_SEP banner) on transitions.

---

# PART C — LOW-LEVEL DESIGN (v2)

## C.1 Updated repository additions

```
backend/app/
├── radio_transport.py     # NEW — Reyax AT protocol: encode AT+SEND, parse +RCV/+OK/+ERR, extract RSSI/SNR
├── protocol.py             # UPDATED — now CSV telemetry parser (competition format) + CMD command builder
├── command_manager.py      # NEW — uplink command queue, ACK tracking, timeouts, rate-limiting, confirm-gating hooks
├── phase_map.py             # UPDATED (was phase_fsm.py) — direct lookup from FLIGHT SOFTWARE STATE field
├── predictor.py               # UPDATED — now explicitly two independent instances (rocket, cansat), unchanged algorithm
├── power.py                    # NEW — voltage/current → percentage conversion (configurable curve), per vehicle
└── ...(rest unchanged from v1: serial_manager.py, telemetry_hub.py, attitude.py, logger.py, simulator.py, ws_routes.py, rest_routes.py, config.py)

frontend/src/components/
├── command/ (CommandConsole.jsx, EjectButton.jsx — hold-to-confirm, CommandLog.jsx)
├── power/ (BatteryIndicator.jsx — aesthetic fill icon + %)
├── signal/ (SignalStrengthCard.jsx — RSSI/SNR + sparkline)
├── altitude/ (DualAltitudeCard.jsx — baro vs GNSS, delta warning)
├── trajectory/ (TrajectoryPanel.jsx — path + climb angle + projected trend-line)
└── ...(rest unchanged from v1: attitude/, map/, graphs/, packets/, prediction/, landing/, replay/, settings/)

assets/models/
├── rocket.glb        # converted from rocket_150.step (one-time, build-time conversion)
└── cansat.glb         # converted from provided CanSat STEP file
```

## C.2 `radio_transport.py` — Reyax RYLR993 AT protocol

**Receiving (parsing incoming lines from the module):**
```
+RCV=<address>,<length>,<data>,<rssi>,<snr>\r\n
```
- `address`: sender's configured module address (int).
- `length`: byte length of `<data>`.
- `data`: the actual application-layer payload — this is where the competition's CSV telemetry line (or an ACK string) lives.
- `rssi`: signal strength in dBm (negative int, e.g. `-72`).
- `snr`: signal-to-noise ratio (float, e.g. `9.5`).

`parse_rcv_line(line: str) -> RadioPacket | None` — returns a dataclass `RadioPacket(address, data, rssi, snr)`, or `None` with an error counter increment if the line doesn't match the expected format (malformed/partial line — e.g. a radio glitch cut it mid-transmission).

**Sending (uplink):**
```
AT+SEND=<address>,<length>,<data>\r\n
```
`build_send_command(address: int, payload: str) -> bytes` — constructs this exact string, encodes to bytes for the serial write.

**Module responses to sent commands:**
- `+OK\r\n` — module accepted and transmitted.
- `+ERR=<code>\r\n` — module-level error (e.g. bad parameters) — surfaced to the UI's command status chip as a distinct failure reason from "no response."

## C.3 `protocol.py` — Application layer (competition format)

**Telemetry (downlink), per CDR §8.4 — exact field order:**
```
TEAM_ID, TIMESTAMP, PACKET_COUNT, ALTITUDE, PRESSURE, TEMP, VOLTAGE,
GNSS_TIME, GNSS_LAT, GNSS_LON, GNSS_ALT, GNSS_SATS, ACCEL_X, ACCEL_Y, ACCEL_Z,
GYRO_X, GYRO_Y, GYRO_Z, FLIGHT_SOFTWARE_STATE
```
**[ASSUMED]** exact decimal precision and accelerometer/gyro field splitting (3 axes each) — the CDR names them as single `<ACCELEROMETER DATA>` / `<GYRO SPIN RATE>` fields without specifying if that's one combined value or three axis values; v2 assumes 3 separate comma fields each, which is the far more common real implementation — **[OPEN — confirm exact field-by-field CSV layout against actual firmware output before final integration; this is the one thing worth getting a real sample telemetry line for.]**

`parse_telemetry_csv(data: str) -> TelemetryRecord | None` — splits on commas, validates field count, parses each field to its expected type; returns `None` (and increments an error counter) on any mismatch, rather than throwing.

**Commands (uplink), per CDR §8.6, plus one custom addition:**
```python
def cmd_telemetry_power(team_id: str, on: bool) -> str:
    return f"CMD,{team_id},TX,{'ON' if on else 'OFF'}"

def cmd_set_time(team_id: str, utc_time: str) -> str:
    return f"CMD,{team_id},ST,{utc_time}"

def cmd_calibrate(team_id: str, which: str) -> str:   # which: 'CG' gyro, 'CB' baro, 'CA' accel
    return f"CMD,{team_id},{which},R"

def cmd_manual_ejection(team_id: str) -> str:          # CUSTOM — not in CDR, team-defined
    return f"CMD,{team_id},EJ,R"
```

## C.4 `command_manager.py`

- `send_command(vehicle, command_str, requires_confirmation: bool, ack_timeout_s: float)`:
  1. If `requires_confirmation` (true for `EJ`, and recommended for `TX,OFF`), the REST endpoint itself requires an explicit `confirmed: true` flag in the request body — the frontend's hold-to-confirm UI is what actually sets that flag, so a bare/accidental API call can't trigger it.
  2. Wraps the command string via `radio_transport.build_send_command()`, writes to the correct serial port.
  3. Tracks `status = SENT`, starts a timeout timer.
  4. On `+OK` from the module → `status = TRANSMITTED` (transport-level ack).
  5. If a subsequent telemetry/ack line from the vehicle explicitly confirms the command (**[OPEN — does the firmware send any command-received acknowledgement back, or is this purely fire-and-forget from the vehicle's side? If firmware doesn't ack, the ground station can only ever show TRANSMITTED, not a true vehicle-side ACKED — flag this to your firmware lead if application-level ACK matters to you.]**) → `status = ACKED`.
  6. On timeout with no `+OK` → `status = NO_RESPONSE`.
- **Rate limiting**: refuses to send the same command type again within a configurable cooldown (e.g. 3 seconds) to prevent accidental double-sends (double-click protection), independent of the UI's own hold-to-confirm gating — belt and suspenders.
- Every call is appended to the command log (persisted to disk alongside the session's telemetry CSV) for post-flight review.

## C.5 `power.py`

- Rocket: `percentage = voltage_to_percent(voltage, curve=ROCKET_BATTERY_CURVE)` — a configurable lookup/interpolation table in `config.py`, since Li-ion/LiPo/NiMH discharge curves differ; current × voltage = power, all three shown.
- CanSat: same `voltage_to_percent()` using its own configurable curve, percentage + voltage only.
- **[OPEN — confirm battery chemistry and voltage range for both vehicles so the percentage curve is accurate; a wrong curve gives a confidently wrong number, which is worse than not showing a percentage at all.]**

## C.6 Dual altitude failsafe logic
- `altitude_delta = abs(baro_altitude - gnss_altitude)`
- If `altitude_delta > ALTITUDE_DISAGREEMENT_THRESHOLD_M` **[ASSUMED default 30m, tune based on real GNSS accuracy specs]**, both values render with a warning style, and an event is logged — this is a passive display failsafe (alerts the operator), not an automatic control action.

## C.7 Trajectory panel algorithm
- Plots recorded (distance-from-launch, altitude) points as the flight progresses.
- During `ASCENT`, fits a simple linear or low-order polynomial trend to the last N points **[ASSUMED N=10]** and draws a short dashed projection forward — explicitly a visual trend, styled to look like an estimate (dashed, translucent), consistent with how the landing predictor is presented.
- Climb angle = `atan2(vertical_speed, horizontal_speed)`, or directly from IMU pitch if preferred — both are reasonable; default to IMU pitch since it's more direct and already available.

## C.8 CAD asset pipeline
- One-time build step (documented in `scripts/`): convert `rocket_150.step` and the CanSat STEP file to `.glb` using a STEP→GLTF conversion tool (e.g. FreeCAD's Python console, or an online/offline STEP-to-GLTF converter — exact tool choice left to Grok/team, since this is a build-time asset step, not runtime code).
- Resulting `.glb` files are loaded in `Body3D.jsx` via `@react-three/drei`'s `useGLTF`, with the same live-rotation-from-IMU-quaternion approach as v1, just applied to the real mesh instead of a procedural shape.

## C.9 Config additions (`config.py`)
```python
REYAX_BAUD = 115200                        # [ASSUMED — confirm against actual Reyax config]
COMMAND_ACK_TIMEOUT_S = 3.0
COMMAND_RATE_LIMIT_S = 3.0
ALTITUDE_DISAGREEMENT_THRESHOLD_M = 30.0    # [ASSUMED]
TRAJECTORY_TREND_WINDOW_SAMPLES = 10        # [ASSUMED]
ROCKET_BATTERY_CURVE = [...]                 # [OPEN] needs real chemistry/voltage range
CANSAT_BATTERY_CURVE = [...]                  # [OPEN] needs real chemistry/voltage range
```

---

# PART D — BUILD PLAN (v2, replaces v1's Part D)

Uplink is now integrated from Phase 2 onward instead of being absent — this is the main structural difference from v1's phase order.

1. **Repo scaffold** — unchanged from v1.
2. **Transport + application protocol + simulator** — `radio_transport.py` (Reyax AT parsing/encoding), `protocol.py` (CSV telemetry + CMD builder), updated `simulator.py` that generates fake `+RCV=` lines wrapping fake CSV telemetry, so simulation mode exercises the full two-layer stack.
3. **Serial layer + hub + WS + uplink REST** — `serial_manager.py`, `telemetry_hub.py`, `command_manager.py`, `ws_routes.py`, and REST endpoints for sending commands — verified by sending a simulated command and seeing `+OK`/ack status flow back in sim mode.
4. **React data layer** — WS client, stores, and a bare Command Console that can actually fire a simulated command end-to-end.
5. **Core visual panels** — value grid, dual altitude card, battery indicators, signal strength card.
6. **HUD/attitude + real CAD 3D models** — convert STEP files, wire up live rotation.
7. **Map + offline tiles + Google Maps handoff button.**
8. **Trajectory panel + ascent trend-line + landing prediction (both vehicles independently).**
9. **Phase display (8 CDR states) + PAYLOAD_SEP separation event banner.**
10. **Packet Monitor**, extended to show RSSI/SNR and transport-layer errors alongside application-layer parse errors.
11. **Command Console full build-out** — calibration buttons, TX on/off, and the hold-to-confirm manual ejection control, plus the command log.
12. **Logging + Replay tab** — now also logs the command log, not just telemetry.
13. **Resilience pass** — reconnect logic, malformed-line handling, command timeout handling, backend crash recovery.
14. **Packaging** — unchanged from v1 (PyInstaller + electron-builder).

---

# APPENDIX 1 — Open items to resolve (isolated, non-blocking to start building)

1. **Exact CSV field-by-field layout** — confirm whether accelerometer/gyro are 3 separate fields each or combined, and confirm decimal precision, against a real sample telemetry line from firmware if one exists.
2. **CanSat voltage sensing method** — direct ADC vs. divider — affects firmware calibration, not ground station code, but worth knowing for the percentage curve.
3. **Application-level command acknowledgement** — does vehicle firmware send any explicit "command received" reply, or is `+OK` (transport-level, module-to-module) the only confirmation available? Determines whether the UI can ever show a true `ACKED` state or only `TRANSMITTED`.
4. **Battery chemistry/voltage range** for both vehicles, to build accurate percentage curves.
5. **True bidirectional signal strength** — only possible if firmware is changed to report the uplink's RSSI back inside its own telemetry; otherwise ground station shows downlink RSSI/SNR only (still fully functional, just one-directional).
6. **Reyax module baud rate and address configuration** (each module needs a configured address for the AT+SEND addressing scheme to work correctly between exactly the right ground/vehicle pair).
7. **Manual ejection command target** — assumed to go to the Rocket/Avionics Bay line (since the separation mechanism appears to live there per the whiteboard's rails/separation-plate design), not the CanSat line — confirm this is correct.

None of these block starting the build — they're each isolated to one specific file/config value, not the overall architecture.

---

# APPENDIX 2 — Grok build prompt

See the companion file **`GROK_BUILD_PROMPT_v2.md`**.
