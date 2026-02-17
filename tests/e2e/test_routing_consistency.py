"""Test that auto routing is deterministic."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_same_web_prompt_routes_consistently(submit_task, require_browser):
    prompt = "Go to example.com and tell me the page title"
    engines_used = []
    for _ in range(3):
        task = await submit_task(prompt, engine="auto")
        assert task["status"] == "complete"
        engines_used.append(task["result"]["engine_used"])
    assert all(e == "browser_use" for e in engines_used), (
        f"Expected all runs to route to browser_use, got: {engines_used}"
    )
