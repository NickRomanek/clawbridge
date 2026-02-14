"""ClawBridge task manager -- lifecycle, queue, and engine routing.

Manages the task queue, dispatches tasks to engines, and tracks lifecycle state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
import httpx
from datetime import datetime, timezone
from typing import Any, Callable

from clawbridge.config import get_settings
from clawbridge.engines.base import EngineBase, EngineError
from clawbridge.engines.browser_use_engine import BrowserUseEngine
from clawbridge.engines.computer_use_engine import ComputerUseEngine
from clawbridge.engines.openclaw_engine import OpenClawEngine
from clawbridge.policy.safety import evaluate_policy, scan_for_prompt_injection
from clawbridge.shared.schemas import (
    ActionClass,
    AuditEvent,
    Citation,
    EngineName,
    EngineStatus,
    Task,
    TaskResult,
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
        self._init_db()
        self._load_tasks_from_db()

    # ── Engine Management ─────────────────────────────────────────────────

    async def initialize_engines(self) -> None:
        """Start all enabled engines."""
        settings = get_settings()
        enabled = settings.enabled_engine_list

        if EngineName.BROWSER_USE in enabled:
            engine = BrowserUseEngine()
            # Set screenshot callback to broadcast frames
            engine.on_screenshot = lambda frame: asyncio.create_task(
                self._broadcast_browser_frame(frame)
            )
            await engine.initialize()
            self._engines[EngineName.BROWSER_USE] = engine

        if EngineName.OPENCLAW in enabled:
            engine = OpenClawEngine()
            await engine.initialize()
            self._engines[EngineName.OPENCLAW] = engine

        if EngineName.COMPUTER_USE in enabled:
            cu_engine = ComputerUseEngine()
            cu_engine.on_screenshot = lambda frame: asyncio.create_task(
                self._broadcast_browser_frame(frame)
            )
            await cu_engine.initialize()
            self._engines[EngineName.COMPUTER_USE] = cu_engine

        # Start Remote Bridge Polling if configured
        if settings.remote_bridge_url:
            asyncio.create_task(self.remote_bridge_loop())

        available = [
            e.display_name
            for e in self._engines.values()
            if asyncio.iscoroutine((status := e.get_status()))
            or True  # will check below
        ]
        logger.info(f"Engines initialized: {list(self._engines.keys())}")

    async def _broadcast_browser_frame(self, frame_base64: str) -> None:
        """Broadcast a browser screenshot frame to connected dashboards."""
        if self._ws_broadcast:
            try:
                await self._ws_broadcast({
                    "type": "browser_frame",
                    "payload": {
                        "frame": frame_base64
                    },
                })
            except Exception as e:
                logger.debug(f"Frame broadcast failed: {e}")

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

    async def _select_engine(
        self, preferred: EngineName, prompt: str = ""
    ) -> EngineBase:
        """Select the best available engine.

        Smart default priority:
        - Desktop tasks: computer-use → browser-use → openclaw
        - Non-desktop tasks: openclaw (when available) → browser-use → computer-use

        OpenClaw is preferred for non-desktop tasks because it has memory/skills support.
        """
        # Explicit engine selection (not AUTO)
        if preferred != EngineName.AUTO and preferred in self._engines:
            engine = self._engines[preferred]
            status = await engine.get_status()
            if status == EngineStatus.AVAILABLE:
                logger.info("Engine selected: %s (explicit)", engine.display_name)
                return engine
            raise EngineError(
                preferred,
                f"Selected engine '{preferred.value}' is not available (status: {status.value})",
                recoverable=True
            )

        # Auto-select: check if the task looks like a desktop task
        from clawbridge.engines.computer_use_engine import looks_like_desktop_task

        is_desktop = prompt and looks_like_desktop_task(prompt)

        if is_desktop:
            # Desktop tasks: prefer computer-use for native app control
            priority = [
                EngineName.COMPUTER_USE,
                EngineName.BROWSER_USE,
                EngineName.OPENCLAW,
            ]
            reason = "desktop task detected"
        else:
            # Non-desktop tasks: prefer OpenClaw (has memory/skills), then browser-use
            priority = [
                EngineName.OPENCLAW,
                EngineName.BROWSER_USE,
                EngineName.COMPUTER_USE,
            ]
            reason = "smart default (OpenClaw preferred when available)"

        # Find first available engine in priority order
        for name in priority:
            if name in self._engines:
                engine = self._engines[name]
                status = await engine.get_status()
                if status == EngineStatus.AVAILABLE:
                    logger.info("Engine selected: %s (%s)", engine.display_name, reason)
                    return engine

        raise EngineError(
            EngineName.AUTO,
            "No functional engines available. Please check your API keys or ENABLED_ENGINES.",
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
        self._save_task_to_db(task)

        return task

    async def _execute_task(self, task: Task) -> None:
        """Execute a task on the selected engine."""
        audit = get_audit_logger()

        try:
            self._running_count += 1
            task.status = TaskStatus.RUNNING
            task.updated_at = datetime.now(tz=timezone.utc)
            await self._broadcast_task_update(task)

            # Select engine
            engine = await self._select_engine(task.engine, prompt=task.prompt)
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
            task.updated_at = datetime.now(tz=timezone.utc)
            audit.log_event(AuditEvent(
                task_id=task.id,
                event_type="task_error",
                detail=str(e),
            ))

        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = f"Unexpected error: {e}"
            task.updated_at = datetime.now(tz=timezone.utc)
            logger.exception(f"Task {task.id} unexpected error")
            audit.log_event(AuditEvent(
                task_id=task.id,
                event_type="task_error",
                detail=f"Unexpected: {e}",
            ))

        finally:
            self._running_count = max(0, self._running_count - 1)
            self._task_futures.pop(task.id, None)
            self._save_task_to_db(task)
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
            task.updated_at = datetime.now(tz=timezone.utc)

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
            task.updated_at = datetime.now(tz=timezone.utc)
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
            task.updated_at = datetime.now(tz=timezone.utc)

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

    # ── Persistence ───────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Initialize SQLite database for task persistence."""
        settings = get_settings()
        try:
            conn = sqlite3.connect(settings.db_path)
            c = conn.cursor()
            c.execute(
                """CREATE TABLE IF NOT EXISTS tasks
                             (id TEXT PRIMARY KEY, prompt TEXT, engine TEXT, status TEXT, 
                              result TEXT, error TEXT, created_at TEXT, updated_at TEXT)"""
            )
            conn.commit()
            conn.close()
            logger.info(f"Database initialized at {settings.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def _load_tasks_from_db(self) -> None:
        """Load recent tasks from SQLite on startup."""
        settings = get_settings()
        try:
            conn = sqlite3.connect(settings.db_path)
            c = conn.cursor()
            c.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100")
            for row in c.fetchall():
                try:
                    res_val = json.loads(row[4]) if row[4] else None
                    t = Task(
                        id=row[0],
                        prompt=row[1],
                        engine=EngineName(row[2]),
                        status=TaskStatus(row[3]),
                        result=TaskResult(**res_val) if res_val else None,
                        error=row[5],
                        created_at=datetime.fromisoformat(row[6]) if datetime.fromisoformat(row[6]).tzinfo else datetime.fromisoformat(row[6]).replace(tzinfo=timezone.utc),
                        updated_at=datetime.fromisoformat(row[7]) if datetime.fromisoformat(row[7]).tzinfo else datetime.fromisoformat(row[7]).replace(tzinfo=timezone.utc),
                    )
                    self._tasks[t.id] = t
                except Exception as e:
                    logger.warning(f"Failed to parse task {row[0]} from DB: {e}")
            conn.close()
            logger.info(f"Loaded {len(self._tasks)} tasks from database")
        except Exception as e:
            logger.error(f"Failed to load tasks from DB: {e}")

    def _save_task_to_db(self, task: Task) -> None:
        """UPSERT task state into SQLite."""
        settings = get_settings()
        try:
            conn = sqlite3.connect(settings.db_path)
            c = conn.cursor()
            res_json = json.dumps(task.result.model_dump(mode="json")) if task.result else None
            c.execute(
                """INSERT OR REPLACE INTO tasks 
                             (id, prompt, engine, status, result, error, created_at, updated_at)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.id,
                    task.prompt,
                    task.engine.value,
                    task.status.value,
                    res_json,
                    task.error,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save task to DB: {e}")

    # ── Remote Bridge ─────────────────────────────────────────────────────

    async def remote_bridge_loop(self) -> None:
        """Background loop to poll for remote tasks from a hub."""
        settings = get_settings()
        if not settings.remote_bridge_url:
            return

        mid = settings.machine_id
        logger.info(f"Starting Remote Bridge polling (Machine ID: {mid})")

        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{settings.remote_bridge_url}/api/bridge/tasks",
                        headers={
                            "X-Machine-ID": mid,
                            "Authorization": f"Bearer {settings.remote_auth_token}",
                        },
                        timeout=30.0,
                    )
                    if resp.status_code == 200:
                        tasks_data = resp.json()
                        for t_data in tasks_data:
                            # Avoid duplicates by check ID if provided or prompt?
                            # Remote typically sends fresh tasks.
                            task = Task(
                                id=t_data.get("id", str(uuid.uuid4())),
                                prompt=t_data["prompt"],
                                engine=EngineName(t_data.get("engine", "auto")),
                            )
                            if task.id not in self._tasks:
                                await self.submit_task(task)
                    elif resp.status_code != 204:  # 204 No Content is normal
                        logger.debug(f"Remote bridge poll status: {resp.status_code}")
            except Exception as e:
                logger.debug(f"Remote bridge poll failed: {e}")

            await asyncio.sleep(10)  # Wait 10s between polls

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
