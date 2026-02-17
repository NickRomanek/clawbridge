"""E2E tests for browser-use content extraction (Phase 0d fix)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_browser_extraction_returns_content(submit_task, require_browser):
    """Extraction prompt must return actual page content, not just step count."""
    task = await submit_task(
        "Go to httpbin.org/html and tell me what text is on the page",
        engine="browser_use",
    )
    assert task["status"] == "complete"
    summary = task["result"]["summary"]
    assert summary.strip(), "Expected non-empty summary"
    # Should NOT be just "Task completed in N steps"
    assert "task completed in" not in summary.lower() or len(summary) > 100, (
        f"Extraction returned only step count, no content: {summary!r}"
    )


async def test_browser_extraction_non_extraction_still_works(
    submit_task, require_browser
):
    """Non-extraction prompts (pure navigation) should still work normally."""
    task = await submit_task(
        "Go to httpbin.org/status/200",
        engine="browser_use",
    )
    assert task["status"] == "complete"
    assert task["result"]["total_steps"] >= 1


async def test_browser_extraction_tell_me_keyword(submit_task, require_browser):
    """'tell me' keyword triggers extraction enhancement."""
    task = await submit_task(
        "Go to example.com and tell me the page heading",
        engine="browser_use",
    )
    assert task["status"] == "complete"
    summary = task["result"]["summary"].lower()
    # example.com heading is "Example Domain"
    assert "example" in summary or len(summary) > 50, (
        f"Expected content about example.com, got: {summary!r}"
    )
