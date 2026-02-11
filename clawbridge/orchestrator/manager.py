"""ClawBridge task manager -- lifecycle, queue, and engine routing.

Manages the task queue, dispatches tasks to engines, and tracks lifecycle state.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

from clawbridge.config import get_settings
from clawbridge.engines.base import EngineBase, EngineError
from clawbridge.engines.browser_use_engine import BrowserUseEngine
from clawbridge.engines.openclaw_engine import OpenClawEngine
from clawbridge.policy.safety import evaluate_policy, scan_for_prompt_injection
from clawbridge.shared.schemas import (
    ActionClass,
    AuditEvent,
    EngineName,
    EngineStatus,
    Task,
    TaskStatus,
)
from clawbridge.telemetry.logger import get_audit_logger

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages the task lifecycle and engine pool.

    Responsibilities:
    - Maintain the set of available engines.
    - Accept tasks, route them to the appropriate engine.
    - Track task status through its lifecycle.
    - Enforce concurrency limits.
    - Emit audit events for every state transition.
    """

    def __init__(self) -> None:
        self._engines: dict[EngineName, EngineBase] = {}
        self._tasks: dict[str, Task] = {}
        self._running_count: int = 0
        self._task_futures: dict[str, asyncio.Task] = {}
        self._ws_broadcast: Callable | None = None  # Set by server for live updates

    # ── Engine Management ─────────────────────────────────────────────────

    async def initialize_engines(self) -> None:
        """Start all enabled engines."""
        settings = get_settings()
        enabled = settings.enabled_engine_list

        if EngineName.BROWSER_USE in enabled:
            engine = BrowserUseEngine()
            await engine.initialize()
            self._engines[EngineName.BROWSER_USE] = engine

        if EngineName.OPENCLAW in enabled:
            engine = OpenClawEngine()
            await engine.initialize()
            self._engines[EngineName.OPENCLAW] = engine

        available = [
            e.display_name
            for e in self._engines.values()
            if asyncio.iscoroutine((status := e.get_status()))
            or True  # will check below
        ]
        logger.info(f"Engines initialized: {list(self._engines.keys())}")

    async def shutdown_engines(self) -> None:
        """Gracefully stop all engines."""
        for name, engine in self._engines.items():
            try:
                await engine.stop()
                logger.info(f"Engine {name.value} stopped")
            except Exception as e:
                logger.warning(f"Error stopping engine {name.value}: {e}")

    def get_engine(self, name: EngineName) -> EngineBase | None:
        """Get an engine by name."""
        return self._engines.get(name)

    async def get_engine_infos(self) -> list[dict]:
        """Get status info for all engines (for dashboard)."""
        infos = []
        for engine in self._engines.values():
            info = await engine.get_info()
            infos.append(info.model_dump())
        return infos

    def _select_engine(self, preferred: EngineName) -> EngineBase:
        """Select the best available engine.

        If preferred is AUTO, pick browser-use first (faster for research tasks),
        fall back to OpenClaw.
        """
        if preferred != EngineName.AUTO and preferred in self._engines:
            return self._engines[preferred]

        # Auto-select: prefer browser-use for speed
        for name in [EngineName.BROWSER_USE, EngineName.OPENCLAW]:
            if name in self._engines:
                return self._engines[name]

        raise EngineError(
            EngineName.AUTO,
            "No engines available. Check ENABLED_ENGINES in .env",
            recoverable=False,
        )

    # ── Task Management ───────────────────────────────────────────────────

    async def submit_task(self, task: Task) -> Task:
        """Submit a new task for execution.

        Validates concurrency limits, selects engine, and starts execution.
        """
        settings = get_settings()
        audit = get_audit_logger()

        # Check concurrency limit
        if self._running_count >= settings.max_concurrent_tasks:
            task.status = TaskStatus.PENDING
            self._tasks[task.id] = task
            audit.log_event(AuditEvent(
                task_id=task.id,
                event_type="task_queued",
                detail=f"Queued (running: {self._running_count}/{settings.max_concurrent_tasks})",
            ))
            return task

        # Store and start
        self._tasks[task.id] = task
        audit.log_event(AuditEvent(
            task_id=task.id,
            event_type="task_created",
            engine=task.engine,
            detail=f"Task submitted: {task.prompt[:100]}",
        ))

        # Execute in background
        future = asyncio.create_task(self._execute_task(task))
        self._task_futures[task.id] = future

        return task

    async def _execute_task(self, task: Task) -> None:
        """Execute a task on the selected engine."""
        audit = get_audit_logger()

        try:
            self._running_count += 1
            task.status = TaskStatus.RUNNING
            task.updated_at = datetime.utcnow()
            await self._broadcast_task_update(task)

            # Select engine
            engine = self._select_engine(task.engine)
            actual_engine = engine.name
            task.engine = actual_engine

            audit.log_event(AuditEvent(
                task_id=task.id,
                event_type="task_started",
                engine=actual_engine,
                detail=f"Engine selected: {engine.display_name}",
            ))

            # Delegate full task to engine's agent loop
            task = await engine.run_task(task)

            # Scan result for prompt injection attempts
            if task.result and task.result.summary:
                injections = scan_for_prompt_injection(task.result.summary)
                if injections:
                    audit.log_event(AuditEvent(
                        task_id=task.id,
                        event_type="security_warning",
                        detail=f"Potential prompt injection detected in result: {injections}",
                    ))
                    logger.warning(
                        f"Task {task.id}: prompt injection patterns detected in result"
                    )

            audit.log_event(AuditEvent(
                task_id=task.id,
                event_type="task_completed" if task.status == TaskStatus.COMPLETE else "task_failed",
                engine=actual_engine,
                status=task.status.value,
                duration_ms=task.result.total_duration_ms if task.result else None,
                detail=task.error or "Success",
            ))

        except EngineError as e:
            task.status = TaskStatus.ERROR
            task.error = str(e)
            task.updated_at = datetime.utcnow()
            audit.log_event(AuditEvent(
                task_id=task.id,
                event_type="task_error",
                detail=str(e),
            ))

        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = f"Unexpected error: {e}"
            task.updated_at = datetime.utcnow()
            logger.exception(f"Task {task.id} unexpected error")
            audit.log_event(AuditEvent(
                task_id=task.id,
                event_type="task_error",
                detail=f"Unexpected: {e}",
            ))

        finally:
            self._running_count = max(0, self._running_count - 1)
            self._task_futures.pop(task.id, None)
            await self._broadcast_task_update(task)

            # Check if any queued tasks can now run
            await self._process_queue()

    async def _process_queue(self) -> None:
        """Start queued tasks if capacity is available."""
        settings = get_settings()
        for task in self._tasks.values():
            if (
                task.status == TaskStatus.PENDING
                and self._running_count < settings.max_concurrent_tasks
            ):
                future = asyncio.create_task(self._execute_task(task))
                self._task_futures[task.id] = future

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks, newest first."""
        return sorted(
            self._tasks.values(),
            key=lambda t: t.created_at,
            reverse=True,
        )

    async def pause_task(self, task_id: str) -> Task | None:
        """Pause a running task."""
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.PAUSED
            task.updated_at = datetime.utcnow()

            # Cancel the running future
            future = self._task_futures.get(task_id)
            if future:
                future.cancel()

            get_audit_logger().log_event(AuditEvent(
                task_id=task_id,
                event_type="task_paused",
                detail="Paused by user",
            ))
            await self._broadcast_task_update(task)
        return task

    async def resume_task(self, task_id: str) -> Task | None:
        """Resume a paused task."""
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.PAUSED:
            task.status = TaskStatus.PENDING
            task.updated_at = datetime.utcnow()
            get_audit_logger().log_event(AuditEvent(
                task_id=task_id,
                event_type="task_resumed",
                detail="Resumed by user",
            ))
            await self._process_queue()
        return task

    async def cancel_task(self, task_id: str) -> Task | None:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED):
            task.status = TaskStatus.CANCELLED
            task.updated_at = datetime.utcnow()

            future = self._task_futures.get(task_id)
            if future:
                future.cancel()

            get_audit_logger().log_event(AuditEvent(
                task_id=task_id,
                event_type="task_cancelled",
                detail="Cancelled by user",
            ))
            await self._broadcast_task_update(task)
        return task

    # ── WebSocket Broadcasting ────────────────────────────────────────────

    def set_broadcast_callback(self, callback: Callable) -> None:
        """Set the WebSocket broadcast function (injected by server)."""
        self._ws_broadcast = callback

    async def _broadcast_task_update(self, task: Task) -> None:
        """Broadcast task state change to connected dashboards."""
        if self._ws_broadcast:
            try:
                await self._ws_broadcast({
                    "type": "task_update",
                    "payload": task.model_dump(mode="json"),
                })
            except Exception as e:
                logger.debug(f"Broadcast failed: {e}")


# Singleton
_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    """Get or create the global task manager."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
