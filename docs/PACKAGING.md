# Packaging — STUDSAT Ground Station (Phase 14)

Build a **fully offline** Windows installer: no Python, Node, or internet required on the competition laptop.

PRD v2 D.14 is the same pipeline as v1 Phase 12: PyInstaller onefile backend + Vite production UI + electron-builder NSIS/portable.

Installer version is **2.0.0**. Backend health reports `version: 2.0.0-phase14`, `v2_phase: 14`, `frozen: true`.

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
electron\dist\STUDSAT-Ground-Station-Setup-2.0.0.exe
electron\dist\STUDSAT-Ground-Station-Portable-2.0.0.exe   (if portable target is built)
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
# browser: http://127.0.0.1:8765/health  → frozen: true, v2_phase: 14
```

### 2. Frontend production bundle

```powershell
cd frontend
npm install
npm run build
# → frontend\dist\  (base: './', no CDN)
# GLB models are copied from frontend/public/models → dist/models
```

### 3. Electron NSIS installer

```powershell
cd electron
npm install
npm run dist
# → electron\dist\STUDSAT-Ground-Station-Setup-2.0.0.exe
```

`CSC_IDENTITY_AUTO_DISCOVERY=false` is set by `package-windows.ps1` so unsigned Windows builds do not fail on winCodeSign.

## Packaged layout

```text
resources/
  backend/studsat-backend.exe
  frontend/index.html + assets/ + models/*.glb
  tiles/   (offline map XYZ)
userData/
  logs/    (CSV sessions + sibling _commands.csv — writable)
```

Not packaged (build-time / source only):

- `venv` / `backend/.venv` / `tools/cad-venv`
- `node_modules`
- `CAED STEP FILES/` (STEP conversion is a build-time CadQuery step)
- `backend/dist` is an extraResource input, not a second copy of Python

Electron main:

1. Spawns `studsat-backend.exe` with `STUDSAT_TILES_DIR` / `STUDSAT_LOGS_DIR`
2. Polls `GET http://127.0.0.1:8765/health`
3. Loads `resources/frontend/index.html`
4. Restarts backend on crash (watchdog, max 5 restarts)

## Offline checklist

- [ ] Unplug network
- [ ] Install on a clean VM / second machine **without** Python/Node
- [ ] Launch from Start Menu / desktop shortcut
- [ ] Backend pill green (`2.0.0-phase14`)
- [ ] Start simulation — HUD / map / packet monitor / command console update
- [ ] Map tiles load (placeholders or preloaded XYZ)
- [ ] 3D models load (`frontend/models/*.glb`)
- [ ] CSV + `_commands.csv` appear under app userData `logs/`
- [ ] Replay a session from the Replay tab
- [ ] Google Maps handoff is the only action that needs internet

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Backend offline forever | Run `studsat-backend.exe` manually; check port 8765 free |
| White window | Confirm `frontend/dist` was built before `npm run dist` |
| Missing tiles | Copy XYZ into `tiles/` before packaging |
| Missing 3D | Confirm `frontend/public/models/*.glb` exist before Vite build |
| Antivirus blocks exe | Code-sign or whitelist PyInstaller/Electron builds |
| Spawn fails | Ensure `backend/dist/studsat-backend.exe` exists before electron-builder |
| Hidden-import crash | `build_backend.spec` must list `app.trajectory` and v2 modules |

## Dev vs package

| Mode | Backend | UI |
|------|---------|-----|
| Dev | `python -m app.main` or Electron spawn venv | Vite `npm run dev` |
| Package | `studsat-backend.exe` | Built `file://` from resources |
