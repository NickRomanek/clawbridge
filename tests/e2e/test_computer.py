"""Computer-use engine E2E tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_computer_opens_notepad(submit_task, require_computer):
    task = await submit_task(
        "Open Notepad and type hello world",
        engine="computer_use",
    )
    assert task["status"] == "complete"
    assert task["result"]["summary"].strip(), "Expected non-empty summary"
    assert task["result"]["total_steps"] >= 1
