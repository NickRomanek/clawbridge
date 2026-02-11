"""OpenClaw engine adapter for ClawBridge.

Manages OpenClaw as a subprocess and communicates via its gateway API.
OpenClaw provides a full AI agent with CDP-based browser control, persistent
memory, and a skill ecosystem.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any

import httpx

from clawbridge.config import get_settings
from clawbridge.engines.base import EngineBase, EngineError
from clawbridge.shared.schemas import (
    Citation,
    EngineName,
    EngineStatus,
    StepResult,
    Task,
    TaskResult,
    TaskStatus,
    TaskStep,
    TokenUsage,
)

logger = logging.getLogger(__name__)

# OpenClaw gateway defaults
OPENCLAW_GATEWAY_HOST = "127.0.0.1"
OPENCLAW_GATEWAY_PORT = 3080
OPENCLAW_GATEWAY_URL = f"http://{OPENCLAW_GATEWAY_HOST}:{OPENCLAW_GATEWAY_PORT}"


class OpenClawEngine(EngineBase):
    """Agent engine powered by OpenClaw (managed subprocess + gateway API)."""

    def __init__(self) -> None:
        self._status: EngineStatus = EngineStatus.STOPPED
        self._process: subprocess.Popen | None = None
        self._openclaw_bin: str | None = None
        self._http_client: httpx.AsyncClient | None = None

    @property
    def name(self) -> EngineName:
        return EngineName.OPENCLAW

    @property
    def display_name(self) -> str:
        return "OpenClaw"

    @property
    def description(self) -> str:
        return "Full AI agent with CDP browser, persistent memory, and skills ecosystem."

    def _capabilities(self) -> list[str]:
        return ["navigate", "extract", "click", "type", "screenshot", "memory", "skills"]

    async def initialize(self) -> None:
        """Detect OpenClaw installation and optionally start the service."""
        self._status = EngineStatus.STARTING

        try:
            # Find OpenClaw binary
            self._openclaw_bin = self._find_openclaw()

            if not self._openclaw_bin:
                self._status = EngineStatus.NOT_INSTALLED
                logger.warning(
                    "OpenClaw not found on PATH. Install with: npm install -g openclaw@latest"
                )
                return

            # Check if OpenClaw gateway is already running
            self._http_client = httpx.AsyncClient(
                base_url=OPENCLAW_GATEWAY_URL,
                timeout=10.0,
            )

            if await self._is_gateway_running():
                self._status = EngineStatus.AVAILABLE
                logger.info("OpenClaw gateway already running -- connected")
                return

            # Start OpenClaw gateway
            await self._start_gateway()
            self._status = EngineStatus.AVAILABLE
            logger.info("OpenClaw engine initialized and gateway started")

        except Exception as e:
            self._status = EngineStatus.ERROR
            logger.error(f"OpenClaw initialization failed: {e}")

    def _find_openclaw(self) -> str | None:
        """Locate the OpenClaw binary."""
        settings = get_settings()

        # Check explicit path first
        if settings.openclaw_path:
            if shutil.which(settings.openclaw_path):
                return settings.openclaw_path

        # Check common names on PATH
        for name in ["openclaw", "openclaw.cmd", "openclaw.exe"]:
            path = shutil.which(name)
            if path:
                return path

        return None

    async def _is_gateway_running(self) -> bool:
        """Check if OpenClaw gateway is already responding."""
        try:
            resp = await self._http_client.get("/health")
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def _start_gateway(self) -> None:
        """Start OpenClaw gateway as a subprocess."""
        if not self._openclaw_bin:
            raise EngineError(
                EngineName.OPENCLAW,
                "OpenClaw binary not found",
                recoverable=False,
            )

        settings = get_settings()

        # Build environment with BYOK keys
        env = dict(**__import__("os").environ)
        if settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        if settings.openai_api_key:
            env["OPENAI_API_KEY"] = settings.openai_api_key

        try:
            self._process = subprocess.Popen(
                [self._openclaw_bin, "gateway", "start"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for gateway to become healthy
            for attempt in range(30):
                await asyncio.sleep(1)
                if await self._is_gateway_running():
                    return

            raise EngineError(
                EngineName.OPENCLAW,
                "Gateway did not become healthy within 30 seconds",
            )

        except FileNotFoundError:
            raise EngineError(
                EngineName.OPENCLAW,
                f"Could not execute OpenClaw at: {self._openclaw_bin}",
                recoverable=False,
            )

    async def execute_step(self, task: Task, step: TaskStep) -> StepResult:
        """Execute a single step via OpenClaw's gateway API."""
        if self._status != EngineStatus.AVAILABLE:
            raise EngineError(
                EngineName.OPENCLAW,
                f"Engine not available (status: {self._status.value})",
            )

        start_time = time.monotonic()

        try:
            # Send message to OpenClaw via gateway API
            message = self._step_to_message(step)

            resp = await self._http_client.post(
                "/api/message",
                json={
                    "content": message,
                    "conversation_id": task.id,
                },
                timeout=120.0,
            )
            resp.raise_for_status()

            result_data = resp.json()
            duration_ms = int((time.monotonic() - start_time) * 1000)

            return self._parse_step_result(result_data, duration_ms)

        except httpx.HTTPError as e:
            raise EngineError(EngineName.OPENCLAW, f"Gateway API error: {e}")
        except Exception as e:
            raise EngineError(EngineName.OPENCLAW, str(e))

    async def run_task(self, task: Task) -> Task:
        """Run a full task using OpenClaw's agent capabilities."""
        if self._status != EngineStatus.AVAILABLE:
            raise EngineError(
                EngineName.OPENCLAW,
                f"Engine not available (status: {self._status.value})",
            )

        self._status = EngineStatus.RUNNING
        start_time = time.monotonic()

        try:
            # Send the full task prompt to OpenClaw
            resp = await self._http_client.post(
                "/api/message",
                json={
                    "content": task.prompt,
                    "conversation_id": task.id,
                },
                timeout=300.0,  # Long timeout for complex tasks
            )
            resp.raise_for_status()

            result_data = resp.json()
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Build task result from OpenClaw response
            task.result = self._build_task_result(result_data, duration_ms)
            task.status = TaskStatus.COMPLETE
            task.updated_at = datetime.utcnow()

            logger.info(
                f"Task {task.id} completed via OpenClaw in {duration_ms}ms"
            )

        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = str(e)
            task.updated_at = datetime.utcnow()
            logger.error(f"Task {task.id} failed via OpenClaw: {e}")

        finally:
            self._status = EngineStatus.AVAILABLE

        return task

    def _step_to_message(self, step: TaskStep) -> str:
        """Convert a TaskStep into an OpenClaw message."""
        action = step.action.lower()
        target = step.target

        if action == "navigate":
            return f"Navigate to {target} and tell me what you find."
        elif action == "extract":
            return f"Extract the following from the current page: {target}"
        elif action == "click":
            return f"Click on: {target}"
        elif action == "type":
            return f"Type: {target}"
        elif action == "summarize":
            return f"Summarize the current page, focusing on: {target}"
        else:
            return f"{action}: {target}"

    def _parse_step_result(self, data: dict[str, Any], duration_ms: int) -> StepResult:
        """Parse OpenClaw API response into a StepResult."""
        content = data.get("content", data.get("message", str(data)))
        return StepResult(
            url=data.get("url", ""),
            title=data.get("title", ""),
            summary=str(content)[:2000],
            snippets=[str(content)[:500]] if content else [],
            duration_ms=duration_ms,
        )

    def _build_task_result(
        self, data: dict[str, Any], duration_ms: int
    ) -> TaskResult:
        """Build a TaskResult from OpenClaw response."""
        content = data.get("content", data.get("message", str(data)))

        # Extract any URLs mentioned as citations
        citations = []
        for url in data.get("urls", data.get("sources", [])):
            if isinstance(url, str):
                citations.append(Citation(url=url))
            elif isinstance(url, dict):
                citations.append(
                    Citation(
                        url=url.get("url", ""),
                        title=url.get("title", ""),
                    )
                )

        return TaskResult(
            summary=str(content)[:5000],
            citations=citations,
            total_duration_ms=duration_ms,
            engine_used=EngineName.OPENCLAW,
        )

    async def stop(self) -> None:
        """Shut down OpenClaw gateway subprocess."""
        try:
            if self._http_client:
                await self._http_client.aclose()
                self._http_client = None

            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                self._process = None

        except Exception as e:
            logger.warning(f"Error stopping OpenClaw: {e}")
        finally:
            self._status = EngineStatus.STOPPED
            logger.info("OpenClaw engine stopped")

    async def get_status(self) -> EngineStatus:
        """Check live status -- verify gateway is still responding."""
        if self._status in (EngineStatus.NOT_INSTALLED, EngineStatus.STOPPED):
            return self._status

        if self._http_client and await self._is_gateway_running():
            if self._status != EngineStatus.RUNNING:
                self._status = EngineStatus.AVAILABLE
        else:
            self._status = EngineStatus.ERROR

        return self._status
