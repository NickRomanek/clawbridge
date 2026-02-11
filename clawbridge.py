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
    ]
    # Map pip package names to their actual import names where they differ
    import_names = {"python-dotenv": "dotenv"}
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
import json
import logging
import sqlite3
import uuid
import webbrowser
from collections import deque
from datetime import datetime
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
    enabled_engines = _env("ENABLED_ENGINES", "browser_use,openclaw")
    browser_headless = _env("BROWSER_HEADLESS", "true").lower() in ("1", "true", "yes")
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

class BrowserUseEngine(EngineBase):
    name = EngineName.BROWSER_USE
    display_name = "browser-use"

    async def initialize(self) -> None:
        try:
            from browser_use import Agent, Browser
            self._Agent = Agent
            self._Browser = Browser
            self._browser = Browser()
            settings = get_settings()
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
            t0 = time.monotonic()
            history = await agent.run(max_steps=min(get_settings().max_actions_per_task, 50))
            duration_ms = int((time.monotonic() - t0) * 1000)
            final = str(getattr(history, "final_result", lambda: str(history))() if callable(getattr(history, "final_result", None)) else str(history))
            task.result = TaskResult(
                summary=final[:5000],
                total_duration_ms=duration_ms,
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

    async def initialize(self) -> None:
        import shutil
        self._openclaw_bin = shutil.which("openclaw") or shutil.which("openclaw.cmd")
        if self._openclaw_bin:
            self._status = EngineStatus.AVAILABLE
            self._error_hint = ""
            import httpx
            self._http_client = httpx.AsyncClient(base_url="http://127.0.0.1:3080", timeout=120.0)
        else:
            self._status = EngineStatus.NOT_INSTALLED
            self._error_hint = "Requires Node.js. Click Install or run: npm install -g openclaw@latest"

    async def _ensure_gateway(self) -> bool:
        if not self._http_client:
            return False
        try:
            resp = await self._http_client.get("/health")
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        
        # Try to start it
        if not self._openclaw_bin:
            return False
            
        import subprocess
        env = dict(**os.environ)
        settings = get_settings()
        if settings.anthropic_api_key: env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        if settings.openai_api_key: env["OPENAI_API_KEY"] = settings.openai_api_key
        
        try:
            subprocess.Popen([self._openclaw_bin, "gateway", "start"], env=env)
            for _ in range(30):
                await asyncio.sleep(1)
                try:
                    resp = await self._http_client.get("/health")
                    if resp.status_code == 200: return True
                except Exception: continue
        except Exception as e:
            logging.warning("Failed to start OpenClaw gateway: %s", e)
        return False

    async def run_task(self, task: Task) -> Task:
        if self._status != EngineStatus.AVAILABLE:
            task.status = TaskStatus.ERROR
            task.error = "OpenClaw engine not installed"
            return task
        
        if not await self._ensure_gateway():
            task.status = TaskStatus.ERROR
            task.error = "OpenClaw gateway not responding"
            return task

        self._status = EngineStatus.RUNNING
        try:
            resp = await self._http_client.post("/api/message", json={"content": task.prompt, "conversation_id": task.id})
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", data.get("message", "Task completed"))
            task.result = TaskResult(
                summary=str(content)[:5000],
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

    def _engine_for(self, preferred: EngineName) -> EngineBase | None:
        if preferred != EngineName.AUTO and preferred in self._engines:
            return self._engines[preferred]
        return self._engines.get(EngineName.BROWSER_USE) or self._engines.get(EngineName.OPENCLAW)

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
        
        engine = self._engine_for(task.engine)
        if not engine:
            task.status = TaskStatus.ERROR
            task.error = "No engine available"
        else:
            task.engine = engine.name
            get_audit().log(AuditEvent(task_id=task.id, event_type="task_started", detail=engine.display_name))
            task = await engine.run_task(task)
            get_audit().log(AuditEvent(task_id=task.id, event_type="task_completed" if task.status == TaskStatus.COMPLETE else "task_error", detail=task.error or "ok"))
        
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
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

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
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;overflow:hidden;}
.header{display:flex;justify-content:space-between;align-items:center;padding:12px 24px;border-bottom:1px solid var(--border);flex-shrink:0;}
.logo{font-weight:700;color:var(--accent);font-size:1.2rem;}
/* Layout & Sidebars */
.layout{display:grid;grid-template-columns:300px 1fr 300px;gap:0;flex:1;overflow:hidden;transition:grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);}
.layout.left-collapsed{grid-template-columns:60px 1fr 300px;}
.layout.right-collapsed{grid-template-columns:300px 1fr 60px;}
.layout.both-collapsed{grid-template-columns:60px 1fr 60px;}

aside{border-right:1px solid var(--border);padding:16px;overflow-y:auto;display:flex;flex-direction:column;gap:16px;position:relative;transition:all 0.3s;}
aside:last-child{border-right:none;border-left:1px solid var(--border);}

.collapsed-icons{display:none;flex-direction:column;align-items:center;gap:20px;padding-top:20px;}
aside.collapsed .collapsed-icons{display:flex;}
aside.collapsed .card, aside.collapsed .btn, aside.collapsed h2{display:none;}
aside.collapsed{padding:10px;overflow:hidden;}

.toggle-btn{background:none;border:none;color:var(--muted);cursor:pointer;padding:8px;z-index:10;transition:color 0.2s;display:flex;align-items:center;justify-content:center;border-radius:8px;}
.toggle-btn:hover{color:var(--accent);background:rgba(255,255,255,0.05);}
.toggle-btn svg{width:20px;height:20px;}
aside.collapsed .toggle-btn svg{transform:rotate(180deg);}
aside:last-child .toggle-btn svg{transform:none;}
aside:last-child.collapsed .toggle-btn svg{transform:rotate(180deg);}

.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;}
.card h2{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
.icon-svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;}
.sidebar-icon-large{width:20px;height:20px;color:var(--muted);cursor:pointer;transition:color 0.2s;}
.sidebar-icon-large:hover{color:var(--accent);}
textarea,select,input{width:100%;background:#2d3748;border:1px solid var(--border);border-radius:8px;color:var(--text);padding:12px;font-size:14px;outline:none;}
textarea:focus,select:focus,input:focus{border-color:var(--accent);}
textarea{min-height:44px;max-height:120px;resize:none;line-height:1.4;}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:10px 20px;border:none;border-radius:8px;font-weight:600;cursor:pointer;background:var(--accent);color:#fff;transition:opacity 0.2s;}
.btn:hover{opacity:.9;}
.btn:disabled{background:var(--muted);cursor:not-allowed;}

/* Chat Area */
main{display:flex;flex-direction:column;height:100%;overflow:hidden;background:rgba(0,0,0,0.2);}
.chat-header{padding:12px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;}
.task-list{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column-reverse;gap:20px;}
.input-area{padding:16px 24px;background:var(--card);border-top:1px solid var(--border);}
.input-container{display:flex;gap:12px;align-items:flex-end;max-width:900px;margin:0 auto;width:100%;}

.task-item{max-width:85%;align-self:flex-start;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;box-shadow:0 4px 12px rgba(0,0,0,0.1);}
.task-item.user{align-self:flex-end;background:var(--accent);border-color:var(--accent);color:#fff;}
.task-badge{font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700;text-transform:uppercase;}
.task-badge.running{background:#f59e0b;color:#fff;}
.task-badge.complete{background:var(--ok);color:#fff;}
.task-badge.error{background:var(--err);color:#fff;}

.task-result{margin-top:12px;padding:12px;background:rgba(0,0,0,0.2);border-radius:8px;font-size:14px;white-space:pre-wrap;border:1px solid rgba(255,255,255,0.05);}
.task-item.user .task-result{background:rgba(255,255,255,0.1);color:#fff;}

.activity-feed{font-size:11px;}
.activity-item{padding:8px;background:rgba(255,255,255,0.02);border-radius:8px;margin-bottom:8px;border-left:2px solid var(--accent);}
.status-dot.error{background:var(--err);}

/* Live View Panel */
.live-view-container{margin:12px;display:none;flex-direction:column;gap:8px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px;max-height:400px;overflow:hidden;}
.live-view-container.active{display:flex;}
.live-view-title{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;display:flex;justify-content:space-between;align-items:center;}
#liveImage{width:100%;height:auto;border-radius:8px;background:#000;object-fit:contain;}
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
  state.ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==="task_update")upsert(m.payload);else if(m.type==="task_list"){state.tasks=m.payload;render();}else if(m.type==="engine_status"){state.engines=m.payload;renderEngines();}else if(m.type==="audit_event")addActivity(m.payload);else if(m.type==="live_view")updateLiveView(m.payload);else if(m.type==="install_progress")addActivity({timestamp:new Date().toISOString(),event_type:"install",detail:m.payload.engine+": "+m.payload.message});};
}
function updateLiveView(p){
  const c=document.getElementById("liveView");
  const i=document.getElementById("liveImage");
  c.classList.add("active");
  i.src="data:image/png;base64,"+p.image;
}
function toggleSidebar(side){
  const l=document.getElementById("mainLayout");
  const a=side==='left'?l.querySelector('aside:first-child'):l.querySelector('aside:last-child');
  const cls=side==='left'?'left-collapsed':'right-collapsed';
  const isBoth=l.classList.contains('left-collapsed')&&l.classList.contains('right-collapsed')||(l.classList.contains(side==='left'?'right-collapsed':'left-collapsed')&&!l.classList.contains(cls));
  
  l.classList.toggle(cls);
  a.classList.toggle('collapsed');
  
  if(l.classList.contains('left-collapsed')&&l.classList.contains('right-collapsed')) l.classList.add('both-collapsed');
  else l.classList.remove('both-collapsed');
  
  localStorage.setItem('sidebar_'+side, a.classList.contains('collapsed'));
}
function upsert(t){const i=state.tasks.findIndex(x=>x.id===t.id);if(i>=0)state.tasks[i]=t;else state.tasks.push(t);render();}
async function submit(){
  const prompt=document.getElementById("prompt").value.trim();if(!prompt)return;
  const engine=document.getElementById("engine").value;
  const btn=document.getElementById("submitBtn");btn.disabled=true;
  try {
    await api("POST","/api/tasks",{prompt,engine});
    document.getElementById("prompt").value="";
    // Auto-resize textarea back to original
    document.getElementById("prompt").style.height = "auto";
  } finally {
    btn.disabled=false;
  }
}
async function cancel(id){await api("PATCH","/api/tasks/"+id,{action:"cancel"});}
function esc(s){if(!s)return"";const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function render(){
  const c=document.getElementById("taskList");const n=document.getElementById("taskCount");
  n.textContent=state.tasks.length+" task(s)";
  if(!state.tasks.length){c.innerHTML='<p style="color:var(--muted);text-align:center;padding:40px">Send a message to start.</p>';return;}
  
  // Render in reverse so flex-direction:column-reverse works (newest at bottom)
  const items = [...state.tasks].sort((a,b)=>new Date(b.created_at)-new Date(a.created_at));
  
  c.innerHTML=items.map(t=>{
    let r="",err="",ctl="";
    if(t.result&&t.result.summary)r='<div class="task-result">'+esc(t.result.summary)+'</div>';
    if(t.error)err='<div style="color:var(--err);margin-top:8px;font-weight:bold">'+esc(t.error)+'</div>';
    if(t.status==="running")ctl='<button class="btn" style="margin-top:8px;padding:4px 12px;font-size:11px" onclick="cancel(\\''+t.id+'\\')">Stop</button>';
    return `
      <div class="task-item">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:4px">
          <span style="font-weight:600">${esc(t.prompt)}</span>
          <span class="task-badge ${t.status}">${t.status}</span>
        </div>
        <div style="font-size:11px;color:var(--muted)">${new Date(t.created_at).toLocaleTimeString()} | ${t.engine}</div>
        ${ctl}${r}${err}
      </div>`;
  }).join("");
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
  
  // Restore sidebar states
  if(localStorage.getItem('sidebar_left')==='true') toggleSidebar('left');
  if(localStorage.getItem('sidebar_right')==='true') toggleSidebar('right');

  refreshConfig();
  connect();
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
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <button class="toggle-btn" onclick="toggleSidebar('left')" title="Toggle Sidebar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="11 17 6 12 11 7"></polyline><polyline points="18 17 13 12 18 7"></polyline></svg>
        </button>
      </div>
      <div class="collapsed-icons">
        <div onclick="toggleSidebar('left')" title="Engines">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Configuration">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
        </div>
      </div>
      <div class="card">
        <h2>
          <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>
          Engines
        </h2>
        <div id="engineList"><p class="muted">Loading...</p></div>
      </div>
      <div class="card">
        <h2>
          <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
          Config
        </h2>
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
      </div>
    </aside>
    <main>
      <div class="chat-header">
        <h2 style="font-size:14px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)">Chat & Tasks</h2>
        <span id="taskCount" style="font-size:12px;color:var(--muted)">0 tasks</span>
      </div>
      <div id="liveView" class="live-view-container">
        <div class="live-view-title">
          <span>Live Browser View</span>
          <button class="btn" style="padding:2px 8px;font-size:10px;background:var(--border)" onclick="document.getElementById('liveView').classList.remove('active')">Hide</button>
        </div>
        <img id="liveImage" src="" alt="Live Browser Feed">
      </div>
      <div id="taskList" class="task-list">
        <p style="color:var(--muted);text-align:center;padding:40px">Send a message to start.</p>
      </div>
      <div class="input-area">
        <form id="taskForm" class="input-container">
          <div style="flex-shrink:0;">
            <select id="engine" style="width:120px;padding:10px">
              <option value="auto">Auto</option>
              <option value="browser_use">browser-use</option>
              <option value="openclaw">OpenClaw</option>
            </select>
          </div>
          <textarea id="prompt" placeholder="Send a message..." rows="1"></textarea>
          <button type="submit" class="btn" id="submitBtn">Send</button>
        </form>
      </div>
    </main>
    <aside id="rightSidebar">
      <div style="display:flex;justify-content:flex-start;margin-bottom:12px;">
        <button class="toggle-btn" onclick="toggleSidebar('right')" title="Toggle Sidebar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline></svg>
        </button>
      </div>
      <div class="collapsed-icons">
        <div onclick="toggleSidebar('right')" title="Activity Feed">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
        </div>
      </div>
      <div class="card" style="flex:1;display:flex;flex-direction:column;overflow:hidden">
        <h2>
          <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
          Activity
        </h2>
        <div id="activityFeed" class="activity-feed" style="overflow-y:auto;flex:1">
          <p class="muted">Recent events will appear here.</p>
        </div>
      </div>
    </aside>
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
