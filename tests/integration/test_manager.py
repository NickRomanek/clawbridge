"""Integration tests for clawbridge.orchestrator.manager -- TaskManager with mocked engines."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawbridge.engines.base import EngineBase, EngineError
from clawbridge.shared.schemas import (
    EngineName,
    EngineStatus,
    Task,
    TaskResult,
    TaskStatus,
)


class FakeEngine(EngineBase):
    """A minimal fake engine for testing TaskManager without real browsers."""

    def __init__(self, engine_name: EngineName = EngineName.BROWSER_USE, should_fail: bool = False):
        self._engine_name = engine_name
        self._should_fail = should_fail
        self._status = EngineStatus.AVAILABLE

    @property
    def name(self) -> EngineName:
        return self._engine_name

    @property
    def display_name(self) -> str:
        return f"fake-{self._engine_name.value}"

    @property
    def description(self) -> str:
        return "Fake engine for testing"

    async def initialize(self) -> None:
        self._status = EngineStatus.AVAILABLE

    async def execute_step(self, task, step):
        pass

    async def run_task(self, task: Task) -> Task:
        if self._should_fail:
            raise EngineError(self._engine_name, "Simulated failure")
        await asyncio.sleep(0.01)  # Simulate some work
        task.status = TaskStatus.COMPLETE
        task.result = TaskResult(
            summary="Fake result",
            total_steps=1,
            total_duration_ms=10,
            engine_used=self._engine_name,
        )
        return task

    async def stop(self) -> None:
        self._status = EngineStatus.STOPPED

    async def get_status(self) -> EngineStatus:
        return self._status


@pytest.fixture
def task_manager():
    """Create a TaskManager with a fake engine pre-registered."""
    from clawbridge.orchestrator.manager import TaskManager
    mgr = TaskManager()
    mgr._engines[EngineName.BROWSER_USE] = FakeEngine(EngineName.BROWSER_USE)
    return mgr


@pytest.fixture
def failing_manager():
    """Create a TaskManager where the engine always fails."""
    from clawbridge.orchestrator.manager import TaskManager
    mgr = TaskManager()
    mgr._engines[EngineName.BROWSER_USE] = FakeEngine(EngineName.BROWSER_USE, should_fail=True)
    return mgr


# ── Engine Selection ─────────────────────────────────────────────────────────


class TestEngineSelection:
    def test_select_specific_engine(self, task_manager):
        engine = task_manager._select_engine(EngineName.BROWSER_USE)
        assert engine.name == EngineName.BROWSER_USE

    def test_auto_selects_browser_use_first(self, task_manager):
        engine = task_manager._select_engine(EngineName.AUTO)
        assert engine.name == EngineName.BROWSER_USE

    def test_auto_falls_back_to_openclaw(self):
        from clawbridge.orchestrator.manager import TaskManager
        mgr = TaskManager()
        mgr._engines[EngineName.OPENCLAW] = FakeEngine(EngineName.OPENCLAW)
        engine = mgr._select_engine(EngineName.AUTO)
        assert engine.name == EngineName.OPENCLAW

    def test_no_engines_raises(self):
        from clawbridge.orchestrator.manager import TaskManager
        mgr = TaskManager()
        with pytest.raises(EngineError):
            mgr._select_engine(EngineName.AUTO)

    def test_get_engine_by_name(self, task_manager):
        engine = task_manager.get_engine(EngineName.BROWSER_USE)
        assert engine is not None

    def test_get_nonexistent_engine(self, task_manager):
        engine = task_manager.get_engine(EngineName.OPENCLAW)
        assert engine is None


# ── Task Submission ──────────────────────────────────────────────────────────


class TestTaskSubmission:
    @pytest.mark.asyncio
    async def test_submit_task_starts_execution(self, task_manager):
        task = Task(prompt="test query")
        result = await task_manager.submit_task(task)
        assert result.id == task.id
        assert result.id in task_manager._tasks

        # Wait for background execution to finish
        await asyncio.sleep(0.1)
        stored = task_manager.get_task(task.id)
        assert stored.status == TaskStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_submit_task_queues_when_at_capacity(self, task_manager):
        os.environ["MAX_CONCURRENT_TASKS"] = "1"
        try:
            # Slow engine to hold the slot
            slow_engine = FakeEngine(EngineName.BROWSER_USE)
            original_run = slow_engine.run_task

            async def slow_run(task):
                await asyncio.sleep(0.5)
                return await original_run(task)

            slow_engine.run_task = slow_run
            task_manager._engines[EngineName.BROWSER_USE] = slow_engine

            t1 = Task(prompt="first")
            t2 = Task(prompt="second")

            await task_manager.submit_task(t1)
            await asyncio.sleep(0.01)  # Let t1 start

            # t2 should be queued since t1 is running
            t2_result = await task_manager.submit_task(t2)
            assert t2_result.status == TaskStatus.PENDING
        finally:
            os.environ.pop("MAX_CONCURRENT_TASKS", None)

    @pytest.mark.asyncio
    async def test_task_error_on_engine_failure(self, failing_manager):
        task = Task(prompt="will fail")
        await failing_manager.submit_task(task)

        await asyncio.sleep(0.1)
        stored = failing_manager.get_task(task.id)
        assert stored.status == TaskStatus.ERROR
        assert stored.error is not None


# ── Task Retrieval ───────────────────────────────────────────────────────────


class TestTaskRetrieval:
    @pytest.mark.asyncio
    async def test_get_task_by_id(self, task_manager):
        task = Task(prompt="test")
        await task_manager.submit_task(task)
        found = task_manager.get_task(task.id)
        assert found is not None
        assert found.prompt == "test"

    def test_get_nonexistent_task(self, task_manager):
        assert task_manager.get_task("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_all_tasks_newest_first(self, task_manager):
        from datetime import datetime

        t1 = Task(prompt="first", created_at=datetime(2026, 1, 1, 0, 0, 0))
        t2 = Task(prompt="second", created_at=datetime(2026, 1, 1, 0, 0, 1))
        await task_manager.submit_task(t1)
        await asyncio.sleep(0.05)
        await task_manager.submit_task(t2)
        await asyncio.sleep(0.1)

        all_tasks = task_manager.get_all_tasks()
        assert len(all_tasks) == 2
        # Newest first (t2 has later created_at)
        assert all_tasks[0].prompt == "second"


# ── Task Lifecycle ───────────────────────────────────────────────────────────


class TestTaskLifecycle:
    @pytest.mark.asyncio
    async def test_pause_running_task(self, task_manager):
        slow_engine = FakeEngine(EngineName.BROWSER_USE)

        async def slow_run(task):
            await asyncio.sleep(5)
            task.status = TaskStatus.COMPLETE
            return task

        slow_engine.run_task = slow_run
        task_manager._engines[EngineName.BROWSER_USE] = slow_engine

        task = Task(prompt="long task")
        await task_manager.submit_task(task)
        await asyncio.sleep(0.05)

        paused = await task_manager.pause_task(task.id)
        assert paused is not None
        assert paused.status == TaskStatus.PAUSED

    @pytest.mark.asyncio
    async def test_pause_nonexistent_task(self, task_manager):
        result = await task_manager.pause_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_task(self, task_manager):
        slow_engine = FakeEngine(EngineName.BROWSER_USE)

        async def slow_run(task):
            await asyncio.sleep(5)
            task.status = TaskStatus.COMPLETE
            return task

        slow_engine.run_task = slow_run
        task_manager._engines[EngineName.BROWSER_USE] = slow_engine

        task = Task(prompt="to cancel")
        await task_manager.submit_task(task)
        await asyncio.sleep(0.05)

        cancelled = await task_manager.cancel_task(task.id)
        assert cancelled is not None
        assert cancelled.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, task_manager):
        result = await task_manager.cancel_task("nonexistent")
        assert result is None


# ── Broadcasting ─────────────────────────────────────────────────────────────


class TestBroadcasting:
    @pytest.mark.asyncio
    async def test_broadcast_callback_called(self, task_manager):
        broadcast_mock = AsyncMock()
        task_manager.set_broadcast_callback(broadcast_mock)

        task = Task(prompt="test")
        await task_manager.submit_task(task)
        await asyncio.sleep(0.15)

        # Should have been called at least twice (running + complete)
        assert broadcast_mock.call_count >= 2

    @pytest.mark.asyncio
    async def test_no_broadcast_without_callback(self, task_manager):
        # Should not raise if no callback is set
        task = Task(prompt="test")
        await task_manager.submit_task(task)
        await asyncio.sleep(0.1)
        assert task_manager.get_task(task.id).status == TaskStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_broadcast_failure_does_not_crash_task(self, task_manager):
        async def bad_broadcast(msg):
            raise RuntimeError("broadcast broken")

        task_manager.set_broadcast_callback(bad_broadcast)

        task = Task(prompt="test")
        await task_manager.submit_task(task)
        await asyncio.sleep(0.1)
        # Task should still complete despite broadcast failure
        assert task_manager.get_task(task.id).status == TaskStatus.COMPLETE


# ── Engine Info ──────────────────────────────────────────────────────────────


class TestEngineInfo:
    @pytest.mark.asyncio
    async def test_get_engine_infos(self, task_manager):
        infos = await task_manager.get_engine_infos()
        assert len(infos) == 1
        assert infos[0]["name"] == "browser_use"
        assert infos[0]["status"] == "available"
