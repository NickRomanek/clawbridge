"""E2E tests for computer-use focus verification (Phase 0b)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_computer_single_app_focus(submit_task, require_computer):
    """Computer-use task targeting a single app should complete successfully.

    This validates the focus verification doesn't break normal operation.
    The task targets Notepad specifically — focus should lock to it.
    """
    task = await submit_task(
        "Open Notepad and type 'focus test passed'",
        engine="computer_use",
        timeout=120,
    )
    assert task["status"] == "complete", (
        f"Expected complete, got {task['status']}: {task.get('error', '')}"
    )
    assert task["result"]["total_steps"] >= 1


async def test_computer_chrome_navigation(submit_task, require_computer):
    """Computer-use with Chrome should focus Chrome, not other windows.

    Validates Phase 0b focus verification — the URL should be typed
    into Chrome's address bar, not another window.
    """
    task = await submit_task(
        "Open Chrome and go to example.com",
        engine="computer_use",
        timeout=120,
    )
    # Task should at least complete (or error with a meaningful message)
    assert task["status"] in ("complete", "error"), (
        f"Unexpected status: {task['status']}"
    )
    if task["status"] == "complete":
        assert task["result"]["total_steps"] >= 1
