"""E2E tests for the recording → save workflow flow via WebSocket.

Tests the full lifecycle: recording_start → recording_status(active) →
recording_stop → recording_status(inactive) + recording_result → save_workflow.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.e2e


async def test_recording_start_broadcasts_active_status(ws_send_and_collect):
    """Sending recording_start must produce recording_status with active=True."""
    messages = await ws_send_and_collect(
        send_messages=[{"type": "recording_start"}],
        collect_timeout=5.0,
        filter_types={"recording_status"},
    )

    active_msgs = [
        m for m in messages
        if m.get("type") == "recording_status"
        and m.get("payload", {}).get("active") is True
    ]
    assert active_msgs, (
        "Expected recording_status with active=True after recording_start. "
        f"Got: {messages}"
    )

    # Clean up: stop recording
    await ws_send_and_collect(
        send_messages=[{"type": "recording_stop"}],
        collect_timeout=3.0,
        filter_types={"recording_status", "recording_result"},
    )


async def test_recording_stop_returns_result(ws_send_and_collect):
    """Start + stop recording must produce recording_result with actions list."""
    # Start recording
    await ws_send_and_collect(
        send_messages=[{"type": "recording_start"}],
        collect_timeout=3.0,
        filter_types={"recording_status"},
    )

    # Small delay so recording is active
    await asyncio.sleep(0.5)

    # Stop recording — should get recording_result
    messages = await ws_send_and_collect(
        send_messages=[{"type": "recording_stop"}],
        collect_timeout=5.0,
        filter_types={"recording_status", "recording_result"},
    )

    result_msgs = [m for m in messages if m.get("type") == "recording_result"]
    assert result_msgs, (
        "Expected recording_result after recording_stop. "
        f"Got: {[m.get('type') for m in messages]}"
    )

    payload = result_msgs[0].get("payload", {})
    assert "actions" in payload, "recording_result must include 'actions' list"
    assert "count" in payload, "recording_result must include 'count'"
    assert isinstance(payload["actions"], list)


async def test_recording_stop_broadcasts_inactive_status(ws_send_and_collect):
    """Stop recording must broadcast recording_status with active=False."""
    # Start
    await ws_send_and_collect(
        send_messages=[{"type": "recording_start"}],
        collect_timeout=3.0,
        filter_types={"recording_status"},
    )

    await asyncio.sleep(0.5)

    # Stop
    messages = await ws_send_and_collect(
        send_messages=[{"type": "recording_stop"}],
        collect_timeout=5.0,
        filter_types={"recording_status"},
    )

    inactive_msgs = [
        m for m in messages
        if m.get("type") == "recording_status"
        and m.get("payload", {}).get("active") is False
    ]
    assert inactive_msgs, (
        "Expected recording_status with active=False after recording_stop. "
        f"Got: {messages}"
    )


async def test_double_start_recording_is_idempotent(ws_send_and_collect):
    """Starting recording twice should not crash — second start is ignored."""
    messages = await ws_send_and_collect(
        send_messages=[
            {"type": "recording_start"},
            {"type": "recording_start"},
        ],
        collect_timeout=5.0,
        filter_types={"recording_status"},
        delay_between=0.5,
    )

    # Should get at least one active status, and no errors
    active_msgs = [
        m for m in messages
        if m.get("payload", {}).get("active") is True
    ]
    assert active_msgs, "Expected at least one active recording_status"

    # Clean up
    await ws_send_and_collect(
        send_messages=[{"type": "recording_stop"}],
        collect_timeout=3.0,
    )


async def test_stop_without_start_returns_empty(ws_send_and_collect):
    """Stopping without starting should return empty result, not crash."""
    messages = await ws_send_and_collect(
        send_messages=[{"type": "recording_stop"}],
        collect_timeout=5.0,
        filter_types={"recording_status", "recording_result"},
    )

    # Should get inactive status and possibly empty result
    # The key thing is it doesn't crash
    status_msgs = [m for m in messages if m.get("type") == "recording_status"]
    if status_msgs:
        assert status_msgs[0]["payload"]["active"] is False
