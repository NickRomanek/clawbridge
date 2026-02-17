"""E2E tests for replay routing (Phase 0f — replay always uses computer_use)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_replay_endpoint_forces_computer_use(
    async_client, list_workflows, require_computer
):
    """Replay API must force engine to computer_use regardless of available engines."""
    workflows = await list_workflows()
    if not workflows:
        pytest.skip("No saved workflows to test replay routing")

    wf = workflows[0]
    resp = await async_client.post(f"/api/workflows/{wf['id']}/replay")
    resp.raise_for_status()
    data = resp.json()

    task = data["task"]
    assert task["engine"] == "computer_use", (
        f"Replay should force computer_use, got {task['engine']}"
    )
    assert task["prompt"].startswith("replay:"), (
        f"Replay prompt should start with 'replay:', got {task['prompt']!r}"
    )


async def test_replay_task_prompt_format(
    async_client, list_workflows, require_computer
):
    """Replay task prompt must be 'replay: <workflow_name>'."""
    workflows = await list_workflows()
    if not workflows:
        pytest.skip("No saved workflows to test replay format")

    wf = workflows[0]
    resp = await async_client.post(f"/api/workflows/{wf['id']}/replay")
    resp.raise_for_status()
    data = resp.json()

    expected_prompt = f"replay: {wf['name']}"
    assert data["task"]["prompt"] == expected_prompt, (
        f"Expected prompt '{expected_prompt}', got {data['task']['prompt']!r}"
    )


async def test_replay_modified_requires_modifications(async_client, list_workflows):
    """replay-modified endpoint must reject empty modifications."""
    workflows = await list_workflows()
    if not workflows:
        pytest.skip("No saved workflows")

    wf = workflows[0]
    resp = await async_client.post(
        f"/api/workflows/{wf['id']}/replay-modified",
        json={"modifications": ""},
    )
    assert resp.status_code == 400, (
        f"Empty modifications should return 400, got {resp.status_code}"
    )
