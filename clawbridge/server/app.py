"""ClawBridge FastAPI application.

Central HTTP/WebSocket server that ties together:
- Task management routes
- Engine status routes
- Configuration routes
- WebSocket for live dashboard updates
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from clawbridge.config import get_settings
from clawbridge.orchestrator.manager import get_task_manager
from clawbridge.server.routes.tasks import router as tasks_router
from clawbridge.server.routes.engines import router as engines_router
from clawbridge.server.routes.config_routes import router as config_router
from clawbridge.server.routes.ws import router as ws_router

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    settings = get_settings()
    logger.info(f"ClawBridge v0.1.0 starting on {settings.host}:{settings.port}")
    logger.info(f"Config: {settings!r}")

    # Initialize engines
    manager = get_task_manager()
    await manager.initialize_engines()

    engine_infos = await manager.get_engine_infos()
    for info in engine_infos:
        logger.info(f"  Engine: {info['display_name']} -> {info['status']}")

    if not settings.has_any_key:
        logger.warning(
            "No API keys configured! Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env"
        )

    logger.info("ClawBridge ready -- dashboard at http://%s:%s", settings.host, settings.port)

    yield

    # Shutdown
    logger.info("ClawBridge shutting down...")
    await manager.shutdown_engines()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="ClawBridge",
        description="Bridging Open-Source AI Agents to Your Machine",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS -- permissive for localhost dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(tasks_router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(engines_router, prefix="/api/engines", tags=["engines"])
    app.include_router(config_router, prefix="/api/config", tags=["config"])
    app.include_router(ws_router, tags=["websocket"])

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    return app
