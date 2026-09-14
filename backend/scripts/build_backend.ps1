# Build studsat-backend.exe with PyInstaller (Phase 12).
# Run from anywhere; switches to backend/ directory.
$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location $BackendRoot

$py = Join-Path $BackendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating venv..."
    python -m venv .venv
    $py = Join-Path $BackendRoot ".venv\Scripts\python.exe"
}

& $py -m pip install -q -r requirements.txt pyinstaller
Write-Host "Running PyInstaller..."
& $py -m PyInstaller --noconfirm --clean build_backend.spec

$exe = Join-Path $BackendRoot "dist\studsat-backend.exe"
if (-not (Test-Path $exe)) {
    throw "Build failed: $exe not found"
}
Write-Host "OK: $exe"
Get-Item $exe | Format-List Name, Length, LastWriteTime
