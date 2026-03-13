# ClawBridge

**Bridge Open-Source AI Agents to Your Desktop & Browser**

ClawBridge is a local-first AI agent platform that unifies multiple automation engines — [browser-use](https://github.com/browser-use/browser-use), [OpenClaw](https://openclaw.ai), and Anthropic computer-use — into a single dashboard with task management, live streaming, and safety controls.

Submit a task, pick an engine (or let Auto choose), and watch it run. Everything stays on your machine — or bridge to the cloud.

**Version:** 0.5.3 | [Website](https://clawbridge.ai) | [Changelog](CHANGELOG.md) | [Discord](https://discord.gg/7QeQ3WsZ)

---

## Repository

**GitHub:** [NickRomanek/clawbridge](https://github.com/NickRomanek/clawbridge)

## Installation

### Windows Installer (Recommended)

Download `ClawBridge-Setup.exe` and run it. The installer:

1. Installs ClawBridge to `C:\Program Files\ClawBridge` (or user folder)
2. Bundles Python 3.12, Playwright, and all dependencies
3. Creates Start Menu shortcuts
4. Optionally installs OpenClaw engine (can also install later from dashboard)
5. Creates `.env` from template on first run
6. Shows a progress bar during post-install setup (Playwright download, engine config)

**Optional installer tasks**:
- **Desktop shortcut**: Quick access from your desktop
- **Start with Windows**: Auto-launch on login
- **Install OpenClaw**: Adds memory & skills support (recommended for power users)

After installation, launch ClawBridge from the Start Menu and open **http://127.0.0.1:8765** in your browser.

### macOS Installer (Coming Soon)

macOS support is in development. The platform abstraction layer is complete, but the macOS build is not yet production-ready. Stay tuned for updates.

### Quick Start (Single File)

The monolith `clawbridge.py` is the primary entry point — one file, no package structure needed:

```bash
pip install fastapi uvicorn pydantic python-dotenv httpx websockets anthropic pyautogui mss pillow pywinauto pynput
# Copy .env.example to .env and add at least one API key
cp .env.example .env
python clawbridge.py
```

Opens **http://127.0.0.1:8765** — the ClawBridge Dashboard.

## Quick Start (Docker)

```bash
git clone <repo-url>
cd clawbridge
cp .env.example .env
# Edit .env -- add at least one API key
docker-compose up
```

Open **http://localhost:8765** in your browser.

## Quick Start (Manual Package Install)

Requires: Python 3.11+, Node 22+ (for OpenClaw)

```bash
cp .env.example .env
# Edit .env -- add at least one API key
pip install -e .
python -m clawbridge
```

---

## Getting Started

When you first open ClawBridge, you'll see a **Getting Started** checklist to help you set up:

### 1. Configure an API Key

ClawBridge requires at least one LLM provider API key. Get yours here:

| Provider | Get Key | Used By |
|----------|---------|---------|
| **Anthropic** | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) | browser-use, computer-use |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | browser-use |
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | All engines (proxy) |

Add your key in the dashboard's Config panel or edit `.env` directly.

### 2. Set Your Identity (Optional)

Customize the agent's personality by editing `workspace/memory/IDENTITY.md`. This gives the AI context about who it's helping.

### 3. Run Your First Task

Type a task in the chat input and press Enter:
- **Web task**: "Search Google for ClawBridge AI"
- **Desktop task**: "Open Notepad and write Hello World"
- **Research task**: "What are the top 3 news stories today?"

### 4. Launch Browser Engine

For authenticated web tasks (tasks that need your logins), click **Launch Chrome Session** in the Config panel. This opens Chrome with a persistent profile where you can sign into your accounts once.

---

## Architecture

ClawBridge has two deployment forms that share the same logic:

| Form | File | Use Case |
|------|------|----------|
| **Monolith** | `clawbridge.py` (~12,700 lines) | Primary. Single file, easy to share/deploy |
| **Package** | `clawbridge/` directory | Modular. For development, testing, extensibility |

### How It Works

```
User → Dashboard (http://127.0.0.1:8765)
         ↓
    Task Manager (routes, queues, concurrency)
         ↓
    Engine Selection (auto or manual)
         ↓
  ┌──────┼──────────┐
  ↓      ↓          ↓
browser-use  computer-use  OpenClaw
(Playwright)  (pyautogui)   (Node.js CDP)
                 ↑
           Perception Layer
           (screenshot + UIA accessibility)
                 ↑
           Recorder / Replay
           (pynput capture → adaptive replay)
  ↓      ↓          ↓
  └──────┼──────────┘
         ↓
    Live View (WebSocket screenshots)
    Audit Log (SQLite)
    Result Synthesis
```

---

## Engines

| Engine | Technology | Best For | Status |
|--------|-----------|----------|--------|
| **browser-use** | Python + Playwright | Web automation, extraction, form filling | Working |
| **computer-use** | Anthropic API + pyautogui + mss + pywinauto | Full desktop control — any app, any window | Working (accessibility-first navigation) |
| **OpenClaw** | Node.js + Chrome DevTools Protocol | AI agent with persistent memory & skills | Requires separate install (`npm i -g openclaw`) |

### Engine Selection (Smart Auto Routing)

ClawBridge uses intelligent engine selection to pick the best engine for each task:

| Task Type | Routes To | Detection |
|-----------|-----------|-----------|
| **Web tasks** | browser-use | URLs, "search", "browse", "navigate", web domains |
| **Desktop tasks** | computer-use | App names (notepad, excel, telegram), "click", "open app", "desktop" |
| **General tasks** | openclaw | Fallback for conversational/research tasks |

- **Auto mode** (default): Smart selection based on URL patterns and keyword detection
- **Manual mode**: User picks engine explicitly from dropdown
- **Economy mode**: Toggle Performance/Economy to use cheaper models (gpt-4o-mini for browser-use, Haiku for replay steps)

### Computer-Use Engine Details

The computer-use engine controls the full desktop via screenshots + mouse/keyboard. Key features:

- **Accessibility-first navigation**: Uses Windows UIA (via pywinauto) to enumerate interactive elements. Model clicks by element ID instead of guessing pixel coordinates — far more reliable.
- **Dual screenshot strategy**: Sends full screen (for coordinates) + zoomed crop of foreground window (for reading text)
- **Auto-focus**: Detects target app from prompt and brings it to foreground before starting
- **DPI-aware**: Calls `SetProcessDPIAware()` so all coordinate systems (pyautogui, mss, GetWindowRect) are consistent
- **Forced reasoning**: Model must follow `[OBSERVE]/[GOAL]/[PLAN]/[ACTION]` protocol before every action
- **Stale detection**: Perceptual hash comparison warns when screenshots don't change after an action
- **Hybrid mechanical + AI execution**: Deterministic actions (app launch, URL navigation, typing) handled programmatically at zero AI cost. AI only invoked when visual reasoning is needed.
- **Mechanical pre-navigation**: Extracts URLs from prompts and navigates deterministically via `webbrowser.open_new()` or `Ctrl+L` hotkeys before AI engagement — saves an entire round of LLM reasoning.
- **Vision fallback**: When UIA tree returns < 5 elements (Electron apps, games, custom UIs), a fast vision model identifies UI elements from the screenshot. Results merged with UIA elements via 30-pixel deduplication.
- **Dual API path**: Direct Anthropic API uses native `computer_20250124`/`computer_20251124` tools; OpenRouter uses function-tool schema. Configurable via `COMPUTER_USE_API` setting.
- **Smart model routing**: Uses Haiku for routine replay steps, Sonnet for complex ones — ~50% cost savings
- **Prompt caching**: System prompt cached after first API call in multi-step tasks — 50-90% input token savings
- **Workflow recording & replay**: Record desktop actions via pynput, save as workflows, replay adaptively with confidence-tiered execution (mechanical/verification/AI), element matching, and LLM fallback (see [Workflow Recording](#workflow-recording--replay))

### Browser-Use Engine Details

- **Headless mode**: Runs Chromium in background, no visible browser
- **CDP mode**: Connects to an existing Chrome via `--remote-debugging-port=9222`
- **User Data Dir mode**: Persistent Chrome profile with stored logins
- **Launch Chrome Session**: Dashboard button launches Chrome with persistent profile at `%LOCALAPPDATA%\ClawBridge\ChromeProfile`

---

## Workflow Recording & Replay

ClawBridge can record your desktop actions and replay them adaptively — even when UI elements move or change.

### Recording

**From Chat** (recommended):
1. Click **Record** in the chat input bar (or type `/record`)
2. Perform your desktop actions (clicks, typing, keyboard shortcuts)
3. Click **Stop** (or type `/stop`) — a save card appears with a pre-filled name
4. Click **Save** or customize the name first

**From Workflows Tab**:
1. Navigate to the **Workflows** tab
2. Click **Start Recording** — a red indicator and timer appear
3. Perform your desktop actions
4. Click **Stop Recording** — enter a name and save

### Replay

- Click **Replay** on any saved workflow, or type `/replay Workflow Name` in chat
- **Confidence-tiered execution**: Each action scored automatically:
  - **>= 0.95**: Pure mechanical replay (free, instant)
  - **0.7 - 0.95**: Mechanical + visual verification (window title, perceptual hash, LLM check)
  - **< 0.7**: AI-powered replay via LLM with screenshot context
- **Element matching** via accessibility tree comparison:
  1. **automation_id exact match** (confidence 1.0)
  2. **name + type + parent** (0.95)
  3. **name + type** (0.85)
  4. **type + proximity** (0.6)
- **Adaptive timing**: Polls UIA tree stability instead of fixed delays
- **Outcome learning**: Tracks success/failure per step. After 3+ mechanical successes, promotes to high confidence. After repeated failures, demotes to AI replay.
- Auto-detects target app from recorded window titles, process names, and known app signatures
- Handles app launch patterns (Win key, search, Enter)

### Parameterized Replay

- After recording, ClawBridge can detect typed text that varies between runs (search queries, filenames, etc.)
- Save parameter defaults and run with custom values each time
- Dashboard shows parameter input form with Save/Run buttons
- Safety-scanned per parameter value

### Perception Layer

The recording system is backed by a standalone perception module (`clawbridge/perception/`):

- **Screenshot utilities**: Async full-screen and window-crop capture, perceptual similarity comparison
- **Accessibility tree**: Enhanced pywinauto UIA wrapper with `ElementSnapshot` dataclass, multi-strategy element matching
- **A11y enrichment at record time**: Click events enriched with element metadata from UIA tree while correct window is in focus

---

## Dashboard

The web dashboard at `http://127.0.0.1:8765` provides:

- **Chat interface**: Submit tasks, see results in a message-bubble layout with inline cost/duration info
- **Engine selector**: Chip bar (Auto / Browser / Desktop / Chat) with tooltips
- **Slash commands**: Type `/` for autocomplete dropdown — `/record`, `/stop`, `/replay <name>`, `/do <number>`, `/browser`, `/computer`, `/chat`
- **Stop button**: Send button swaps to red Stop while a task is running — always visible, one-click cancel
- **Workflow recording from chat**: Click Record, perform actions, click Stop — save card appears with pre-filled name
- **Live View**: Real-time screenshot stream from browser or desktop
- **Engine status**: See which engines are available/running/errored
- **Config panel**: API key management, browser session controls, machine ID
- **Activity feed**: Audit trail of every action taken
- **Workflows tab**: Record, save, and replay desktop workflows
- **Soul/Memory tabs**: Edit agent personality and view memory logs

## Configuration

All configuration lives in `.env`. See `.env.example` for the full list.

### API Keys (BYOK)

You need at least one:

| Key | Provider | Used By |
|-----|----------|---------|
| `ANTHROPIC_API_KEY` | Anthropic (direct) | browser-use, computer-use |
| `OPENAI_API_KEY` | OpenAI | browser-use |
| `OPENROUTER_API_KEY` | OpenRouter (proxy) | computer-use, browser-use |

### Key Settings

```env
# Server
CLAWBRIDGE_HOST=127.0.0.1
CLAWBRIDGE_PORT=8765

# Engines
ENABLED_ENGINES=browser_use,computer_use    # comma-separated
DEFAULT_MODEL=openai/gpt-4o                 # for browser-use

# Computer-Use
COMPUTER_USE_MODEL=anthropic/claude-sonnet-4.5   # primary model
COMPUTER_USE_MODEL_FAST=anthropic/claude-haiku-4-5  # cheap model for routine replay
COMPUTER_USE_API=auto                            # auto | direct | openrouter
COMPUTER_USE_MAX_SCREEN_WIDTH=1920
COMPUTER_USE_MAX_SCREEN_HEIGHT=1080
COMPUTER_USE_ACTION_DELAY_MS=500

# Economy Mode
ECONOMY_MODEL=                                   # optional: google/gemini-flash-2.0

# Recording
RECORDING_SCREENSHOTS=true
RECORDING_INTENT_EXTRACTION=true
SCREENPIPE_INTEGRATION=true

# Browser
BROWSER_HEADLESS=true
BROWSER_MODE=default                        # default | cdp | user_data_dir
BROWSER_CDP_URL=http://localhost:9222
BROWSER_USER_DATA_DIR=

# Policy
POLICY_MODE=guarded                         # guarded | permissive | strict
MAX_CONCURRENT_TASKS=3
MAX_ACTIONS_PER_TASK=50

# Remote Bridge (beta)
REMOTE_BRIDGE_URL=
REMOTE_AUTH_TOKEN=
```

## Automation Modes

ClawBridge supports two automation modes to balance speed vs. safety:

| Mode | Behavior | Best For |
|------|----------|----------|
| **Supervised** (default) | Pauses for approval before high-risk actions | Financial tasks, unfamiliar workflows, production systems |
| **Autonomous** | Runs without interruption | Trusted tasks, development, demos |

### Supervised Mode Features

When running in Supervised mode, ClawBridge automatically detects and pauses for:

**Sensitive Domains** (banking, shopping, cloud admin):
- Banking: chase.com, bankofamerica.com, wellsfargo.com, paypal.com, etc.
- Shopping: amazon.com, ebay.com, walmart.com checkout pages
- Cloud: console.aws.amazon.com, portal.azure.com, console.cloud.google.com
- Email: gmail.com, outlook.com (compose/send actions)

**High-Risk Actions**:
- Purchases and payments (`buy`, `purchase`, `checkout`, `pay`)
- Form submissions (`submit`, `confirm`, `send`)
- Deletions (`delete`, `remove`, `clear`)
- Account changes (`password`, `settings`, `account`)

When a high-risk action is detected:
1. Task pauses and shows an approval modal in the dashboard
2. You see exactly what action the AI wants to take
3. Click **Approve** to proceed or **Deny** to block
4. 2-minute timeout auto-denies if no response

### Changing Modes

**From Dashboard**: Use the Automation Mode toggle in the Config panel

**From .env**:
```env
AUTOMATION_MODE=supervised   # or: autonomous
```

**Tip**: Start with Supervised mode until you're comfortable with the AI's behavior, then switch to Autonomous for trusted workflows.

---

## Security

- All data stays on your machine in local mode. No cloud egress.
- API keys are never logged or transmitted.
- **Dashboard authentication**: Token-based auth with HttpOnly cookie, CSRF token protection on all state-changing endpoints.
- **WebSocket authentication**: Token verified before connection is accepted.
- Actions classified as safe/sensitive/high-risk with configurable policy.
- Sensitive domain detection (banking, cloud consoles) auto-elevates risk level.
- Credential and PII detection with automatic redaction before memory storage.
- Prompt injection pattern detection and filtering in stored memory.
- Path traversal protection on personality file endpoints.
- Remote bridge requires HTTPS for non-localhost URLs.
- XSS protection via DOMPurify with safe fallback.
- Full audit trail in SQLite database.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Dashboard UI |
| `GET` | `/health` | Health check |
| `POST` | `/api/tasks` | Create task |
| `GET` | `/api/tasks` | List all tasks |
| `GET` | `/api/tasks/{id}` | Get single task |
| `PATCH` | `/api/tasks/{id}` | Pause/resume/cancel |
| `DELETE` | `/api/tasks/{id}` | Remove task |
| `DELETE` | `/api/tasks` | Clear all tasks |
| `GET` | `/api/tasks/{id}/steps` | Get step-by-step replay |
| `GET` | `/api/engines` | List engines + status |
| `POST` | `/api/engines/openclaw/install` | Install OpenClaw engine |
| `GET` | `/api/config` | Get config (keys redacted, includes version) |
| `POST` | `/api/config/keys` | Save API keys to .env |
| `POST` | `/api/config/automation` | Set automation mode (supervised/autonomous) |
| `POST` | `/api/browser/launch` | Launch Chrome with CDP |
| `GET` | `/api/browser/status` | Check Chrome connection |
| `GET` | `/api/schedules` | List task schedules |
| `POST` | `/api/schedules` | Create recurring schedule |
| `DELETE` | `/api/schedules/{id}` | Delete schedule |
| `GET` | `/api/templates` | List task templates |
| `POST` | `/api/templates` | Create task template |
| `GET` | `/api/workflows` | List saved workflows |
| `GET` | `/api/workflows/{id}` | Get workflow details |
| `POST` | `/api/workflows` | Create workflow from recorded actions |
| `DELETE` | `/api/workflows/{id}` | Delete workflow |
| `POST` | `/api/workflows/{id}/replay` | Trigger workflow replay |
| `POST` | `/api/workflows/{id}/replay-parameterized` | Replay with parameter substitution |
| `POST` | `/api/workflows/{id}/save-params` | Save parameter defaults |
| `POST` | `/api/workflows/{id}/extract-intent` | Trigger intent extraction |
| `POST` | `/api/config/model-tier` | Switch Performance/Economy mode |
| `POST` | `/api/config/computer-use-api` | Switch API path (Auto/Direct/OpenRouter) |
| `POST` | `/api/recording/start` | Start desktop recording |
| `POST` | `/api/recording/stop` | Stop recording, return actions |
| `POST` | `/api/auth/login` | Authenticate and set HttpOnly session cookie |
| `WS` | `/ws` | WebSocket (tasks, frames, audit, approvals, workflows) |

### WebSocket Events

| Event Type | Direction | Description |
|------------|-----------|-------------|
| `task_update` | Server → Client | Task status change |
| `browser_frame` | Server → Client | Screenshot stream (base64) |
| `audit_event` | Server → Client | Audit log entry |
| `approval_request` | Server → Client | High-risk action needs approval |
| `approval_response` | Client → Server | User approves/denies action |
| `approval_ack` | Server → Client | Confirmation of approval processing |
| `recording_status` | Server → Client | Recording started/stopped status |
| `recording_result` | Server → Client | Recorded actions after stop |
| `workflow_update` | Server → Client | Workflow list changed |
| `workflow_saved` | Server → Client | Workflow saved confirmation |
| `replay_started` | Server → Client | Workflow replay task created |
| `recording_event` | Server → Client | Live action during recording |
| `engine_status` | Server → Client | Engine status/model info changed |
| `config_update` | Server → Client | Configuration setting changed |
| `safety_warning` | Server → Client | Safety scan flag detected |

## Remote Bridge (Beta)

ClawBridge can connect to a remote orchestration service:

- Set `REMOTE_BRIDGE_URL` and `REMOTE_AUTH_TOKEN` in `.env`
- Local instance polls remote for tasks every 10 seconds
- Each machine identified by persistent `clawbridge.id` (UUID)
- Remote tasks execute locally, results flow back
- Dashboard shows "Bridge Online/Offline" status

This enables the **bridge architecture**: local machines provide the "hands" (desktop/browser access), remote service provides the "brain" (task orchestration, hosted engines).

## Project Structure

```
clawbridge.py                 # Monolith — primary entry point (~12,700 lines)
clawbridge_mcp.py             # MCP server (stdio/HTTP proxy to REST API)
clawbridge/
  config.py                   # Settings & BYOK key management
  engines/
    base.py                   # EngineBase abstract interface
    browser_use_engine.py     # Playwright-based web automation
    computer_use_engine.py    # Desktop control via Anthropic API
    openclaw_engine.py        # Node.js CDP agent
  perception/                 # Perception layer
    screenshot.py             # Async screenshot utilities
    accessibility.py          # Platform-aware accessibility wrapper
  recorder/                   # Workflow recording
    capture.py                # pynput mouse/keyboard capture
    processor.py              # Raw event → enriched action processing
  platform/                   # Platform abstraction layer (v0.5.0)
    _base.py                  # 14 abstract methods
    _windows.py               # ctypes/pywinauto backend
    _macos.py                 # PyObjC/AXUIElement backend
    _linux.py                 # Stub (placeholder)
  orchestrator/
    manager.py                # Task lifecycle, engine routing
  server/
    app.py                    # FastAPI app factory
    routes/
      tasks.py                # Task CRUD endpoints
      engines.py              # Engine status endpoints
      config_routes.py        # Config & key management
      ws.py                   # WebSocket streaming
  policy/
    safety.py                 # Action classification, injection detection
  telemetry/
    logger.py                 # Audit logging to SQLite
  shared/
    schemas.py                # Pydantic models
build.py                      # Portable Windows build system
build_macos.py                # macOS DMG build (arm64/x64)
installer.iss                 # Inno Setup installer script
.env.example                  # Configuration template
.mcp.json                     # MCP server registration for Claude Code
```

## MCP Server

ClawBridge exposes its full API as an MCP (Model Context Protocol) server, enabling integration with Claude Code, Cursor, and other MCP-compatible tools.

```bash
# Register with Claude Code
claude mcp add clawbridge -- python clawbridge_mcp.py

# Or run standalone with HTTP transport
python clawbridge_mcp.py --http
```

**15 tools** available: `run_task`, `get_task_status`, `list_tasks`, `cancel_task`, `list_engines`, `get_task_steps`, `get_task_audit`, `search_memory`, `get_agent_context`, `append_memory`, `list_schedules`, `create_schedule`, `get_config`, `get_license_info`, `list_workflows`

See `.mcp.json` for project-level registration.

---

## Roadmap

### Completed
- [x] Dashboard UI overhaul (chat interface, activity feed, live view)
- [x] Smart engine selection with URL/keyword auto-routing
- [x] OpenClaw one-click install from dashboard
- [x] Windows installer via Inno Setup with progress bar
- [x] Onboarding checklist for first-time users
- [x] Task scheduling and templates
- [x] Personality/memory system
- [x] Step-level streaming and task replay
- [x] Dashboard authentication (token-based)
- [x] Real-time cost tracking
- [x] Error recovery with exponential backoff
- [x] MCP server mode (15 tools, stdio + HTTP)
- [x] Supervised/Autonomous automation modes
- [x] Workflow recording & replay with perception layer
- [x] Security hardening Phase 1 & 2 (CSRF, path traversal, XSS, auth, key combo blocklist)
- [x] Slash command autocomplete with workflow name suggestions
- [x] Always-visible Stop button during task execution
- [x] Computer-use focus verification (retry + LLM feedback)
- [x] Ultrawide monitor support (active window crop as primary screenshot)
- [x] Browser-use extraction-aware prompting (page content fallback)
- [x] Chat-integrated workflow save (record from chat, save with one click)
- [x] E2E test suite (33 tests covering dashboard, cancel, engines, replay)
- [x] Smart model routing (Haiku for routine steps, Sonnet for complex)
- [x] Economy mode (Performance/Economy toggle, gpt-4o-mini for browser-use)
- [x] Prompt caching (50-90% input token savings on multi-step tasks)
- [x] Workflows tab in sidebar
- [x] Enhanced recording (live action feed, a11y enrichment, screenshots, intent extraction)
- [x] Direct Anthropic API for computer-use (dual API path with tool versioning)
- [x] AI-powered replay (confidence-tiered execution, visual verification, outcome learning)
- [x] Workflow parameterization (variable detection, parameter inputs, save defaults)
- [x] Model details panel and API path toggle in dashboard
- [x] Licensing & activation system with Stripe integration
- [x] Apache 2.0 license and Contributor License Agreement
- [x] Task queue promotion, task-level timeouts, redirect detection (v0.4.0)
- [x] Personality context gating, stale action hard-stop, fallback-before-retry (v0.4.0)
- [x] macOS support with platform abstraction layer and PyObjC backend (v0.5.0)
- [x] macOS DMG distribution for arm64 and x64 (v0.5.0)
- [x] App-mode browser launch (chromeless window) (v0.5.0)
- [x] Scaffolding profile system (full/standard/minimal/raw) (v0.5.0)
- [x] Multi-engine task orchestration with LLM planner (v0.5.2)
- [x] Hybrid DOM + Visual engine (CDP bridge tools on computer-use) (v0.5.2)
- [x] Auto-launch Chrome with CDP for browser-use (anti-bot avoidance) (v0.5.2)
- [x] Planner sanity checks (URL-in-prompt always routes to browser) (v0.5.2)

### What's Next

- Reliability improvements: self-verification loops, better element matching, cross-workflow learning
- Distribution: auto-update, template gallery, community launch
- Integrations and extensibility

## Contributing

We welcome contributions! Here's how:

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make your changes and test them
4. Commit (`git commit -m "Add my feature"`)
5. Push and open a PR

Please open an issue first for large changes so we can discuss the approach.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Copyright (c) 2026 RomaTek AI.
