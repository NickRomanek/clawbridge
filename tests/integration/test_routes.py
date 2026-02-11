"""Integration tests for FastAPI routes using TestClient."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
import os

import pytest
from fastapi.testclient import TestClient

from clawbridge.engines.base import EngineBase, EngineError
from clawbridge.shared.schemas import (
    EngineName,
    EngineInfo,
    EngineStatus,
    Task,
    TaskResult,
    TaskStatus,
)


class FakeEngine(EngineBase):
    """Fake engine for route testing."""

    @property
    def name(self) -> EngineName:
        return EngineName.BROWSER_USE

    @property
    def display_name(self) -> str:
        return "fake-browser-use"

    @property
    def description(self) -> str:
        return "Fake engine for route tests"

    async def initialize(self) -> None:
        pass

    async def execute_step(self, task, step):
        pass

    async def run_task(self, task: Task) -> Task:
        task.status = TaskStatus.COMPLETE
        task.result = TaskResult(
            summary="Fake result",
            total_steps=1,
            total_duration_ms=10,
            engine_used=EngineName.BROWSER_USE,
        )
        return task

    async def stop(self) -> None:
        pass

    async def get_status(self) -> EngineStatus:
        return EngineStatus.AVAILABLE


@pytest.fixture
def client(tmp_path):
    """Create a TestClient with mocked engine initialization and isolated DB."""
    from clawbridge.server.app import create_app
    from clawbridge.orchestrator import manager
    from clawbridge.orchestrator.manager import TaskManager
    
    db_file = tmp_path / "test_api.db"
    os.environ["CLAWBRIDGE_DB"] = str(db_file)
    manager._task_manager = None # Reset singleton

    async def fake_init(self):
        self._engines[EngineName.BROWSER_USE] = FakeEngine()

    with patch.object(TaskManager, "initialize_engines", fake_init):
        app = create_app()
        with TestClient(app) as c:
            yield c
            
    os.environ.pop("CLAWBRIDGE_DB", None)
    manager._task_manager = None


# ── Health Check ─────────────────────────────────────────────────────────────


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"


# ── Task Routes ──────────────────────────────────────────────────────────────


class TestTaskRoutes:
    def test_create_task(self, client):
        resp = client.post("/api/tasks", json={"prompt": "Search for Python best practices"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["prompt"] == "Search for Python best practices"
        assert data["status"] in ("pending", "running", "complete")
        assert "id" in data

    def test_create_task_with_engine(self, client):
        resp = client.post("/api/tasks", json={
            "prompt": "test",
            "engine": "browser_use",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] in ("browser_use", "auto")

    def test_create_task_empty_prompt_rejected(self, client):
        resp = client.post("/api/tasks", json={"prompt": ""})
        # Note: Depending on Pydantic version/min_length, it might be 422
        assert resp.status_code == 422  # Validation error

    def test_create_task_missing_prompt_rejected(self, client):
        resp = client.post("/api/tasks", json={})
        assert resp.status_code == 422

    def test_list_tasks(self, client):
        client.post("/api/tasks", json={"prompt": "task 1"})
        client.post("/api/tasks", json={"prompt": "task 2"})

        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_get_task_by_id(self, client):
        create_resp = client.post("/api/tasks", json={"prompt": "find me"})
        task_id = create_resp.json()["id"]

        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

    def test_get_nonexistent_task_returns_404(self, client):
        resp = client.get("/api/tasks/nonexistent-id")
        assert resp.status_code == 404

    def test_update_task_invalid_action(self, client):
        create_resp = client.post("/api/tasks", json={"prompt": "test"})
        task_id = create_resp.json()["id"]

        resp = client.patch(f"/api/tasks/{task_id}", json={"action": "invalid"})
        assert resp.status_code == 400

    def test_update_nonexistent_task_returns_404(self, client):
        resp = client.patch("/api/tasks/nonexistent", json={"action": "cancel"})
        assert resp.status_code == 404

    def test_delete_task(self, client):
        create_resp = client.post("/api/tasks", json={"prompt": "to delete"})
        task_id = create_resp.json()["id"]

        resp = client.delete(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify it's gone
        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 404

    def test_delete_nonexistent_task(self, client):
        resp = client.delete("/api/tasks/nonexistent")
        assert resp.status_code == 404


# ── Engine Routes ────────────────────────────────────────────────────────────


class TestEngineRoutes:
    def test_list_engines(self, client):
        resp = client.get("/api/engines")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_engine_by_name(self, client):
        resp = client.get("/api/engines/browser_use")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "browser_use"


# ── Config Routes ────────────────────────────────────────────────────────────


class TestConfigRoutes:
    def test_get_config(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "policy" in data
        assert "mode" in data["policy"]
        assert "keys" in data
        assert "server" in data

    def test_get_key_status(self, client):
        resp = client.get("/api/config/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert "anthropic" in data
        assert "openai" in data

    def test_get_policy(self, client):
        resp = client.get("/api/config/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data

    def test_get_audit_events(self, client):
        resp = client.get("/api/config/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
