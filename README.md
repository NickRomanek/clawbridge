# ClawBridge

**Bridging Open-Source AI Agents to Your Machine**

ClawBridge is a local-first AI agent service that bundles [OpenClaw](https://openclaw.ai) and [browser-use](https://github.com/browser-use/browser-use) into a single platform with unified task management, monitoring, and controls.

Submit a task, pick an engine, and let it run. Everything stays on your machine.

---

## Repository

**GitHub:** [NickRomanek/clawbridge](https://github.com/NickRomanek/clawbridge)

## Quick Start (Single File)

One file, no package structure. Install deps once, then run:

```bash
pip install fastapi uvicorn pydantic python-dotenv httpx websockets browser-use langchain-anthropic langchain-openai
# Optional: copy .env.example to .env and add ANTHROPIC_API_KEY or OPENAI_API_KEY
python clawbridge.py
```

Opens **http://127.0.0.1:8765** in your browser. Use this to share ClawBridge with someone who only needs the single script.

## Quick Start (Docker)

```bash
git clone <repo-url>
cd clawbridge
cp .env.example .env
# Edit .env -- add at least one API key (ANTHROPIC_API_KEY or OPENAI_API_KEY)
docker-compose up
```

Open **http://localhost:8765** in your browser.

## Quick Start (Manual Install)

Requires: Python 3.11+, Node 22+ (for OpenClaw)

**Mac / Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows (PowerShell):**
```powershell
.\setup.ps1
```

Then:
```bash
cp .env.example .env
# Edit .env -- add at least one API key
python -m clawbridge
```

Open **http://localhost:8765** in your browser.

---

## What You Can Do

- **Submit tasks** via the web dashboard (research queries, ticket analysis, etc.)
- **Choose your engine:** browser-use (Playwright-based) or OpenClaw (CDP-based)
- **Watch live** as the agent browses, extracts, and synthesizes
- **Pause / Stop / Resume** any task at any time
- **BYOK** -- bring your own API keys. Keys stay local, never leave your machine.

## Engines

| Engine | Technology | Best For |
|---|---|---|
| browser-use | Python + Playwright | Fast browser automation, structured extraction |
| OpenClaw | Node.js + CDP | Full AI agent with memory, skills, chat integrations |

## Configuration

All configuration lives in `.env`. See `.env.example` for all available options.

Key settings:
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` -- at least one required
- `ENABLED_ENGINES` -- which engines to activate
- `POLICY_MODE` -- `guarded` (default), `permissive`, or `strict`
- `BROWSER_HEADLESS` -- `true` for background, `false` to watch the browser

## Security

- All data stays on your machine. No cloud egress in local mode.
- API keys are never logged or transmitted.
- Actions are classified as safe/sensitive/high-risk with configurable policy.
- Full audit trail of every action the agent takes.

## Project Structure

```
clawbridge/
  __main__.py          # Entry point
  config.py            # Configuration loader
  server/              # FastAPI API + WebSocket
  orchestrator/        # Task management + LLM reasoning
  engines/             # Engine adapters (browser-use, OpenClaw)
  policy/              # Safety policy engine
  telemetry/           # Audit logging
  shared/              # Schemas and types
  web/                 # Dashboard UI
```

## License

Proprietary -- see LICENSE.txt. Third-party components are governed by their respective open-source licenses.

Copyright (c) 2026 RomaTek AI.
