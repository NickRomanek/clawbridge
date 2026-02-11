"""Configuration routes.

GET  /api/config              -- Get current config (keys redacted)
PUT  /api/config/keys         -- Validate that keys are set (not the actual values)
GET  /api/config/policy       -- Get current policy settings
GET  /api/config/audit        -- Get recent audit events
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from clawbridge.config import get_settings
from clawbridge.telemetry.logger import get_audit_logger

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_config():
    """Get current configuration (API keys are never returned -- only presence flags)."""
    settings = get_settings()
    return {
        "server": {
            "host": settings.host,
            "port": settings.port,
        },
        "keys": {
            "anthropic_configured": settings.has_anthropic_key,
            "openai_configured": settings.has_openai_key,
            "default_model": settings.default_model,
        },
        "engines": {
            "enabled": settings.enabled_engines,
        },
        "browser": {
            "headless": settings.browser_headless,
        },
        "policy": {
            "mode": settings.policy_mode.value,
            "max_concurrent_tasks": settings.max_concurrent_tasks,
            "max_actions_per_task": settings.max_actions_per_task,
        },
        "telemetry": {
            "log_level": settings.log_level,
            "log_retention_hours": settings.log_retention_hours,
        },
    }


@router.get("/keys")
async def get_key_status():
    """Check which BYOK keys are configured (never returns actual values)."""
    settings = get_settings()
    return {
        "anthropic": {
            "configured": settings.has_anthropic_key,
            "model": settings.default_model if settings.has_anthropic_key and "claude" in settings.default_model else None,
        },
        "openai": {
            "configured": settings.has_openai_key,
            "model": settings.default_model if settings.has_openai_key and "gpt" in settings.default_model else None,
        },
    }


@router.get("/policy")
async def get_policy():
    """Get current safety policy settings."""
    settings = get_settings()
    return {
        "mode": settings.policy_mode.value,
        "description": {
            "guarded": "Auto-run safe reads. Prompt for sensitive writes and high-risk actions.",
            "permissive": "Auto-run all actions. Full local trust mode.",
            "strict": "Prompt for everything except basic navigation.",
        }.get(settings.policy_mode.value, "Unknown"),
        "max_concurrent_tasks": settings.max_concurrent_tasks,
        "max_actions_per_task": settings.max_actions_per_task,
    }


@router.get("/audit")
async def get_audit_events(
    limit: int = Query(default=50, ge=1, le=500),
    task_id: str | None = Query(default=None),
):
    """Get recent audit events from the activity log."""
    audit = get_audit_logger()
    events = audit.get_recent_events(limit=limit, task_id=task_id)
    return [e.model_dump(mode="json") for e in events]
