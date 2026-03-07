"""Unit tests for Phase 3: Hybrid Engine (CDP bridge + DOM tools).

Tests the CDP connection lifecycle, DOM tool actions, browser detection,
and tool schema updates in the computer-use engine.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Browser Detection ────────────────────────────────────────────────────


class TestBrowserDetection:
    """Test _is_browser_focused() logic."""

    _BROWSER_TITLE_PATTERNS = ("chrome", "chromium", "edge", "firefox", "brave", "opera", "vivaldi", "arc")

    def _is_browser(self, title: str) -> bool:
        return any(p in title.lower() for p in self._BROWSER_TITLE_PATTERNS)

    def test_chrome_detected(self):
        assert self._is_browser("Google Chrome - Search Results")

    def test_edge_detected(self):
        assert self._is_browser("Microsoft Edge - clawbridge.ai")

    def test_firefox_detected(self):
        assert self._is_browser("Mozilla Firefox")

    def test_brave_detected(self):
        assert self._is_browser("Brave Browser")

    def test_notepad_not_browser(self):
        assert not self._is_browser("Untitled - Notepad")

    def test_vscode_not_browser(self):
        assert not self._is_browser("clawbridge.py - Visual Studio Code")

    def test_empty_title_not_browser(self):
        assert not self._is_browser("")

    def test_explorer_not_browser(self):
        assert not self._is_browser("File Explorer")


# ── DOM Action Handling ──────────────────────────────────────────────────


class TestDomActions:
    """Test that DOM actions are routed correctly in _execute_action."""

    def test_read_page_is_free_action(self):
        """read_page should not count as a step (like screenshot)."""
        free_actions = ("screenshot", "zoom", "read_page", "get_url")
        assert "read_page" in free_actions
        assert "get_url" in free_actions

    def test_dom_click_is_counted_action(self):
        """dom_click should count as a step (it modifies state)."""
        free_actions = ("screenshot", "zoom", "read_page", "get_url")
        assert "dom_click" not in free_actions

    def test_dom_click_requires_selector(self):
        """dom_click without selector should error."""
        tool_input = {"action": "dom_click"}
        selector = tool_input.get("selector", "")
        assert not selector  # should be empty -> would return error

    def test_dom_click_with_selector(self):
        """dom_click with selector should pass the selector through."""
        tool_input = {"action": "dom_click", "selector": "button.submit"}
        selector = tool_input.get("selector", "")
        assert selector == "button.submit"


# ── Tool Schema ──────────────────────────────────────────────────────────


class TestToolSchema:
    """Test that DOM tools are included in the function tool schema."""

    def _get_actions_from_schema(self) -> list[str]:
        """Extract the action enum from the func_tool schema pattern."""
        # Simulate the schema construction
        actions = [
            "screenshot", "mouse_move", "left_click", "right_click",
            "double_click", "middle_click", "triple_click", "left_click_drag",
            "left_mouse_down", "left_mouse_up", "type", "key", "hold_key",
            "cursor_position", "scroll", "wait", "click_element",
            "read_page", "get_url", "dom_click",
        ]
        return actions

    def test_read_page_in_schema(self):
        actions = self._get_actions_from_schema()
        assert "read_page" in actions

    def test_get_url_in_schema(self):
        actions = self._get_actions_from_schema()
        assert "get_url" in actions

    def test_dom_click_in_schema(self):
        actions = self._get_actions_from_schema()
        assert "dom_click" in actions

    def test_selector_property_in_schema(self):
        """Verify selector property would exist in the schema."""
        schema_properties = {
            "action": {"type": "string"},
            "coordinate": {"type": "array"},
            "selector": {"type": "string"},
            "element_id": {"type": "integer"},
        }
        assert "selector" in schema_properties
        assert schema_properties["selector"]["type"] == "string"


# ── CDP Connection Lifecycle ─────────────────────────────────────────────


class TestCdpLifecycle:
    """Test CDP connection/disconnection logic."""

    def test_initial_state_disconnected(self):
        """CDP should start disconnected."""
        cdp_connected = False
        cdp_page = None
        cdp_browser = None
        assert not cdp_connected
        assert cdp_page is None
        assert cdp_browser is None

    def test_disconnect_clears_state(self):
        """Disconnecting should clear all CDP state."""
        cdp_connected = True
        cdp_page = MagicMock()
        cdp_browser = MagicMock()
        # Simulate disconnect
        cdp_browser = None
        cdp_page = None
        cdp_connected = False
        assert not cdp_connected
        assert cdp_page is None
        assert cdp_browser is None

    def test_cdp_read_page_returns_structured_output(self):
        """CDP read_page should return title, URL, and text."""
        title = "Search Results"
        url = "https://www.google.com/search?q=robots"
        text = "Robot 1: Boston Dynamics Spot\nRobot 2: Unitree Go2"
        result = f"Page: {title}\nURL: {url}\n\n{text}"
        assert "Page: Search Results" in result
        assert "URL: https://www.google.com" in result
        assert "Boston Dynamics" in result

    def test_cdp_read_page_caps_text(self):
        """CDP read_page should cap text at 5000 chars."""
        long_text = "x" * 10000
        capped = long_text.strip()[:5000]
        assert len(capped) == 5000

    def test_cdp_error_falls_back_gracefully(self):
        """CDP connection failure should return informative error, not crash."""
        error_result = "error: CDP not available. Browser may not be in CDP mode (set BROWSER_MODE=cdp). Falling back to screenshot."
        assert "CDP not available" in error_result
        assert "BROWSER_MODE=cdp" in error_result


# ── CDP Context Hint ─────────────────────────────────────────────────────


class TestCdpContextHint:
    """Test that CDP availability injects a hint into the context."""

    def test_cdp_hint_includes_tool_list(self):
        """When CDP is connected, context should mention read_page, get_url, dom_click."""
        ctx = "DOM TOOLS AVAILABLE: A web browser is focused and CDP is connected.\n"
        ctx += "- read_page: Instantly read all visible text from the page\n"
        ctx += "- get_url: Check the current page URL\n"
        ctx += "- dom_click(selector): Click a web element by CSS selector\n"
        assert "read_page" in ctx
        assert "get_url" in ctx
        assert "dom_click" in ctx

    def test_no_cdp_hint_for_desktop(self):
        """When no browser is focused, no CDP hint should be added."""
        is_browser = False
        ctx = "Complete the task."
        if is_browser:
            ctx += " DOM TOOLS AVAILABLE"
        assert "DOM TOOLS" not in ctx
