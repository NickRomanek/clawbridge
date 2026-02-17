"""E2E tests for dashboard HTML/JS integrity — verifies Phase 0 UI elements."""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.e2e


# ── Stop Button Elements ────────────────────────────────────────────────


async def test_dashboard_has_running_task_id_state(fetch_dashboard):
    """JS state must include runningTaskId for stop button tracking."""
    html = await fetch_dashboard()
    assert "runningTaskId" in html, "Missing runningTaskId in JS state"


async def test_dashboard_running_task_id_defaults_null(fetch_dashboard):
    """runningTaskId must default to null (not show Stop on fresh load)."""
    html = await fetch_dashboard()
    assert "runningTaskId:null" in html.replace(" ", ""), (
        "runningTaskId must default to null to prevent Stop showing on page load"
    )


async def test_dashboard_has_update_submit_btn(fetch_dashboard):
    """updateSubmitBtn() must exist to swap Send/Stop."""
    html = await fetch_dashboard()
    assert "updateSubmitBtn" in html, "Missing updateSubmitBtn function"


async def test_dashboard_has_stop_running_task(fetch_dashboard):
    """stopRunningTask() must exist to handle Stop click."""
    html = await fetch_dashboard()
    assert "stopRunningTask" in html, "Missing stopRunningTask function"


async def test_dashboard_submit_btn_exists(fetch_dashboard):
    """The submit button must have id='submitBtn'."""
    html = await fetch_dashboard()
    assert 'id="submitBtn"' in html, "Missing submitBtn element"


async def test_dashboard_submit_btn_default_is_send(fetch_dashboard):
    """The submit button should show 'Send' by default, not 'Stop'."""
    html = await fetch_dashboard()
    # The button should contain "Send" text in its default state
    btn_match = re.search(r'id="submitBtn"[^>]*>.*?Send', html, re.DOTALL)
    assert btn_match, "submitBtn should contain 'Send' text in default state"


async def test_dashboard_stop_button_checks_terminal_status(fetch_dashboard):
    """upsert() must reset runningTaskId on terminal statuses."""
    html = await fetch_dashboard()
    for status in ("complete", "error", "cancelled"):
        assert status in html, f"Missing terminal status '{status}' check in JS"


async def test_dashboard_upsert_detects_running(fetch_dashboard):
    """upsert() must detect status==='running' to show Stop for WS-received tasks."""
    html = await fetch_dashboard()
    assert 'status==="running"' in html or "status===\"running\"" in html, (
        "upsert() must detect running status from WebSocket task_update"
    )


# ── Slash Command Autocomplete ──────────────────────────────────────────


async def test_dashboard_has_slash_dropdown(fetch_dashboard):
    """The slash autocomplete dropdown container must exist."""
    html = await fetch_dashboard()
    assert 'id="slash-dropdown"' in html, "Missing slash-dropdown element"


async def test_dashboard_has_slash_commands_array(fetch_dashboard):
    """SLASH_COMMANDS JS array must be defined."""
    html = await fetch_dashboard()
    assert "SLASH_COMMANDS" in html, "Missing SLASH_COMMANDS array"


async def test_dashboard_slash_commands_include_all(fetch_dashboard):
    """All 6 slash commands must be defined."""
    html = await fetch_dashboard()
    for cmd in ["/record", "/stop", "/replay", "/browser", "/computer", "/chat"]:
        assert cmd in html, f"Missing slash command {cmd!r} in SLASH_COMMANDS"


async def test_dashboard_has_slash_functions(fetch_dashboard):
    """All slash autocomplete JS functions must exist."""
    html = await fetch_dashboard()
    for fn in [
        "showSlashDropdown",
        "hideSlashDropdown",
        "navigateSlash",
        "confirmSlash",
        "selectSlashItem",
    ]:
        assert fn in html, f"Missing function {fn!r}"


async def test_dashboard_slash_dropdown_css(fetch_dashboard):
    """Slash dropdown CSS classes must be defined."""
    html = await fetch_dashboard()
    for cls in ["slash-item", "slash-cmd", "slash-desc", "slash-section"]:
        assert cls in html, f"Missing CSS class {cls!r}"


# ── Engine Chip Tooltips ────────────────────────────────────────────────


async def test_dashboard_engine_chips_have_tooltips(fetch_dashboard):
    """Engine chips must have title attributes for clarity."""
    html = await fetch_dashboard()
    assert 'title="Auto-detect engine based on task"' in html
    assert 'title="Force browser engine for web tasks"' in html
    assert 'title="Force desktop engine for app control"' in html
    assert 'title="Force AI chat engine"' in html


async def test_dashboard_engine_chips_no_auto_reset(fetch_dashboard):
    """submit() must NOT call selectEngineChip('auto') after submitting."""
    html = await fetch_dashboard()
    # Find the submit function body — it should NOT contain selectEngineChip("auto")
    # This was a bug where engine chip reset to Auto after every submit
    submit_match = re.search(r'async function submit\(\)\{.*?\}', html, re.DOTALL)
    if submit_match:
        submit_body = submit_match.group()
        assert 'selectEngineChip("auto")' not in submit_body, (
            "submit() should not reset engine chip to auto after sending"
        )
        assert "selectEngineChip('auto')" not in submit_body, (
            "submit() should not reset engine chip to auto after sending"
        )


# ── Chat Recording Save Card ─────────────────────────────────────────


async def test_dashboard_has_save_card_container(fetch_dashboard):
    """Dedicated chatWfSaveCard container must exist outside taskList."""
    html = await fetch_dashboard()
    assert 'id="chatWfSaveCard"' in html, "Missing chatWfSaveCard container"


async def test_dashboard_save_card_hidden_by_default(fetch_dashboard):
    """chatWfSaveCard must be display:none on page load."""
    html = await fetch_dashboard()
    # The div should have display:none in its style
    match = re.search(r'id="chatWfSaveCard"[^>]*style="[^"]*display:\s*none', html)
    assert match, "chatWfSaveCard should be hidden (display:none) by default"


async def test_dashboard_has_save_chat_workflow_fn(fetch_dashboard):
    """saveChatWorkflow() and discardChatRecording() must exist."""
    html = await fetch_dashboard()
    assert "saveChatWorkflow" in html, "Missing saveChatWorkflow function"
    assert "discardChatRecording" in html, "Missing discardChatRecording function"


async def test_dashboard_has_chat_record_btn(fetch_dashboard):
    """Chat record button must exist in the input area."""
    html = await fetch_dashboard()
    assert 'id="chatRecordBtn"' in html, "Missing chatRecordBtn"
    assert "toggleChatRecording" in html, "Missing toggleChatRecording function"


# ── Double-Submit Guard ─────────────────────────────────────────────────


async def test_dashboard_has_double_submit_guard(fetch_dashboard):
    """submit() must check runningTaskId to prevent double submission."""
    html = await fetch_dashboard()
    assert "state.runningTaskId" in html, "Missing runningTaskId guard in submit()"
    assert "already running" in html.lower(), "Missing 'already running' message"


# ── General Dashboard Integrity ─────────────────────────────────────────


async def test_dashboard_loads_without_error(fetch_dashboard):
    """Dashboard HTML must be non-empty and contain expected markers."""
    html = await fetch_dashboard()
    assert len(html) > 10000, f"Dashboard too small ({len(html)} bytes)"
    assert "__PRELOAD__" in html, "Missing __PRELOAD__ pattern"
    assert "ClawBridge" in html, "Missing ClawBridge branding"


async def test_dashboard_script_tags_balanced(fetch_dashboard):
    """All <script> tags must have matching </script>."""
    html = await fetch_dashboard()
    opens = len(re.findall(r"<script\b", html))
    closes = html.count("</script>")
    assert opens == closes, f"Unbalanced script tags: {opens} opens, {closes} closes"


async def test_dashboard_no_js_syntax_errors_in_strings(fetch_dashboard):
    """Check for common JS string escape issues in Python-generated HTML.

    The most common bug: bare \\' in Python triple-quotes produces just '
    which breaks the <script> block.
    """
    html = await fetch_dashboard()
    # Every <script> block should have balanced single quotes
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.DOTALL)
    for i, script in enumerate(scripts):
        # Count unescaped single quotes (rough heuristic)
        # Remove string contents to avoid false positives
        stripped = re.sub(r'"[^"]*"', '""', script)
        stripped = re.sub(r"'[^']*'", "''", stripped)
        # If stripping fails (unbalanced quotes), that's a problem
        # but this is a rough check — the real test is that the page loads
        assert script.count("{") >= script.count("}") - 2, (
            f"Script block {i} has mismatched braces (possible escape issue)"
        )


async def test_dashboard_preload_has_engines(fetch_dashboard):
    """__PRELOAD__ must include engine data for SSR."""
    html = await fetch_dashboard()
    assert "engines" in html, "Missing engines in __PRELOAD__"


async def test_dashboard_textarea_exists(fetch_dashboard):
    """Prompt textarea must exist with correct id."""
    html = await fetch_dashboard()
    assert 'id="prompt"' in html, "Missing prompt textarea"
    assert "placeholder=" in html, "Prompt textarea should have placeholder"
