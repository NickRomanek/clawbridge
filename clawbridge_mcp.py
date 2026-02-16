"""
ClawBridge MCP Server
=====================
Exposes ClawBridge as an MCP tool server for Claude Code, Cursor, and other
MCP-compatible clients.

Prerequisites:
    - ClawBridge must be running on localhost:8765 (or set CLAWBRIDGE_URL)
    - pip install "mcp[cli]" (usually already installed with browser-use)

Usage (stdio — for Claude Code):
    python clawbridge_mcp.py

Usage (HTTP — for remote clients):
    python clawbridge_mcp.py --http

Register with Claude Code:
    claude mcp add clawbridge -- python clawbridge_mcp.py

Or add to .mcp.json in project root (see .mcp.json).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLAWBRIDGE_URL = os.environ.get("CLAWBRIDGE_URL", "http://127.0.0.1:8765")

# Logging goes to stderr (stdout is reserved for JSON-RPC in stdio mode)
logging.basicConfig(
    level=logging.INFO,
    format="[ClawBridge MCP] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("clawbridge_mcp")

mcp = FastMCP(
    "ClawBridge",
    instructions=(
        "ClawBridge is a desktop & browser automation agent. "
        "Use 'run_task' to execute automation tasks like web browsing, "
        "form filling, data extraction, desktop app control, and scheduled tasks. "
        "Use 'list_engines' to see available engines. "
        "Use 'get_task_status' to check on running tasks."
    ),
)


# ---------------------------------------------------------------------------
# HTTP client helper
# ---------------------------------------------------------------------------
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=CLAWBRIDGE_URL, timeout=600.0)


async def _health_check() -> bool:
    """Check if ClawBridge is running."""
    try:
        async with _client() as c:
            resp = await c.get("/health")
            return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def run_task(prompt: str, engine: str = "auto", wait: bool = True) -> dict:
    """Submit and execute a task on ClawBridge.

    ClawBridge will use AI to automate the task — browsing the web,
    controlling desktop apps, filling forms, extracting data, etc.

    Args:
        prompt: Natural language description of what to do.
                Examples: "Go to google.com and search for ClawBridge",
                "Open Notepad and type Hello World",
                "What is the weather in San Francisco?"
        engine: Which engine to use.
                - "auto" (default): automatically picks the best engine
                - "openclaw": fast chat-based AI (no browser/desktop control)
                - "computer_use": full desktop automation with screenshots
                - "browser_use": headless browser automation
        wait: If True (default), wait for the task to complete before returning.
              If False, return immediately with the task ID for polling.

    Returns:
        Task object with id, status, result (summary, steps, tokens, cost), and error if any.
    """
    if not await _health_check():
        return {"error": "ClawBridge is not running. Start it with: python clawbridge.py"}

    async with _client() as client:
        resp = await client.post("/api/tasks", json={"prompt": prompt, "engine": engine})
        resp.raise_for_status()
        task = resp.json()

        if not wait:
            return task

        # Poll until task completes (with timeout)
        task_id = task["id"]
        poll_count = 0
        max_polls = 300  # 10 minutes max (2s intervals)
        while task["status"] in ("pending", "running") and poll_count < max_polls:
            await asyncio.sleep(2)
            resp = await client.get(f"/api/tasks/{task_id}")
            resp.raise_for_status()
            task = resp.json()
            poll_count += 1

        return task


@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """Check the current status and result of a ClawBridge task.

    Args:
        task_id: The UUID of the task to check.

    Returns:
        Task object with current status, result if complete, error if failed.
    """
    async with _client() as client:
        resp = await client.get(f"/api/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def list_tasks(limit: int = 20) -> list[dict]:
    """List recent ClawBridge tasks with their statuses and results.

    Args:
        limit: Maximum number of tasks to return (default 20).

    Returns:
        List of task objects sorted by creation time.
    """
    async with _client() as client:
        resp = await client.get("/api/tasks")
        resp.raise_for_status()
        tasks = resp.json()
        return tasks[:limit]


@mcp.tool()
async def cancel_task(task_id: str) -> dict:
    """Cancel a running or pending ClawBridge task.

    Args:
        task_id: The UUID of the task to cancel.

    Returns:
        Updated task object.
    """
    async with _client() as client:
        resp = await client.patch(f"/api/tasks/{task_id}", json={"action": "cancel"})
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Engine Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_engines() -> list[dict]:
    """List all available ClawBridge automation engines and their status.

    Returns:
        List of engines with name, display_name, status (available/running/stopped/error),
        and error hints if any.
    """
    async with _client() as client:
        resp = await client.get("/api/engines")
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Task History & Audit Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_task_steps(task_id: str) -> dict:
    """Get the step-by-step trace for a completed task.

    Shows exactly what actions the agent took — clicks, typing, screenshots,
    reasoning at each step, token usage, and timing.

    Args:
        task_id: The UUID of the task.

    Returns:
        Object with task_id, list of steps, and total_steps count.
    """
    async with _client() as client:
        resp = await client.get(f"/api/tasks/{task_id}/steps")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_task_audit(task_id: str) -> list[dict]:
    """Get the audit trail for a specific task.

    Shows lifecycle events: created, started, retries, safety flags, completed/failed.

    Args:
        task_id: The UUID of the task.

    Returns:
        List of audit events with timestamps and details.
    """
    async with _client() as client:
        resp = await client.get(f"/api/tasks/{task_id}/audit")
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Memory & Personality Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_memory(query: str) -> list[dict]:
    """Search the agent's memory and daily logs for past activity.

    Args:
        query: Keyword(s) to search for across memory files and daily logs.

    Returns:
        List of matching memory entries with file source and content.
    """
    async with _client() as client:
        resp = await client.get("/api/memory/search", params={"q": query})
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_agent_context() -> str:
    """Get the agent's current personality and memory context.

    Returns the assembled context from SOUL.md, IDENTITY.md, USER.md,
    MEMORY.md, and today's activity log.

    Returns:
        The full personality/memory context string.
    """
    async with _client() as client:
        resp = await client.get("/api/personality/context")
        resp.raise_for_status()
        data = resp.json()
        return data.get("context", "")


@mcp.tool()
async def append_memory(content: str, daily: bool = True) -> dict:
    """Add an entry to the agent's memory.

    Args:
        content: The text to add to memory.
        daily: If True (default), append to today's daily log.
               If False, append to the durable MEMORY.md file.

    Returns:
        Confirmation message.
    """
    async with _client() as client:
        resp = await client.post("/api/memory", json={"text": content, "daily": daily})
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Scheduling Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_schedules() -> list[dict]:
    """List all configured task schedules.

    Returns:
        List of schedules with ID, prompt, engine, interval, and enabled status.
    """
    async with _client() as client:
        resp = await client.get("/api/schedules")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def create_schedule(
    prompt: str,
    engine: str = "auto",
    interval_minutes: int = 60,
    cron: str = "",
) -> dict:
    """Create a recurring task schedule.

    Args:
        prompt: The task to run on each schedule trigger.
        engine: Which engine to use (auto, openclaw, computer_use, browser_use).
        interval_minutes: Run every N minutes (ignored if cron is set).
        cron: Cron expression (e.g., "0 9 * * *" for daily at 9am). Overrides interval.

    Returns:
        Created schedule object.
    """
    async with _client() as client:
        body = {"prompt": prompt, "engine": engine, "interval_minutes": interval_minutes}
        if cron:
            body["cron"] = cron
        resp = await client.post("/api/schedules", json=body)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Configuration Tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_config() -> dict:
    """Get the current ClawBridge configuration.

    Returns enabled engines, browser mode, configured API keys (masked),
    policy mode, and other settings.

    Returns:
        Configuration summary dict.
    """
    async with _client() as client:
        resp = await client.get("/api/config")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_license_info() -> dict:
    """Get ClawBridge license status, tier, and remaining credits.

    Returns:
        License info including status (activated/byok/not_activated),
        tier (starter/byok), credit balance, and top-up URL.
    """
    async with _client() as client:
        resp = await client.get("/api/license/status")
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Status Resource
# ---------------------------------------------------------------------------

@mcp.resource("clawbridge://status")
async def get_status() -> str:
    """Current ClawBridge server status and engine availability."""
    try:
        async with _client() as client:
            health = await client.get("/health")
            engines = await client.get("/api/engines")
            config = await client.get("/api/config")

            status_parts = [f"ClawBridge Status: {'OK' if health.status_code == 200 else 'DOWN'}"]
            status_parts.append(f"URL: {CLAWBRIDGE_URL}")

            if engines.status_code == 200:
                for e in engines.json():
                    status_parts.append(f"  Engine: {e['display_name']} — {e['status']}")

            if config.status_code == 200:
                cfg = config.json()
                status_parts.append(f"  Policy: {cfg.get('policy_mode', 'unknown')}")
                status_parts.append(f"  Browser: {cfg.get('browser_mode', 'unknown')}")

            return "\n".join(status_parts)
    except Exception as e:
        return f"ClawBridge Status: UNREACHABLE ({e})\nURL: {CLAWBRIDGE_URL}\nMake sure ClawBridge is running: python clawbridge.py"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--http" in sys.argv:
        log.info("Starting ClawBridge MCP server (HTTP mode) — connecting to %s", CLAWBRIDGE_URL)
        mcp.run(transport="streamable-http")
    else:
        log.info("Starting ClawBridge MCP server (stdio mode) — connecting to %s", CLAWBRIDGE_URL)
        mcp.run(transport="stdio")
