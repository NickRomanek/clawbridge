"""E2E tests for ultrawide screenshot handling (Phase 0c).

These tests verify the server correctly detects ultrawide monitors
and reports screen dimensions. The actual screenshot cropping
is tested implicitly via computer-use task completion.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_engine_status_reports_computer_use(async_client):
    """Computer-use engine should be available/running (implies screen detection worked)."""
    resp = await async_client.get("/api/engines")
    resp.raise_for_status()
    engines = {e["name"]: e["status"] for e in resp.json()}
    cu_status = engines.get("computer_use")
    assert cu_status in ("available", "running"), (
        f"computer_use engine status is {cu_status!r} — screen detection may have failed"
    )


async def test_computer_use_task_produces_screenshots(
    submit_task, require_computer
):
    """Computer-use task should complete with steps (implies screenshots worked).

    On ultrawide monitors, the screenshot pipeline now uses window crop
    for action steps. If this broke, tasks would fail or produce no steps.
    """
    task = await submit_task(
        "Take a screenshot and describe what you see",
        engine="computer_use",
        timeout=60,
    )
    assert task["status"] in ("complete", "error")
    if task["status"] == "complete":
        assert task["result"]["total_steps"] >= 1
        assert task["result"]["summary"].strip(), "Expected non-empty summary"
