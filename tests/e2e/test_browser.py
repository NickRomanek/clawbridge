"""Browser-use engine E2E tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_browser_navigates_and_returns_content(submit_task, require_browser):
    task = await submit_task(
        "Go to httpbin.org/get and tell me my IP address",
        engine="browser_use",
    )
    assert task["status"] == "complete"
    assert task["result"]["summary"].strip(), "Expected non-empty summary"
    assert task["result"]["total_steps"] >= 1
