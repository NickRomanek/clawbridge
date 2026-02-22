"""Tests for auto engine routing logic."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_auto_routes_web_prompt_to_computer(submit_task, require_computer):
    task = await submit_task("Go to example.com and tell me the page title", engine="auto")
    assert task["status"] == "complete"
    assert task["result"]["engine_used"] == "computer_use"


async def test_auto_routes_desktop_prompt_to_computer(submit_task, require_computer):
    task = await submit_task("Open Notepad", engine="auto")
    assert task["status"] == "complete"
    assert task["result"]["engine_used"] == "computer_use"


async def test_auto_routes_chat_prompt_to_openclaw(submit_task, require_openclaw):
    task = await submit_task("What is 2+2?", engine="auto")
    assert task["status"] == "complete"
    assert task["result"]["engine_used"] == "openclaw"
