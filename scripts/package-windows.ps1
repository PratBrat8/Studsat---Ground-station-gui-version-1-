# STUDSAT Ground Station — full Windows package (Phase 14 / PRD v2 D.14).
# Prerequisites: Python 3.10+, Node.js 18+, npm
# Output: electron/dist/*.exe installer (NSIS) — Setup-2.0.0.exe
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== 1/3 Backend (PyInstaller) ===" -ForegroundColor Cyan
& "$RepoRoot\backend\scripts\build_backend.ps1"
if (-not (Test-Path "$RepoRoot\backend\dist\studsat-backend.exe")) {
    throw "backend exe missing"
}

Write-Host "=== 2/3 Frontend (Vite production) ===" -ForegroundColor Cyan
Set-Location "$RepoRoot\frontend"
if (-not (Test-Path "node_modules")) { npm install }
npm run build
if (-not (Test-Path "dist\index.html")) { throw "frontend dist missing" }

Write-Host "=== 3/3 Electron installer (electron-builder) ===" -ForegroundColor Cyan
Set-Location "$RepoRoot\electron"
if (-not (Test-Path "node_modules")) { npm install }
# Ensure electron-builder present
npm install --save-dev electron-builder@^25.1.8
# Avoid winCodeSign symlink privilege errors on Windows without Developer Mode
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
npx electron-builder --win nsis --config.win.signAndEditExecutable=false --publish never

Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "Installer under: $RepoRoot\electron\dist\"
Get-ChildItem "$RepoRoot\electron\dist" -File -ErrorAction SilentlyContinue | Format-Table Name, @{N='MB';E={[math]::Round($_.Length/1MB,2)}}
