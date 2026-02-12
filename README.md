# ClawBridge

**Bridge Open-Source AI Agents to Your Desktop & Browser**

ClawBridge is a local-first AI agent platform that unifies multiple automation engines — [browser-use](https://github.com/browser-use/browser-use), [OpenClaw](https://openclaw.ai), and Anthropic computer-use — into a single dashboard with task management, live streaming, and safety controls.

Submit a task, pick an engine (or let Auto choose), and watch it run. Everything stays on your machine — or bridge to the cloud.

---

## Repository

**GitHub:** [NickRomanek/clawbridge](https://github.com/NickRomanek/clawbridge)

## Quick Start (Single File)

The monolith `clawbridge.py` is the primary entry point — one file, no package structure needed:

```bash
pip install fastapi uvicorn pydantic python-dotenv httpx websockets anthropic pyautogui mss pillow pywinauto
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

## Architecture

ClawBridge has two deployment forms that share the same logic:

| Form | File | Use Case |
|------|------|----------|
| **Monolith** | `clawbridge.py` (~2400 lines) | Primary. Single file, easy to share/deploy |
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
| **browser-use** | Python + Playwright | Web automation, extraction, form filling | Working (needs browser-use lib update) |
| **computer-use** | Anthropic API + pyautogui + mss + pywinauto | Full desktop control — any app, any window | Working (accessibility-first navigation) |
| **OpenClaw** | Node.js + Chrome DevTools Protocol | AI agent with persistent memory & skills | Requires separate install (`npm i -g openclaw`) |

### Engine Selection

- **Auto mode**: Analyzes the prompt — desktop keywords → computer-use, web keywords → browser-use, fallback → first available
- **Manual mode**: User picks engine from dropdown in dashboard

### Computer-Use Engine Details

The computer-use engine controls the full Windows desktop via screenshots + mouse/keyboard. Key features:

- **Accessibility-first navigation**: Uses Windows UIA (via pywinauto) to enumerate interactive elements. Model clicks by element ID instead of guessing pixel coordinates — far more reliable.
- **Dual screenshot strategy**: Sends full screen (for coordinates) + zoomed crop of foreground window (for reading text)
- **Auto-focus**: Detects target app from prompt and brings it to foreground before starting
- **DPI-aware**: Calls `SetProcessDPIAware()` so all coordinate systems (pyautogui, mss, GetWindowRect) are consistent
- **Forced reasoning**: Model must follow `[OBSERVE]/[GOAL]/[PLAN]/[ACTION]` protocol before every action
- **Stale detection**: Perceptual hash comparison warns when screenshots don't change after an action
- **OpenRouter compatible**: Uses function-tool schema when routing through OpenRouter, native `computer_20241022` for direct Anthropic

### Browser-Use Engine Details

- **Headless mode**: Runs Chromium in background, no visible browser
- **CDP mode**: Connects to an existing Chrome via `--remote-debugging-port=9222`
- **User Data Dir mode**: Persistent Chrome profile with stored logins
- **Launch Chrome Session**: Dashboard button launches Chrome with persistent profile at `%LOCALAPPDATA%\ClawBridge\ChromeProfile`

---

## Dashboard

The web dashboard at `http://127.0.0.1:8765` provides:

- **Chat interface**: Submit tasks, see results in a message-bubble layout
- **Engine selector**: Dropdown to pick Auto, browser-use, computer-use, or OpenClaw
- **Live View**: Real-time screenshot stream from browser or desktop
- **Engine status**: See which engines are available/running/errored
- **Config panel**: API key management, browser session controls, machine ID
- **Activity feed**: Audit trail of every action taken

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
COMPUTER_USE_MODEL=anthropic/claude-sonnet-4-20250514
COMPUTER_USE_MAX_SCREEN_WIDTH=1920
COMPUTER_USE_MAX_SCREEN_HEIGHT=1080
COMPUTER_USE_ACTION_DELAY_MS=500

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

## Security

- All data stays on your machine in local mode. No cloud egress.
- API keys are never logged or transmitted.
- Actions classified as safe/sensitive/high-risk with configurable policy.
- Sensitive domain detection (banking, cloud consoles) auto-elevates risk level.
- Credential pattern detection prevents leaking API keys, passwords, etc.
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
| `GET` | `/api/engines` | List engines + status |
| `GET` | `/api/config` | Get config (keys redacted) |
| `POST` | `/api/config/keys` | Save API keys to .env |
| `POST` | `/api/browser/launch` | Launch Chrome with CDP |
| `GET` | `/api/browser/status` | Check Chrome connection |
| `WS` | `/ws` | WebSocket (tasks, frames, audit) |

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
clawbridge.py                 # Monolith — primary entry point
clawbridge/
  config.py                   # Settings & BYOK key management
  engines/
    base.py                   # EngineBase abstract interface
    browser_use_engine.py     # Playwright-based web automation
    computer_use_engine.py    # Desktop control via Anthropic API
    openclaw_engine.py        # Node.js CDP agent
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
.env.example                  # Configuration template
```

## Roadmap

- [ ] Fix browser-use engine import compatibility
- [ ] Test & stabilize "Launch Chrome Session" persistent profile flow
- [ ] OpenClaw engine proper integration & auto-install
- [ ] Remote Bridge cloud service
- [ ] Hosted engine backends (cloud browser-use, cloud OpenClaw)
- [ ] `pip install clawbridge` one-command setup
- [ ] Multi-machine fleet management via Remote Bridge

## License

Proprietary — see LICENSE.txt. Third-party components are governed by their respective open-source licenses.

Copyright (c) 2026 RomaTek AI.
