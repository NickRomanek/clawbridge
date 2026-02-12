#!/usr/bin/env python3
"""
ClawBridge - Single-file runnable.
Bridging Open-Source AI Agents to Your Machine.

Usage:
    python clawbridge.py

On first run, missing dependencies are installed automatically. Then open http://127.0.0.1:8765
Optional: create .env with ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY (BYOK).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# Auto-install dependencies if missing (run once, then exit; user runs again)
# ---------------------------------------------------------------------------

def _ensure_dependencies() -> None:
    required = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "python-dotenv",
        "httpx",
        "websockets",
        "browser-use",
        "langchain-anthropic",
        "langchain-openai",
        "anthropic",
        "pyautogui",
        "Pillow",
        "mss",
    ]
    # Map pip package names to their actual import names where they differ
    import_names = {"python-dotenv": "dotenv", "Pillow": "PIL"}
    missing = []
    for pkg in required:
        mod = import_names.get(pkg, pkg.replace("-", "_").split("[")[0])
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    print("Installing missing dependencies (one-time setup)...")
    print(f"  Missing: {', '.join(missing)}")
    print()
    # Use --user if system Python site-packages is not writable
    pip_cmd = [sys.executable, "-m", "pip", "install", "-q"]
    import site
    site_dir = site.getsitepackages()[0] if site.getsitepackages() else None
    if site_dir and not os.access(site_dir, os.W_OK):
        pip_cmd.append("--user")
        print("  (using --user install -- system Python detected)")
    subprocess.run(pip_cmd + required, check=True)
    print("Installing Chromium for browser automation...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    print()
    print("Setup complete. Run the script again:")
    print("  python clawbridge.py")
    print()
    sys.exit(0)

_ensure_dependencies()

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Rest of imports (now guaranteed present)
import asyncio
import base64
import io
import json
import logging
import sqlite3
import time
import uuid
import webbrowser
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
import uvicorn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

class Settings:
    host = _env("CLAWBRIDGE_HOST", "127.0.0.1")
    port = int(_env("CLAWBRIDGE_PORT", "8765"))
    anthropic_api_key = _env("ANTHROPIC_API_KEY")
    openai_api_key = _env("OPENAI_API_KEY")
    openrouter_api_key = _env("OPENROUTER_API_KEY")
    default_model = _env("DEFAULT_MODEL", "gpt-4o")
    enabled_engines = _env("ENABLED_ENGINES", "browser_use,openclaw,computer_use")
    browser_headless = _env("BROWSER_HEADLESS", "true").lower() in ("1", "true", "yes")
    browser_mode = _env("BROWSER_MODE", "default")  # "default" | "cdp" | "user_data_dir"
    browser_cdp_url = _env("BROWSER_CDP_URL", "http://localhost:9222")
    browser_user_data_dir = _env("BROWSER_USER_DATA_DIR", "")
    # Computer-use engine settings
    computer_use_model = _env("COMPUTER_USE_MODEL", "anthropic/claude-sonnet-4.5")
    computer_use_max_screen_width = int(_env("COMPUTER_USE_MAX_SCREEN_WIDTH", "1920"))
    computer_use_max_screen_height = int(_env("COMPUTER_USE_MAX_SCREEN_HEIGHT", "1080"))
    computer_use_action_delay_ms = int(_env("COMPUTER_USE_ACTION_DELAY_MS", "500"))
    # OpenClaw engine settings
    openclaw_gateway_port = int(_env("OPENCLAW_GATEWAY_PORT", "18789"))
    openclaw_api_key = _env("OPENCLAW_API_KEY", "")  # Optional bearer token for gateway auth
    policy_mode = _env("POLICY_MODE", "guarded")
    max_concurrent_tasks = int(_env("MAX_CONCURRENT_TASKS", "3"))
    max_actions_per_task = int(_env("MAX_ACTIONS_PER_TASK", "50"))
    log_level = _env("LOG_LEVEL", "INFO")
    db_path = _env("CLAWBRIDGE_DB", "clawbridge.db")
    remote_bridge_url = _env("REMOTE_BRIDGE_URL", "")
    remote_auth_token = _env("REMOTE_AUTH_TOKEN", "")

    @classmethod
    def has_anthropic_key(cls) -> bool:
        return bool(cls.anthropic_api_key)

    @classmethod
    def has_openai_key(cls) -> bool:
        return bool(cls.openai_api_key)

    @classmethod
    def has_openrouter_key(cls) -> bool:
        return bool(cls.openrouter_api_key)

    @classmethod
    def has_any_key(cls) -> bool:
        return cls.has_anthropic_key() or cls.has_openai_key() or cls.has_openrouter_key()

    @classmethod
    def enabled_engine_list(cls) -> list[str]:
        return [x.strip().lower() for x in cls.enabled_engines.split(",") if x.strip()]

def get_settings() -> type:
    return Settings

def get_machine_id() -> str:
    """Load or generate a unique machine ID."""
    id_file = Path("clawbridge.id")
    if id_file.exists():
        return id_file.read_text().strip()
    mid = str(uuid.uuid4())
    id_file.write_text(mid)
    return mid

def init_db():
    """Initialize SQLite database for task persistence."""
    conn = sqlite3.connect(Settings.db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (id TEXT PRIMARY KEY, prompt TEXT, engine TEXT, status TEXT, 
                  result TEXT, error TEXT, created_at TEXT, updated_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------------------------
# Schemas (Pydantic)
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"
    PAUSED = "paused"
    CANCELLED = "cancelled"

class EngineName(str, Enum):
    BROWSER_USE = "browser_use"
    OPENCLAW = "openclaw"
    COMPUTER_USE = "computer_use"
    AUTO = "auto"

class EngineStatus(str, Enum):
    AVAILABLE = "available"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    NOT_INSTALLED = "not_installed"
    NO_API_KEY = "no_api_key"

class Citation(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""

class TaskResult(BaseModel):
    summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    total_steps: int = 0
    total_duration_ms: int = 0
    engine_used: str = "auto"
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0

class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = ""
    engine: EngineName = EngineName.AUTO
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    result: TaskResult | None = None
    error: str | None = None

class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    task_id: str = ""
    event_type: str = ""
    detail: str = ""

# ---------------------------------------------------------------------------
# Audit logger (in-memory + optional file)
# ---------------------------------------------------------------------------

class AuditLogger:
    def __init__(self, maxlen: int = 500):
        self._buffer: deque[AuditEvent] = deque(maxlen=maxlen)
        self._on_log: Callable[[AuditEvent], Any] | None = None

    def log(self, event: AuditEvent) -> None:
        self._buffer.append(event)
        if self._on_log:
            try:
                self._on_log(event)
            except Exception:
                pass

    def recent(self, limit: int = 50, task_id: str | None = None) -> list[AuditEvent]:
        events = list(self._buffer)
        if task_id:
            events = [e for e in events if e.task_id == task_id]
        return events[-limit:]

_audit = AuditLogger()

def get_audit() -> AuditLogger:
    return _audit

# ---------------------------------------------------------------------------
# Engines (browser-use only in single-file; OpenClaw stubbed)
# ---------------------------------------------------------------------------

class EngineBase:
    name: EngineName = EngineName.AUTO
    display_name: str = ""
    _status: EngineStatus = EngineStatus.STOPPED
    _error_hint: str = ""

    async def initialize(self) -> None:
        raise NotImplementedError

    async def run_task(self, task: Task) -> Task:
        raise NotImplementedError

    async def get_status(self) -> EngineStatus:
        return self._status

    async def get_info(self) -> dict:
        return {
            "name": self.name.value,
            "display_name": self.display_name,
            "status": self._status.value,
            "description": "",
            "error_hint": self._error_hint,
        }

def _find_chrome_exe() -> str | None:
    """Find the real Chrome/Edge executable on Windows."""
    import glob
    candidates = [
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for c in candidates:
        for p in glob.glob(c):
            if os.path.isfile(p):
                return p
    # Fallback: try shutil.which
    for name in ("chrome", "google-chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None

class BrowserUseEngine(EngineBase):
    name = EngineName.BROWSER_USE
    display_name = "browser-use"
    on_screenshot: Callable[[str], Any] | None = None  # receives base64 image string

    async def initialize(self) -> None:
        try:
            from browser_use import Agent, Browser, BrowserProfile
            from browser_use.browser.profile import ViewportSize
            self._Agent = Agent
            self._Browser = Browser
            settings = get_settings()
            vp = ViewportSize(width=1280, height=900)
            mode = settings.browser_mode
            if mode == "cdp":
                profile = BrowserProfile(
                    cdp_url=settings.browser_cdp_url,
                    viewport=vp,
                    window_size=vp,
                )
                logging.info("browser-use: connecting via CDP to %s", settings.browser_cdp_url)
            elif mode == "user_data_dir" and settings.browser_user_data_dir:
                # Find real Chrome executable so Google doesn't block Playwright's Chromium
                chrome_exe = _find_chrome_exe()
                profile = BrowserProfile(
                    user_data_dir=settings.browser_user_data_dir,
                    executable_path=chrome_exe,
                    headless=settings.browser_headless,
                    viewport=vp,
                    window_size=vp,
                )
                logging.info("browser-use: user data dir %s, chrome=%s", settings.browser_user_data_dir, chrome_exe)
            else:
                profile = BrowserProfile(
                    headless=settings.browser_headless,
                    viewport=vp,
                    window_size=vp,
                )
            self._browser = Browser(browser_profile=profile)
            if settings.has_anthropic_key():
                from browser_use.llm import ChatAnthropic
                self._llm = ChatAnthropic(model=settings.default_model, api_key=settings.anthropic_api_key)
            elif settings.has_openai_key():
                from browser_use.llm import ChatOpenAI
                self._llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)
            elif settings.has_openrouter_key():
                from browser_use.llm import ChatOpenRouter
                self._llm = ChatOpenRouter(
                    model=settings.default_model,
                    api_key=settings.openrouter_api_key,
                )
            else:
                self._status = EngineStatus.NO_API_KEY
                self._error_hint = "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in .env"
                return
            self._status = EngineStatus.AVAILABLE
        except ImportError:
            self._status = EngineStatus.NOT_INSTALLED
            self._error_hint = "Run: pip install browser-use"
        except Exception as e:
            logging.warning("browser-use init failed: %s", e)
            self._status = EngineStatus.ERROR
            self._error_hint = str(e)

    async def run_task(self, task: Task) -> Task:
        if self._status != EngineStatus.AVAILABLE:
            task.status = TaskStatus.ERROR
            task.error = "browser-use engine not available"
            return task
        self._status = EngineStatus.RUNNING
        try:
            agent = self._Agent(task=task.prompt, llm=self._llm, browser=self._browser)
            import time
            import base64

            async def on_step_end(agent_instance):
                """Capture and broadcast screenshot after each step for in-app live view."""
                if not self.on_screenshot:
                    return
                b64_img = None
                try:
                    from browser_use.browser.events import ScreenshotEvent
                    event = agent_instance.browser_session.event_bus.dispatch(
                        ScreenshotEvent(full_page=False)
                    )
                    await event
                    result = await event.event_result(raise_if_any=False, raise_if_none=False)
                    if result is not None:
                        if isinstance(result, bytes):
                            b64_img = base64.b64encode(result).decode("utf-8")
                        elif isinstance(result, str):
                            b64_img = result
                        else:
                            b64_img = getattr(result, "image", None) or (base64.b64encode(result).decode("utf-8") if result else None)
                except Exception as e:
                    logging.debug("Live view ScreenshotEvent: %s", e)
                # Fallback: CDP Page.captureScreenshot directly
                if not b64_img:
                    try:
                        from cdp_use.cdp.page import CaptureScreenshotParameters
                        session = agent_instance.browser_session
                        t = session.get_focused_target()
                        if not t or getattr(t, "target_type", "") not in ("page", "tab"):
                            page_targets = session.get_page_targets()
                            t = page_targets[-1] if page_targets else None
                        if t:
                            cdp = await session.get_or_create_cdp_session(t.target_id, focus=True)
                            params = CaptureScreenshotParameters(format="png", captureBeyondViewport=False)
                            r = await cdp.cdp_client.send.Page.captureScreenshot(params=params, session_id=cdp.session_id)
                            if r and r.get("data"):
                                b64_img = r["data"]
                    except Exception as e:
                        logging.debug("Live view CDP fallback: %s", e)
                if b64_img:
                    self.on_screenshot(b64_img)

            t0 = time.monotonic()
            logging.info("browser-use: starting agent for task '%s'", task.prompt[:80])
            history = await agent.run(
                max_steps=min(get_settings().max_actions_per_task, 25),
                on_step_end=on_step_end,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)

            # Extract final result — browser-use returns None for action tasks
            final = None
            try:
                fr = getattr(history, "final_result", None)
                if callable(fr):
                    final = fr()
                elif fr is not None:
                    final = fr
            except Exception:
                pass

            # Extract token usage and step details from browser-use history
            total_in = 0; total_out = 0; n_steps = 0
            step_summaries = []
            try:
                steps = getattr(history, "history", []) or []
                n_steps = len(steps)
                for i, step in enumerate(steps):
                    usage = getattr(step, "token_usage", None) or getattr(step, "usage", None)
                    if usage:
                        total_in += getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0
                        total_out += getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0
                    # Log each step's action for debugging
                    action = getattr(step, "action", None)
                    result = getattr(step, "result", None)
                    action_str = str(action)[:200] if action else "?"
                    result_str = str(result)[:200] if result else ""
                    logging.info("browser-use step %d/%d: %s -> %s", i+1, n_steps, action_str, result_str)
                    # Build human-readable step summary
                    if action:
                        step_summaries.append(f"Step {i+1}: {action_str}")
            except Exception as e:
                logging.debug("browser-use step extraction error: %s", e)

            # Build final summary — if final_result is None, summarize what steps were taken
            if final and str(final).strip() and str(final).strip() != "None":
                summary_text = str(final)
            elif step_summaries:
                summary_text = f"Completed {n_steps} steps:\n" + "\n".join(step_summaries[-5:])  # show last 5 steps
                if n_steps > 5:
                    summary_text = f"Completed {n_steps} steps (showing last 5):\n" + "\n".join(step_summaries[-5:])
            else:
                summary_text = f"Task completed in {n_steps} steps ({duration_ms}ms)"

            logging.info("browser-use: finished in %d steps, %dms. Result: %s", n_steps, duration_ms, summary_text[:200])

            # Estimate cost: GPT-4o via OpenRouter ~$2.5/M in, ~$10/M out
            cost = (total_in * 2.5 / 1_000_000) + (total_out * 10.0 / 1_000_000)
            task.result = TaskResult(
                summary=summary_text[:5000],
                total_steps=n_steps,
                total_duration_ms=duration_ms,
                tokens_in=total_in,
                tokens_out=total_out,
                estimated_cost_usd=round(cost, 4),
                engine_used=self.name.value,
            )
            task.status = TaskStatus.COMPLETE
        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = str(e)
        finally:
            self._status = EngineStatus.AVAILABLE
        task.updated_at = datetime.utcnow()
        return task

class OpenClawEngine(EngineBase):
    name = EngineName.OPENCLAW
    display_name = "OpenClaw"

    def __init__(self):
        self._status = EngineStatus.STOPPED
        self._openclaw_bin = None
        self._http_client = None
        self._gateway_proc = None
        self._node_version = None

    async def initialize(self) -> None:
        import shutil
        self._openclaw_bin = shutil.which("openclaw") or shutil.which("openclaw.cmd")
        if not self._openclaw_bin:
            self._status = EngineStatus.NOT_INSTALLED
            self._error_hint = "Requires Node.js >= 22. Click Install or run: npm install -g openclaw@latest"
            return
        # Check Node.js version — OpenClaw requires >= 22
        try:
            import subprocess as _sp
            node_out = _sp.check_output(["node", "--version"], timeout=5, text=True, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)).strip()
            self._node_version = node_out
            major = int(node_out.lstrip("v").split(".")[0])
            if major < 22:
                self._status = EngineStatus.ERROR
                self._error_hint = f"OpenClaw requires Node.js >= 22, found {node_out}. Update Node.js to use this engine."
                logging.warning("OpenClaw: Node.js %s too old (need >= 22)", node_out)
                return
        except Exception as e:
            self._status = EngineStatus.ERROR
            self._error_hint = f"Cannot check Node.js version: {e}"
            return
        settings = get_settings()
        port = settings.openclaw_gateway_port
        import httpx
        self._http_client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=180.0)
        self._status = EngineStatus.AVAILABLE
        self._error_hint = ""
        logging.info("OpenClaw engine initialized (binary=%s, node=%s, port=%d)", self._openclaw_bin, self._node_version, port)

    async def _ensure_gateway(self) -> bool:
        """Check if OpenClaw gateway is running; start it if not."""
        if not self._http_client:
            return False
        # Try connecting to the gateway root (serves web UI)
        try:
            resp = await self._http_client.get("/", timeout=3.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        # Try the /v1 endpoint as alternate health check
        try:
            resp = await self._http_client.get("/v1/models", timeout=3.0)
            if resp.status_code in (200, 401):  # 401 = running but needs auth
                return True
        except Exception:
            pass
        # Gateway not running — try to start it
        if not self._openclaw_bin:
            return False
        import subprocess
        env = dict(**os.environ)
        settings = get_settings()
        if settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        if settings.openai_api_key:
            env["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.openrouter_api_key:
            env["OPENROUTER_API_KEY"] = settings.openrouter_api_key
        try:
            logging.info("Starting OpenClaw gateway...")
            self._gateway_proc = subprocess.Popen(
                [self._openclaw_bin, "gateway", "start"],
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Poll for gateway readiness
            for _ in range(30):
                await asyncio.sleep(1)
                try:
                    resp = await self._http_client.get("/", timeout=3.0)
                    if resp.status_code == 200:
                        logging.info("OpenClaw gateway started successfully")
                        return True
                except Exception:
                    continue
            logging.warning("OpenClaw gateway did not become ready after 30s")
        except Exception as e:
            logging.warning("Failed to start OpenClaw gateway: %s", e)
        return False

    async def run_task(self, task: Task) -> Task:
        if self._status != EngineStatus.AVAILABLE:
            task.status = TaskStatus.ERROR
            task.error = f"OpenClaw engine not available ({self._error_hint or 'unknown'})"
            return task
        if not await self._ensure_gateway():
            task.status = TaskStatus.ERROR
            task.error = "OpenClaw gateway not responding. Start it with: openclaw gateway start"
            return task
        self._status = EngineStatus.RUNNING
        t0 = time.monotonic()
        try:
            settings = get_settings()
            headers = {}
            if settings.openclaw_api_key:
                headers["Authorization"] = f"Bearer {settings.openclaw_api_key}"
            # Use OpenAI-compatible chat completions endpoint
            payload = {
                "model": "openclaw",
                "messages": [{"role": "user", "content": task.prompt}],
                "stream": False,
            }
            resp = await self._http_client.post(
                "/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            # Parse OpenAI-compatible response
            content = "Task completed"
            total_in = 0
            total_out = 0
            try:
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", content)
                usage = data.get("usage", {})
                total_in = usage.get("prompt_tokens", 0)
                total_out = usage.get("completion_tokens", 0)
            except Exception:
                # Fallback: try flat format
                content = data.get("content", data.get("message", content))
            duration_ms = int((time.monotonic() - t0) * 1000)
            # Estimate cost (depends on which model OpenClaw uses internally)
            cost = (total_in * 3.0 / 1_000_000) + (total_out * 15.0 / 1_000_000)
            task.result = TaskResult(
                summary=str(content)[:5000],
                total_duration_ms=duration_ms,
                tokens_in=total_in,
                tokens_out=total_out,
                estimated_cost_usd=round(cost, 4),
                engine_used=self.name.value,
            )
            task.status = TaskStatus.COMPLETE
        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = str(e)
        finally:
            self._status = EngineStatus.AVAILABLE
        task.updated_at = datetime.utcnow()
        return task

    async def stop(self):
        if self._gateway_proc and self._gateway_proc.poll() is None:
            self._gateway_proc.terminate()
        if self._http_client:
            await self._http_client.aclose()
        self._status = EngineStatus.STOPPED

    async def get_status(self):
        return self._status

# ---------------------------------------------------------------------------
# Computer-use engine (desktop control via Anthropic computer-use tool)
# ---------------------------------------------------------------------------

DESKTOP_KEYWORDS = [
    # OS elements
    "desktop", "taskbar", "start menu", "system tray", "notification",
    "folder", "file manager", "explorer", "finder", "dock", "spotlight",
    "system preferences", "settings", "control panel",
    # Office / productivity
    "app", "application", "notepad", "excel", "word", "powerpoint",
    "libreoffice", "calc", "writer", "outlook", "onenote",
    # Terminal
    "terminal", "command prompt", "powershell", "cmd", "wsl", "bash",
    # Messaging / communication
    "telegram", "discord", "slack", "whatsapp", "signal", "skype",
    "teams", "zoom", "webex", "google meet",
    # Browsers (when referenced as desktop apps)
    "chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari",
    # Media
    "spotify", "vlc", "media player", "foobar", "winamp", "itunes",
    # Dev tools
    "vscode", "vs code", "visual studio", "intellij", "pycharm",
    "sublime", "atom", "cursor",
    # Gaming / misc
    "steam", "epic games", "obs", "obs studio",
    # Knowledge / notes
    "notion", "obsidian", "evernote", "todoist", "trello",
    # Window actions
    "drag", "window", "minimize", "maximize", "close window",
    "screenshot", "snipping tool", "paint",
]

SYSTEM_PROMPT_TEMPLATE = """\
You are a desktop automation agent controlling a Windows PC.
The screen is {scaled_width}x{scaled_height} pixels.

================================================================
MANDATORY REASONING PROTOCOL
================================================================
Before choosing ANY action, you MUST write your reasoning in this format:

[OBSERVE] What I see on screen right now (list visible windows, apps, UI elements)
[GOAL] The specific sub-goal I need to accomplish next
[PLAN] Which decision path I will follow (reference the trees below)
[ACTION] The exact action I will take and why

Do NOT skip this reasoning. It makes your actions more accurate.

================================================================
DECISION TREE 1: FINDING OR SWITCHING TO AN APP
================================================================
For ANY app you need to interact with, follow this EXACT order.
STOP at the first level that succeeds.

LEVEL 1 — IS THE APP ALREADY VISIBLE ON SCREEN?
  Scan the entire screenshot for the app window. Visual fingerprints:

  Telegram:
    - Blue header bar with app name
    - Chat list on the left side
    - Message input at BOTTOM with placeholder "Write a message..."
    - If you see "Write a message..." anywhere, Telegram is open

  Discord:
    - Dark gray/purple UI
    - Channel sidebar on the left
    - Message box at bottom with "Message #channel" placeholder

  Slack:
    - Purple/white UI with channel sidebar
    - Message composer at bottom of conversation

  WhatsApp:
    - Green header bar
    - Chat list or conversation view

  Browser (Chrome / Edge / Firefox):
    - Tab bar at the very top
    - Address bar just below tabs
    - Webpage content area

  VS Code / Cursor:
    - Dark sidebar with file tree on left
    - Editor tabs across the top
    - Integrated terminal at the bottom

  File Explorer:
    - Navigation breadcrumb at top
    - Folder tree on left pane
    - File/folder list on right pane

  Spotify:
    - Dark UI with green accent color
    - Playlist sidebar on left
    - Playback controls at bottom

  -> If the app is VISIBLE: interact with it directly.
     DO NOT search for it, re-open it, or navigate to it.

LEVEL 2 — IS IT ON THE TASKBAR?
  Look at the BOTTOM of the screen. The Windows taskbar shows:
  - Pinned app icons (always visible)
  - Running app icons (have a thin line/underline beneath them)
  -> If ON TASKBAR: single-click the icon to bring app to foreground.
     Then WAIT for the next screenshot to confirm it appeared.

LEVEL 3 — USE WINDOWS SEARCH (LAST RESORT ONLY)
  -> Click the search icon on the taskbar or press the Windows key.
  -> Type the app name, wait for results, click the matching result.
  -> Only use this if the app is NOT visible AND NOT on the taskbar.

================================================================
DECISION TREE 2: MESSAGING APPS (Telegram, Discord, Slack, etc.)
================================================================
Once the messaging app is in the foreground:

Step 1: Is the correct conversation/chat already open?
  HOW TO CHECK: Read the FOREGROUND WINDOW line in the SYSTEM INFO section.
  The window title typically contains the chat/channel name.
  Examples:
    - "Agent intelligence – (351553)" means Telegram has "Agent intelligence" open
    - "$BOOTS Community – (351556)" means a DIFFERENT chat is open
    - "#general - Discord" means Discord has the #general channel open
  -> If the correct chat IS open in the window title: skip to Step 3
  -> If a DIFFERENT chat is open or you're unsure: go to Step 2

Step 2: Navigate to the correct conversation using SEARCH
  CRITICAL: NEVER click on chat items in the sidebar list — they are NOT in
  the INTERACTIVE ELEMENTS list and coordinate clicks WILL miss. You MUST
  use the search bar (look for the "Search" element in INTERACTIVE ELEMENTS):
  1. Use click_element on the "Search" Edit field
  2. Type the chat/channel name
  3. Wait for search results
  4. Click the first matching result

  For Telegram:
    1. Click the search bar at the top of Telegram (or press Escape first
       to clear any current state, then click the search field)
    2. Type the chat/group name
    3. Wait for search results to appear
    4. Click the FIRST matching result
    5. Wait for the conversation to load and verify via SYSTEM INFO

  For Discord:
    1. Press Ctrl+K to open Quick Switcher
    2. Type the channel name
    3. Click the matching result

  For Slack:
    1. Press Ctrl+K to open Quick Switcher
    2. Type the channel/person name
    3. Click the matching result

Step 3: Type and send the message
  - Click the message input field at the BOTTOM of the conversation
    (look for placeholder text like "Write a message...", "Type a message...",
     "Message #channel", etc.)
  - Type the message text
  - Press Enter to send (unless the task says NOT to send)

================================================================
DECISION TREE 3: BROWSER TASKS
================================================================
Step 1: Is a browser already open?
  -> If YES: click the address bar (or press Ctrl+L), type the URL, press Enter
  -> If NO: follow Decision Tree 1 to open a browser first

Step 2: Do NOT close or rearrange existing tabs unless the task requires it.

================================================================
HOW TO USE SYSTEM INFO
================================================================
Each tool result includes SYSTEM INFO from Windows accessibility APIs.
This is MORE RELIABLE than trying to read text from the screenshot.

- FOREGROUND WINDOW: Tells you the title of the currently focused window.
  Use this to determine WHICH app and WHICH chat/document is active.
- VISIBLE WINDOWS: Lists all open windows. Use this to determine what's available.
- RUNNING APPS: Lists running processes. Use this to know what's installed/running.

ALWAYS check SYSTEM INFO before deciding your next action.

================================================================
ANTI-PATTERNS — NEVER DO THESE
================================================================
- NEVER click on chat names in messaging app sidebars (Telegram, Discord, Slack).
  Sidebar chat items are NOT accessible UI elements and clicking by coordinates
  WILL hit the wrong chat. ALWAYS use the Search field instead (click_element on
  the "Search" element, then type the chat name).
- NEVER search for an app that is already visible on screen
- NEVER re-open an app that is already in the foreground
- NEVER type text without first clicking the target input field
- NEVER use the Start menu / search if the app icon is on the taskbar
- NEVER close, minimize, or move windows you don't need to touch
- NEVER take more than 3 actions to reach an input field already visible on screen
- NEVER repeat the same failed action — try a different approach
- NEVER request a "screenshot" action — you already receive a fresh screenshot
  after every action automatically

================================================================
CLICKING UI ELEMENTS — ACCESSIBILITY-FIRST
================================================================
Each tool result includes an INTERACTIVE ELEMENTS list showing clickable
UI elements discovered via the Windows accessibility API. Each element has:
  [id] Type: "Name" at (x,y)

ALWAYS PREFER using click_element over coordinate-based clicks:
  action="click_element", element_id=<id>

This is FAR MORE RELIABLE than guessing pixel coordinates from screenshots.
Use coordinate-based clicks (left_click) ONLY when:
  - The target is NOT in the INTERACTIVE ELEMENTS list
  - You need to click a specific pixel location (e.g., inside a canvas)

Example workflow for Telegram:
  1. See element [5] Edit: "Search" at (556,83)
  2. Use action="click_element", element_id=5
  3. Then action="type", text="Agent Intelligence"
  4. Wait for results, find the matching element, click_element again

================================================================
CORE RULES
================================================================
1. ONE action per turn. Examine the result screenshot before the next action.
2. PREFER click_element over coordinate clicks for ALL named UI elements.
3. Be efficient — take the FEWEST actions possible to complete the task.
4. If an action didn't work (screenshot looks the same), try a DIFFERENT approach.
5. When the task is complete, respond with a text summary (no tool call).
6. TRUST the SYSTEM INFO and INTERACTIVE ELEMENTS over what you see in screenshots.

================================================================
SCREENSHOT
================================================================
Each turn you receive ONE full-screen screenshot at {scaled_width}x{scaled_height}.
ALL coordinate-based actions (clicks, drags) use coordinates from this image.
Use the INTERACTIVE ELEMENTS list to read element names/text reliably.
"""

class ComputerUseEngine(EngineBase):
    def __init__(self):
        self._status = EngineStatus.STOPPED
        self._client = None
        self._model = ""
        self._screen_width = 0
        self._screen_height = 0
        self._scaled_width = 0
        self._scaled_height = 0
        self.on_screenshot = None
        self._last_ui_elements: list[dict] = []  # cached element list for click_element
        self._cancel_requested = False

    @property
    def name(self) -> EngineName:
        return EngineName.COMPUTER_USE
    @property
    def display_name(self) -> str:
        return "computer-use"
    @property
    def description(self) -> str:
        return "Full desktop control via mouse, keyboard, and screenshots."
    def _capabilities(self) -> list[str]:
        return ["mouse", "keyboard", "screenshot", "desktop_control", "type", "click"]

    async def initialize(self) -> None:
        self._status = EngineStatus.STARTING
        settings = get_settings()
        try:
            import anthropic as _anth; import pyautogui; import mss as _mss; from PIL import Image as _img  # noqa
        except ImportError as e:
            self._status = EngineStatus.NOT_INSTALLED
            logging.warning(f"computer-use deps not installed: {e}")
            return
        try:
            import ctypes as _ct
            _ct.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
        try:
            self._screen_width, self._screen_height = pyautogui.size()
        except Exception as e:
            self._status = EngineStatus.ERROR
            logging.error(f"Cannot detect screen: {e}")
            return
        max_w, max_h = settings.computer_use_max_screen_width, settings.computer_use_max_screen_height
        scale = min(max_w / self._screen_width, max_h / self._screen_height, 1.0)
        self._scaled_width = int(self._screen_width * scale)
        self._scaled_height = int(self._screen_height * scale)
        self._model = settings.computer_use_model
        self._is_openrouter = False
        import anthropic
        if settings.has_anthropic_key():
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        elif settings.has_openrouter_key():
            # OpenRouter's "Anthropic Skin" -- base_url must be /api (not /api/v1)
            self._client = anthropic.Anthropic(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api")
            self._is_openrouter = True
            # OpenRouter uses its own model naming convention
            if "/" not in self._model:
                self._model = f"anthropic/{self._model}"
        else:
            self._status = EngineStatus.ERROR
            logging.warning("computer-use requires ANTHROPIC_API_KEY or OPENROUTER_API_KEY")
            return
        self._status = EngineStatus.AVAILABLE
        logging.info(f"computer-use engine initialized (model={self._model}, scaled={self._scaled_width}x{self._scaled_height})")

    async def _take_screenshot(self) -> str:
        import mss as mss_mod; from PIL import Image; import io as _io
        loop = asyncio.get_event_loop()
        def _cap():
            with mss_mod.mss() as sct:
                raw = sct.grab(sct.monitors[1])
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                if img.width > self._scaled_width or img.height > self._scaled_height:
                    img = img.resize((self._scaled_width, self._scaled_height), Image.LANCZOS)
                buf = _io.BytesIO()
                img.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("utf-8")
        return await loop.run_in_executor(None, _cap)

    async def _get_foreground_window_rect(self) -> tuple[int, int, int, int] | None:
        """Get the foreground window bounding box in raw screen pixels."""
        loop = asyncio.get_event_loop()
        def _get():
            import ctypes
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            try:
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if not hwnd: return None
                rect = RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)): return None
                left, top = max(0, rect.left), max(0, rect.top)
                right, bottom = min(self._screen_width, rect.right), min(self._screen_height, rect.bottom)
                w, h = right - left, bottom - top
                if w <= 0 or h <= 0: return None
                if w >= self._screen_width * 0.95 and h >= self._screen_height * 0.95: return None
                if w < 200 or h < 150: return None
                return (left, top, right, bottom)
            except Exception: return None
        try: return await loop.run_in_executor(None, _get)
        except Exception: return None

    async def _take_window_crop(self, rect: tuple[int, int, int, int], max_dim: int = 1280) -> str | None:
        """Capture the foreground window region at higher resolution."""
        import mss as mss_mod; from PIL import Image
        left, top, right, bottom = rect
        loop = asyncio.get_event_loop()
        def _capture():
            try:
                with mss_mod.mss() as sct:
                    monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
                    raw = sct.grab(monitor)
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                    w, h = img.size
                    if max(w, h) > max_dim:
                        scale = max_dim / max(w, h)
                        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    return base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception: return None
        try: return await loop.run_in_executor(None, _capture)
        except Exception: return None

    async def _get_ui_elements(self) -> list[dict]:
        """Enumerate interactive UI elements from the foreground window using Windows UIA."""
        loop = asyncio.get_event_loop()
        def _enumerate():
            try:
                import ctypes
                from pywinauto import Desktop
                d = Desktop(backend='uia')
                user32 = ctypes.windll.user32
                fg_hwnd = user32.GetForegroundWindow()
                if not fg_hwnd:
                    return []
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(fg_hwnd, buf, 512)
                fg_title = buf.value
                # Find matching pywinauto window
                target_win = None
                for w in d.windows():
                    try:
                        if w.window_text() == fg_title:
                            target_win = w
                            break
                    except:
                        pass
                if not target_win:
                    # Fallback: try partial match
                    for w in d.windows():
                        try:
                            wt = w.window_text()
                            if wt and fg_title and fg_title[:20] in wt:
                                target_win = w
                                break
                        except:
                            pass
                if not target_win:
                    return []
                elements = []
                clickable_types = {'Button', 'Edit', 'MenuItem', 'ListItem', 'TabItem',
                                   'ComboBox', 'CheckBox', 'RadioButton', 'Hyperlink',
                                   'TreeItem', 'DataItem'}
                for c in target_win.descendants(depth=8):
                    try:
                        ct = c.element_info.control_type
                        if ct not in clickable_types:
                            continue
                        r = c.rectangle()
                        if r.width() < 10 or r.height() < 10:
                            continue
                        name = (c.window_text() or '').strip()[:80]
                        if not name:
                            continue
                        # Convert to scaled coordinates
                        cx = (r.left + r.right) // 2
                        cy = (r.top + r.bottom) // 2
                        # Skip elements with invalid/offscreen coordinates
                        if cx <= 0 or cy <= 0 or cx >= self._screen_width or cy >= self._screen_height:
                            continue
                        # Scale if needed
                        sx = int(cx * self._scaled_width / self._screen_width) if self._screen_width != self._scaled_width else cx
                        sy = int(cy * self._scaled_height / self._screen_height) if self._screen_height != self._scaled_height else cy
                        elements.append({
                            'id': len(elements),
                            'type': ct,
                            'name': name,
                            'center_x': sx,
                            'center_y': sy,
                            'raw_x': cx,
                            'raw_y': cy,
                        })
                        if len(elements) >= 40:
                            break
                    except:
                        pass
                return elements
            except Exception as exc:
                logging.debug("UI element enumeration failed: %s", exc)
                return []
        try:
            return await loop.run_in_executor(None, _enumerate)
        except Exception:
            return []

    def _format_ui_elements(self, elements: list[dict]) -> str:
        """Format UI element list as text for the model."""
        if not elements:
            return ""
        lines = ["INTERACTIVE ELEMENTS (use click_element action with element_id for reliable clicking):"]
        for el in elements:
            lines.append(f"  [{el['id']}] {el['type']}: \"{el['name']}\" at ({el['center_x']},{el['center_y']})")
        return "\n".join(lines)

    async def _execute_action(self, tool_input: dict) -> str:
        import pyautogui; loop = asyncio.get_event_loop()
        action = tool_input.get("action", "")
        def _sc(coord):
            x, y = coord
            sx = max(0, min(int(x * self._screen_width / self._scaled_width), self._screen_width - 1))
            sy = max(0, min(int(y * self._screen_height / self._scaled_height), self._screen_height - 1))
            return sx, sy
        if action == "screenshot":
            return "screenshot_taken"
        elif action == "mouse_move":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.moveTo(rx, ry, duration=0.3))
            return f"mouse_moved_{rx}_{ry}"
        elif action == "left_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.click(rx, ry))
            return f"clicked_{rx}_{ry}"
        elif action == "right_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.rightClick(rx, ry))
            return f"right_clicked_{rx}_{ry}"
        elif action == "double_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.doubleClick(rx, ry))
            return f"double_clicked_{rx}_{ry}"
        elif action == "middle_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.middleClick(rx, ry))
            return f"middle_clicked_{rx}_{ry}"
        elif action == "left_click_drag":
            start = _sc(tool_input["start_coordinate"]); end = _sc(tool_input["coordinate"])
            def _d():
                pyautogui.moveTo(start[0], start[1]); pyautogui.drag(end[0]-start[0], end[1]-start[1], duration=0.5)
            await loop.run_in_executor(None, _d)
            return f"dragged_{start}_to_{end}"
        elif action == "type":
            text = tool_input.get("text", "")
            def _t():
                if text.isascii(): pyautogui.write(text, interval=0.02)
                else:
                    import pyperclip; pyperclip.copy(text); pyautogui.hotkey("ctrl", "v")
            await loop.run_in_executor(None, _t)
            return f"typed_{len(text)}_chars"
        elif action == "key":
            kc = tool_input.get("text", "")
            def _k():
                keys = [k.strip() for k in kc.split("+")]
                pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
            await loop.run_in_executor(None, _k)
            return f"pressed_{kc}"
        elif action == "cursor_position":
            pos = pyautogui.position()
            return f"cursor_at_{pos.x}_{pos.y}"
        elif action == "scroll":
            rx, ry = _sc(tool_input.get("coordinate", [self._scaled_width//2, self._scaled_height//2]))
            clicks = tool_input.get("amount", 3)
            await loop.run_in_executor(None, lambda: pyautogui.scroll(clicks, x=rx, y=ry))
            return f"scrolled_{clicks}"
        elif action == "click_element":
            eid = tool_input.get("element_id")
            if eid is None:
                return "error: element_id required"
            eid = int(eid)
            if eid < 0 or eid >= len(self._last_ui_elements):
                return f"error: element_id {eid} out of range (0-{len(self._last_ui_elements)-1})"
            el = self._last_ui_elements[eid]
            rx, ry = el['raw_x'], el['raw_y']
            logging.info("click_element [%d] '%s' at raw (%d,%d)", eid, el['name'], rx, ry)
            await loop.run_in_executor(None, lambda: pyautogui.click(rx, ry))
            return f"clicked_element_{eid}_{el['name']}_at_{rx}_{ry}"
        return f"unknown_{action}"

    @staticmethod
    def _screenshots_similar(b64_a: str, b64_b: str, threshold: int = 5) -> bool:
        """Compare two base64 screenshots using average perceptual hash."""
        from PIL import Image
        def _avg_hash(b64):
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            img = img.resize((8, 8), Image.LANCZOS).convert("L")
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            return sum(1 << i for i, p in enumerate(pixels) if p >= avg)
        return bin(_avg_hash(b64_a) ^ _avg_hash(b64_b)).count("1") <= threshold

    async def _describe_screen(self) -> str:
        """Use Windows APIs to describe visible windows as text."""
        loop = asyncio.get_event_loop()
        def _gather():
            import subprocess as _sp
            lines = []
            try:
                ps = "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object ProcessName, MainWindowTitle | Format-Table -AutoSize -HideTableHeaders"
                out = _sp.check_output(["powershell", "-NoProfile", "-Command", ps], timeout=3, text=True, creationflags=_sp.CREATE_NO_WINDOW)
                windows = [w.strip() for w in out.strip().splitlines() if w.strip()]
                if windows:
                    lines.append("VISIBLE WINDOWS:")
                    for w in windows[:15]:
                        lines.append(f"  - {w}")
            except Exception: pass
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if buf.value:
                    lines.append(f"\nFOREGROUND WINDOW: {buf.value}")
            except Exception: pass
            try:
                ps2 = "Get-Process -Name Telegram,Discord,Slack,Spotify,chrome,msedge,firefox,Code,Telegram.Desktop -ErrorAction SilentlyContinue | Select-Object ProcessName -Unique | Format-Table -HideTableHeaders"
                out2 = _sp.check_output(["powershell", "-NoProfile", "-Command", ps2], timeout=3, text=True, creationflags=_sp.CREATE_NO_WINDOW)
                apps = [a.strip() for a in out2.strip().splitlines() if a.strip()]
                if apps:
                    lines.append(f"\nRUNNING APPS: {', '.join(apps)}")
            except Exception: pass
            return "\n".join(lines) if lines else ""
        try:
            return await loop.run_in_executor(None, _gather)
        except Exception:
            return ""

    async def _bring_app_to_foreground(self, app_keyword: str) -> bool:
        """Try to bring a window matching app_keyword to the foreground. Returns True if successful."""
        loop = asyncio.get_event_loop()
        def _focus():
            try:
                import ctypes
                from pywinauto import Desktop
                d = Desktop(backend='uia')
                for w in d.windows():
                    try:
                        title = w.window_text()
                        if app_keyword.lower() in title.lower():
                            w.set_focus()
                            import time as _t; _t.sleep(0.5)
                            return True
                    except:
                        pass
                # Fallback: try win32 backend for apps like Telegram
                d2 = Desktop(backend='win32')
                for w in d2.windows():
                    try:
                        title = w.window_text()
                        if app_keyword.lower() in title.lower():
                            w.set_focus()
                            import time as _t; _t.sleep(0.5)
                            return True
                    except:
                        pass
            except Exception as exc:
                logging.debug("Failed to bring %s to foreground: %s", app_keyword, exc)
            return False
        try:
            return await loop.run_in_executor(None, _focus)
        except Exception:
            return False

    def _detect_target_app(self, prompt: str) -> str | None:
        """Detect which app the task is targeting from the prompt text."""
        prompt_lower = prompt.lower()
        app_keywords = {
            'telegram': 'Telegram',
            'discord': 'Discord',
            'slack': 'Slack',
            'whatsapp': 'WhatsApp',
            'signal': 'Signal',
            'chrome': 'Chrome',
            'brave': 'Brave',
            'firefox': 'Firefox',
            'edge': 'Edge',
            'spotify': 'Spotify',
            'vs code': 'Code',
            'vscode': 'Code',
            'cursor': 'Cursor',
            'notepad': 'Notepad',
        }
        for keyword, app_name in app_keywords.items():
            if keyword in prompt_lower:
                return app_name
        return None

    async def run_task(self, task: Task) -> Task:
        if self._status != EngineStatus.AVAILABLE:
            task.status = TaskStatus.ERROR; task.error = "computer-use engine not available"; return task
        self._status = EngineStatus.RUNNING
        self._cancel_requested = False
        start = time.monotonic()
        settings = get_settings()
        max_steps = min(settings.max_actions_per_task, 50)
        delay = settings.computer_use_action_delay_ms / 1000.0
        try:
            # Pre-action: bring target app to foreground automatically
            target_app = self._detect_target_app(task.prompt)
            focused = False
            if target_app:
                focused = await self._bring_app_to_foreground(target_app)
                if focused:
                    logging.info("Pre-action: brought '%s' to foreground", target_app)
                    await asyncio.sleep(1.0)  # Let Windows fully switch focus
                    # Focus again to be sure
                    await self._bring_app_to_foreground(target_app)
                    await asyncio.sleep(0.5)
                else:
                    logging.info("Pre-action: could not find '%s' window", target_app)
            init_ss = await self._take_screenshot()
            if self.on_screenshot:
                try: self.on_screenshot(init_ss)
                except: pass
            screen_desc = await self._describe_screen()
            if screen_desc:
                logging.info("Screen description:\n%s", screen_desc)
            # Native Anthropic computer-use tool (direct API only)
            native_tool = [{"type": "computer_20241022", "name": "computer", "display_width_px": self._scaled_width, "display_height_px": self._scaled_height, "display_number": 1}]
            # Standard function tool for OpenRouter compatibility
            func_tool = [{"name": "computer", "description": f"Control the computer screen ({self._scaled_width}x{self._scaled_height}). Returns a screenshot and a list of interactive UI elements after every action. PREFER click_element over coordinate-based clicks for buttons, fields, and other named UI elements.", "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["screenshot", "mouse_move", "left_click", "right_click", "double_click", "middle_click", "left_click_drag", "type", "key", "cursor_position", "scroll", "click_element"], "description": "The action to perform. Use 'click_element' with 'element_id' to click a UI element by its ID from the INTERACTIVE ELEMENTS list — this is MORE RELIABLE than coordinate-based clicks."}, "coordinate": {"type": "array", "items": {"type": "integer"}, "description": "[x, y] pixel coordinates for mouse actions (not needed for click_element)"}, "start_coordinate": {"type": "array", "items": {"type": "integer"}, "description": "[x, y] start coordinates for drag"}, "text": {"type": "string", "description": "Text to type, or key combo like 'ctrl+c'"}, "amount": {"type": "integer", "description": "Scroll amount (positive=up, negative=down)"}, "element_id": {"type": "integer", "description": "ID of the UI element to click (from the INTERACTIVE ELEMENTS list). Use with action='click_element'."}}, "required": ["action"]}}]
            tools = native_tool if not self._is_openrouter else func_tool
            sys_prompt = SYSTEM_PROMPT_TEMPLATE.format(scaled_width=self._scaled_width, scaled_height=self._scaled_height)
            ctx = ""
            if target_app and focused:
                ctx += f"IMPORTANT: {target_app} has ALREADY been brought to the foreground for you. It is the active window. Do NOT click the taskbar or try to switch to it — just interact with its UI elements directly.\n\n"
            if screen_desc:
                ctx += f"SYSTEM INFO (from Windows accessibility APIs):\n{screen_desc}\n\nUse this info to understand what is ALREADY open. If the target app is listed in VISIBLE WINDOWS or FOREGROUND WINDOW, it is already on screen — interact with it directly."
            # Enumerate interactive UI elements
            self._last_ui_elements = await self._get_ui_elements()
            ui_text = self._format_ui_elements(self._last_ui_elements)
            if ui_text:
                ctx += f"\n\n{ui_text}"
                logging.info("UI elements found: %d", len(self._last_ui_elements))
            ctx += "\n\nComplete the task. PREFER click_element over coordinate-based clicks."
            content_blocks = [
                {"type": "text", "text": task.prompt},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": init_ss}},
                {"type": "text", "text": ctx},
            ]
            messages = [{"role": "user", "content": content_blocks}]
            step_count = 0; total_in = 0; total_out = 0; final_text = ""; prev_ss = init_ss
            while step_count < max_steps:
                if self._cancel_requested:
                    logging.info("Task cancelled by user at step %d", step_count)
                    final_text = f"Task stopped by user after {step_count} steps."
                    break
                api_kwargs = dict(model=self._model, max_tokens=4096, system=sys_prompt, tools=tools, messages=messages)
                if not self._is_openrouter:
                    api_kwargs["betas"] = ["computer-use-2024-10-22"]
                logging.info("Calling API (step %d, messages=%d)...", step_count + 1, len(messages))
                try:
                    resp = self._client.messages.create(**api_kwargs)
                except Exception as api_err:
                    logging.error("API call failed: %s", api_err)
                    raise
                total_in += resp.usage.input_tokens; total_out += resp.usage.output_tokens
                logging.info("API response: stop=%s, tokens_in=%d, tokens_out=%d", resp.stop_reason, total_in, total_out)
                tu_blocks = [b for b in resp.content if b.type == "tool_use"]
                txt_blocks = [b.text for b in resp.content if b.type == "text"]
                if txt_blocks:
                    final_text = "\n".join(txt_blocks)
                    for _tb in txt_blocks:
                        logging.info("computer-use reasoning (step %d): %s", step_count + 1, _tb[:500])
                if not tu_blocks: break
                tool_results = []
                for tb in tu_blocks:
                    action_name = tb.input.get("action", "")
                    is_ss_only = action_name == "screenshot"
                    if not is_ss_only:
                        step_count += 1
                    logging.info("computer-use step %d/%d: %s%s", step_count, max_steps, action_name or "?", " (free)" if is_ss_only else "")
                    if not is_ss_only:
                        # Re-focus target app before every action to prevent wrong-window clicks
                        if target_app and action_name in ("left_click", "right_click", "double_click", "click_element", "type", "key"):
                            await self._bring_app_to_foreground(target_app)
                            await asyncio.sleep(0.5)
                        await self._execute_action(tb.input)
                        await asyncio.sleep(delay)
                    # Re-focus target before screenshot so the model sees the right window
                    if target_app:
                        await self._bring_app_to_foreground(target_app)
                        await asyncio.sleep(0.5)
                    ss = await self._take_screenshot()
                    if self.on_screenshot:
                        try: self.on_screenshot(ss)
                        except: pass
                    step_desc = await self._describe_screen()
                    # Refresh UI elements after each action
                    self._last_ui_elements = await self._get_ui_elements()
                    ui_text = self._format_ui_elements(self._last_ui_elements)
                    hint = f"[Step {step_count} of {max_steps}]"
                    if step_desc:
                        hint += f"\n\nCURRENT SYSTEM STATE:\n{step_desc}"
                    if ui_text:
                        hint += f"\n\n{ui_text}"
                    rc = [{"type": "text", "text": hint}]
                    if not is_ss_only and prev_ss and self._screenshots_similar(prev_ss, ss):
                        rc.append({"type": "text", "text": "WARNING: The screenshot appears unchanged after your last action. The action may have had no effect. Consider trying a different approach."})
                        logging.warning("Stale screenshot detected at step %d", step_count)
                    rc.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ss}})
                    tool_results.append({"type": "tool_result", "tool_use_id": tb.id, "content": rc})
                    prev_ss = ss
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                if not final_text: final_text = f"Reached max step limit ({max_steps})."
            dur = int((time.monotonic() - start) * 1000)
            # Estimate cost: Sonnet 4 via OpenRouter ~$3/M in, ~$15/M out
            cost = (total_in * 3.0 / 1_000_000) + (total_out * 15.0 / 1_000_000)
            task.result = TaskResult(
                summary=(final_text or "Task completed.")[:5000],
                engine_used=EngineName.COMPUTER_USE.value,
                total_steps=step_count,
                total_duration_ms=dur,
                tokens_in=total_in,
                tokens_out=total_out,
                estimated_cost_usd=round(cost, 4),
            )
            task.status = TaskStatus.CANCELLED if self._cancel_requested else TaskStatus.COMPLETE
        except Exception as e:
            task.status = TaskStatus.ERROR; task.error = str(e)
        finally:
            self._status = EngineStatus.AVAILABLE
        task.updated_at = datetime.utcnow()
        return task

    async def execute_step(self, task, step):
        micro = Task(prompt=f"{step.action}: {step.target}", engine=EngineName.COMPUTER_USE)
        r = await self.run_task(micro)
        return {"summary": r.result.summary if r.result else "Done", "duration_ms": 0}
    def request_cancel(self):
        """Signal the running task to stop at the next loop iteration."""
        self._cancel_requested = True
        logging.info("Cancel requested for computer-use engine")
    async def stop(self):
        self._client = None; self._status = EngineStatus.STOPPED
    async def get_status(self):
        return self._status

# ---------------------------------------------------------------------------
# Task manager
# ---------------------------------------------------------------------------

class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._engines: dict[EngineName, EngineBase] = {}
        self._running = 0
        self._futures: dict[str, asyncio.Task] = {}
        self._broadcast: Callable | None = None
        self._load_tasks_from_db()

    def _load_tasks_from_db(self):
        try:
            conn = sqlite3.connect(Settings.db_path)
            c = conn.cursor()
            c.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100")
            for row in c.fetchall():
                res_val = json.loads(row[4]) if row[4] else None
                t = Task(
                    id=row[0], prompt=row[1], engine=row[2], 
                    status=TaskStatus(row[3]),
                    result=TaskResult(**res_val) if res_val else None,
                    error=row[5],
                    created_at=datetime.fromisoformat(row[6]),
                    updated_at=datetime.fromisoformat(row[7])
                )
                self._tasks[t.id] = t
            conn.close()
        except Exception as e:
            logging.error(f"Failed to load tasks from DB: {e}")

    def _save_task_to_db(self, task: Task):
        try:
            conn = sqlite3.connect(Settings.db_path)
            c = conn.cursor()
            res_json = json.dumps(task.result.dict()) if task.result else None
            c.execute("""INSERT OR REPLACE INTO tasks 
                         (id, prompt, engine, status, result, error, created_at, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                      (task.id, task.prompt, task.engine, task.status.value, 
                       res_json, task.error, task.created_at.isoformat(), task.updated_at.isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Failed to save task to DB: {e}")

    async def init_engines(self) -> None:
        for name in get_settings().enabled_engine_list():
            if name == EngineName.BROWSER_USE.value or name == "browser_use":
                e = BrowserUseEngine()
                e.on_screenshot = lambda img: asyncio.create_task(self._broadcast({"type": "live_view", "payload": {"image": img}})) if self._broadcast else None
                await e.initialize()
                self._engines[EngineName.BROWSER_USE] = e
            elif name == EngineName.OPENCLAW.value or name == "openclaw":
                e = OpenClawEngine()
                await e.initialize()
                self._engines[EngineName.OPENCLAW] = e
            elif name == EngineName.COMPUTER_USE.value or name == "computer_use":
                e = ComputerUseEngine()
                e.on_screenshot = lambda img: asyncio.create_task(self._broadcast({"type": "live_view", "payload": {"image": img}})) if self._broadcast else None
                await e.initialize()
                self._engines[EngineName.COMPUTER_USE] = e

    def _engine_for(self, preferred: EngineName, prompt: str = "") -> EngineBase | None:
        if preferred != EngineName.AUTO and preferred in self._engines:
            return self._engines[preferred]
        # Auto-select: desktop-sounding tasks prefer computer-use
        if prompt and any(kw in prompt.lower() for kw in DESKTOP_KEYWORDS):
            if EngineName.COMPUTER_USE in self._engines:
                return self._engines[EngineName.COMPUTER_USE]
        return (self._engines.get(EngineName.BROWSER_USE)
                or self._engines.get(EngineName.COMPUTER_USE)
                or self._engines.get(EngineName.OPENCLAW))

    async def submit(self, task: Task) -> Task:
        get_audit().log(AuditEvent(task_id=task.id, event_type="task_created", detail=task.prompt[:100]))
        self._tasks[task.id] = task
        if self._running < get_settings().max_concurrent_tasks:
            fut = asyncio.create_task(self._run(task))
            self._futures[task.id] = fut
        else:
            task.status = TaskStatus.PENDING
        self._save_task_to_db(task)
        return task

    async def _run(self, task: Task) -> None:
        self._running += 1
        task.status = TaskStatus.RUNNING
        task.updated_at = datetime.utcnow()
        self._save_task_to_db(task)
        if self._broadcast:
            await self._broadcast({"type": "task_update", "payload": task.model_dump(mode="json")})
        
        engine = self._engine_for(task.engine, prompt=task.prompt)
        if not engine:
            task.status = TaskStatus.ERROR
            task.error = "No engine available"
        else:
            task.engine = engine.name
            get_audit().log(AuditEvent(task_id=task.id, event_type="task_started", detail=engine.display_name))
            try:
                task = await engine.run_task(task)
            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                task.error = None
                logging.info("Task %s cancelled", task.id)
            get_audit().log(AuditEvent(task_id=task.id, event_type="task_completed" if task.status == TaskStatus.COMPLETE else "task_cancelled" if task.status == TaskStatus.CANCELLED else "task_error", detail=task.error or "ok"))

        self._running -= 1
        self._futures.pop(task.id, None)
        self._save_task_to_db(task)
        if self._broadcast:
            await self._broadcast({"type": "task_update", "payload": task.model_dump(mode="json")})

    async def remote_bridge_loop(self):
        """Background loop to poll for remote tasks from clawbridge.ai or custom URL."""
        if not Settings.remote_bridge_url:
            logging.info("Remote Bridge URL not set, skipping polling.")
            return

        logging.info(f"Starting Remote Bridge polling for Machine ID: {get_machine_id()}")
        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{Settings.remote_bridge_url}/api/bridge/tasks",
                        headers={
                            "X-Machine-ID": get_machine_id(),
                            "Authorization": f"Bearer {Settings.remote_auth_token}"
                        },
                        timeout=30
                    )
                    if resp.status_code == 200:
                        tasks_data = resp.json()
                        for t_data in tasks_data:
                            task = Task(
                                id=str(uuid.uuid4()),
                                prompt=t_data["prompt"],
                                engine=EngineName(t_data.get("engine", "auto")),
                                created_at=datetime.utcnow(),
                                updated_at=datetime.utcnow()
                            )
                            await self.submit(task)
            except Exception as e:
                logging.debug(f"Remote Bridge poll failed: {e}")
            
            await asyncio.sleep(10) # Poll every 10 seconds

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        def _sort_key(t: Task):
            dt = t.created_at
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        return sorted(self._tasks.values(), key=_sort_key, reverse=True)

    async def clear_tasks(self) -> int:
        """Remove all non-running tasks and clear them from the DB. Returns count removed."""
        to_remove = [tid for tid, t in self._tasks.items() if t.status not in (TaskStatus.RUNNING,)]
        for tid in to_remove:
            fut = self._futures.pop(tid, None)
            if fut:
                fut.cancel()
            del self._tasks[tid]
        # Clear DB
        try:
            conn = sqlite3.connect(Settings.db_path)
            conn.execute("DELETE FROM tasks WHERE status != 'running'")
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Failed to clear tasks from DB: {e}")
        return len(to_remove)

    async def engine_infos(self) -> list[dict]:
        return [await e.get_info() for e in self._engines.values()]

    async def pause(self, task_id: str) -> Task | None:
        t = self._tasks.get(task_id)
        if t and t.status == TaskStatus.RUNNING:
            fut = self._futures.get(task_id)
            if fut:
                fut.cancel()
            t.status = TaskStatus.PAUSED
            t.updated_at = datetime.utcnow()
        return t

    async def cancel(self, task_id: str) -> Task | None:
        t = self._tasks.get(task_id)
        if t and t.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED):
            # Signal the engine to stop gracefully
            if t.engine in self._engines:
                eng = self._engines[t.engine]
                if hasattr(eng, 'request_cancel'):
                    eng.request_cancel()
            fut = self._futures.get(task_id)
            if fut:
                fut.cancel()
            t.status = TaskStatus.CANCELLED
            t.updated_at = datetime.utcnow()
        return t

_manager: TaskManager | None = None

def get_manager() -> TaskManager:
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager

# ---------------------------------------------------------------------------
# Embedded dashboard (HTML + CSS + JS in one response)
# ---------------------------------------------------------------------------

def _dashboard_html() -> str:
    # Inline CSS (enhanced for chat-like experience)
    css = """
:root{--bg:#0f1117;--card:#1e2130;--border:#2d3148;--text:#e4e6f0;--muted:#a0aec0;--accent:#6366f1;--ok:#22c55e;--err:#ef4444;}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{overflow:hidden;width:100%;height:100%;}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column;}
*::-webkit-scrollbar{width:6px;height:0px;}
*::-webkit-scrollbar-track{background:transparent;}
*::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.15);border-radius:3px;}
*::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.25);}
.header{display:flex;justify-content:space-between;align-items:center;padding:12px 24px;border-bottom:1px solid var(--border);flex-shrink:0;}
.logo{font-weight:700;color:var(--accent);font-size:1.2rem;}
/* Layout & Sidebars */
.layout{display:grid;grid-template-columns:300px 1fr;gap:0;flex:1;overflow:hidden;max-width:100%;transition:grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);}
.layout.left-collapsed{grid-template-columns:52px 1fr;}

aside{border-right:1px solid var(--border);padding:16px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;position:relative;transition:all 0.3s;}

.collapsed-icons{display:none;flex-direction:column;align-items:center;gap:12px;padding-top:16px;}
aside.collapsed .collapsed-icons{display:flex;}
aside.collapsed .card, aside.collapsed .btn, aside.collapsed h2{display:none;}
aside.collapsed{padding:10px;overflow:hidden;min-width:52px;}

.toggle-btn{background:none;border:none;color:var(--muted);cursor:pointer;padding:8px;z-index:10;transition:color 0.2s;display:flex;align-items:center;justify-content:center;border-radius:8px;}
.toggle-btn:hover{color:var(--accent);background:rgba(255,255,255,0.05);}
.toggle-btn svg{width:20px;height:20px;}
aside.collapsed .toggle-btn svg{transform:rotate(180deg);}

/* Expandable sidebar sections */
.expandable-header{cursor:pointer;user-select:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0;}
.expandable-header:hover{color:var(--accent);}
.expandable-header .chevron{width:14px;height:14px;color:var(--muted);transition:transform 0.2s;}
.expandable-header .chevron.collapsed{transform:rotate(-90deg);}
.expandable-content{overflow:hidden;transition:max-height 0.25s ease;max-height:600px;}
.expandable-content.collapsed{max-height:0 !important;overflow:hidden;padding-top:0 !important;margin-top:0 !important;padding-bottom:0 !important;margin-bottom:0 !important;}
.card.expandable .expandable-content:not(.collapsed){margin-top:12px;}
.card.expandable{padding:12px 16px;}

.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;}
.card h2{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
.icon-svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;}
.sidebar-icon-large{width:20px;height:20px;color:var(--muted);cursor:pointer;transition:color 0.2s;}
.sidebar-icon-large:hover{color:var(--accent);}
textarea,select,input{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:10px 14px;font-size:14px;outline:none;transition:border-color 0.2s,box-shadow 0.2s;}
textarea:focus,select:focus,input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(99,102,241,0.15);}
select{width:auto !important;min-width:0;padding:8px 32px 8px 12px;font-size:13px;font-weight:500;border-radius:10px;cursor:pointer;appearance:none;-webkit-appearance:none;background:var(--bg) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23a0aec0' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E") no-repeat right 10px center;}
select option{background:#1e2130;color:#e4e6f0;padding:8px 12px;}
textarea{min-height:44px;max-height:120px;resize:none;line-height:1.4;flex:1;}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:10px 20px;border:none;border-radius:10px;font-weight:600;font-size:14px;cursor:pointer;background:var(--accent);color:#fff;transition:all 0.2s;white-space:nowrap;}
.btn:hover{opacity:.9;transform:translateY(-1px);box-shadow:0 4px 12px rgba(99,102,241,0.3);}
.btn:active{transform:translateY(0);}
.btn:disabled{background:var(--muted);cursor:not-allowed;transform:none;box-shadow:none;}

/* Chat Area */
main{display:flex;flex-direction:column;height:100%;overflow:hidden;max-width:100%;background:rgba(0,0,0,0.2);}
.chat-header{padding:10px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-shrink:0;}
.task-list{flex:1;overflow-y:auto;overflow-x:hidden;padding:16px 0;display:flex;flex-direction:column;gap:0;}
.input-area{padding:12px 20px 16px;background:var(--bg);border-top:1px solid var(--border);flex-shrink:0;}
.input-container{display:flex;gap:8px;align-items:flex-end;max-width:800px;margin:0 auto;width:100%;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:6px;transition:border-color 0.2s,box-shadow 0.2s;}
.input-container:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px rgba(99,102,241,0.1);}
.input-container select{border:1px solid var(--border);background:var(--bg) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' fill='%23a0aec0' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E") no-repeat right 8px center;padding:8px 28px 8px 10px;font-size:12px;font-weight:600;border-radius:8px;color:var(--text);letter-spacing:0.3px;}
.input-container select:focus{box-shadow:none;outline:none;border-color:var(--accent);}
.input-container select option{background:#1e2130;color:#e4e6f0;padding:8px 12px;font-weight:500;}
.input-container textarea{border:none;background:transparent;padding:8px 8px;min-height:36px;border-radius:0;font-size:14px;}
.input-container textarea:focus{box-shadow:none;border:none;}
.input-container .btn{border-radius:10px;padding:8px 18px;font-size:13px;flex-shrink:0;}

/* Chat message groups - like Claude/ChatGPT */
.msg-group{max-width:800px;margin:0 auto;width:100%;padding:0 24px;}
.msg-user{padding:16px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
.msg-user-bubble{display:flex;justify-content:flex-end;}
.msg-user-inner{background:var(--accent);color:#fff;padding:10px 16px;border-radius:18px 18px 4px 18px;max-width:75%;font-size:14px;line-height:1.5;word-break:break-word;}
.msg-assistant{padding:16px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
.msg-meta{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:11px;color:var(--muted);}
.msg-meta .engine-tag{background:rgba(99,102,241,0.15);color:var(--accent);padding:2px 8px;border-radius:6px;font-weight:600;font-size:10px;text-transform:uppercase;}
.msg-status{font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700;text-transform:uppercase;}
.msg-status.running{background:rgba(245,158,11,0.2);color:#f59e0b;}
.msg-status.complete{background:rgba(34,197,94,0.15);color:var(--ok);}
.msg-status.error{background:rgba(239,68,68,0.15);color:var(--err);}
.msg-status.cancelled{background:rgba(160,174,192,0.15);color:var(--muted);}
.msg-status.pending{background:rgba(160,174,192,0.15);color:var(--muted);}
.msg-body{font-size:14px;line-height:1.6;color:var(--text);white-space:pre-wrap;word-break:break-word;overflow-wrap:break-word;}
.msg-cost{font-size:10px;color:var(--muted);margin-left:auto;display:flex;gap:8px;align-items:center;}
.msg-cost span{background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;}
.msg-error{margin-top:8px;padding:8px 12px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.2);border-radius:8px;color:var(--err);font-size:13px;word-break:break-word;}
.msg-actions{margin-top:8px;}
.msg-actions .btn{padding:4px 12px;font-size:11px;}

.activity-feed{font-size:11px;}
.activity-item{padding:8px;background:rgba(255,255,255,0.02);border-radius:8px;margin-bottom:8px;border-left:2px solid var(--accent);}
.status-dot.error{background:var(--err);}

/* Live View in Sidebar */
.live-view-img-wrap{background:#0a0a0f;border-radius:8px;overflow:hidden;display:flex;align-items:center;justify-content:center;min-height:80px;}
#liveImage{max-width:100%;display:block;border-radius:8px;}
#livePlaceholder{color:var(--muted);font-size:11px;text-align:center;padding:16px;}
#liveImage[src=""]{display:none;}
#liveImage:not([src=""])~#livePlaceholder{display:none;}
@keyframes monitor-pulse{0%,100%{color:var(--ok);}50%{color:rgba(34,197,94,0.3);}}
.monitor-active{animation:monitor-pulse 2s ease-in-out infinite;}
"""
    # Inline JS
    js = """
const state={ws:null,tasks:[],engines:[],connected:false};
async function api(method,path,body=null){
  const r=await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):null});
  if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||r.statusText);
  return r.json();
}
function connect(){
  state.ws=new WebSocket((location.protocol==="https:"?"wss:":"ws:")+"//"+location.host+"/ws");
  state.ws.onopen=()=>{state.connected=true;document.querySelector(".ws-status").previousElementSibling.className="status-dot connected";document.querySelector(".ws-status").textContent="Connected";};
  state.ws.onclose=()=>{state.connected=false;document.querySelector(".ws-status").previousElementSibling.className="status-dot error";document.querySelector(".ws-status").textContent="Disconnected";setTimeout(connect,3000);};
  state.ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==="task_update")upsert(m.payload);else if(m.type==="task_list"){state.tasks=m.payload;render();}else if(m.type==="engine_status"){state.engines=m.payload;renderEngines();}else if(m.type==="audit_event")addActivity(m.payload);else if(m.type==="live_view")updateLiveView(m.payload);else if(m.type==="install_progress")addActivity({timestamp:new Date().toISOString(),event_type:"install",detail:m.payload.engine+": "+m.payload.message});else if(m.type==="tasks_cleared"){state.tasks=[];render();}};
}
let _liveTimer=null;
function updateLiveView(p){
  if(!p||!p.image)return;
  const i=document.getElementById("liveImage");
  const ph=document.getElementById("livePlaceholder");
  const st=document.getElementById("liveStatus");
  const icon=document.getElementById("monitorIcon");
  i.src="data:image/png;base64,"+p.image;
  i.style.display="block";
  if(ph)ph.style.display="none";
  if(st){st.textContent="Streaming";st.style.color="var(--ok)";}
  if(icon)icon.classList.add("monitor-active");
  // Auto-expand the liveview section if collapsed
  const content=document.getElementById("liveviewContent");
  if(content&&content.classList.contains("collapsed")){
    toggleSection("liveview");
  }
  // Reset idle timer - collapse after 10s of no frames
  clearTimeout(_liveTimer);
  _liveTimer=setTimeout(()=>{
    if(st){st.textContent="Idle";st.style.color="var(--muted)";}
    if(icon)icon.classList.remove("monitor-active");
  },10000);
}
function toggleSidebar(side){
  const l=document.getElementById("mainLayout");
  const a=l.querySelector('#leftSidebar');
  l.classList.toggle('left-collapsed');
  a.classList.toggle('collapsed');
  localStorage.setItem('sidebar_left', a.classList.contains('collapsed'));
}
function toggleSection(id){
  const card=document.getElementById('card-'+id);
  const content=document.getElementById(id+'Content');
  const chevron=card.querySelector('.chevron');
  const collapsed=content.classList.toggle('collapsed');
  chevron.classList.toggle('collapsed',collapsed);
  localStorage.setItem('section_'+id, collapsed?'1':'0');
}
function upsert(t){const i=state.tasks.findIndex(x=>x.id===t.id);if(i>=0)state.tasks[i]=t;else state.tasks.push(t);render();}
function scrollToBottom(){const el=document.getElementById("taskList");if(el)requestAnimationFrame(()=>el.scrollTop=el.scrollHeight);}
async function submit(){
  const prompt=document.getElementById("prompt").value.trim();if(!prompt)return;
  const engine=document.getElementById("engine").value;
  const btn=document.getElementById("submitBtn");btn.disabled=true;
  try {
    if(engine!=="computer_use")await ensureBrowser();
    await api("POST","/api/tasks",{prompt,engine});
    document.getElementById("prompt").value="";
    document.getElementById("prompt").style.height = "auto";
    scrollToBottom();
  } finally {
    btn.disabled=false;
  }
}
async function cancel(id){
  const btn=event&&event.target?event.target.closest('button'):null;
  if(btn){btn.disabled=true;btn.style.background='rgba(239,68,68,0.4)';btn.style.color='#fff';btn.textContent='Stopping...';}
  try{await api("PATCH","/api/tasks/"+id,{action:"cancel"});}catch(e){console.error(e);}
  if(btn){btn.style.background='rgba(160,174,192,0.3)';btn.textContent='Stopped';}
}
async function clearChat(){
  if(!state.tasks.length)return;
  try{await api("DELETE","/api/tasks");state.tasks=[];render();}catch(e){console.error("Clear failed:",e);}
}
function esc(s){if(!s)return"";const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function render(){
  const c=document.getElementById("taskList");const n=document.getElementById("taskCount");
  n.textContent=state.tasks.length+" task(s)";
  if(!state.tasks.length){c.innerHTML='<p style="color:var(--muted);text-align:center;padding:40px">Send a message to start.</p>';return;}

  const items = [...state.tasks].sort((a,b)=>new Date(a.created_at)-new Date(b.created_at));

  c.innerHTML=items.map(t=>{
    const time=new Date(t.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
    const hasResult=t.result&&t.result.summary;
    const hasError=t.error;
    let ctl="";
    if(t.status==="running")ctl='<div class="msg-actions"><button class="btn" onclick="cancel(\\''+t.id+'\\')">Stop</button></div>';

    let assistantHtml="";
    if(hasResult||hasError||t.status!=="pending"){
      let costHtml='';
      if(t.result&&t.result.tokens_in){
        const ti=t.result.tokens_in;const to=t.result.tokens_out;const c=t.result.estimated_cost_usd;
        const steps=t.result.total_steps||0;const dur=t.result.total_duration_ms||0;
        const durStr=dur>=60000?(dur/60000).toFixed(1)+'m':(dur/1000).toFixed(1)+'s';
        costHtml='<div class="msg-cost">'
          +'<span>'+steps+' steps</span>'
          +'<span>'+durStr+'</span>'
          +'<span>'+(ti+to).toLocaleString()+' tok</span>'
          +'<span>$'+c.toFixed(4)+'</span>'
          +'</div>';
      }
      assistantHtml='<div class="msg-assistant"><div class="msg-meta">'
        +'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>'
        +'<span class="engine-tag">'+esc(t.engine)+'</span>'
        +'<span class="msg-status '+t.status+'">'+t.status+'</span>'
        +'<span>'+time+'</span>'
        +costHtml
        +'</div>';
      if(hasResult)assistantHtml+='<div class="msg-body">'+esc(t.result.summary)+'</div>';
      if(hasError)assistantHtml+='<div class="msg-error">'+esc(t.error)+'</div>';
      assistantHtml+=ctl+'</div>';
    }

    return '<div class="msg-group">'
      +'<div class="msg-user"><div class="msg-user-bubble"><div class="msg-user-inner">'+esc(t.prompt)+'</div></div></div>'
      +assistantHtml
      +'</div>';
  }).join("");
  scrollToBottom();
}
function renderEngines(){
  const c=document.getElementById("engineList");
  if(!state.engines.length){c.innerHTML='<p class="muted">No engines</p>';return;}
  c.innerHTML=state.engines.map(e=>{
    const sc=e.status==="available"?"color:var(--ok)":e.status==="no_api_key"?"color:#f59e0b":e.status==="error"?"color:var(--err)":"color:var(--muted)";
    let extra="";
    if(e.error_hint)extra+='<div style="font-size:10px;color:var(--muted);margin-top:2px">'+esc(e.error_hint)+'</div>';
    if(e.status==="not_installed"&&e.name==="openclaw")extra+='<button class="btn" style="font-size:10px;padding:4px 10px;margin-top:6px" onclick="installEngine(\\'openclaw\\')">Install</button>';
    return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03)"><div style="display:flex;justify-content:space-between"><span>'+esc(e.display_name)+'</span><span style="font-weight:600;'+sc+'">'+e.status+'</span></div>'+extra+'</div>';
  }).join("");
}
async function installEngine(name){
  const btn=event.target;btn.disabled=true;btn.textContent="Installing...";
  try{await api("POST","/api/engines/"+name+"/install");}
  catch(e){btn.textContent="Retry";btn.disabled=false;addActivity({timestamp:new Date().toISOString(),event_type:"install_error",detail:name+": "+e.message});}
}
function toggleKeyForm(){
  const f=document.getElementById("keyForm");f.style.display=f.style.display==="none"?"block":"none";
}
async function saveKey(){
  const key=document.getElementById("keyInput").value.trim();
  const provider=document.getElementById("keyProvider").value;
  const st=document.getElementById("keySaveStatus");
  if(!key){st.textContent="Enter a key first";st.style.color="var(--err)";return;}
  st.textContent="Saving...";st.style.color="var(--muted)";
  try{
    const r=await api("POST","/api/config/keys",{provider,key});
    st.textContent="Saved!";st.style.color="var(--ok)";
    document.getElementById("keyInput").value="";
    refreshConfig();
    setTimeout(()=>st.textContent="",2000);
  }catch(e){st.textContent=e.message;st.style.color="var(--err)";}
}
async function ensureBrowser(){
  try{
    const s=await api("GET","/api/browser/status");
    if(s.cdp_reachable)return true;
    addActivity({timestamp:new Date().toISOString(),event_type:"browser",detail:"Launching dedicated Chrome window..."});
    await api("POST","/api/browser/launch",{});
    checkBrowserStatus();
    return true;
  }catch(e){
    addActivity({timestamp:new Date().toISOString(),event_type:"browser_error",detail:"Failed to launch Chrome: "+e.message});
    return false;
  }
}
async function launchChrome(){
  if(!confirm("This will close any open Chrome windows and launch a dedicated ClawBridge Chrome profile with debug access.\\n\\nFirst time? You'll need to sign into your accounts once.\\nContinue?"))return;
  const btn=document.getElementById("launchChromeBtn");
  btn.disabled=true;btn.textContent="Closing Chrome & relaunching...";
  try{
    await api("POST","/api/browser/launch",{});
    checkBrowserStatus();
  }catch(e){alert("Failed to launch Chrome: "+e.message);}
  finally{btn.disabled=false;btn.textContent="Launch Chrome (with your logins)";}
}
async function stopChrome(){
  try{await api("POST","/api/browser/stop");}catch(e){}
  checkBrowserStatus();
}
async function checkBrowserStatus(){
  try{
    const s=await api("GET","/api/browser/status");
    const dot=document.getElementById("chromeStatusDot");
    const txt=document.getElementById("chromeStatusText");
    const mode=document.getElementById("chromeModeText");
    const launchBtn=document.getElementById("launchChromeBtn");
    const stopBtn=document.getElementById("stopChromeBtn");
    if(s.cdp_reachable){
      dot.style.background="var(--ok)";
      txt.textContent="Chrome connected (CDP)";txt.style.color="var(--ok)";
      mode.textContent="Tasks will use your signed-in browser";
      launchBtn.style.display="none";stopBtn.style.display="block";
    }else if(s.launched){
      dot.style.background="var(--warn)";
      txt.textContent="Chrome starting...";txt.style.color="var(--warn)";
      mode.textContent="Waiting for debug connection";
      launchBtn.style.display="none";stopBtn.style.display="block";
    }else{
      dot.style.background="var(--muted)";
      txt.textContent="Not connected";txt.style.color="var(--text)";
      mode.textContent=s.mode==="default"?"Using fresh Chromium (no logins)":"";
      launchBtn.style.display="block";stopBtn.style.display="none";
    }
  }catch(e){}
}
function refreshConfig(){
  api("GET","/api/config").then(c=>{
    document.getElementById("configSummary").innerHTML='<div style="display:flex;justify-content:space-between;padding:4px 0"><span style="color:var(--muted)">Anthropic</span><span>'+(c.keys.anthropic_configured?"Yes":"No")+'</span></div><div style="display:flex;justify-content:space-between;padding:4px 0"><span style="color:var(--muted)">OpenAI</span><span>'+(c.keys.openai_configured?"Yes":"No")+'</span></div><div style="display:flex;justify-content:space-between;padding:4px 0"><span style="color:var(--muted)">OpenRouter</span><span>'+(c.keys.openrouter_configured?"Yes":"No")+'</span></div><div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.05);font-size:10px;"><div style="color:var(--muted);margin-bottom:4px">MACHINE ID</div><div style="word-break:break-all;color:var(--accent)">'+c.machine_id+'</div></div>';
    
    // Update remote bridge status in header
    const rdot = document.getElementById("remoteDot");
    const rtext = document.getElementById("remoteText");
    if(c.remote.configured){
      rdot.className="status-dot connected";
      rtext.textContent="Bridge Active";
      rtext.style.color="var(--ok)";
    } else {
      rdot.className="status-dot";
      rtext.textContent="Bridge Offline";
      rtext.style.color="var(--muted)";
    }
    // Show detected Chrome path
    if(c.browser){
      const cei=document.getElementById("chromeExeInfo");
      if(cei&&c.browser.chrome_exe&&c.browser.chrome_exe!=="not found")cei.textContent="Chrome: "+c.browser.chrome_exe;
    }
    checkBrowserStatus();
  }).catch(()=>{});
}
function addActivity(ev){
  const c=document.getElementById("activityFeed");
  if(c.querySelector(".muted"))c.innerHTML="";
  c.insertAdjacentHTML("afterbegin",'<div class="activity-item"><span style="color:var(--muted);font-size:10px">'+new Date(ev.timestamp).toLocaleTimeString()+'</span> <strong>'+esc(ev.event_type)+'</strong><div style="color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+esc(ev.detail)+'</div></div>');
  while(c.children.length>50)c.removeChild(c.lastChild);
}
document.addEventListener("DOMContentLoaded",()=>{
  const prompt = document.getElementById("prompt");
  prompt.onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();submit();}};
  prompt.oninput=e=>{prompt.style.height="auto";prompt.style.height=prompt.scrollHeight+"px";};
  document.getElementById("taskForm").onsubmit=e=>{e.preventDefault();submit();};
  
  if(localStorage.getItem('sidebar_left')==='true') toggleSidebar('left');
  ['engines','config','activity','liveview'].forEach(id=>{
    const c=document.getElementById(id+'Content');
    const card=document.getElementById('card-'+id);
    if(c&&card&&localStorage.getItem('section_'+id)==='1'){c.classList.add('collapsed');card.querySelector('.chevron')?.classList.add('collapsed');}
  });
  refreshConfig();
  connect();
  // Poll browser status every 10s
  setInterval(checkBrowserStatus,10000);
});
"""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ClawBridge Dashboard</title>
  <style>""" + css + """</style>
</head>
<body>
  <header class="header">
    <h1 class="logo">ClawBridge</h1>
    <div style="display:flex;gap:16px;align-items:center;">
      <div style="font-size:12px;display:flex;items-center:center;gap:6px">
        <span id="remoteDot" class="status-dot"></span>
        <span id="remoteText" class="status-text" style="color:var(--muted)">Bridge Offline</span>
      </div>
      <div style="font-size:12px;display:flex;items-center:center;gap:6px">
        <span class="status-dot error"></span>
        <span class="status-text ws-status">Connecting...</span>
      </div>
    </div>
  </header>
  <div class="layout" id="mainLayout">
    <aside id="leftSidebar">
      <div style="display:flex;justify-content:flex-end;margin-bottom:8px;">
        <button class="toggle-btn" onclick="toggleSidebar('left')" title="Toggle Sidebar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="11 17 6 12 11 7"></polyline><polyline points="18 17 13 12 18 7"></polyline></svg>
        </button>
      </div>
      <div class="collapsed-icons">
        <div onclick="toggleSidebar('left')" title="Engines">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Config">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Activity">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Browser View">
          <svg id="monitorIconCollapsed" class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
        </div>
      </div>
      <div class="card expandable" id="card-engines">
        <h2 class="expandable-header" onclick="toggleSection('engines')">
          <span style="display:flex;align-items:center;gap:8px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path></svg>Engines</span>
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </h2>
        <div class="expandable-content" id="enginesContent"><div id="engineList"><p class="muted">Loading...</p></div></div>
      </div>
      <div class="card expandable" id="card-config">
        <h2 class="expandable-header" onclick="toggleSection('config')">
          <span style="display:flex;align-items:center;gap:8px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>Config</span>
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </h2>
        <div class="expandable-content" id="configContent">
          <div id="configSummary"><p class="muted">Loading...</p></div>
          <div id="keyForm" style="margin-top:12px;display:none">
            <input type="password" id="keyInput" placeholder="Paste API key..." style="margin-bottom:8px">
            <select id="keyProvider" style="margin-bottom:8px">
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="openrouter">OpenRouter</option>
            </select>
            <button class="btn" style="width:100%;font-size:13px" onclick="saveKey()">Save Key</button>
            <div id="keySaveStatus" style="font-size:11px;margin-top:4px"></div>
          </div>
          <button class="btn" id="toggleKeyBtn" style="width:100%;font-size:12px;margin-top:8px;background:#2d3748;border:1px solid var(--border)" onclick="toggleKeyForm()">Add / Update API Keys</button>
          <div style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.06)">
            <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Browser Session</div>
            <div id="browserSessionStatus" style="font-size:12px;margin-bottom:8px;padding:8px;background:rgba(255,255,255,0.03);border-radius:6px">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
                <span id="chromeStatusDot" style="width:8px;height:8px;border-radius:50%;background:var(--muted);flex-shrink:0"></span>
                <span id="chromeStatusText" style="font-size:12px">Not connected</span>
              </div>
              <div id="chromeModeText" style="font-size:10px;color:var(--muted)"></div>
            </div>
            <button class="btn" id="launchChromeBtn" style="width:100%;font-size:12px;margin-bottom:6px" onclick="launchChrome()">Launch Chrome Session</button>
            <button class="btn" id="stopChromeBtn" style="width:100%;font-size:12px;margin-bottom:6px;background:rgba(239,68,68,0.15);color:var(--err);display:none" onclick="stopChrome()">Stop Chrome Session</button>
            <div style="font-size:10px;color:var(--muted);line-height:1.4">Opens a dedicated Chrome profile for ClawBridge. Sign into your accounts once — logins persist between sessions.</div>
            <div id="chromeExeInfo" style="font-size:10px;color:var(--muted);margin-top:6px"></div>
          </div>
        </div>
      </div>
      <div class="card expandable" id="card-activity">
        <h2 class="expandable-header" onclick="toggleSection('activity')">
          <span style="display:flex;align-items:center;gap:8px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>Activity</span>
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </h2>
        <div class="expandable-content" id="activityContent">
          <div id="activityFeed" class="activity-feed" style="overflow-y:auto;max-height:150px;"><p class="muted">Waiting for activity...</p></div>
        </div>
      </div>
      <div class="card expandable" id="card-liveview">
        <h2 class="expandable-header" onclick="toggleSection('liveview')">
          <span style="display:flex;align-items:center;gap:8px;"><svg id="monitorIcon" class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>Browser</span>
          <span style="display:flex;align-items:center;gap:6px;">
            <span id="liveStatus" style="font-size:9px;color:var(--muted)">Idle</span>
            <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
          </span>
        </h2>
        <div class="expandable-content collapsed" id="liveviewContent">
          <div class="live-view-img-wrap">
            <img id="liveImage" src="" alt="Live Browser Feed">
            <div id="livePlaceholder">Streams here when a task runs</div>
          </div>
        </div>
      </div>
    </aside>
    <main>
      <div class="chat-header">
        <h2 style="font-size:14px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)">Chat & Tasks</h2>
        <div style="display:flex;align-items:center;gap:10px;">
          <span id="taskCount" style="font-size:12px;color:var(--muted)">0 tasks</span>
          <button id="clearChatBtn" onclick="clearChat()" title="Clear chat" style="background:none;border:1px solid var(--border);border-radius:6px;padding:4px 8px;cursor:pointer;color:var(--muted);display:flex;align-items:center;gap:4px;font-size:11px;transition:all 0.15s;" onmouseenter="this.style.color='var(--err)';this.style.borderColor='var(--err)'" onmouseleave="this.style.color='var(--muted)';this.style.borderColor='var(--border)'">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
            Clear
          </button>
        </div>
      </div>
      <div id="taskList" class="task-list">
        <p style="color:var(--muted);text-align:center;padding:40px">Send a message to start.</p>
      </div>
      <div class="input-area">
        <form id="taskForm" class="input-container">
          <select id="engine">
            <option value="auto">Auto</option>
            <option value="browser_use">browser-use</option>
            <option value="computer_use">computer-use</option>
            <option value="openclaw">OpenClaw</option>
          </select>
          <textarea id="prompt" placeholder="Send a message..." rows="1"></textarea>
          <button type="submit" class="btn" id="submitBtn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            Send
          </button>
        </form>
      </div>
    </main>
  </div>
  <script>""" + js + """</script>
</body>
</html>"""
    return html

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(title="ClawBridge", version="0.1.0")

    @app.on_event("startup")
    async def startup():
        logging.basicConfig(level=getattr(logging, get_settings().log_level.upper(), logging.INFO))
        await get_manager().init_engines()
        get_manager()._broadcast = _broadcast
        # Link audit logger to websocket broadcast
        get_audit()._on_log = lambda ev: asyncio.create_task(_broadcast({"type": "audit_event", "payload": ev.model_dump(mode="json")}))
        asyncio.create_task(get_manager().remote_bridge_loop())

    connections: list[WebSocket] = []

    async def _broadcast(msg: dict) -> None:
        for ws in connections[:]:
            try:
                await ws.send_json(msg)
            except Exception:
                connections.remove(ws)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _dashboard_html()

    @app.post("/api/tasks")
    async def create_task(body: dict):
        task = Task(prompt=body["prompt"], engine=EngineName(body.get("engine", "auto")))
        return (await get_manager().submit(task)).model_dump(mode="json")

    @app.get("/api/tasks")
    async def list_tasks():
        return [t.model_dump(mode="json") for t in get_manager().list_tasks()]

    @app.delete("/api/tasks")
    async def clear_tasks():
        count = await get_manager().clear_tasks()
        await _broadcast({"type": "tasks_cleared", "payload": {}})
        return {"cleared": count}

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        t = get_manager().get(task_id)
        if not t:
            raise HTTPException(404, "Task not found")
        return t.model_dump(mode="json")

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, body: dict):
        action = body.get("action")
        if action == "cancel":
            t = await get_manager().cancel(task_id)
        elif action == "pause":
            t = await get_manager().pause(task_id)
        else:
            raise HTTPException(400, "Unknown action")
        if not t:
            raise HTTPException(404, "Task not found")
        return t.model_dump(mode="json")

    @app.get("/api/engines")
    async def list_engines():
        return await get_manager().engine_infos()

    @app.post("/api/engines/openclaw/install")
    async def install_openclaw():
        npm = shutil.which("npm")
        if not npm:
            raise HTTPException(400, "Node.js/npm not found. Install Node.js first: https://nodejs.org")
        await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "installing", "message": "Running npm install -g openclaw@latest ..."}})
        try:
            proc = await asyncio.create_subprocess_shell(
                f'"{npm}" install -g openclaw@latest',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                err_msg = (stderr or stdout or b"").decode(errors="replace").strip()
                await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "error", "message": err_msg}})
                raise HTTPException(500, f"npm install failed: {err_msg}")
        except HTTPException:
            raise
        except asyncio.TimeoutError:
            await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "error", "message": "Install timed out after 120s"}})
            raise HTTPException(500, "Install timed out")
        except Exception as e:
            msg = str(e)
            await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "error", "message": msg}})
            raise HTTPException(500, f"Install error: {msg}")
        # Re-initialize the engine
        mgr = get_manager()
        e = OpenClawEngine()
        await e.initialize()
        mgr._engines[EngineName.OPENCLAW] = e
        await _broadcast({"type": "engine_status", "payload": await mgr.engine_infos()})
        await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "done", "message": "OpenClaw installed successfully"}})
        return {"status": "ok", "engine_status": e._status.value}

    @app.get("/api/config")
    async def get_config():
        s = get_settings()
        return {
            "keys": {"anthropic_configured": s.has_anthropic_key(), "openai_configured": s.has_openai_key(), "openrouter_configured": s.has_openrouter_key(), "default_model": s.default_model},
            "policy": {"mode": s.policy_mode, "max_concurrent_tasks": s.max_concurrent_tasks},
            "browser": {"mode": s.browser_mode, "cdp_url": s.browser_cdp_url, "user_data_dir": s.browser_user_data_dir, "chrome_exe": _find_chrome_exe() or "not found"},
            "machine_id": get_machine_id(),
            "remote": {
                "url": s.remote_bridge_url,
                "configured": bool(s.remote_bridge_url)
            }
        }

    @app.post("/api/config/keys")
    async def save_key(body: dict):
        provider = body.get("provider", "")
        key = body.get("key", "").strip()
        env_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
        env_var = env_map.get(provider)
        if not env_var:
            raise HTTPException(400, f"Unknown provider: {provider}")
        if not key:
            raise HTTPException(400, "Key cannot be empty")
        # Update .env file
        env_path = Path(".env")
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(env_var + "=") or line.strip().startswith(env_var + " ="):
                lines[i] = f"{env_var}={key}"
                found = True
                break
        if not found:
            lines.append(f"{env_var}={key}")
        env_path.write_text("\n".join(lines) + "\n")
        # Update in-memory settings and env
        os.environ[env_var] = key
        setattr(Settings, env_var.lower().replace("api_key", "api_key"), key)
        # Map to Settings attribute names
        attr_map = {"anthropic": "anthropic_api_key", "openai": "openai_api_key", "openrouter": "openrouter_api_key"}
        setattr(Settings, attr_map[provider], key)
        # Re-initialize engines so browser-use picks up the new key
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok", "provider": provider}

    @app.post("/api/config/browser")
    async def save_browser_config(body: dict):
        mode = body.get("mode", "default")
        if mode not in ("default", "cdp", "user_data_dir"):
            raise HTTPException(400, f"Invalid browser mode: {mode}")
        cdp_url = body.get("cdp_url", "").strip()
        user_data_dir = body.get("user_data_dir", "").strip()
        # Persist to .env
        env_path = Path(".env")
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        env_updates = {"BROWSER_MODE": mode, "BROWSER_CDP_URL": cdp_url, "BROWSER_USER_DATA_DIR": user_data_dir}
        for env_var, val in env_updates.items():
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(env_var + "=") or line.strip().startswith(env_var + " ="):
                    lines[i] = f"{env_var}={val}"
                    found = True
                    break
            if not found:
                lines.append(f"{env_var}={val}")
        env_path.write_text("\n".join(lines) + "\n")
        # Update in-memory
        Settings.browser_mode = mode
        Settings.browser_cdp_url = cdp_url or "http://localhost:9222"
        Settings.browser_user_data_dir = user_data_dir
        os.environ["BROWSER_MODE"] = mode
        os.environ["BROWSER_CDP_URL"] = cdp_url or "http://localhost:9222"
        os.environ["BROWSER_USER_DATA_DIR"] = user_data_dir
        # Re-initialize engines
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok", "mode": mode}

    # ── Chrome Launcher ──────────────────────────────────────────────────
    _chrome_proc: subprocess.Popen | None = None
    _CLAWBRIDGE_PROFILE = os.path.expandvars(r"%LOCALAPPDATA%\ClawBridge\ChromeProfile")

    @app.post("/api/browser/launch")
    async def launch_chrome(body: dict = {}):
        nonlocal _chrome_proc
        port = int(body.get("port", 9222))
        chrome_exe = _find_chrome_exe()
        if not chrome_exe:
            raise HTTPException(400, "Chrome not found on this system")
        # Kill our previously launched Chrome if still running
        if _chrome_proc and _chrome_proc.poll() is None:
            _chrome_proc.terminate()
            try:
                _chrome_proc.wait(timeout=5)
            except Exception:
                pass
        # Kill any existing Chrome so the new instance gets the debug port
        chrome_name = os.path.basename(chrome_exe).lower()
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/IM", chrome_name], capture_output=True, timeout=10)
            else:
                subprocess.run(["pkill", "-f", chrome_name], capture_output=True, timeout=10)
            await asyncio.sleep(2)
        except Exception as e:
            logging.warning("Failed to kill existing Chrome: %s", e)
        # Chrome requires a NON-default user-data-dir for --remote-debugging-port.
        # Use a dedicated ClawBridge profile — user signs in once, sessions persist.
        debug_udd = _CLAWBRIDGE_PROFILE
        os.makedirs(debug_udd, exist_ok=True)
        cmd = [
            chrome_exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={debug_udd}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1300,950",
        ]
        logging.info("Launching Chrome: %s", " ".join(cmd))
        _chrome_proc = subprocess.Popen(cmd)
        # Auto-set CDP mode so tasks use this Chrome
        Settings.browser_mode = "cdp"
        Settings.browser_cdp_url = f"http://localhost:{port}"
        os.environ["BROWSER_MODE"] = "cdp"
        os.environ["BROWSER_CDP_URL"] = f"http://localhost:{port}"
        # Wait for CDP to become available
        cdp_ok = False
        import httpx
        for _ in range(15):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    r = await client.get(f"http://localhost:{port}/json/version")
                    if r.status_code == 200:
                        cdp_ok = True
                        break
            except Exception:
                continue
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok", "pid": _chrome_proc.pid, "port": port, "cdp_url": f"http://localhost:{port}", "cdp_ready": cdp_ok}

    @app.get("/api/browser/status")
    async def browser_status():
        nonlocal _chrome_proc
        running = _chrome_proc is not None and _chrome_proc.poll() is None
        # Also try to ping the CDP endpoint
        cdp_reachable = False
        if Settings.browser_mode == "cdp":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=2) as client:
                    r = await client.get(f"{Settings.browser_cdp_url}/json/version")
                    cdp_reachable = r.status_code == 200
            except Exception:
                pass
        return {"launched": running, "pid": _chrome_proc.pid if running else None, "cdp_reachable": cdp_reachable, "mode": Settings.browser_mode}

    @app.post("/api/browser/stop")
    async def stop_chrome():
        nonlocal _chrome_proc
        if _chrome_proc and _chrome_proc.poll() is None:
            _chrome_proc.terminate()
            _chrome_proc.wait(timeout=5)
            _chrome_proc = None
        # Revert to default mode
        Settings.browser_mode = "default"
        os.environ["BROWSER_MODE"] = "default"
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok"}

    @app.get("/api/config/audit")
    async def get_audit_events(limit: int = 50, task_id: str | None = None):
        return [e.model_dump(mode="json") for e in get_audit().recent(limit=limit, task_id=task_id)]

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        connections.append(websocket)
        try:
            await websocket.send_json({"type": "engine_status", "payload": await get_manager().engine_infos()})
            await websocket.send_json({"type": "task_list", "payload": [t.model_dump(mode="json") for t in get_manager().list_tasks()]})
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in connections:
                connections.remove(websocket)

    return app

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    s = get_settings()
    print()
    print("  ClawBridge (single file) v0.1.0")
    print("  Dashboard: http://%s:%s" % (s.host, s.port))
    print()
    if not s.has_any_key():
        print("  [!] Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in .env")
    url = "http://%s:%s" % (s.host, s.port)
    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open(url)
    import threading
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(create_app(), host=s.host, port=s.port, log_level=s.log_level.lower())

if __name__ == "__main__":
    main()
