"""WebSocket route for live dashboard updates.

Streams task status changes, audit events, and approval requests
to connected dashboard clients in real time.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from clawbridge.orchestrator.manager import get_task_manager
from clawbridge.telemetry.logger import get_audit_logger
from clawbridge.shared.schemas import AuditEvent

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections for live broadcasting."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.debug(f"Dashboard connected ({len(self._connections)} active)")

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        logger.debug(f"Dashboard disconnected ({len(self._connections)} active)")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected dashboards."""
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            try:
                self._connections.remove(ws)
            except ValueError:
                pass


# Singleton connection manager
_manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    return _manager


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint for live dashboard updates.

    On connect:
    - Sends current engine status.
    - Streams task updates and audit events in real time.
    - Listens for approval responses from the user.
    """
    await _manager.connect(ws)

    # Register broadcast callback with task manager
    task_manager = get_task_manager()
    task_manager.set_broadcast_callback(_manager.broadcast)

    # Register audit event streaming
    audit = get_audit_logger()

    def on_audit_event(event: AuditEvent):
        """Sync callback -- schedules async send."""
        asyncio.create_task(
            _manager.broadcast({
                "type": "audit_event",
                "payload": event.model_dump(mode="json"),
            })
        )

    audit.subscribe(on_audit_event)

    try:
        # Send initial engine status
        engine_infos = await task_manager.get_engine_infos()
        await ws.send_json({
            "type": "engine_status",
            "payload": engine_infos,
        })

        # Send current tasks
        tasks = task_manager.get_all_tasks()
        await ws.send_json({
            "type": "task_list",
            "payload": [t.model_dump(mode="json") for t in tasks],
        })

        # Listen for messages from dashboard (approval responses, etc.)
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "approval_response":
                # Handle user approval for sensitive actions
                step_id = data.get("step_id")
                approved = data.get("approved", False)
                logger.info(
                    f"User approval for step {step_id}: {'approved' if approved else 'denied'}"
                )
                # TODO: Route approval to waiting step in orchestrator

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
    finally:
        audit.unsubscribe(on_audit_event)
        _manager.disconnect(ws)
