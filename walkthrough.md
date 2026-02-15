# ClawBridge - Implementation Walkthrough & Status Tracker

**Last updated:** February 2026
**Version:** 0.2.0
**Repository:** [NickRomanek/clawbridge](https://github.com/NickRomanek/clawbridge)
**Branch:** main

---

## Completed Work

### Phase 1: Core Scaffolding
**Status: COMPLETE**

- Python package structure (`clawbridge/`) with modular architecture
- Configuration management (`config.py`) using Pydantic BaseSettings with BYOK key support
- Shared schemas (`shared/schemas.py`) -- Pydantic models for Task, TaskStep, TaskResult, PolicyDecision, AuditEvent, WSMessage, and all supporting types
- Enums: TaskStatus (8 states), EngineName, ActionClass, PolicyMode, EngineStatus
- `.env` support with `.env.example` template

### Phase 2: Engine Integration
**Status: COMPLETE**

- Abstract engine interface (`engines/base.py`) -- EngineBase ABC with initialize/execute_step/run_task/stop/get_status
- **browser-use engine** (`engines/browser_use_engine.py`) -- Playwright-based automation using native `browser_use.llm` wrappers (ChatAnthropic, ChatOpenAI, ChatOpenRouter). Supports headless mode, viewport config, screenshot broadcasting.
- **computer-use engine** (`engines/computer_use_engine.py`) -- Full desktop automation via Anthropic API + pyautogui + mss + pywinauto. Features:
  - Accessibility-first navigation using Windows UIA
  - Dual screenshot strategy (full screen + zoomed foreground window)
  - DPI-aware coordinate systems
  - Forced reasoning protocol: `[OBSERVE]/[GOAL]/[PLAN]/[ACTION]`
  - Stale detection via perceptual hash comparison
  - OpenRouter compatibility with function-tool schema fallback
- **OpenClaw engine** (`engines/openclaw_engine.py`) -- Node.js + CDP adapter. Manages gateway subprocess lifecycle, communicates via HTTP API, supports BYOK key passthrough.
- **Smart engine selection** -- Auto-detects desktop vs web tasks:
  - Desktop tasks: computer-use → browser-use → OpenClaw
  - Non-desktop tasks: OpenClaw → browser-use → computer-use (prefers memory/skills)
- LLM provider migration from LangChain wrappers to native browser-use wrappers (resolved `"ChatOpenAI" object has no field "provider"` error)

### Phase 3: Orchestration, Persistence & Safety
**Status: COMPLETE**

- **TaskManager** (`orchestrator/manager.py`) -- singleton task lifecycle management with concurrency limits, queue processing, engine selection (auto prefers browser-use), WebSocket broadcasting
- **Policy engine** (`policy/safety.py`) -- 3-tier action classification (safe_read/sensitive_write/high_risk), 3 policy modes (guarded/permissive/strict), sensitive content detection (credentials, PII, password fields), credential redaction, prompt injection scanning
- **Audit logger** (`telemetry/logger.py`) -- ring buffer (500 events) for live dashboard feed, JSONL file persistence, WebSocket subscriber notification, sensitive content redaction before writing
- **SQLite persistence** -- task history in `clawbridge.db`, survives server restarts
- **Machine identity** -- UUID in `clawbridge.id` for future remote bridge identification
- **Remote bridge polling** -- background service for `REMOTE_BRIDGE_URL` / `REMOTE_AUTH_TOKEN` support

### Phase 4: Server, Dashboard & UI
**Status: COMPLETE**

- **FastAPI server** (`server/app.py`) -- factory pattern with async lifespan, CORS, static file serving
- **REST API routes:**
  - `POST /api/tasks` -- submit task with prompt + engine selection
  - `GET /api/tasks` -- list all tasks (newest first)
  - `GET /api/tasks/{id}` -- get task details
  - `PATCH /api/tasks/{id}` -- pause/resume/cancel
  - `DELETE /api/tasks/{id}` -- remove task
  - `GET /api/engines` -- list engine status
  - `GET /api/engines/{name}` -- specific engine info
  - `GET /api/config` -- configuration summary (keys redacted)
  - `GET /api/config/keys` -- key presence status
  - `GET /api/config/policy` -- policy mode details
  - `GET /api/config/audit` -- recent audit events
  - `GET /health` -- health check
- **WebSocket** (`/ws`) -- real-time events:
  - `task_update`: task status changes
  - `browser_frame`: screenshot stream (base64)
  - `audit_event`: audit log entries
  - `approval_request`: high-risk action needs approval (Supervised mode)
  - `approval_response`: user approves/denies action
  - `approval_ack`: confirmation of approval processing
  - ping/pong keepalive
- **Web dashboard** -- modern chat-like interface with:
  - Message bubbles with markdown rendering (marked.js, GFM support)
  - Engine selector dropdown with status indicators
  - Collapsible sidebar sections (ENGINES, CONFIG, BROWSER, etc.)
  - Config panel with green/gray status chips
  - Live browser screenshot panel with idle detection
  - Color-coded activity feed with event type borders
  - Task history tab with filtering and expandable rows
  - Onboarding checklist (Getting Started card with progress bar)
  - Approval modal for Supervised mode high-risk actions
  - Automation Mode toggle (Supervised/Autonomous)
  - Connection status indicator
  - Modern dark theme with gradients and premium aesthetics
- **Docker support** -- Dockerfile + docker-compose.yml with optional OpenClaw service
- **Cross-platform setup** -- `setup.sh` (Unix) + `setup.ps1` (Windows)
- **Single-file mode** -- `clawbridge.py` (~6,200 lines) as standalone distributable with embedded HTML/CSS/JS dashboard

### Phase 5: Automation Modes & Approval Workflow
**Status: COMPLETE**

- **Automation modes** -- Supervised (default) vs Autonomous:
  - Supervised: pauses for user approval before high-risk actions
  - Autonomous: runs without interruption
- **Approval workflow** (`ApprovalManager` class in `clawbridge.py`):
  - Uses asyncio.Future for blocking approval requests
  - WebSocket-based real-time approval request/response
  - 2-minute timeout with auto-deny
- **High-risk action detection**:
  - Sensitive domains: banking (chase.com, paypal.com, etc.), shopping (amazon.com checkout), cloud admin (AWS, Azure, GCP consoles), email (gmail, outlook)
  - High-risk patterns: purchases, form submissions, deletions, account changes
- **UI integration**:
  - Automation Mode toggle in Config panel
  - Approval modal with Approve/Deny buttons
  - Activity feed shows approval requests and responses

### Phase 6: Windows Installer & Packaging
**Status: COMPLETE**

- **build.py** -- Portable build system:
  - Embeds Python 3.12 from python.org
  - Bundles Playwright with Chromium browser
  - Optional Node.js + OpenClaw bundling
  - Creates `dist/ClawBridge/` portable folder
  - `--version` flag for version checking
- **installer.iss** -- Inno Setup script:
  - Installs to Program Files or user folder
  - Desktop shortcut (optional)
  - Start with Windows (optional)
  - Install OpenClaw (optional, can install later from dashboard)
  - Preserves .env and workspace on upgrade
  - Creates .env from template on first run
- **Output**: `dist/ClawBridge-Setup-0.2.0.exe` (~295 MB)
- **Post-install progress bar**: Visual progress through Playwright download, optional OpenClaw install, and workspace setup

### Phase 7: Workflow Recording & Perception Layer
**Status: COMPLETE**

- **Perception modules** (`clawbridge/perception/`):
  - `screenshot.py` -- async screenshot utilities (full screen, window crop, perceptual similarity)
  - `accessibility.py` -- enhanced pywinauto UIA wrapper with `ElementSnapshot` dataclass, 4-strategy element matching (automation_id → name+type+parent → name+type → proximity)
- **Recorder modules** (`clawbridge/recorder/`):
  - `capture.py` -- `InputRecorder` class using pynput mouse/keyboard listeners with per-event window title capture and keystroke coalescing
  - `processor.py` -- converts raw pynput events into enriched `RecordedAction` objects
- **Engine integration** (in `ComputerUseEngine`):
  - `start_recording()` / `stop_recording()` -- lazy-imports InputRecorder, captures and processes events
  - `replay_workflow()` -- adaptive replay loop with element matching, LLM fallback, auto target-app detection, and step broadcasting
  - `_find_matching_workflow()` -- safe matching via `replay: Name` prefix or exact name match (no substring false positives)
- **WorkflowManager** -- file-based JSON persistence in `workspace/workflows/`, follows TemplateManager pattern
- **Schemas**: `RecordedAction`, `WorkflowTemplate`, `ReplayState` Pydantic models; `workflows` SQLite table
- **REST routes**: 7 endpoints for workflow CRUD, replay, and recording start/stop
- **WebSocket handlers**: `recording_start`, `recording_stop`, `save_workflow`, `replay_workflow` with corresponding server→client events
- **Dashboard UI**: Workflows tab with record/stop toggle, timer, save form, workflow cards with replay/delete
- **Dependency**: `pynput>=1.7.6` added to requirements.txt and auto-install

### Infrastructure
**Status: COMPLETE**

- GitHub repository: `NickRomanek/clawbridge` (main branch)
- `.gitignore` configured (excludes .env, .db, .id, __pycache__, node_modules, logs)
- `LICENSE.txt` -- Proprietary RomaTek AI license with AI automation disclaimer
- `build.py` -- build automation for packaging
- `CHANGELOG.md` -- Keep a Changelog format with semantic versioning

---

## Current Gaps (To Address Next)

### Testing
- **Limited tests exist.** Basic integration tests only (workflow CRUD + recording endpoints tested, 13 pass).
- Highest-ROI targets: `schemas.py` (pure models), `safety.py` (pure functions), `config.py` (settings properties)
- Secondary: `manager.py` (async orchestration with mocked engines), API routes (FastAPI TestClient)
- Need approval workflow integration tests
- Need workflow replay integration tests with mock accessibility tree

### Polish
- browser-use engine runtime testing and stabilization
- Refine workflow replay element matching accuracy across different apps
- Test "Launch Chrome Session" persistent profile flow on various Windows versions
- Code signing certificate for Windows installer (eliminates SmartScreen warnings)

### Deferred Features (Post-Launch)
- Auto-update mechanism for Windows installer
- macOS build support
- Remote Bridge cloud service (multi-machine orchestration)
- Hosted engine backends (cloud browser-use, cloud OpenClaw)
- `pip install clawbridge` one-command setup
- Discord community for user support
- Video tutorials / YouTube walkthrough

### Original Spec (Not Planned for MVP)
- Tauri-based desktop agent (currently Python/FastAPI only)
- Cloudflare Tunnel integration
- Managed cloud browsing tier with domain allowlist enforcement
- Enterprise SSO & RBAC
- Advanced plugin framework
- Full browser replay/video stream
- Multi-tenant governance controls
- Signed command envelope for cloud-to-agent security
- Landing page and beta waitlist

---

## Architecture Summary

```
Web Dashboard (HTML/JS/CSS)
    |  WebSocket + REST
    |  (task_update, browser_frame, audit_event, approval_request)
FastAPI Server
    |
    +-- Task Routes (/api/tasks)
    +-- Engine Routes (/api/engines)
    +-- Config Routes (/api/config, /api/config/automation)
    +-- Schedule Routes (/api/schedules)
    +-- Template Routes (/api/templates)
    +-- Workflow Routes (/api/workflows, /api/recording)
    +-- WebSocket (/ws)
    |
TaskManager (orchestrator)
    |  Smart engine selection (auto-detects desktop vs web)
    |
    +-- BrowserUseEngine (Playwright + browser-use)
    +-- ComputerUseEngine (pyautogui + mss + pywinauto)
    |       +-- Workflow Recording (pynput capture)
    |       +-- Adaptive Replay (element matching + LLM fallback)
    |       +-- Perception Layer (screenshot + accessibility)
    +-- OpenClawEngine (Node.js + CDP gateway)
    |
    +-- WorkflowManager (file-based JSON persistence)
    +-- ApprovalManager (Supervised mode)
    |       |
    |       +-- High-risk action detection
    |       +-- WebSocket approval request/response
    |       +-- 2-minute timeout handling
    |
Policy Engine (safety.py)
    |
    +-- Action classification (safe/sensitive/high-risk)
    +-- Sensitive domain detection
    +-- Credential pattern scanning
    +-- Prompt injection detection
    |
Audit Logger (telemetry)
    |
    +-- SQLite persistence
    +-- JSONL file logging
    +-- WebSocket broadcast
```

## Technology Stack

| Layer | Technology |
|---|---|
| Server | FastAPI + Uvicorn |
| Validation | Pydantic 2.x |
| Browser automation | browser-use + Playwright |
| Desktop automation | pyautogui + mss + pywinauto (Windows UIA) |
| Workflow recording | pynput (mouse + keyboard capture) |
| Alt engine | OpenClaw (Node.js + CDP) |
| LLM providers | Anthropic, OpenAI, OpenRouter (BYOK) |
| Persistence | SQLite |
| Real-time | WebSocket |
| Config | pydantic-settings + .env |
| Logging | stdlib logging + JSONL audit trail |
| Markdown rendering | marked.js (GFM support) |
| Windows installer | Inno Setup |
| Build system | Python build.py (portable packaging) |
| Containerization | Docker + docker-compose |
