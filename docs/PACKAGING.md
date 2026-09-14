# Packaging — STUDSAT Ground Station (Phase 12)

Build a **fully offline** Windows installer: no Python, Node, or internet required on the competition laptop.

## Prerequisites (build machine only)

- Windows x64
- Python 3.10+
- Node.js 18+ and npm
- ~2 GB free disk for Electron cache

## One-shot build

```powershell
cd "X:\path\to\STUDSAT - GROUND STATION GUI"
.\scripts\package-windows.ps1
```

Output installer:

```text
electron\dist\STUDSAT-Ground-Station-Setup-1.0.0.exe
```

## Step-by-step

### 1. Backend executable

```powershell
cd backend
.\scripts\build_backend.ps1
# → backend\dist\studsat-backend.exe
```

Smoke-test the exe:

```powershell
$env:STUDSAT_TILES_DIR = (Resolve-Path ..\tiles)
$env:STUDSAT_LOGS_DIR = (Resolve-Path ..\logs)
.\dist\studsat-backend.exe
# browser: http://127.0.0.1:8765/health  → frozen: true, phase: 12
```

### 2. Frontend production bundle

```powershell
cd frontend
npm install
npm run build
# → frontend\dist\  (base: './', no CDN)
```

### 3. Electron NSIS installer

```powershell
cd electron
npm install
npm run dist
# → electron\dist\STUDSAT-Ground-Station-Setup-*.exe
```

## Packaged layout

```text
resources/
  backend/studsat-backend.exe
  frontend/index.html + assets/
  tiles/   (offline map XYZ)
userData/
  logs/    (CSV sessions — writable)
```

Electron main:

1. Spawns `studsat-backend.exe` with `STUDSAT_TILES_DIR` / `STUDSAT_LOGS_DIR`
2. Polls `GET http://127.0.0.1:8765/health`
3. Loads `resources/frontend/index.html`
4. Restarts backend on crash (watchdog)

## Offline checklist

- [ ] Unplug network
- [ ] Install on a clean VM / second machine **without** Python/Node
- [ ] Launch from Start Menu / desktop shortcut
- [ ] Backend pill green (`1.0.0-phase12`)
- [ ] Start simulation — HUD / map / packet monitor update
- [ ] Map tiles load (placeholders or preloaded XYZ)
- [ ] CSV appears under app userData `logs/`
- [ ] Replay a session from the Replay tab

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Backend offline forever | Run `studsat-backend.exe` manually; check port 8765 free |
| White window | Confirm `frontend/dist` was built before `npm run dist` |
| Missing tiles | Copy XYZ into `tiles/` before packaging |
| Antivirus blocks exe | Code-sign or whitelist PyInstaller/Electron builds |
| Spawn fails | Ensure `backend/dist/studsat-backend.exe` exists before electron-builder |

## Dev vs package

| Mode | Backend | UI |
|------|---------|-----|
| Dev | `python -m app.main` or Electron spawn venv | Vite `npm run dev` |
| Package | `studsat-backend.exe` | Built `file://` from resources |
