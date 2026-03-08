# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is ClawBridge?

ClawBridge is a desktop and browser automation agent with a web dashboard. It orchestrates three AI-powered engines (browser-use, computer-use, OpenClaw) behind a FastAPI server with a WebSocket-driven chat UI. BYOK (bring your own key) — all LLM API keys stay local.

## Development Model: Monolith-First

**`clawbridge.py`** (~12,900 lines) is the single-file monolith and the **only active development target**. All changes go here first. It contains the full application: FastAPI routes, engine implementations, dashboard HTML/JS, safety system, personality manager, task orchestrator, SQLite persistence, and inline CSS/JS.

`clawbridge/` is a modular package that mirrors the monolith's logic split across files. It exists for reference and testing but lags behind the monolith. The test suite (`tests/`) imports from the package, not the monolith.

`clawbridge_mcp.py` is a standalone MCP server that proxies to the monolith's REST API. It has no shared code with the monolith — it's a thin HTTP client wrapper.

## Commands

```bash
# Run the server (primary way)
python clawbridge.py
# Dashboard at http://localhost:8765

# Run with Docker
docker-compose up

# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests (unit + integration, against the package)
pytest

# Run a single test file
pytest tests/unit/test_safety.py

# Run a single test by name
pytest tests/unit/test_safety.py -k "test_scan_detects_aws_key"

# Run with coverage
pytest --cov=clawbridge

# Smoke tests (requires running server on :8765)
python tests/smoke_test.py

# Build portable Windows distribution
python build.py

# Build Windows installer (needs Inno Setup ISCC.exe on PATH)
python build.py --inno

# Build macOS app
python build_macos.py --arch arm64
```

## Architecture

```
Request flow:
  Dashboard (inline HTML/JS) ──WebSocket──▶ FastAPI ──▶ TaskManager ──▶ Engine
                                                            │
                                                    ┌───────┼───────┐
                                                    ▼       ▼       ▼
                                              browser-use  computer  openclaw
                                              (Playwright) (pyauto   (Node.js
                                               + LLM)      gui+UIA)  gateway)
```

### Engine selection
- `auto` (default): LLM task planner (`_plan_task()`) decomposes prompts into 1-3 steps with engine assignments. All web tasks route to browser-use, desktop apps to computer-use, chat to openclaw. Falls back to keyword heuristic (`_engine_for()`) if planner times out (3s).
- Each engine implements `EngineBase(ABC)` with `run_task()` and `get_status()`

### Key subsystems in the monolith
- **Settings** — Pydantic model loading from `.env`. BYOK key management.
- **TaskManager** — Async queue with configurable concurrency (`MAX_CONCURRENT_TASKS`). Handles engine routing, personality context injection, safety screening, retry with exponential backoff, task-level timeouts, and automatic pending task promotion.
- **PersonalityManager** — File-based identity system (`workspace/SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, daily logs). Context assembled by `get_system_context()` and injected into each engine differently.
- **Safety/Policy** — `safety_scan_prompt()` detects credentials/PII/injection. `safety_redact()` scrubs before logging. Three policy modes: permissive, guarded (default), strict.
- **AuditLogger** — SQLite with tables: `tasks`, `task_steps`, `audit_log`, `replay_outcomes`, `planner_items`. Step traces persisted for replay. Outcome data powers confidence model learning.
- **Planner** — Kanban-style checklist in the dashboard for tracking project work. SQLite-backed with phases (observability, reliability, benchmarks, content). API: `GET/POST/PUT/DELETE /api/planner`, `POST /api/planner/seed`. Pre-seeded with 28 items covering benchmark strategy, reliability improvements, and content creation with actionable notes on each item.
- **Failure Analysis** — `analyze_task_failure()` algorithmically diagnoses failed tasks by parsing step traces. Detects: repeated actions (3+ same action at same coordinates), stale sequences, max-steps hit, hard-stops. Auto-populated on task ERROR. Displayed as color-coded timeline in dashboard history view.
- **Dashboard HTML** — ~1,800 lines of inline HTML/JS/CSS rendered by `_dashboard_html()`. Server-side rendering via `window.__PRELOAD__` pattern. Includes slash command autocomplete, always-visible stop button, and chat-integrated workflow save card.
- **WorkflowManager** — Desktop action recording (pynput) and adaptive replay with accessibility-tree element matching + LLM fallback.

### Task Queue & Reliability
- **Pending task promotion**: When a task finishes (or is cancelled/blocked by safety), `_promote_pending_task()` scans for the first PENDING task and starts it. Concurrency slot is reserved immediately (before `_run()` executes) to prevent double-promotion race conditions.
- **Task-level timeout**: `engine.run_task()` is wrapped in `asyncio.wait_for(timeout=TASK_TIMEOUT)`. Default 300s (5 min). Prevents zombie tasks from blocking concurrency slots. Set `TASK_TIMEOUT=0` to disable.
- **Fallback-before-retry**: When an engine fails, TaskManager tries a different engine first (fallback), then retries the *original* engine with exponential backoff. `tried_engines` list is cleared between retry passes.
- **Stale hard-stop**: Computer-use tasks that produce `MAX_CONSECUTIVE_STALE` consecutive identical screenshots are stopped with ERROR status to prevent token waste.
- **Action repetition detection**: Tracks last 3 actions via `_recent_actions` list. If 3 identical actions occur at coordinates within 20px, fast-tracks `_consecutive_stale` to 2 and injects a warning telling the model to try a different approach.
- **Earlier stale diagnostic**: Haiku diagnostic (`_verify_stale_action`) fires at `_consecutive_stale == 2` for both `full` and `standard` scaffolding profiles (was stale==3, full-only). Cost: ~$0.001 per diagnostic call.

### Singletons
`get_manager()`, `get_personality()`, `get_approval_manager()` return module-level singletons. Tests reset these in `conftest.py` via `_reset_singletons` fixture.

## Configuration

Copy `.env.example` to `.env`. Key variables:
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` — at least one required
- `ENABLED_ENGINES` — comma-separated: `browser_use,computer_use,openclaw`
- `POLICY_MODE` — `guarded` (default), `permissive`, or `strict`
- `DASHBOARD_TOKEN` — empty = no auth, set a value to require login
- `BROWSER_MODE` — `default`, `cdp` (connect to Chrome on port 9222), or `user_data_dir`
- `BROWSER_HEADLESS` — run browser in headless mode (default: `true`). Togglable at runtime via `/api/browser/headless`
- `COMPUTER_USE_MODEL` — primary model (default: `anthropic/claude-sonnet-4.5`)
- `COMPUTER_USE_MODEL_FAST` — cheap model for routine replay steps (default: `anthropic/claude-haiku-4-5`)
- `COMPUTER_USE_API` — `auto` (default: Anthropic if key exists, else OpenRouter), `direct`, `openrouter`
- `ECONOMY_MODEL` — optional economy model override (e.g. `google/gemini-2.5-flash`)
- `TASK_TIMEOUT` — max seconds per engine run, 0=disabled (default: `300`)
- `MAX_CONSECUTIVE_STALE` — hard-stop after N consecutive stale actions (default: `5`)
- `RECORDING_SCREENSHOTS` — capture screenshots during recording (default: `true`)
- `RECORDING_INTENT_EXTRACTION` — run LLM intent extraction post-recording (default: `true`)
- `SCREENPIPE_INTEGRATION` — use ScreenPipe OCR if available (default: `true`)
- `SCAFFOLDING_PROFILE` — controls system prompt verbosity and runtime compensations (default: `standard`)

## Scaffolding Profile System

The `SCAFFOLDING_PROFILE` setting controls how much guidance the system gives the AI model. As models improve, users can dial down scaffolding to let the AI do more on its own.

| Profile | System Prompt | Pre-Navigation | Focus Mgmt | Stale Warnings | Vision Fallback | Redirect Detection |
|---------|--------------|----------------|------------|----------------|-----------------|-------------------|
| `full` | All sections (~3,000 tokens): decision trees, reasoning protocol, anti-patterns, SoM, core rules | Yes | Every action | Full escalation + diagnostic | <5 elements | Yes |
| `standard` | Balanced (~1,500 tokens): reasoning protocol, system info, SoM, core rules. No decision trees or anti-patterns | Yes | Every action | Warning at 2 + hard-stop | <5 elements | Yes |
| `minimal` | Lean (~800 tokens): SoM + core rules only | No | Click actions only | Hard-stop only | <3 elements | No |
| `raw` | Minimal (~300 tokens): preamble + screenshot description only | No | None | Hard-stop only | Disabled | No |

The system prompt is decomposed into named sections (`_PROMPT_PREAMBLE`, `_PROMPT_REASONING`, `_PROMPT_DECISION_TREES`, `_PROMPT_SYSTEM_INFO`, `_PROMPT_ANTI_PATTERNS`, `_PROMPT_SOM`, `_PROMPT_FINISHING`, `_PROMPT_CORE_RULES`, `_PROMPT_SCREENSHOT`). The `_SCAFFOLDING_PROFILES` dict maps each profile to its list of sections. `_build_system_prompt(profile, **kwargs)` assembles the final prompt.

Hard-stop (stale action safety limit) always applies regardless of profile.

## Port Layout

| Service | Port | Notes |
|---------|------|-------|
| ClawBridge | 8765 | Dashboard + API |
| OpenClaw gateway | 18789 | Auto-started by monolith |
| Chrome CDP | 9222 | When using `cdp` browser mode |

## Testing Notes

- Tests run against the **package** (`clawbridge/`), not the monolith. If you change `clawbridge.py`, the package may need syncing for tests to reflect those changes.
- `conftest.py` auto-resets singletons (`_settings`, `_task_manager`, `_audit_logger`) between tests and stubs API keys to empty strings.
- `asyncio_mode = auto` in `pytest.ini` — async test functions are auto-detected.
- Smoke tests (`tests/smoke_test.py`) require a running server and hit live endpoints.
- **E2E tests** (`tests/e2e/`) require `--run-e2e` flag and a running server on :8765. Function-scoped async clients prevent Windows ProactorEventLoop cascade failures.
- **Test counts** (as of 2026-03-07): 275 unit+integration passing, 36+ E2E, 20 smoke.

## Engine-Specific Notes

### OpenClaw (primary engine)
- Gateway auto-starts via `openclaw gateway --port 18789 --bind loopback --allow-unconfigured --auth none --dev` (foreground). Do NOT use `gateway start` (requires admin for system services).
- Auth: reads API keys from `~/.openclaw/openclaw.json` `env` block, NOT from `.env`. ClawBridge passes `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` in a minimal env dict when auto-starting (no `os.environ.copy()`).
- Gateway binds to loopback only via `--bind loopback`. Do NOT use `--host` (not a valid OpenClaw flag).
- Bundled binary: installed environments have `nodejs/openclaw.CMD` next to clawbridge.py. `initialize()` checks this path if `shutil.which()` fails.
- Model naming: use `openrouter/anthropic/claude-sonnet-4` — dated slugs like `-20250514` are NOT recognized.
- Config hot-reload: gateway watches `openclaw.json` for changes.
- Concurrency: RUNNING status is fine — gateway handles concurrent HTTP requests. Don't block on `status != AVAILABLE`.
- Token usage: gateway returns `usage` block but all zeros — it doesn't track tokens internally. Expected behavior.
- **Economy mode**: When `MODEL_TIER=economy` and `ECONOMY_MODEL` is set, OpenClaw chat tasks use the economy model (e.g. `google/gemini-2.5-flash`) instead of the default. Cost tracking uses the actual model used.

### Computer-Use
- Accessibility-first navigation via pywinauto UIA. Model uses `click_element(element_id=N)` instead of guessing coordinates.
- Auto-focuses target app before starting. Re-focuses before every screenshot (Windows steals focus).
- **Focus verification**: `_verify_focus()` checks foreground window title via ctypes after every focus attempt. Retries once on mismatch. `_focus_warning` fed back to LLM so it knows if focus is wrong.
- DPI awareness: `SetProcessDPIAware()` at startup -> pyautogui/mss report logical (1920x1080) not physical resolution.
- Dual screenshot strategy: full screen (for coordinates) + zoomed crop of foreground window (for reading text).
- **Ultrawide support**: Monitors with aspect ratio > 2.0 auto-detected (`_is_ultrawide`). Uses active window crop as primary screenshot (better for LLM reasoning). Full screen only on first screenshot or when no foreground window. Override via `COMPUTER_USE_MAX_SCREEN_WIDTH`/`HEIGHT` in `.env`.
- **Dual API path**: Direct Anthropic API uses native computer-use tool (`computer_20250124` or `computer_20251124`) via `client.beta.messages.create()`. OpenRouter uses function-tool schema via `client.messages.create()`. `COMPUTER_USE_API` setting controls which path (`auto`/`direct`/`openrouter`).
- **Tool versioning**: `_get_tool_version()` maps model to correct tool type and beta header. Opus 4.6/Sonnet 4.6/Opus 4.5 use `computer_20251124`, all others use `computer_20250124`.
- **New actions** (20250124+): `scroll` with direction/amount, `triple_click`, `left_mouse_down`/`left_mouse_up`, `hold_key`, `wait`. All handled in `_execute_action()`.
- **Zoom action** (20251124): `enable_zoom: true` in tool definition. Claude can request a cropped screenshot of a specific region at full resolution via `zoom` action with `region: [x1, y1, x2, y2]`. Handled by `_take_zoom_screenshot()` which scales from model coords to physical pixels.
- Forced reasoning protocol: `[OBSERVE]/[GOAL]/[PLAN]/[ACTION]` before every action.
- **Hybrid mechanical + AI execution**: Deterministic actions (app launch via Win key + search, URL navigation) handled programmatically at zero AI cost. AI only invoked when visual reasoning is needed.
- **Mechanical pre-navigation**: `_mechanical_pre_navigate()` extracts URLs from prompts via `_extract_navigation_target()`. Tries CDP first (`/json/new` on port 9222) to open a new tab in the existing browser-use Chrome instance, avoiding a second browser. Falls back to `webbrowser.open_new_tab()` if CDP is unavailable. LLM told "PRE-NAVIGATION COMPLETE" to skip redundant navigation steps.
- **Vision fallback**: `_get_ui_elements_vision()` uses fast vision model (Haiku) to identify UI elements from screenshots when UIA tree returns < 5 elements (Electron apps, games, custom UIs). Results cached via perceptual hash similarity check. `_merge_ui_elements()` deduplicates against UIA elements within 30px.
- **Redirect detection**: `_detect_redirect()` checks browser window title after click actions. If the expected navigation domain (from `_extract_navigation_target()`) differs from the actual window title and a known ad/redirect indicator is present (Amazon, eBay, etc.), injects a warning telling the model to close the tab and go back. Prevents ad-click redirects from derailing tasks.
- **Stale action hard-stop**: After `MAX_CONSECUTIVE_STALE` (default 5) consecutive actions with no visible screen change, the task is force-stopped with ERROR status. Prevents burning tokens on stuck loops. The escalation: hint at 1, diagnostic at 2 (full+standard), hard-stop at MAX_CONSECUTIVE_STALE.
- **Action repetition detection**: `_recent_actions` list tracks last 3 actions with coordinates. 3 identical actions within 20px fast-tracks stale counter to 2 and injects warning to try different approach.

### Browser-Use
- Three modes: `default` (fresh Chromium), `cdp` (connect to existing Chrome on port 9222), `user_data_dir` (persistent profile at `%LOCALAPPDATA%\ClawBridge\ChromeProfile`).
- **CDP auto-launch**: On first browser-use task, auto-launches Chrome with `--remote-debugging-port=9222`. Tracked via `BrowserUseEngine._auto_chrome_proc` class attribute. Computer-use engine reuses this Chrome via CDP for pre-navigation instead of opening a second browser.
- **Headless toggle**: `BROWSER_HEADLESS` setting (default `true`). Togglable at runtime via `POST /api/browser/headless`. Dashboard PiP panel has an eye icon for quick toggle. Changing headless mode kills the running Chrome (port-level kill via `netstat`/`lsof`) and re-initializes the engine.
- Uses browser-use v0.11.9: `Agent`, `Browser`, `BrowserProfile`, `ViewportSize` all import correctly.
- **Extraction-aware prompting**: When prompts contain extraction keywords ("tell me", "what is", "show me", etc.), appends instruction for browser-use to return findings as final answer. Falls back to `page.inner_text("body")` + LLM summary when `final_result` is None.
- **URL safety (VULN-102)**: Prompt is double-URL-decoded before checking blocked schemes (`file://`, `ftp://`, etc.) to prevent `file%3A%2F%2F` bypass.
- **Judge stripping**: browser-use's internal `[Simple judge:...]` evaluation annotations are stripped from user-facing output via regex.

## Personality & Memory System

- **Files**: `workspace/SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, `memory/YYYY-MM-DD.md`
- **Context injection** via `TaskManager._run()`: computer-use gets it in system prompt, browser-use gets it prepended to task prompt, OpenClaw gets it as system message.
- **Context gating**: Personality context is skipped for simple OpenClaw chat tasks that don't reference memory/identity keywords (saves 5-20K tokens). Tasks routed to computer-use or browser-use always get full context.
- **`get_system_context()`** assembles: SOUL.md + IDENTITY.md + USER.md + MEMORY.md + today's daily log.
- **Auto-logging**: every task completion appends to daily log (safety-redacted). Context grows as the day progresses.
- **`_personality_context`** is a `PrivateAttr` on the Task Pydantic model — not serialized.

## Safety/Policy System

- `safety_scan_prompt()` scans for 8 credential patterns, 2 PII patterns, 5 injection patterns.
- `safety_redact()` replaces credentials/PII with `[REDACTED_CREDENTIAL]` / `[REDACTED_PII]` before logging to memory. Also applied to personality context before LLM injection.
- **Policy modes**: `permissive` (no blocking), `guarded` (warns, doesn't block — default), `strict` (blocks credentials in prompt).
- **Key combo blocklist**: `_BLOCKED_KEY_COMBOS` blocks Win+R, Win+X, Ctrl+Alt+Delete, Ctrl+Shift+Esc, Win+L, Win+Pause, Alt+F4 in both computer-use engine and replay paths.
- **Replay concurrency lock**: `_replay_lock` (asyncio.Lock) prevents concurrent replays from corrupting engine state.
- Safety flags logged to `audit_log` table and broadcast via WebSocket `safety_warning` message.

## Network Security

Security model: localhost-only with opt-in auth. Open on localhost is fine for a desktop tool. Defenses target cross-origin attacks and accidental exposure.

- **WebSocket origin validation**: `/ws` handler checks `Origin` header before `accept()`. Only `127.0.0.1`, `localhost`, `::1` allowed. Missing origin (non-browser clients like MCP, wscat) is permitted. Rejects with close code 1008.
- **CORS middleware**: `CORSMiddleware` restricts `allow_origins` to `http://127.0.0.1:{port}` and `http://localhost:{port}`. No wildcard. HTTPS variants not included (not needed for local-only; would need adding if reverse proxy support is added).
- **Rate limiting**: In-memory sliding window via `_rate_limit()`. Applied as middleware (not per-endpoint) to avoid breaking existing `body: dict` endpoint signatures. Limits: `/api/auth/login` POST 5/60s, `/api/tasks` POST 10/60s per client IP. Returns 429 with `Retry-After` header.
- **Host binding guard**: `main()` refuses to start with `CLAWBRIDGE_HOST=0.0.0.0` or `::` unless `DASHBOARD_TOKEN` is set. Exits with `sys.exit(1)` and clear error message. If token is set, prints a warning.
- **Middleware ordering**: Starlette processes last-added first (LIFO). Order of `add_middleware()` calls: Auth → RateLimit → CORS. Execution order: CORS (outermost) → RateLimit → Auth (innermost). This ensures OPTIONS preflight is handled by CORS before Auth can reject it with 401.
- **Loading server**: No `Access-Control-Allow-Origin` header (removed wildcard `*`). Loading page JS is same-origin.

## SQLite Schema

- **tasks**: id, prompt, engine, status, result (JSON — includes `failure_summary` dict on ERROR tasks), error, created_at, updated_at
- **task_steps**: id (autoincrement), task_id, step_num, max_steps, action, detail, reasoning, tokens_in, tokens_out, timestamp. Indexed on task_id.
- **audit_log**: id (UUID), task_id, event_type, detail, timestamp. Indexed on task_id.
- **replay_outcomes**: id (autoincrement), workflow_id, task_id, step_index, action_type, method, success, confidence, tokens_used, duration_ms, action_fingerprint, timestamp. Indexed on workflow_id and action_fingerprint.
- **planner_items**: id (text PK), phase, title, description, status (pending/in_progress/done), position, notes, created_at, updated_at. Indexed on phase. Pre-seeded with 28 default items across 4 phases.

## Known Gotchas

- **JS in Python triple-quoted strings**: To produce `\'` in JavaScript output, write `\\'` in Python. A bare `\'` becomes just `'` and can break the `<script>` block with cascading SyntaxError.
- **Browser extensions break dashboard**: MetaMask/Coinbase inject SES lockdown that corrupts JS globals. Test dashboard in Chrome with extensions disabled.
- **Installer filename**: Always `ClawBridge-Setup.exe` with no version suffix — the download URL must remain stable.
- **`window.__PRELOAD__`**: Server-injected data pattern in `<head>` for JS to consume on DOMContentLoaded. SSR fallback renders engine list and config summary in Python.
- **First-start dependency install**: Uses `importlib.invalidate_caches()` + sys.path refresh to continue after pip install, no restart needed.

## Don't Do

- Don't modify `clawbridge/` package without syncing from monolith first — it lags behind.
- Don't use `openclaw gateway start` — use `gateway` (foreground, `--bind loopback`).
- Don't use `--host` with OpenClaw gateway — it's not a valid flag. Use `--bind loopback` instead.
- Don't add version numbers to installer filename — must stay `ClawBridge-Setup.exe`.
- Don't use dated model slugs (e.g. `-20250514`) with OpenClaw or OpenRouter — they're not recognized. Use undated slugs: `anthropic/claude-sonnet-4.5`, `anthropic/claude-haiku-4-5`.
- Don't use `time.sleep()` in async functions — use `asyncio.sleep()`.
- Don't render user data in dashboard HTML without escaping — use the `esc()` JS function.
- Don't write to memory/logs without calling `safety_redact()` first.
- Don't call `self.run_task()` from within an engine method while engine status is RUNNING — the task will be rejected. Must temporarily set `self._status = EngineStatus.AVAILABLE` with try/finally restore.
- Don't allow replay tasks (prefixed `replay:`) to fall through to engine fallback logic — they'll get conversational responses from OpenClaw instead of failing cleanly.
- Don't assume `OPENAI_API_KEY` is actually an OpenAI key — users sometimes put OpenRouter keys there. Check `has_openai_key()` which detects `sk-or-` prefix.
- Don't use unicode characters (arrows, special symbols) in log messages on Windows — cp1252 encoding will crash. Use ASCII equivalents (`->` not `→`).
- Don't pass `os.environ.copy()` to subprocesses — construct minimal env with only required keys. Gateway gets PATH, SYSTEMROOT, TEMP, HOME, USERPROFILE, APPDATA, LOCALAPPDATA + API keys.
- Don't use `safety_scan_prompt()` key `"credential_flags"` — the correct key is `"credentials"`. Same for `"pii"` and `"injection_flags"`.
- Don't add dangerous key combos (Win+R, Ctrl+Alt+Del, etc.) to the `_BLOCKED_KEY_COMBOS` bypass — they're blocked for safety.
- Don't increment `_running` inside `_run()` for promoted tasks — `_promote_pending_task()` already reserves the slot. `_run()` checks `task.status != RUNNING` before incrementing.
- Don't set task status after the action loop without guarding — `if task.status != TaskStatus.ERROR:` prevents overwriting ERROR from stale hard-stop or mid-loop failures.
- Don't bind to `0.0.0.0` or `::` without setting `DASHBOARD_TOKEN` — `main()` will refuse to start. Containers need a bypass (e.g. `CLAWBRIDGE_CONTAINER=1`) since they always bind `0.0.0.0`.
- Don't reorder `add_middleware()` calls — CORS must be added last (runs first) so OPTIONS preflight doesn't get 401'd by Auth. See Network Security section.

## MCP Server

`clawbridge_mcp.py` exposes 15 tools and 1 resource (`clawbridge://status`). Registered in `.mcp.json`. Runs via stdio (default) or HTTP (`--http` flag). Auth token passthrough on all tools.

## Dashboard UX Features

- **Always-visible Stop button**: Send button swaps to red Stop when any task is running. `state.runningTaskId` tracks active task via WebSocket `task_update`. Resets on terminal status.
- **Slash command autocomplete**: Typing `/` shows dropdown above input with commands and saved workflow names. Arrow keys navigate, Enter selects, Escape dismisses.
- **Chat recording save card**: Stopping a recording from chat shows a save card (between task list and input area, outside render cycle) with pre-filled timestamp name. User can Save immediately or customize.
- **Engine dropdown**: Compact `<select id="engine">` in the chip row above the text input. Options: Auto (default), Browser, Computer, Chat. Slash commands `/browser`, `/computer`, `/chat` set it programmatically via `selectEngineChip()`. The hidden `<select>` inside the form was removed — the visible dropdown IS the value source for `sendMsg()`.
- **Replay routing clarity**: `/replay` always forces `computer_use` engine regardless of dropdown selection. Routing info shows "Replaying Workflow (Visual Automation)".
- **Dashboard click filtering**: `stop_recording()` strips trailing events whose `window_title` contains "clawbridge dashboard", "localhost:8765", or "127.0.0.1:8765". Prevents Stop Record button click from being saved in the workflow.
- **Double-submit guard**: Prevents sending new tasks while one is already running.
- **App-mode browser launch**: `_open_app_mode(url)` opens the dashboard in a chromeless Chrome/Edge window via `--app=` flag (no URL bar, no tabs). Tries Edge first on Windows (always present on Win10+), then Chrome. Falls back to regular `webbrowser.open()` if no Chromium browser found. Used by: auto-open on startup (`CLAWBRIDGE_OPEN_BROWSER=1`), tray icon "Open Dashboard", and overlay focus fallback.
- **Planner view**: Kanban-style checklist with collapsible phase sections. Color-coded left borders per phase (blue=observability, green=reliability, purple=benchmarks, amber=content). Each item has checkbox, title, notes preview, hover-reveal edit/delete buttons. Overall progress bar in header. Add Item form with phase dropdown. Reset button re-seeds defaults. Pre-loaded via `window.__PRELOAD__`.

## Recorder Notes

- **`clawbridge/recorder/capture.py`** -- pynput-based input recording with inline enrichment:
  - Key coalescing: `_KEY_COALESCE_DELAY=0.3s`, space mapped via `_PRINTABLE_KEY_MAP`, unknown special keys become standalone `key` events
  - **Window title at click point**: `_get_window_title_at(x, y)` uses `WindowFromPoint` -> `GetAncestor(GA_ROOT)` to get the correct window, even when a click causes a window to dismiss. Falls back to `GetForegroundWindow`.
  - **Process name capture**: `_get_fg_process_name()` gets process name (e.g. `Telegram.exe`) via `OpenProcess` + `QueryFullProcessImageNameW`. Enables app detection for apps whose window titles don't contain the app name.
  - **Window-relative coordinates**: `_get_fg_window_rect()` captures foreground window bounds for `window_x`/`window_y` on click events.
  - **A11y enrichment**: `_get_a11y_element_at(x, y)` runs on a background thread after click event is recorded (non-blocking). Click recorded immediately, then a11y data populated async. UIA tree cached 0.5s via `_a11y_cache` with threading lock. `stop()` waits up to 1.5s for pending enrichment threads.
  - **Screenshot at click time**: `_capture_screenshot_sync()` captures 720p JPEG via mss, base64-encoded. Also runs on background enrichment thread.
  - **Modifier key suppression**: Tracks `_last_modifier_key`/`_last_modifier_time`, suppresses duplicate modifier events within 0.15s (prevents 20-30 Windows key-repeat events when holding Shift/Ctrl/Alt/Win).
  - **Live action feed**: `on_action` callback fires immediately on each action for real-time WebSocket streaming to dashboard.
  - **Dashboard click filtering**: Tracks `_last_app_title` and uses `_DASHBOARD_TITLE_MARKERS` to detect and skip dashboard interactions.
- **`clawbridge/recorder/processor.py`** -- Mostly pass-through now. Events arrive pre-enriched from InputRecorder. Normalizes into RecordedAction schema. Optionally queries ScreenPipe (`localhost:3030`) for OCR text enrichment (capped to 500 chars). ScreenPipe availability cached after first check (0.3s timeout).
- **Critical**: A11y enrichment happens at click time, NOT in post-processing. If done after recording stops, the user has already switched back to the dashboard, so the wrong window's a11y tree would be enumerated.

## AI-Powered Recording/Replay System

### Smart Recording (Phase A)
- **A11y enrichment at record time**: Click events get `element_name`, `element_type`, `element_automation_id`, `element_parent_name`, `confidence` populated from UIA tree. Cached 0.5s to avoid re-enumeration on rapid clicks.
- **Screenshot capture**: 720p JPEG before each click, stored as `screenshot_b64` on `RecordedAction`. Toggle via `RECORDING_SCREENSHOTS` setting.
- **ScreenPipe integration**: Optional OCR enrichment from ScreenPipe (`localhost:3030`). Auto-detected at recording start. Toggle via `SCREENPIPE_INTEGRATION` setting.
- **Intent extraction**: Post-recording LLM call (Haiku/GPT-4o-mini, ~$0.001) extracts `intent`, `semantic_steps`, `detected_variables`, `target_apps`. Runs in background via `asyncio.create_task`. Toggle via `RECORDING_INTENT_EXTRACTION` setting.

### Intelligent Replay (Phase B)
- **Confidence-tiered execution**: `_compute_step_confidence()` scores each action. >= 0.95 = pure mechanical, 0.7-0.95 = mechanical + visual verification, < 0.7 = AI replay via LLM.
- **Visual verification**: Window title match (free) → perceptual hash comparison (free) → LLM visual check (fallback, ~$0.002).
- **Adaptive timing**: `_wait_for_ui_ready()` polls UIA tree stability instead of fixed delays. 10s timeout for app switches, 3s for in-app.
- **Graceful degradation**: No API key → falls back to mechanical-only replay seamlessly.

### Parameterization (Phase C)
- **Variable detection**: LLM identifies typed text that can be parameterized (e.g., search queries, filenames).
- **Parameterized replay**: `POST /api/workflows/{id}/replay-parameterized` with `{"params": {...}}`. Safety-scanned per value.
- **Dashboard UI**: Workflow cards show "Params..." button with input form when `detected_variables` exist. Sensitive params use `type="password"`.

### Learning & Optimization (Phase D)
- **Outcome tracking**: `replay_outcomes` SQLite table records per-step success/failure, method, confidence, duration, action fingerprint hash.
- **Confidence model**: `_query_historical_confidence(action_dict, workflow_id)` — scoped to workflow_id to prevent cross-workflow poisoning. After 3+ mechanical successes, promotes to 0.99 (mechanical-only). After 2+ mechanical failures with AI success, demotes to 0.3.
- **Action fingerprint**: MD5 hash of action_type + element_name + element_type + automation_id + window_title. Scoped per workflow.

### Prompt Caching
System prompt wrapped in content blocks with `cache_control: {"type": "ephemeral"}`. On multi-step tasks, the system prompt (~2000+ tokens) is cached after the first API call. Steps 2+ hit the cache, saving ~50-90% on input tokens. Works with both direct Anthropic API and OpenRouter.

### Smart Model Routing
During replay, AI steps use `COMPUTER_USE_MODEL_FAST` (Haiku) for routine actions and `COMPUTER_USE_MODEL` (Sonnet) for hard ones:
- Verification retry (confidence 0.7-0.95): Haiku (fast)
- Low-confidence AI replay (0.4-0.7): Haiku
- Very low-confidence AI replay (< 0.4): Sonnet (full model)
- Last-resort LLM fallback: Sonnet

## Release Checklist

When cutting a new release (e.g. `v0.5.4`):

1. **Bump version** in all 6 locations:
   - `clawbridge.py` line ~14 (`__version__`)
   - `build.py` line ~32 (`VERSION`)
   - `build_macos.py` line ~36 (`VERSION`)
   - `installer.iss` line ~10 (`#define MyAppVersion`)
   - `website/frontend/src/pages/download.astro` (version string)
   - `website/frontend/src/pages/index.astro` (`softwareVersion` in JSON-LD)

2. **Update CHANGELOG.md** — add a section for the new version with categorized changes.

3. **Run tests**: `pytest` (unit+integration), optionally `python tests/smoke_test.py` with server running.

4. **Commit, tag, push**:
   ```bash
   git add -A && git commit -m "v0.5.4: description"
   git tag v0.5.4
   git push && git push --tags
   ```

5. **CI builds automatically** on tag push (`.github/workflows/build.yml`):
   - Windows: portable ZIP + installer (Inno Setup, `ClawBridge-Setup.exe`)
   - macOS: arm64 + x64 DMGs and ZIPs
   - Release job uploads all 6 artifacts to GitHub Releases

6. **Deploy website** (if download page or homepage changed):
   ```bash
   cd website/frontend && npm run build && npx wrangler pages deploy dist --project-name clawbridge-site
   cd website/backend && npx wrangler deploy  # only if backend changed
   ```

7. **Verify**: check GitHub release page has all artifacts, test download link (`/releases/download/v0.5.4/ClawBridge-Setup.exe`).

## Roadmap

- ~~**Phase 1: Core Features**~~ — DONE. Smart routing, model routing, economy mode, prompt caching, workflows, enhanced recording, direct Anthropic API, zoom action support.
- ~~**Phase 2a: Reliability Batch 1+2**~~ — DONE. Task queue promotion, task-level timeouts, redirect detection, personality context gating, stale action hard-stop, fallback-before-retry.
- ~~**Phase 2b: Reliability Batch 3**~~ — DONE. Post-action hints, action-repetition detection, earlier diagnostic trigger (stale=2 for full+standard), failure analysis with auto-populate.
- ~~**Phase 2d: Multi-Engine Orchestration**~~ — DONE. LLM task planner, result chaining, hybrid DOM+visual engine, CDP auto-launch, planner sanity checks, updated routing heuristics.
- ~~**Phase 2e: Security Hardening**~~ — DONE. WebSocket origin validation, CORS middleware, rate limiting, host binding guard, loading server CORS removal.
- **Phase 2c: Reliability (remaining)** — Self-verification loops, element matching improvements, cross-workflow learning, scaffolding profile comparison.
- **Phase 3: Distribution** — App-mode window (done), containerization, auto-update, template gallery, community launch.
- **Phase 4: Benchmarks & Content** — Run existing benchmark suite, cross-tool comparisons (vs Cowork, vs browser-use), YouTube-first content strategy, blog posts with data.

See `ROADMAP.local.md` (gitignored) for detailed internal planning.
