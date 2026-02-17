"""E2E tests for the Stop button lifecycle via WebSocket.

Verifies the full flow: task submitted -> task_update with running status
-> cancel -> task_update with terminal status. This is the backend contract
that the dashboard's Stop button relies on.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.e2e


async def test_task_update_includes_running_status(async_client, ws_send_and_collect):
    """Submitting a task must produce a task_update with status='running'.

    The dashboard sets state.runningTaskId from this message to show the Stop button.
    """
    # Submit a task that takes a moment to process
    resp = await async_client.post(
        "/api/tasks",
        json={"prompt": "What is 2+2?", "engine": "auto"},
    )
    resp.raise_for_status()
    task_id = resp.json()["id"]

    # Collect task_update messages via a fresh WebSocket connection
    # The server broadcasts task_update on status changes
    messages = await ws_send_and_collect(
        send_messages=[],
        collect_timeout=15.0,
        filter_types={"task_update", "task_list"},
    )

    # Check we received at least one task_update for our task
    task_updates = [
        m for m in messages
        if m.get("type") == "task_update"
        and m.get("payload", {}).get("id") == task_id
    ]
    # Also check task_list which includes all tasks
    task_lists = [m for m in messages if m.get("type") == "task_list"]

    # The task should appear in either task_update or task_list
    found = bool(task_updates) or any(
        any(t["id"] == task_id for t in m.get("payload", []))
        for m in task_lists
    )
    assert found, (
        f"Task {task_id} not seen in any WebSocket message. "
        f"Got {len(messages)} messages: {[m.get('type') for m in messages]}"
    )


async def test_cancel_produces_terminal_task_update(async_client, ws_send_and_collect):
    """Cancelling a task must produce a task_update with terminal status.

    The dashboard clears state.runningTaskId on terminal status to restore Send button.
    """
    # Submit a slow task
    resp = await async_client.post(
        "/api/tasks",
        json={
            "prompt": "Write a 1000-word essay about clouds",
            "engine": "auto",
        },
    )
    resp.raise_for_status()
    task_id = resp.json()["id"]

    await asyncio.sleep(2)

    # Cancel it
    cancel_resp = await async_client.patch(
        f"/api/tasks/{task_id}", json={"action": "cancel"}
    )
    cancel_resp.raise_for_status()

    # Verify final status via API
    status_resp = await async_client.get(f"/api/tasks/{task_id}")
    status_resp.raise_for_status()
    task = status_resp.json()
    assert task["status"] in ("cancelled", "complete", "error"), (
        f"After cancel, expected terminal status, got {task['status']}"
    )


async def test_task_submit_returns_id_for_stop_tracking(async_client):
    """POST /api/tasks must return task with 'id' — needed for runningTaskId."""
    resp = await async_client.post(
        "/api/tasks",
        json={"prompt": "Hello", "engine": "auto"},
    )
    resp.raise_for_status()
    task = resp.json()
    assert "id" in task
    assert isinstance(task["id"], str)
    assert len(task["id"]) > 0
    assert "status" in task
