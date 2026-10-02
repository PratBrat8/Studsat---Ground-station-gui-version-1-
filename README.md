# STUDSAT Dual Ground Station

Offline desktop ground station for **Rocket** + **Satellite** telemetry (university STUDSAT team).

Spec: `docs/STUDSAT_Ground_Station_PRD_v2.md` (single source of truth). Build order: **Part D** phases 1–14.

| Layer | Stack |
|--------|--------|
| Shell | Electron (Windows primary) |
| Backend | Python, PySerial, FastAPI + WebSocket |
| Frontend | React (Vite), react-leaflet, recharts, R3F/Three.js, Zustand |

**Hard requirement:** zero internet/CDN at runtime.

---

## Current phase: 14 — Packaging (v2.0)

All PRD v2 build phases **1–14** are implemented.

**Package (Windows NSIS, offline):**

```powershell
.\scripts\package-windows.ps1
# → electron\dist\STUDSAT-Ground-Station-Setup-2.0.0.exe
```

Details: [`docs/PACKAGING.md`](docs/PACKAGING.md)

### Prerequisites

- **Python 3.10+** on `PATH` as `python` (Windows) or set `STUDSAT_PYTHON`
- **Node.js 18+** and npm (for UI/Electron; not required for Phase 2 tests)

### One-time setup

```powershell
# From repo root
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd ..\frontend
npm install

cd ..\electron
npm install
```

### Verify Phase 6 (offline map)

```powershell
# Backend tiles
cd backend
.\.venv\Scripts\Activate.ps1
python scripts/generate_demo_tiles.py   # optional local XYZ around sim pad
python -m app.main

# Check tile endpoint (PNG, offline)
# GET http://127.0.0.1:8765/tiles/14/11600/7340.png
# GET http://127.0.0.1:8765/tiles/info

# Frontend — Start simulation → map marker + trail move
cd frontend
npm run dev
```

### Verify Phase 4–5 (UI live numbers / panels via sim)

```powershell
# Terminal 1 — backend
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.main

# Terminal 2 — frontend (requires Node/npm)
cd frontend
npm install
npm run dev
# Open http://127.0.0.1:5173
# Rocket tab → Start simulation → altitude/pitch/etc. should tick live
# Settings → independent sim toggles for Rocket and Satellite
```

Backend tests (includes Phase 3 WS integration):

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests -v
# Expect: 30 passed
```

**Manual smoke (sim mode → live JSON updates):**

```powershell
# Terminal 1
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.main

# Terminal 2 — enable sim, then open WS (PowerShell example uses curl + python)
curl -X POST http://127.0.0.1:8765/simulate -H "Content-Type: application/json" -d "{\"vehicle\":\"rocket\",\"enabled\":true}"
python -c "import asyncio,json; import websockets; 
async def m():
  async with websockets.connect('ws://127.0.0.1:8765/ws/rocket') as ws:
    for i in range(5):
      print(json.loads(await ws.recv())['type'], json.loads(await (lambda: ws.recv())()) if False else '')
"
```

Simpler Python client:

```powershell
python -c "
import json, urllib.request
from websocket import create_connection
urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8765/simulate', data=b'{\"vehicle\":\"rocket\",\"enabled\":true}', headers={'Content-Type':'application/json'}))
# or use: pytest tests/test_phase3_integration.py -v
print('use pytest for WS verification if websocket-client not installed')
"
```

REST quick check:

```text
GET  /health
GET  /ports
POST /simulate   {"vehicle":"rocket","enabled":true}
GET  /status
WS   /ws/rocket  → snapshot then update messages
POST /disconnect {"vehicle":"rocket"}
POST /connect    {"vehicle":"rocket","port":"COM3","baud":115200}
```

### How to run the app shell

```powershell
# Terminal 1 — backend
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.main
# → http://127.0.0.1:8765/health  (phase: 3)

# Terminal 2 — frontend
cd frontend
npm run dev
```

### Electron (optional)

```powershell
cd frontend; npm run dev
# other terminal:
cd electron; npm run dev
```

---

## Repository layout (PRD C.1)

See tree; protocol/parser/simulator are implemented. Serial hub + WS land in Phase 3.
