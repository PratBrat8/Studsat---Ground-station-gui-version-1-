# Prompt to paste into Grok / Grok Code (v2 — major update)

This is a major update to an existing project. Attach/open `STUDSAT_Ground_Station_PRD_v2.md` in the workspace alongside the existing v1 codebase before pasting this.

---

I'm upgrading my existing STUDSAT ground station app (built through v1's Phase 9-12) with a major set of changes. **Read `STUDSAT_Ground_Station_PRD_v2.md` fully before writing any code.** It supersedes the original `STUDSAT_Ground_Station_PRD.md` — Part A.1 of the v2 document has a table summarizing exactly what changed and why (real CSV telemetry format instead of guessed binary, real uplink command spec, real Reyax RYLR993 dual-LoRa radio hardware instead of a generic assumption, real CAD models, and several new features).

**Do not treat this as a from-scratch rebuild.** Keep the existing architecture (Electron + Python/FastAPI backend + React frontend, two parallel vehicle pipelines, WebSocket telemetry streaming, offline map tiles, CSV session logging, simulation mode) — that structure was validated in v1 and stays. What's changing is: the wire protocol underneath, the addition of a full uplink/command system, and a set of new UI panels.

**The single most important architectural change: this is now a two-layer protocol, not one.** PRD section B.1 and C.2 explain this in detail — the competition's CSV telemetry and CMD command format are carried *inside* the Reyax RYLR993 radio module's own AT-command protocol (`+RCV=...`, `AT+SEND=...`, `+OK`/`+ERR`). Implement `radio_transport.py` (the Reyax layer) as a clean, separate module from `protocol.py` (the competition CSV/CMD layer) — don't merge them, since they're genuinely two different concerns and this separation is what makes RSSI/SNR "free" for the signal strength feature (PRD C.2).

**Major new capability — uplink.** This is the most important addition. Build it per PRD sections A.5.1, C.3, and C.4:
- The exact 5 competition commands (`TX ON/OFF`, `ST`, `CG`, `CB`, `CA`) plus one custom command (`EJ` for manual CanSat ejection).
- A command status lifecycle (`SENT → TRANSMITTED → ACKED/NO_RESPONSE`) shown live in the UI, not fire-and-forget.
- **The manual ejection command (`EJ`) must require a hold-to-confirm or two-step arm/fire UI interaction — never a single click.** This is the highest-consequence action in the whole app; treat the confirmation requirement as a hard constraint, not a nice-to-have.
- Rate-limiting so no command can be accidentally double-sent.
- A persisted command log (timestamped, sent alongside session telemetry logs) for post-flight/competition review.

**New UI panels to build**, per PRD A.5.2–A.5.10 — dual altitude (baro vs GNSS with disagreement warning), battery indicators (rocket gets voltage+current+power+%, CanSat gets voltage+% only — they're different, don't build one generic component and assume it fits both), signal strength (RSSI/SNR + sparkline, sourced directly from the Reyax transport layer), trajectory panel with a live ascent trend-line projection, the 8-state CDR flight phase display with a distinct "CanSat Separated" event banner on the `PAYLOAD_SEP` transition, and a Google Maps handoff button.

**Real CAD models.** Two STEP files are provided in the file called "CAED STEP FILES" (rocket + CanSat). Convert them once to `.glb` (build-time step, document how you did it in the repo so it's repeatable) and load them in the existing 3D attitude view in place of the procedural placeholder shapes from v1, keeping the same live IMU-driven rotation approach.

**Explicitly dropped from scope:** video/GoPro. Don't build any video panel or leave stub code for it — if it's added later it'll be scoped as its own independent addition.

**Follow the v2 build plan in PRD Part D, phase by phase (1 through 14)**, same as before — show me what's built and how to verify it after each phase, don't generate everything at once.

**Ask me before assuming anything listed in PRD Appendix 1** (exact CSV field layout for accelerometer/gyro, CanSat voltage sensing method, whether firmware sends any application-level command acknowledgement, battery chemistry/voltage ranges for the percentage curves, Reyax baud rate/addressing, and confirming the manual ejection command should target the Rocket/Avionics line). These are each isolated to one config value or one function — flag them clearly in your output rather than silently guessing, since a wrong guess here (e.g. a wrong battery curve) produces a confidently wrong number on screen, which is worse than an obviously missing one.

Start by showing me a diff-style summary of exactly what files you're about to add/change for Phase 2 (transport + protocol layer) before writing the full implementation, since this is the foundation everything else sits on.
