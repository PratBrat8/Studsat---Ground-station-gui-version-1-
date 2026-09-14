"""
WebSocket telemetry stream (PRD C.3 ws_routes.py).

  WS /ws/{vehicle}  vehicle = rocket | satellite

On connect: one snapshot, then throttled update messages from TelemetryHub.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.telemetry_hub import VEHICLES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{vehicle}")
async def vehicle_ws(websocket: WebSocket, vehicle: str) -> None:
    vehicle = vehicle.lower().strip()
    if vehicle not in VEHICLES:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    hub = websocket.app.state.hub
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    hub.subscribe(vehicle, queue)

    try:
        # Initial snapshot (PRD C.3)
        snap = hub.latest_state(vehicle, msg_type="snapshot", full_history=True)
        await websocket.send_text(json.dumps(snap, allow_nan=False))

        while True:
            # Wait for hub notify OR client message (ping/close)
            get_task = asyncio.create_task(queue.get())
            recv_task = asyncio.create_task(websocket.receive_text())
            done, pending = await asyncio.wait(
                {get_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

            if recv_task in done:
                try:
                    msg = recv_task.result()
                except WebSocketDisconnect:
                    break
                except Exception:
                    break
                # Optional client ping: {"type":"ping"}
                if msg:
                    try:
                        data = json.loads(msg)
                        if data.get("type") == "ping":
                            await websocket.send_text(
                                json.dumps({"type": "pong", "vehicle": vehicle})
                            )
                    except Exception:
                        pass

            if get_task in done:
                try:
                    get_task.result()
                except Exception:
                    pass
                try:
                    update = hub.latest_state(
                        vehicle, msg_type="update", full_history=False
                    )
                    await websocket.send_text(json.dumps(update, allow_nan=False))
                except WebSocketDisconnect:
                    break
                except Exception as exc:
                    logger.debug("ws send failed: %s", exc)
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("ws error: %s", exc)
    finally:
        hub.unsubscribe(vehicle, queue)
