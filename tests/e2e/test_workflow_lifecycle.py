"""E2E tests for the full workflow lifecycle: create → list → get → replay → delete.

Uses the REST API with synthetic actions (no real recording needed).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

# Synthetic actions that mimic a real recording (click + type + key)
FAKE_ACTIONS = [
    {
        "action_type": "click",
        "timestamp": 0.5,
        "x": 500,
        "y": 300,
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
        "timestamp": 1.0,
        "x": 0,
        "y": 0,
        "button": "",
        "text": "hello world",
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
        "timestamp": 2.0,
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

WF_NAME = "_e2e_test_workflow"


async def test_create_workflow_via_api(async_client):
    """POST /api/workflows creates a workflow and returns it."""
    resp = await async_client.post(
        "/api/workflows",
        json={
            "name": WF_NAME,
            "description": "E2E test workflow",
            "actions": FAKE_ACTIONS,
            "tags": ["e2e", "test"],
        },
    )
    resp.raise_for_status()
    wf = resp.json()
    assert wf["name"] == WF_NAME
    assert len(wf["actions"]) == len(FAKE_ACTIONS)
    assert "id" in wf


async def test_list_workflows_includes_created(async_client):
    """GET /api/workflows must include the workflow we created."""
    # Ensure it exists
    await async_client.post(
        "/api/workflows",
        json={"name": WF_NAME, "actions": FAKE_ACTIONS},
    )

    resp = await async_client.get("/api/workflows")
    resp.raise_for_status()
    workflows = resp.json()
    names = [w["name"] for w in workflows]
    assert WF_NAME in names, f"Expected {WF_NAME!r} in {names}"


async def test_get_workflow_by_id(async_client):
    """GET /api/workflows/{id} returns the correct workflow."""
    # Create
    create_resp = await async_client.post(
        "/api/workflows",
        json={"name": WF_NAME + "_get", "actions": FAKE_ACTIONS},
    )
    create_resp.raise_for_status()
    wf_id = create_resp.json()["id"]

    # Get
    resp = await async_client.get(f"/api/workflows/{wf_id}")
    resp.raise_for_status()
    wf = resp.json()
    assert wf["id"] == wf_id
    assert wf["name"] == WF_NAME + "_get"
    assert len(wf["actions"]) == len(FAKE_ACTIONS)

    # Clean up
    await async_client.delete(f"/api/workflows/{wf_id}")


async def test_workflow_actions_preserve_types(async_client):
    """Saved workflow actions must preserve action_type, text, and key fields."""
    create_resp = await async_client.post(
        "/api/workflows",
        json={"name": WF_NAME + "_types", "actions": FAKE_ACTIONS},
    )
    create_resp.raise_for_status()
    wf_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/workflows/{wf_id}")
    resp.raise_for_status()
    actions = resp.json()["actions"]

    assert actions[0]["action_type"] == "click"
    assert actions[1]["action_type"] == "type"
    assert actions[1]["text"] == "hello world"
    assert actions[2]["action_type"] == "key"
    assert actions[2]["key"] == "enter"

    # Clean up
    await async_client.delete(f"/api/workflows/{wf_id}")


async def test_workflow_text_with_spaces_preserved(async_client):
    """Typed text with spaces must be stored exactly (regression for space bug)."""
    actions_with_spaces = [
        {
            "action_type": "type",
            "timestamp": 1.0,
            "x": 0, "y": 0,
            "button": "", "key": "",
            "text": "hello beautiful world",
            "scroll_amount": 0,
            "element_type": "", "element_name": "",
            "element_automation_id": "", "element_parent_name": "",
            "window_title": "Notepad",
        },
    ]
    create_resp = await async_client.post(
        "/api/workflows",
        json={"name": WF_NAME + "_spaces", "actions": actions_with_spaces},
    )
    create_resp.raise_for_status()
    wf_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/workflows/{wf_id}")
    resp.raise_for_status()
    stored_text = resp.json()["actions"][0]["text"]
    assert stored_text == "hello beautiful world", (
        f"Expected 'hello beautiful world', got {stored_text!r}"
    )

    await async_client.delete(f"/api/workflows/{wf_id}")


async def test_replay_workflow_creates_task(async_client, require_computer):
    """POST /api/workflows/{id}/replay must create a task with replay: prompt."""
    create_resp = await async_client.post(
        "/api/workflows",
        json={"name": WF_NAME + "_replay", "actions": FAKE_ACTIONS},
    )
    create_resp.raise_for_status()
    wf_id = create_resp.json()["id"]

    replay_resp = await async_client.post(f"/api/workflows/{wf_id}/replay")
    replay_resp.raise_for_status()
    data = replay_resp.json()

    assert "task" in data
    assert data["task"]["engine"] == "computer_use"
    assert data["task"]["prompt"].startswith("replay:")

    # Clean up
    await async_client.delete(f"/api/workflows/{wf_id}")


async def test_delete_workflow(async_client):
    """DELETE /api/workflows/{id} removes the workflow."""
    create_resp = await async_client.post(
        "/api/workflows",
        json={"name": WF_NAME + "_delete", "actions": FAKE_ACTIONS},
    )
    create_resp.raise_for_status()
    wf_id = create_resp.json()["id"]

    del_resp = await async_client.delete(f"/api/workflows/{wf_id}")
    assert del_resp.status_code in (200, 204)

    # Verify it's gone
    get_resp = await async_client.get(f"/api/workflows/{wf_id}")
    assert get_resp.status_code == 404


async def test_delete_nonexistent_workflow_returns_404(async_client):
    """DELETE /api/workflows/{id} for missing workflow returns 404."""
    resp = await async_client.delete("/api/workflows/nonexistent-id-12345")
    assert resp.status_code == 404
