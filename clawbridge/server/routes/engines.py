"""Engine status routes.

GET /api/engines          -- List all engines and their status
GET /api/engines/{name}   -- Get a specific engine's status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from clawbridge.orchestrator.manager import get_task_manager
from clawbridge.shared.schemas import EngineName

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[dict])
async def list_engines():
    """Get status info for all registered engines."""
    manager = get_task_manager()
    return await manager.get_engine_infos()


@router.get("/{engine_name}", response_model=dict)
async def get_engine(engine_name: str):
    """Get status of a specific engine."""
    manager = get_task_manager()

    try:
        name = EngineName(engine_name)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown engine: {engine_name}. Available: {[e.value for e in EngineName]}",
        )

    engine = manager.get_engine(name)
    if not engine:
        raise HTTPException(status_code=404, detail=f"Engine {engine_name} not registered")

    info = await engine.get_info()
    return info.model_dump()
