"""
REST control API (PRD C.3 rest_routes.py).

  GET  /ports
  POST /connect      {vehicle, port, baud}
  POST /disconnect   {vehicle}
  POST /simulate     {vehicle, enabled}
  GET  /status
  GET  /tiles/{z}/{x}/{y}.png  (mounted from main in later polish; also here-ready)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import DEFAULT_BAUD

router = APIRouter(tags=["control"])


class ConnectBody(BaseModel):
    vehicle: str = Field(..., description="rocket | satellite")
    port: str
    baud: int = DEFAULT_BAUD


class DisconnectBody(BaseModel):
    vehicle: str


class SimulateBody(BaseModel):
    vehicle: str
    enabled: bool = True


class RecoverBody(BaseModel):
    vehicle: str


def _mgr(request: Request):
    mgr = getattr(request.app.state, "connections", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="connection manager not ready")
    return mgr


@router.get("/ports")
def get_ports(request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    return {"ports": mgr.list_ports()}


@router.post("/connect")
def post_connect(body: ConnectBody, request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    try:
        return mgr.connect_serial(body.vehicle, body.port, body.baud)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"connect failed: {exc}") from exc


@router.post("/disconnect")
def post_disconnect(body: DisconnectBody, request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    try:
        return mgr.disconnect(body.vehicle)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/simulate")
def post_simulate(body: SimulateBody, request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    try:
        return mgr.start_simulate(body.vehicle, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"simulate failed: {exc}") from exc


@router.get("/status")
def get_status(request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    hub = request.app.state.hub
    return {
        "connections": mgr.status(),
        "vehicles": hub.connection_summary(),
    }


@router.post("/recover")
def post_recover(body: RecoverBody, request: Request) -> dict[str, Any]:
    """Operator marks vehicle recovered: LANDED → RECOVERED (PRD B.4)."""
    hub = getattr(request.app.state, "hub", None)
    if hub is None:
        raise HTTPException(status_code=503, detail="hub not ready")
    try:
        return hub.mark_recovered(body.vehicle)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/packets/{vehicle}")
def get_packets(
    vehicle: str, request: Request, limit: int = 50
) -> dict[str, Any]:
    """
    Packet Monitor data (PRD C.5) — counters + recent raw frames + fields.
    Lighter-weight than relying only on the WS stream for deep debugging.
    """
    hub = getattr(request.app.state, "hub", None)
    if hub is None:
        raise HTTPException(status_code=503, detail="hub not ready")
    try:
        return hub.packets_snapshot(vehicle, limit=limit)
    except KeyError:
        raise HTTPException(
            status_code=400, detail="vehicle must be rocket or satellite"
        ) from None


# --- Replay / logs (Phase 10) ---


class ReplayLoadBody(BaseModel):
    filename: str
    speed: float = 1.0
    vehicle: Optional[str] = None


class ReplaySpeedBody(BaseModel):
    speed: float = 1.0


class ReplayPauseBody(BaseModel):
    paused: bool = True


@router.get("/replay/sessions")
def get_replay_sessions(request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    return {"sessions": mgr.list_replay_sessions()}


@router.post("/replay/load")
def post_replay_load(body: ReplayLoadBody, request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    try:
        return mgr.start_replay(body.filename, speed=body.speed, vehicle=body.vehicle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"replay failed: {exc}") from exc


@router.post("/replay/stop")
def post_replay_stop(request: Request) -> dict[str, Any]:
    return _mgr(request).stop_replay()


@router.post("/replay/pause")
def post_replay_pause(body: ReplayPauseBody, request: Request) -> dict[str, Any]:
    return _mgr(request).pause_replay(body.paused)


@router.post("/replay/speed")
def post_replay_speed(body: ReplaySpeedBody, request: Request) -> dict[str, Any]:
    return _mgr(request).set_replay_speed(body.speed)


@router.get("/replay/status")
def get_replay_status(request: Request) -> dict[str, Any]:
    return _mgr(request).replay_status()
