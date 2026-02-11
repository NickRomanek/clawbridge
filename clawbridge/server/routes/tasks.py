"""Task management routes.

POST /api/tasks           -- Submit a new task
GET  /api/tasks           -- List all tasks
GET  /api/tasks/{id}      -- Get task details
PATCH /api/tasks/{id}     -- Pause, resume, or cancel a task
DELETE /api/tasks/{id}    -- Remove a task from history
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from clawbridge.orchestrator.manager import get_task_manager
from clawbridge.shared.schemas import EngineName, Task

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateTaskRequest(BaseModel):
    """Request body for creating a new task."""
    prompt: str = Field(..., min_length=1, max_length=10000, description="Task description or question")
    engine: EngineName = Field(default=EngineName.AUTO, description="Engine to use (auto, browser_use, openclaw)")


class UpdateTaskRequest(BaseModel):
    """Request body for updating task state."""
    action: str = Field(..., description="pause, resume, or cancel")


@router.post("", response_model=dict)
async def create_task(req: CreateTaskRequest):
    """Submit a new task for the agent to execute."""
    manager = get_task_manager()

    task = Task(
        prompt=req.prompt,
        engine=req.engine,
    )

    task = await manager.submit_task(task)
    logger.info(f"Task created: {task.id} (engine: {task.engine.value})")

    return task.model_dump(mode="json")


@router.get("", response_model=list[dict])
async def list_tasks():
    """Get all tasks, newest first."""
    manager = get_task_manager()
    tasks = manager.get_all_tasks()
    return [t.model_dump(mode="json") for t in tasks]


@router.get("/{task_id}", response_model=dict)
async def get_task(task_id: str):
    """Get a single task by ID."""
    manager = get_task_manager()
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.model_dump(mode="json")


@router.patch("/{task_id}", response_model=dict)
async def update_task(task_id: str, req: UpdateTaskRequest):
    """Pause, resume, or cancel a task."""
    manager = get_task_manager()

    if req.action == "pause":
        task = await manager.pause_task(task_id)
    elif req.action == "resume":
        task = await manager.resume_task(task_id)
    elif req.action == "cancel":
        task = await manager.cancel_task(task_id)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task.model_dump(mode="json")


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """Remove a task from the task list (does not stop a running task)."""
    manager = get_task_manager()
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Cancel if running
    if task.status.value in ("pending", "running"):
        await manager.cancel_task(task_id)

    # Remove from manager
    manager._tasks.pop(task_id, None)
    return {"status": "deleted", "task_id": task_id}
