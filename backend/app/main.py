"""
STUDSAT Ground Station — FastAPI backend entry point.

Phase 12: runs as `python -m app.main` in dev, or as frozen studsat-backend.exe.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure `backend` is on path when run as `python -m app.main`.
_APP_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _APP_DIR.parent
if not getattr(sys, "frozen", False) and str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import HOST, LOGS_DIR, PORT, TILES_DIR
from app.connection_manager import ConnectionManager
from app.rest_routes import router as rest_router
from app.telemetry_hub import TelemetryHub
from app.tile_server import router as tile_router
from app.ws_routes import router as ws_router

APP_VERSION = "1.0.0-phase12"


@asynccontextmanager
async def lifespan(app: FastAPI):
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    hub = TelemetryHub()
    connections = ConnectionManager(hub)
    app.state.hub = hub
    app.state.connections = connections

    loop = asyncio.get_running_loop()
    hub.set_loop(loop)
    broadcaster = asyncio.create_task(hub.start_broadcaster())
    app.state.broadcaster = broadcaster

    try:
        yield
    finally:
        broadcaster.cancel()
        try:
            await broadcaster
        except asyncio.CancelledError:
            pass
        connections.stop_all()


app = FastAPI(
    title="STUDSAT Ground Station Backend",
    version=APP_VERSION,
    description="Offline dual-vehicle (Rocket + Satellite) telemetry backend.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)
app.include_router(ws_router)
app.include_router(tile_router)


@app.get("/health")
def health() -> dict:
    """Used by Electron main process; includes light diagnostics (Phase 11)."""
    body: dict = {
        "status": "ok",
        "version": APP_VERSION,
        "phase": 12,
        "service": "studsat-ground-station",
        "frozen": bool(getattr(sys, "frozen", False)),
        "tiles_dir": str(TILES_DIR),
        "logs_dir": str(LOGS_DIR),
    }
    try:
        hub = getattr(app.state, "hub", None)
        connections = getattr(app.state, "connections", None)
        if hub is not None:
            body["vehicles"] = hub.connection_summary()
        if connections is not None:
            body["connections"] = connections.status()
    except Exception:
        body["diag_error"] = True
    return body


def run() -> None:
    import uvicorn

    # Frozen: pass app object (module string import path is unreliable).
    # Dev: string path enables cleaner reloads if ever re-enabled.
    if getattr(sys, "frozen", False):
        uvicorn.run(
            app,
            host=HOST,
            port=PORT,
            reload=False,
            log_level="info",
        )
    else:
        uvicorn.run(
            "app.main:app",
            host=HOST,
            port=PORT,
            reload=False,
            log_level="info",
        )


if __name__ == "__main__":
    run()
