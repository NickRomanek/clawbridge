"""OpenClaw engine E2E tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_openclaw_answers_factual_question(submit_task, require_openclaw):
    task = await submit_task("What is the capital of France?", engine="openclaw")
    assert task["status"] == "complete"
    summary = task["result"]["summary"].lower()
    assert "paris" in summary, f"Expected 'paris' in summary, got: {summary!r}"
