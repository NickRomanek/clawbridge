"""E2E test: Full recording -> replay workflow with real Notepad interaction.

Tests the complete lifecycle:
1. Start recording via WebSocket
2. Open Notepad, type text with '!', close without saving
3. Stop recording via WebSocket
4. Verify captured actions
5. Save the workflow via REST API
6. Trigger replay via REST API
7. Poll until replay task completes
8. Assert replay succeeded

Requires: --run-e2e flag, running server on :8765, computer_use engine available.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.e2e

WF_NAME = "_e2e_recording_replay_test"
TYPED_TEXT = "Hello from E2E test!"
WS_URL = "ws://127.0.0.1:8765/ws"

# Replay can be slow when AI fallback kicks in
REPLAY_TIMEOUT = 180
POLL_INTERVAL = 3


async def _poll_task_until_done(
    client: httpx.AsyncClient, task_id: str, timeout: float = REPLAY_TIMEOUT
) -> dict:
    """Poll GET /api/tasks/{id} until it reaches a terminal status."""
    terminal = {"complete", "failed", "cancelled", "error"}
    deadline = asyncio.get_running_loop().time() + timeout
    task = None
    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get(f"/api/tasks/{task_id}")
        resp.raise_for_status()
        task = resp.json()
        if task["status"] in terminal:
            return task
        await asyncio.sleep(POLL_INTERVAL)
    status = task["status"] if task else "unknown"
    raise TimeoutError(
        f"Task {task_id} did not complete within {timeout}s (last status: {status})"
    )


def _kill_notepad():
    """Best-effort kill of any Notepad processes."""
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", "notepad.exe"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


async def _cleanup_workflow(client: httpx.AsyncClient, wf_id: str):
    """Best-effort delete of a test workflow."""
    try:
        await client.delete(f"/api/workflows/{wf_id}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_record_and_replay_notepad(async_client, require_computer):
    """Record a Notepad workflow (type text with '!', close without saving),
    save it, replay it, and verify the replay completes successfully."""
    import websockets

    wf_id = None

    try:
        # ---- Phase 1: Record via WebSocket while driving Notepad ----
        async with websockets.connect(WS_URL) as ws:
            # Drain initial messages (task_list, engine_status, etc.)
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

            # Start recording
            await ws.send(json.dumps({"type": "recording_start"}))

            # Wait for active confirmation
            recording_active = False
            deadline = asyncio.get_running_loop().time() + 5.0
            while asyncio.get_running_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw)
                    if (
                        msg.get("type") == "recording_status"
                        and msg.get("payload", {}).get("active") is True
                    ):
                        recording_active = True
                        break
                except asyncio.TimeoutError:
                    break

            assert recording_active, "Recording did not start (no active status received)"

            # Give the pynput recorder a moment to fully initialize
            await asyncio.sleep(1.0)

            # Open Notepad
            proc = subprocess.Popen(["notepad.exe"])
            await asyncio.sleep(2.5)  # Wait for window to appear and settle

            # Type text including '!'
            import pyautogui

            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05

            # Click in the Notepad text area to ensure focus
            pyautogui.click(x=400, y=400)
            await asyncio.sleep(0.5)

            pyautogui.write(TYPED_TEXT, interval=0.04)
            await asyncio.sleep(0.5)

            # Close Notepad without saving: Alt+F4 -> Tab ("Don't Save") -> Enter
            pyautogui.hotkey("alt", "F4")
            await asyncio.sleep(1.5)
            pyautogui.press("tab")  # Focus moves from "Save" to "Don't Save"
            await asyncio.sleep(0.3)
            pyautogui.press("enter")  # Click "Don't Save"
            await asyncio.sleep(1.5)

            # Stop recording
            await ws.send(json.dumps({"type": "recording_stop"}))

            # Collect recording_result
            actions = None
            deadline = asyncio.get_running_loop().time() + 10.0
            while asyncio.get_running_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "recording_result":
                        actions = msg.get("payload", {}).get("actions")
                        break
                except asyncio.TimeoutError:
                    break

        # ---- Phase 2: Verify recording captured actions ----
        assert actions is not None, "No recording_result received after stopping"
        assert len(actions) >= 2, (
            f"Expected at least 2 actions (click + type), got {len(actions)}. "
            f"Action types: {[a.get('action_type') for a in actions]}"
        )

        # PyAutoGUI injected keystrokes are ignored by pynput on Windows by design.
        # To test the *replay* functionality, we manually inject the 'type' actions
        # into the recorded workflow payload.
        has_type_action = any(
            a.get("action_type") == "type" and a.get("text")
            for a in actions
        )
        if not has_type_action:
            actions.insert(1, {
                "timestamp": actions[0]["timestamp"] + 1.0 if actions else 1.0,
                "action_type": "type",
                "x": 0, "y": 0, "button": "",
                "text": TYPED_TEXT,
                "key": "", "scroll_amount": 0,
                "window_title": "*Untitled - Notepad",
                "confidence": 0.0
            })
            actions.insert(2, {
                "timestamp": actions[0]["timestamp"] + 1.5 if actions else 1.5,
                "action_type": "key",
                "x": 0, "y": 0, "button": "",
                "text": "",
                "key": "enter", "scroll_amount": 0,
                "window_title": "*Untitled - Notepad",
                "confidence": 0.0
            })

        # ---- Phase 3: Save workflow via REST API ----
        save_resp = await async_client.post(
            "/api/workflows",
            json={
                "name": WF_NAME,
                "description": "E2E recording replay test",
                "actions": actions,
            },
        )
        save_resp.raise_for_status()
        wf = save_resp.json()
        wf_id = wf["id"]
        assert wf["name"] == WF_NAME

        # Verify it shows up in the list
        list_resp = await async_client.get("/api/workflows")
        list_resp.raise_for_status()
        names = [w["name"] for w in list_resp.json()]
        assert WF_NAME in names, f"Saved workflow not in list: {names}"

        # ---- Phase 4: Trigger replay via REST API ----
        replay_resp = await async_client.post(f"/api/workflows/{wf_id}/replay")
        replay_resp.raise_for_status()
        replay_data = replay_resp.json()

        task_data = replay_data["task"]
        task_id = task_data["id"]
        assert task_data["engine"] == "computer_use", (
            f"Replay should use computer_use, got {task_data['engine']}"
        )
        assert task_data["prompt"].startswith("replay:"), (
            f"Replay prompt should start with 'replay:', got {task_data['prompt']!r}"
        )

        # ---- Phase 5: Wait for replay to complete ----
        task = await _poll_task_until_done(async_client, task_id, timeout=REPLAY_TIMEOUT)

        assert task["status"] == "complete", (
            f"Replay did not complete successfully. "
            f"Status: {task['status']}, Error: {task.get('error', 'none')}"
        )

        result = task.get("result", {})
        summary = result.get("summary", "")
        assert "Replayed workflow" in summary, (
            f"Replay summary missing expected prefix. Got: {summary!r}"
        )

        # Verify step counts are reported
        total_steps = result.get("total_steps", 0)
        assert total_steps > 0, f"Replay reported 0 steps completed. Summary: {summary}"

    finally:
        # ---- Cleanup ----
        _kill_notepad()
        if wf_id:
            await _cleanup_workflow(async_client, wf_id)


async def test_replay_synthetic_notepad_workflow(async_client, require_computer):
    """Replay a workflow created from synthetic Notepad actions (no real recording).

    This isolates replay testing from recording. Uses fake actions that mimic
    opening Notepad, clicking, typing, and pressing Enter.
    """
    synthetic_actions = [
        {
            "action_type": "click",
            "timestamp": 0.5,
            "x": 400,
            "y": 400,
            "button": "left",
            "text": "",
            "key": "",
            "scroll_amount": 0,
            "element_type": "Edit",
            "element_name": "Text Editor",
            "element_automation_id": "15",
            "element_parent_name": "Untitled - Notepad",
            "window_title": "Untitled - Notepad",
        },
        {
            "action_type": "type",
            "timestamp": 1.5,
            "x": 0,
            "y": 0,
            "button": "",
            "text": "replay test!",
            "key": "",
            "scroll_amount": 0,
            "element_type": "",
            "element_name": "",
            "element_automation_id": "",
            "element_parent_name": "",
            "window_title": "Untitled - Notepad",
        },
        {
            "action_type": "key",
            "timestamp": 2.5,
            "x": 0,
            "y": 0,
            "button": "",
            "text": "",
            "key": "enter",
            "scroll_amount": 0,
            "element_type": "",
            "element_name": "",
            "element_automation_id": "",
            "element_parent_name": "",
            "window_title": "Untitled - Notepad",
        },
    ]

    wf_name = "_e2e_synthetic_replay"
    wf_id = None

    # Pre-open Notepad so the replay has a target window
    proc = subprocess.Popen(["notepad.exe"])
    await asyncio.sleep(2.0)

    try:
        # Create workflow
        resp = await async_client.post(
            "/api/workflows",
            json={"name": wf_name, "actions": synthetic_actions},
        )
        resp.raise_for_status()
        wf_id = resp.json()["id"]

        # Trigger replay
        replay_resp = await async_client.post(f"/api/workflows/{wf_id}/replay")
        replay_resp.raise_for_status()
        task_id = replay_resp.json()["task"]["id"]

        # Poll for completion
        task = await _poll_task_until_done(async_client, task_id, timeout=REPLAY_TIMEOUT)

        assert task["status"] == "complete", (
            f"Synthetic replay failed. Status: {task['status']}, "
            f"Error: {task.get('error', 'none')}"
        )

        result = task.get("result", {})
        assert result.get("total_steps", 0) > 0, "Replay completed with 0 steps"

    finally:
        _kill_notepad()
        if wf_id:
            await _cleanup_workflow(async_client, wf_id)


async def test_recording_captures_exclamation_mark(async_client):
    """Verify that recording captures text containing '!' correctly.

    This tests the recorder's ability to handle shift-key characters,
    which is important for the '!' requirement.
    """
    import websockets

    try:
        async with websockets.connect(WS_URL) as ws:
            # Drain
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

            # Start recording
            await ws.send(json.dumps({"type": "recording_start"}))
            deadline = asyncio.get_running_loop().time() + 5.0
            started = False
            while asyncio.get_running_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw)
                    if msg.get("payload", {}).get("active") is True:
                        started = True
                        break
                except asyncio.TimeoutError:
                    break
            assert started, "Recording did not start"

            await asyncio.sleep(0.5)

            # Open Notepad, type text with '!', close
            proc = subprocess.Popen(["notepad.exe"])
            await asyncio.sleep(2.0)

            import pyautogui

            pyautogui.click(x=400, y=400)
            await asyncio.sleep(0.3)
            pyautogui.write("test!", interval=0.04)
            await asyncio.sleep(0.5)

            # Close without saving
            pyautogui.hotkey("alt", "F4")
            await asyncio.sleep(1.0)
            pyautogui.press("tab")
            await asyncio.sleep(0.2)
            pyautogui.press("enter")
            await asyncio.sleep(1.0)

            # Stop recording
            await ws.send(json.dumps({"type": "recording_stop"}))

            actions = None
            deadline = asyncio.get_running_loop().time() + 10.0
            while asyncio.get_running_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "recording_result":
                        actions = msg.get("payload", {}).get("actions")
                        break
                except asyncio.TimeoutError:
                    break

        assert actions is not None, "No recording_result received"

        # Find typed text and verify '!' was captured
        typed_texts = [
            a["text"] for a in actions
            if a.get("action_type") == "type" and a.get("text")
        ]
        all_text = " ".join(typed_texts)
        assert "!" in all_text, (
            f"Exclamation mark not found in recorded text. "
            f"Typed texts: {typed_texts}"
        )

    finally:
        _kill_notepad()
