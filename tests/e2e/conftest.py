"""E2E test fixtures — submit real tasks to a running ClawBridge server."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8765"
WS_URL = "ws://127.0.0.1:8765/ws"

# Per-engine default timeouts (seconds)
ENGINE_TIMEOUTS = {
    "browser_use": 120,
    "computer_use": 120,
    "openclaw": 60,
    "auto": 120,
}

POLL_INTERVAL = 2  # seconds between status polls

# Cache engine availability across tests (fetched once per session)
_engine_cache: dict[str, str] | None = None


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run E2E tests against a live ClawBridge server on :8765",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="E2E tests require --run-e2e flag")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


async def _submit_and_poll(
    client: httpx.AsyncClient,
    prompt: str,
    engine: str = "auto",
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST a task, poll until terminal status, return the task dict."""
    if timeout is None:
        timeout = ENGINE_TIMEOUTS.get(engine, 120)

    resp = await client.post("/api/tasks", json={"prompt": prompt, "engine": engine})
    resp.raise_for_status()
    task = resp.json()
    task_id = task["id"]

    deadline = asyncio.get_running_loop().time() + timeout
    terminal = {"complete", "failed", "cancelled", "error"}

    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get(f"/api/tasks/{task_id}")
        resp.raise_for_status()
        task = resp.json()
        if task["status"] in terminal:
            return task
        await asyncio.sleep(POLL_INTERVAL)

    raise TimeoutError(
        f"Task {task_id} did not reach terminal status within {timeout}s "
        f"(last status: {task['status']})"
    )


async def _submit_and_cancel(
    client: httpx.AsyncClient,
    prompt: str,
    engine: str = "auto",
    cancel_after: float = 3.0,
    poll_timeout: float = 30.0,
) -> dict[str, Any]:
    """POST a task, wait cancel_after seconds, cancel it, poll until terminal."""
    resp = await client.post("/api/tasks", json={"prompt": prompt, "engine": engine})
    resp.raise_for_status()
    task = resp.json()
    task_id = task["id"]

    await asyncio.sleep(cancel_after)

    cancel_resp = await client.patch(
        f"/api/tasks/{task_id}", json={"action": "cancel"}
    )
    cancel_resp.raise_for_status()

    deadline = asyncio.get_running_loop().time() + poll_timeout
    terminal = {"complete", "failed", "cancelled", "error"}

    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get(f"/api/tasks/{task_id}")
        resp.raise_for_status()
        task = resp.json()
        if task["status"] in terminal:
            return task
        await asyncio.sleep(POLL_INTERVAL)

    raise TimeoutError(
        f"Task {task_id} did not reach terminal/cancelled status within {poll_timeout}s "
        f"(last status: {task['status']})"
    )


async def _get_engines(client: httpx.AsyncClient) -> dict[str, str]:
    """Fetch engine availability, with caching."""
    global _engine_cache
    if _engine_cache is not None:
        return _engine_cache
    resp = await client.get("/api/engines")
    resp.raise_for_status()
    _engine_cache = {e["name"]: e["status"] for e in resp.json()}
    return _engine_cache


@pytest.fixture
async def async_client():
    """Function-scoped httpx client. Fresh client per test prevents event loop cascade."""
    client = httpx.AsyncClient(base_url=BASE_URL, timeout=120.0)
    try:
        resp = await client.get("/api/engines")
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        await client.aclose()
        pytest.fail(
            f"ClawBridge server not reachable at {BASE_URL}. "
            f"Start it with `python clawbridge.py` before running E2E tests. ({exc})"
        )
    yield client
    await client.aclose()


@pytest.fixture
async def available_engines(async_client: httpx.AsyncClient) -> dict[str, str]:
    """Returns {engine_name: status} from the live server."""
    return await _get_engines(async_client)


@pytest.fixture
def require_browser(available_engines: dict[str, str]) -> None:
    status = available_engines.get("browser_use")
    if status not in ("available", "running"):
        pytest.skip(f"browser_use engine not available (status={status})")


@pytest.fixture
def require_computer(available_engines: dict[str, str]) -> None:
    status = available_engines.get("computer_use")
    if status not in ("available", "running"):
        pytest.skip(f"computer_use engine not available (status={status})")


@pytest.fixture
def require_openclaw(available_engines: dict[str, str]) -> None:
    status = available_engines.get("openclaw")
    if status not in ("available", "running"):
        pytest.skip(f"openclaw engine not available (status={status})")


@pytest.fixture
def submit_task(async_client: httpx.AsyncClient):
    """Returns an async callable: submit_task(prompt, engine, timeout) -> task dict."""
    async def _submit(
        prompt: str,
        engine: str = "auto",
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await _submit_and_poll(async_client, prompt, engine, timeout)
    return _submit


@pytest.fixture
def cancel_task(async_client: httpx.AsyncClient):
    """Returns an async callable: cancel_task(prompt, engine, cancel_after) -> task dict."""
    async def _cancel(
        prompt: str,
        engine: str = "auto",
        cancel_after: float = 3.0,
        poll_timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await _submit_and_cancel(
            async_client, prompt, engine, cancel_after, poll_timeout
        )
    return _cancel


@pytest.fixture
def fetch_dashboard(async_client: httpx.AsyncClient):
    """Returns an async callable that fetches the dashboard HTML."""
    async def _fetch() -> str:
        resp = await async_client.get("/")
        resp.raise_for_status()
        return resp.text
    return _fetch


@pytest.fixture
def list_workflows(async_client: httpx.AsyncClient):
    """Returns an async callable that fetches saved workflows."""
    async def _list() -> list[dict[str, Any]]:
        resp = await async_client.get("/api/workflows")
        resp.raise_for_status()
        return resp.json()
    return _list


async def _collect_ws_messages(
    timeout: float = 10.0,
    filter_types: set[str] | None = None,
) -> list[dict]:
    """Connect to WebSocket, collect messages for `timeout` seconds, return them.

    If filter_types is set, only messages with matching 'type' are returned.
    """
    import websockets

    messages: list[dict] = []
    try:
        async with websockets.connect(WS_URL) as ws:
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    if filter_types is None or msg.get("type") in filter_types:
                        messages.append(msg)
                except asyncio.TimeoutError:
                    break
    except Exception:
        pass
    return messages


async def _ws_send_and_collect(
    send_messages: list[dict],
    collect_timeout: float = 10.0,
    filter_types: set[str] | None = None,
    delay_between: float = 0.5,
) -> list[dict]:
    """Connect to WebSocket, send messages, collect responses."""
    import websockets

    messages: list[dict] = []
    try:
        async with websockets.connect(WS_URL) as ws:
            # Drain initial task_list etc.
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg = json.loads(raw)
                    if filter_types is None or msg.get("type") in filter_types:
                        messages.append(msg)
            except asyncio.TimeoutError:
                pass

            # Send our messages
            for m in send_messages:
                await ws.send(json.dumps(m))
                await asyncio.sleep(delay_between)

            # Collect responses
            deadline = asyncio.get_running_loop().time() + collect_timeout
            while asyncio.get_running_loop().time() < deadline:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    if filter_types is None or msg.get("type") in filter_types:
                        messages.append(msg)
                except asyncio.TimeoutError:
                    break
    except Exception:
        pass
    return messages


@pytest.fixture
def ws_collect():
    """Returns _collect_ws_messages for tests that need WebSocket listening."""
    return _collect_ws_messages


@pytest.fixture
def ws_send_and_collect():
    """Returns _ws_send_and_collect for tests that need WebSocket interaction."""
    return _ws_send_and_collect
