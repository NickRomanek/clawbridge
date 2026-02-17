"""E2E tests for task cancellation (Stop button backend)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_cancel_running_task(cancel_task, require_openclaw):
    """Submit a slow task, cancel it mid-flight, verify cancelled status."""
    task = await cancel_task(
        "Write a very long detailed essay about the history of computing, "
        "covering every decade from 1950 to 2020 in extreme detail",
        engine="openclaw",
        cancel_after=3.0,
    )
    assert task["status"] == "cancelled", (
        f"Expected cancelled, got {task['status']}"
    )


async def test_cancel_returns_via_patch_api(async_client, require_openclaw):
    """PATCH /api/tasks/{id} with cancel returns the updated task."""
    import asyncio

    resp = await async_client.post(
        "/api/tasks",
        json={
            "prompt": "Explain quantum mechanics in exhaustive detail",
            "engine": "openclaw",
        },
    )
    resp.raise_for_status()
    task_id = resp.json()["id"]

    await asyncio.sleep(2)

    cancel_resp = await async_client.patch(
        f"/api/tasks/{task_id}", json={"action": "cancel"}
    )
    cancel_resp.raise_for_status()
    result = cancel_resp.json()
    assert result["status"] == "cancelled", (
        f"PATCH cancel should return cancelled status, got {result['status']}"
    )
    assert result["id"] == task_id


async def test_task_submit_returns_id(async_client):
    """POST /api/tasks returns a task dict with 'id' field (needed for stop button)."""
    resp = await async_client.post(
        "/api/tasks",
        json={"prompt": "Say hello", "engine": "openclaw"},
    )
    resp.raise_for_status()
    task = resp.json()
    assert "id" in task, "Task response must include 'id' for stop button tracking"
    assert isinstance(task["id"], str)
    assert len(task["id"]) > 0
    assert task["status"] in ("pending", "running")
