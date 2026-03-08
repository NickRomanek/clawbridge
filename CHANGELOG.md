# Changelog

All notable changes to ClawBridge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.4] - 2026-03-07

### Fixed
- **Loading page stuck on fresh install**: Loading page polls `/startup-status` during startup, but if the stdlib loading server shut down before the JS detected 100% progress, Uvicorn returned 404 (no such route) causing an infinite poll loop. Added `/startup-status` endpoint to FastAPI that always returns `progress: 100`.
- **Loading server ConnectionAbortedError on Windows**: Wrapped `_LoadingHandler.do_GET()` in try/except for `ConnectionAbortedError`, `ConnectionResetError`, `BrokenPipeError` — common when browser disconnects mid-response during server transition.
- **Loading page transition timing**: Increased pre-shutdown sleep from 0.5s to 1.0s to ensure the loading page JS (600ms poll interval) detects 100% progress before the stdlib server shuts down.

### Added
- **Planner UX**: Expandable notes (click to toggle), click-to-copy command pills for `RUN:` commands, `[AUTO]`/`[RECORD]` task tags.
- **Planner phases**: Merged measure/fix into single "Benchmark & Fix" phase. New 5-phase layout: benchmark, show, ship, grow, done.
- **Smoke test**: `/startup-status` endpoint now covered in smoke test suite.

---

## [0.5.3] - 2026-03-07

### Added

#### Network Security
- **WebSocket origin validation**: `/ws` handler checks `Origin` header before `accept()`. Only localhost origins allowed (`127.0.0.1`, `localhost`, `::1`). Missing origin (non-browser clients like MCP) is permitted. Rejects with close code 1008.
- **CORS middleware**: `CORSMiddleware` restricts `allow_origins` to `http://127.0.0.1:{port}` and `http://localhost:{port}`. No wildcard.
- **Rate limiting**: In-memory sliding window via `_rate_limit()`. Login: 5/60s, task submission: 10/60s per client IP. Returns 429 with `Retry-After` header.
- **Host binding guard**: `main()` refuses to start with `CLAWBRIDGE_HOST=0.0.0.0` unless `DASHBOARD_TOKEN` is set. Exits with clear error message.
- **Loading server CORS removal**: Removed wildcard `Access-Control-Allow-Origin: *` from the startup loading page handler.

#### Browser Management
- **Chrome process tracking**: Browser-use engine's auto-launched Chrome subprocess is now tracked via `BrowserUseEngine._auto_chrome_proc`. All API endpoints (`/api/browser/status`, `/stop`, `/launch`) and shutdown cleanup coordinate with it.
- **CDP-first pre-navigation**: Computer-use engine always tries CDP (`localhost:9222`) before falling back to system browser. Prevents dual-browser issue where both CDP Chrome and the default browser opened simultaneously.
- **Headless toggle in PiP**: Eye icon button in the Live View panel titlebar toggles between visible and headless Chrome. Persists to `.env`, restarts Chrome with new setting. Real-time sync via WebSocket.
- **`POST /api/browser/headless`**: New endpoint toggles `BROWSER_HEADLESS`, kills Chrome on CDP port (even untracked instances), re-initializes engines.
- **`GET /api/browser/status`**: Now includes `headless` field in response.
- **Port-level Chrome kill**: Stop and headless toggle endpoints find and kill Chrome by CDP port using `netstat`/`lsof`, not just tracked process handles.

#### Infrastructure
- **Dependabot**: Automated dependency vulnerability scanning for pip, npm, and GitHub Actions.
- **Security response headers**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` on all responses.
- **SECURITY.md updated**: Current supported versions, new defenses documented.

### Changed
- **Task planner routing**: Browser-use now handles ALL web tasks (email, forms, shopping, login) since it uses real Chrome with CDP (sessions preserved). Computer-use reserved for native desktop apps only. Fallback `_engine_for()` heuristic synced to match.
- **Monolith grew from ~12,700 to ~12,900 lines** with security hardening and browser management.

---

## [0.5.2] - 2026-03-07

### Added

#### Multi-Engine Task Orchestration
- **LLM-powered task planner**: `_plan_task()` decomposes prompts into 1-3 sequential steps, each routed to the best engine. Uses cheapest available LLM (~$0.001 per plan). 3s timeout with 5-minute cache.
- **Result chaining**: Previous step results injected as `[PREVIOUS STEP RESULTS]` context into next step's prompt (capped at 3,000 chars).
- **Dashboard plan visualization**: `task_plan` and `step_plan_progress` WebSocket events show multi-step progress in chat.
- **Planner sanity checks**: If planner says CHAT but prompt contains a URL or web keywords, auto-overrides to BROWSER. Applied both at single-step level and per-step inside the planner.

#### Hybrid DOM + Visual Engine
- **CDP bridge on computer-use**: When browser is focused, computer-use gains `read_page`, `get_url`, and `dom_click` tools via Chrome DevTools Protocol. DOM tools are free (don't count as steps).
- **Browser detection**: `_is_browser_focused()` checks window title for Chrome/Edge/Firefox/Brave patterns.
- **Lazy CDP connection**: `_cdp_connect()` establishes Playwright CDP connection on demand, `_cdp_disconnect()` cleans up on task completion.

#### Browser-Use Reliability
- **Auto-launch Chrome with CDP**: browser-use now auto-launches real Chrome with `--remote-debugging-port=9222` for `default` and `user_data_dir` modes. Avoids anti-bot detection that blocks Playwright's isolated Chromium.
- **CDP session pre-connect**: `browser.start()` called during initialization so CDP is ready before the first task. Fixes race condition where initial navigation failed with "CDP client not initialized".
- **Headless Chrome support**: `BROWSER_HEADLESS=true` adds `--headless=new` flag — Chrome runs invisible, users see activity via PiP live view in dashboard.

#### Updated Routing Heuristics
- **Web research routes to browser-use**: Non-interactive web tasks (URLs, search, reading) now route to browser-use (DOM access, 5-10x faster) instead of computer-use.
- **Interactive web stays on computer-use**: Tasks with login/form/purchase keywords still use computer-use for real browser with saved sessions.
- **Stronger planner prompt**: Explicit rules that URLs/domains = BROWSER, never CHAT.

### Changed
- Monolith grew from ~11,300 to ~12,700 lines with multi-engine orchestration, hybrid engine, and CDP auto-management.
- `_classify_prompt_with_llm()` is now a thin wrapper around `_plan_task()` for backward compatibility.
- macOS download disabled on website (not production-ready yet).

---

## [0.5.1] - 2026-03-01

### Fixed
- **macOS DMG: self-contained .app bundle** — App bundle now embeds all dependencies inside `Contents/Resources/bundle/` instead of requiring a sibling folder. DMG shows 2 items (app + Applications) instead of 3.
- **macOS DMG: drag-to-Applications works** — Previously, dragging only the .app to `/Applications` broke it because the launcher referenced a sibling `ClawBridge/` folder. Now fully self-contained.
- **CI: x64 macOS build uses Intel runner** — Changed from `macos-14` (ARM) to `macos-13` (Intel) so the x64 DMG produces true x86_64 binaries without Rosetta.
- **Windows build version synced** — `build.py` VERSION updated from 0.3.5 to match release.

## [0.5.0] - 2026-03-01

### Added

#### macOS Support
- **Platform abstraction layer**: `clawbridge/platform/` with `_windows.py`, `_macos.py`, `_linux.py` backends, auto-selected by `sys.platform`
- **PyObjC backend**: AXUIElement accessibility, Quartz screen capture, Cocoa window management
- **macOS DMG distribution**: `build_macos.py --arch arm64|x64` for Apple Silicon and Intel Macs
- **macOS permissions endpoint**: `/api/permissions` checks Accessibility + Screen Recording, dashboard shows non-dismissable banner if missing
- **Key remapping**: Ctrl-based shortcuts automatically remapped to Cmd on macOS (pre-navigation, key combos, blocked combos)
- **Download page**: OS auto-detection via `navigator.userAgent`, separate arm64/x64 macOS DMGs with quickstart guide

#### Scaffolding Profile System
- **`SCAFFOLDING_PROFILE` setting**: `full`, `standard` (default), `minimal`, `raw` — controls system prompt verbosity and runtime compensations
- **System prompt decomposition**: 9 named sections (`_PROMPT_PREAMBLE`, `_PROMPT_REASONING`, `_PROMPT_DECISION_TREES`, etc.) assembled by `_build_system_prompt()`
- **Runtime gating**: Pre-navigation, focus management, stale escalation, vision fallback threshold, and redirect detection all vary by profile
- **Dashboard toggle**: 4-button selector in settings panel, persists to `.env`, broadcasts via WebSocket

#### Dashboard & UX
- **App-mode browser launch**: `_open_app_mode(url)` opens dashboard in chromeless Chrome/Edge window via `--app=` flag (no URL bar, no tabs)
- **Floating PiP live view panel**: Replaces sidebar live view card with draggable picture-in-picture panel
- **Workflow UX improvements**: Streamlined params panel ("Run with params" -> "Run", "Save defaults" -> "Save"), AI Edit "Save as New" button

### Changed
- Monolith grew from ~10,200 to ~11,300 lines with platform abstraction, scaffolding profiles, and app-mode window
- All `ctypes.windll` calls extracted from monolith into `clawbridge/platform/` — zero platform-specific code remains in `clawbridge.py`
- Recorder and perception modules now use platform abstraction layer
- Computer-use mechanical pre-navigation uses Cmd instead of Ctrl on macOS

---

## [0.4.0] - 2026-02-22

### Added

#### Task Queue & Reliability
- **Pending task promotion**: `_promote_pending_task()` auto-starts next PENDING task when concurrency slots open. Reserves `_running` immediately to prevent double-promotion race condition.
- **Task-level timeout**: `TASK_TIMEOUT=300` wraps `engine.run_task()` in `asyncio.wait_for()`. Default 5 minutes, set 0 to disable.
- **Stale action hard-stop**: `MAX_CONSECUTIVE_STALE=5` stops task with ERROR after N consecutive identical screenshots. Prevents token waste on stuck loops.
- **Fallback-before-retry**: Tries different engine first (fallback), then retries original engine with backoff. `tried_engines` cleared between retry passes.

#### Computer-Use Improvements
- **Redirect detection**: `_detect_redirect()` checks browser window title after click actions against expected domain. Catches ad-click domain redirects (ESPN->Amazon), warns model to close tab and go back.
- **Personality context gating**: Skips full context injection for simple OpenClaw chat tasks (saves 5-20K tokens). Keyword-triggered: "remember", "you are", "my name", etc.

### Changed
- Monolith grew from ~10,000 to ~10,200 lines with task queue promotion, timeouts, and redirect detection

---

## [0.2.0] - 2026-02-15

### Added

#### Workflow Recording & Replay
- **Desktop recording**: Record mouse clicks, keyboard input, and scroll events via pynput with per-event window title capture
- **Keystroke coalescing**: Rapid keystrokes within 0.3s are merged into single "type" events
- **Adaptive replay**: Replays workflows using accessibility tree element matching with 4-strategy confidence scoring (automation_id, name+type+parent, name+type, proximity)
- **LLM fallback**: When element match confidence < 0.7, describes intended step to AI model with screenshot for intelligent recovery
- **Auto target-app detection**: Detects target application from recorded window titles, handles app launch patterns (Win key → search → Enter)
- **WorkflowManager**: File-based JSON persistence in `workspace/workflows/` with create, get, delete, list, and replay tracking
- **Dashboard Workflows tab**: Record/stop toggle with timer, save form, workflow list with replay/delete buttons, step count and replay history

#### Perception Layer (`clawbridge/perception/`)
- **Screenshot utilities**: Async full-screen and window-crop capture, perceptual similarity comparison using PIL
- **Accessibility module**: Enhanced pywinauto UIA wrapper with `ElementSnapshot` dataclass, `get_accessibility_tree()`, `get_element_at_point()`, and multi-strategy `find_matching_element()`

#### New API Endpoints
- `GET /api/workflows` — list all saved workflows
- `GET /api/workflows/{id}` — get workflow details
- `POST /api/workflows` — create workflow from recorded actions
- `DELETE /api/workflows/{id}` — delete workflow
- `POST /api/workflows/{id}/replay` — trigger adaptive replay
- `POST /api/recording/start` — start desktop recording
- `POST /api/recording/stop` — stop recording, return enriched actions

#### New WebSocket Events
- `recording_start` / `recording_stop` — control recording via WebSocket
- `recording_status` / `recording_result` — recording state updates
- `save_workflow` / `workflow_saved` — save and confirm workflow
- `replay_workflow` / `replay_started` — trigger and confirm replay
- `workflow_update` — workflow list changed notification

#### Installer Improvements
- Progress bar during post-install setup (Playwright download, OpenClaw install, workspace creation)
- Visual step labels and percentage tracking

### Changed
- Monolith grew from ~5600 to ~6700 lines with workflow recording, replay, perception integration, and security hardening
- `pynput>=1.7.6` added to dependencies
- Updated `_ensure_dependencies()` to auto-install pynput on first run
- SQLite schema now includes `workflows` table

### Fixed
- Window title now captured per-event during recording (was previously captured once at stop time)
- Key name translation from pynput to pyautogui (cmd→win, ctrl_l→ctrlleft, etc.)
- Pre-focus correctly skipped when workflow starts with Win key press (app launch pattern)

---

## [0.1.0] - 2026-02-14

### Added

#### Dashboard UI
- Modern chat-style interface with message bubbles and markdown rendering (marked.js, GFM support)
- Consolidated system status bar with hover dropdown showing engine health
- Sidebar sections with collapsible panels (ENGINES, CONFIG, BROWSER, etc.)
- Config section with visual chips (green/gray) showing active/inactive status
- Color-coded activity feed with event type borders
- Chat input with ENGINE label dropdown and keyboard shortcuts (Enter to send, Shift+Enter for newline)
- Browser live view panel with streaming screenshots and idle state detection
- Tab system with tooltips, badges, and History tab for task history
- Filterable, expandable task history panel
- Onboarding checklist (4-item Getting Started card with progress bar)

#### Engines
- **browser-use**: Playwright-based web automation with headless/visible modes
- **computer-use**: Full desktop automation via Anthropic API + pyautogui + accessibility (pywinauto)
- **OpenClaw**: Node.js CDP agent with persistent memory and skills (optional install)
- Smart engine selection: auto-detects desktop vs web tasks, prefers OpenClaw when available for memory support
- Engine status indicators and one-click OpenClaw installation from dashboard

#### Automation Features
- Task scheduling with cron expressions
- Task templates with one-click execution
- Webhook triggers for external automation
- Personality system with customizable SOUL.md, IDENTITY.md, USER.md
- Memory system with daily logs and durable memory storage
- Step-by-step task replay viewer

#### Security
- Safety policy modes: guarded, permissive, strict
- Credential and PII detection in prompts
- Prompt injection pattern scanning
- Full audit trail in SQLite database

#### Infrastructure
- Single-file monolithic deployment (clawbridge.py)
- Modular package structure for development
- Windows installer via Inno Setup
- Portable build system (build.py) with embedded Python, Playwright, and optional Node.js
- WebSocket real-time updates for tasks, browser frames, and audit events
- Chrome session management with persistent profile support

### Changed
- Engine selection now prefers OpenClaw for non-desktop tasks when available (smart default)
- Version information now available via `/api/config` endpoint
- Updated EULA with clearer AI automation disclaimer and liability protection
- Added Automation Mode setting (Supervised/Autonomous) for controlling action approval

### Supervised Mode Features
- **Approval workflow**: High-risk actions pause and show approval modal
- **Sensitive domain detection**: Banking, shopping, email, cloud admin sites trigger approval
- **High-risk action patterns**: Purchases, form submissions, file deletion, etc.
- **WebSocket-based communication**: Real-time approval requests/responses
- **2-minute timeout**: Actions denied if no response within timeout
- **Activity feed integration**: Shows approval requests and responses

### Fixed
- DPI awareness for consistent coordinate systems in computer-use engine
- Screenshot scaling and stale detection in computer-use engine

---

## [0.3.0] - 2026-02-17

### Added

#### Dashboard UX Overhaul (Phase 0)
- **Always-visible Stop button**: Send button swaps to red Stop when any task is running. Tracks via `state.runningTaskId` set from WebSocket `task_update` events. Resets on terminal status (complete/error/cancelled). Double-submit guard prevents sending while task is active.
- **Slash command autocomplete**: Typing `/` shows dropdown above input with all commands (`/record`, `/stop`, `/replay`, `/browser`, `/computer`, `/chat`) and saved workflow names. Arrow keys navigate, Enter selects, Escape dismisses.
- **Chat workflow save card**: Stopping a recording from chat shows a save card (positioned between task list and input, outside render cycle) with pre-filled timestamp name. One-click save or customize.
- **Engine chip tooltips**: All 4 engine chips (Auto/Browser/Desktop/Chat) have descriptive `title=` attributes.

#### Computer-Use Improvements
- **Focus verification**: `_verify_focus()` checks foreground window title via ctypes after every focus attempt. Retries once on mismatch. `_focus_warning` string fed back to LLM so it knows when focus is wrong.
- **Ultrawide monitor support**: Monitors with aspect ratio > 2.0 auto-detected. Uses active window crop as primary screenshot (better for LLM reasoning). Full screen only on first screenshot or explicit `force_full=True`. Configurable via `COMPUTER_USE_MAX_SCREEN_WIDTH`/`HEIGHT`.

#### Browser-Use Improvements
- **Extraction-aware prompting**: When prompts contain extraction keywords ("tell me", "what is", "show me", etc.), appends instruction for browser-use Agent to return findings as final answer.
- **Page content fallback**: When `final_result` is None and prompt asked for information, extracts page text via `page.inner_text("body")` and summarizes with LLM.

#### Replay & Recording Fixes
- **Replay routing clarity**: `/replay` always forces `computer_use` engine regardless of chip selection. Routing info shows "Replaying Workflow (Visual Automation)".
- **Recorder space key fix**: pynput `Key.space` now mapped to actual `" "` character via `_PRINTABLE_KEY_MAP` before text coalescing. Previously recorded as literal string "space" (e.g., "spaceu" instead of " u").
- **Unknown special key safety**: pynput keys not in special list or printable map now recorded as standalone `key` events, preventing key names like "f1" or "home" from being dumped into text buffer.

#### Testing
- **E2E test suite**: 33 tests across 10 files covering dashboard integrity, task cancel, browser extraction, replay routing, computer focus, ultrawide, and engine routing
- **E2E harness fix**: Function-scoped async clients prevent Windows ProactorEventLoop cascade failures
- **Recorder unit tests**: 5 tests verifying space key mapping, character coalescing, enter breaking, unknown key handling

### Changed
- Monolith grew from ~6700 to ~7400 lines with UX features, focus verification, ultrawide support, and extraction enhancement
- Engine chip no longer resets to Auto after submitting a task
- Recording save from chat now uses dedicated container div (outside render cycle) instead of chatExtras (which was wiped by innerHTML replacement)

### Fixed
- Stop button no longer shows on fresh page load when orphaned "running" tasks exist from killed server sessions
- Chat recording save card now actually appears (was targeting nonexistent `chatMessages` element; actual ID is `taskList`)

---

## [0.3.5] - 2026-02-22

### Added

#### Hybrid Mechanical + AI Computer-Use
- **Mechanical pre-navigation**: `_mechanical_pre_navigate()` extracts URLs from prompts and navigates deterministically via `webbrowser.open_new()` or `Ctrl+L` hotkeys before AI engagement -- saves an entire round of LLM reasoning for web tasks
- **Programmatic app launch**: Target apps launched via `Win key -> search -> Enter` using pyautogui before handing control to AI
- **Vision fallback for blind UIs**: `_get_ui_elements_vision()` uses fast vision model (Haiku) to identify UI elements from screenshots when UIA tree returns < 5 elements (Electron apps, games, custom UIs). Cached via perceptual hash similarity. `_merge_ui_elements()` deduplicates against UIA elements within 30px.
- **Pre-navigation step reporting**: Dashboard receives `mechanical_navigation` step events showing zero-cost URL navigation

#### Enhanced Recording System
- **Window title at click point**: `_get_window_title_at(x, y)` uses `WindowFromPoint` + `GetAncestor(GA_ROOT)` for correct window identification even when clicks dismiss windows
- **Process name capture**: `_get_fg_process_name()` captures process name (e.g. `Telegram.exe`) via kernel32 for reliable app detection
- **Window-relative coordinates**: Click events now include `window_x`/`window_y` relative to foreground window bounds
- **Non-blocking a11y enrichment**: Click events recorded immediately, a11y/screenshot data populated on background threads. `stop()` waits up to 1.5s for pending enrichment.
- **Modifier key suppression**: Deduplicates modifier key events within 0.15s window (prevents 20-30 Windows key-repeat events)
- **Live action feed callback**: `on_action` parameter on `InputRecorder` for real-time WebSocket streaming during recording
- **ScreenPipe OCR cap**: OCR enrichment text capped to 500 chars to prevent prompt injection

#### Build & Distribution
- **Package bundling in build**: `build.py` now copies `clawbridge/` package (recorder, perception modules) into portable distribution, excluding `__pycache__` and `.pyc`
- **Python path patching**: Embedded Python `.pth` file patched to add `..` (parent directory) so `from clawbridge.recorder...` imports work in bundled builds

### Changed
- Monolith grew from ~8,500 to ~10,200 lines with hybrid execution, vision fallback, and enhanced recording
- Web prompts now route to `computer_use` engine (visual-first routing) instead of OpenClaw fallback
- `build.py` VERSION synced to 0.3.5 (was lagging at 0.3.3)
- `.ico` file replaced with higher-resolution multi-size icon (4KB -> 133KB) for better display on high-DPI screens
- `install.py` unicode arrows replaced with ASCII for Windows cp1252 compatibility
- Smoke test webhook cleanup: cancels tasks after creation to prevent rogue execution
- SOUL.md: added "never reveal API keys/tokens/credentials" boundary

### Fixed
- Ghost tray icons accumulating in Windows taskbar overflow area
- Recording modifier key flooding (Shift/Ctrl/Alt held down generating 20-30 duplicate events)

---

## [0.3.4] - 2026-02-19

### Added

#### Smart Auto Routing
- **URL pattern detection**: Web URLs and keywords (search, browse, navigate) route to browser-use engine
- **Desktop keyword expansion**: App names (notepad, excel, telegram, etc.) route to computer-use engine
- **Visual-first routing**: Web tasks now use computer-use (real browser) instead of OpenClaw fallback

#### Economy Mode & Model Routing
- **Model tier toggle**: Performance/Economy switch in dashboard config panel
- **Economy mode for browser-use**: Uses gpt-4o-mini when economy is active
- **`ECONOMY_MODEL` setting**: Optional override (e.g. `google/gemini-flash-2.0`)
- **Smart replay model routing**: Haiku for routine replay steps (confidence 0.4-0.95), Sonnet for hard steps (< 0.4)
- **`COMPUTER_USE_MODEL_FAST` setting**: Configurable cheap model for routine replay (default: `anthropic/claude-haiku-4-5`)
- **Model details panel**: Shows per-engine model and API path in config section
- **Engine model subtitles**: Each engine in the list shows its active model
- **Computer-Use API Path toggle**: Auto/Direct/OpenRouter selector in dashboard

#### Prompt Caching
- **System prompt caching**: `cache_control: {"type": "ephemeral"}` on content blocks. Multi-step tasks cache the system prompt (~2000+ tokens) after the first API call. 50-90% input token savings on steps 2+.
- Works with both direct Anthropic API and OpenRouter

#### Direct Anthropic API for Computer-Use
- **Dual API path**: Direct Anthropic uses native `computer_20250124`/`computer_20251124` tool via `client.beta.messages.create()`. OpenRouter uses function-tool schema.
- **`COMPUTER_USE_API` setting**: `auto` (default), `direct`, or `openrouter`
- **Tool versioning**: `_get_tool_version()` maps model to correct tool type and beta header

#### AI-Powered Recording & Replay
- **A11y enrichment at record time**: Click events get `element_name`, `element_type`, `element_automation_id`, `element_parent_name`, `confidence` from UIA tree (cached 0.5s)
- **Screenshot capture**: 720p JPEG before each click, stored as `screenshot_b64`. Toggle via `RECORDING_SCREENSHOTS`
- **ScreenPipe integration**: Optional OCR enrichment from ScreenPipe (`localhost:3030`). Toggle via `SCREENPIPE_INTEGRATION`
- **Intent extraction**: Post-recording LLM call extracts `intent`, `semantic_steps`, `detected_variables`, `target_apps`. Toggle via `RECORDING_INTENT_EXTRACTION`
- **Confidence-tiered replay**: >= 0.95 mechanical, 0.7-0.95 + visual verification, < 0.7 AI replay via LLM
- **Visual verification**: Window title match -> perceptual hash -> LLM visual check (graceful fallback chain)
- **Adaptive timing**: `_wait_for_ui_ready()` polls UIA tree stability instead of fixed delays
- **Parameterized replay**: `POST /api/workflows/{id}/replay-parameterized` with `{"params": {...}}`. Dashboard shows param input form with Save defaults button.
- **Outcome learning**: `replay_outcomes` SQLite table tracks per-step success/failure. After 3+ mechanical successes, promotes to 0.99 confidence. After 2+ failures with AI success, demotes to 0.3.

#### Dashboard Improvements
- **Workflows tab**: Saved workflows visible in sidebar tab with replay/delete/parameterize controls
- **Live recording feed**: Real-time action events via WebSocket during recording
- **Save defaults button**: Save parameterized workflow defaults without triggering replay

#### Security Hardening
- **WebSocket authentication**: Token checked before `accept()` using `hmac.compare_digest`
- **CSRF protection**: Token per session, validated on cookie-based state-changing requests
- **HttpOnly cookie**: `POST /api/auth/login` sets session cookie server-side
- **Path traversal protection**: Validates personality filenames against `..`, `/`, `\`
- **Memory injection filtering**: `safety_redact()` strips prompt injection patterns
- **Expanded injection detection**: 11 patterns (up from 6)
- **Remote bridge validation**: Requires HTTPS for non-localhost URLs

#### Security Hardening (Phase 2)
- **Key combo blocklist**: Blocks Win+R, Win+X, Ctrl+Alt+Delete, Ctrl+Shift+Esc, Win+L, Win+Pause, Alt+F4 in engine and replay paths
- **Gateway localhost binding**: OpenClaw gateway binds to `127.0.0.1` only
- **Minimal gateway env**: Subprocess gets only required env vars instead of `os.environ.copy()`
- **Personality context redaction**: `safety_redact()` applied before LLM injection
- **Replay concurrency lock**: `asyncio.Lock` prevents concurrent replays
- **Workflow-scoped confidence**: Historical confidence scoped per workflow to prevent cross-workflow poisoning
- **Browser launch port validation**: Validated to 1024-65535 range
- **Chrome kill by PID only**: No longer kills all Chrome instances system-wide

#### MCP Server Improvements
- **Auth token passthrough**: MCP proxy sends Bearer header to ClawBridge API
- **Error handling**: All 15 MCP tools wrapped with structured error dicts
- **`create_schedule` fix**: Parameters match monolith API
- **Health check timeout**: Reduced from 600s to 5s

#### Licensing & Activation System
- **Activation Backend** (`website/backend/`): Cloudflare Worker with D1 database for license management
- **Dashboard Activation Modal**: First-launch flow for activation code entry or BYOK setup
- **License Badge**: Header badge showing PRO/BYOK/FREE status
- **Credit Balance Widget**: Real-time credit tracking with top-up button
- **API Endpoints**: `/api/license/activate` and `/api/license/status`

#### Website (`website/frontend/`)
- Astro-based static site for clawbridge.ai
- Landing, pricing, download, account, and documentation pages

#### New API Endpoints
- `POST /api/workflows/{id}/extract-intent` — trigger intent extraction
- `POST /api/workflows/{id}/replay-parameterized` — replay with parameter substitution
- `POST /api/workflows/{id}/save-params` — save parameter defaults
- `POST /api/config/model-tier` — switch Performance/Economy mode
- `POST /api/config/computer-use-api` — switch API path (Auto/Direct/OpenRouter)

### Changed
- Monolith grew from ~7400 to ~8500+ lines
- License changed from MIT to Apache 2.0
- Engine selection rewritten: URL/web tasks -> browser-use, desktop keywords -> computer-use, fallback -> openclaw
- `RecordedAction` model now includes `process_name` field for reliable app detection
- `save_workflow` handler uses multi-strategy app detection (`_detect_target_from_actions`)
- Installer AppURL updated to https://clawbridge.ai

### Fixed
- `safety_scan_prompt()` callers checking non-existent key `"credential_flags"` — corrected to `"credentials"`
- Computer-use post-action re-focus race condition — dialogs/popups no longer hidden by immediate re-focus
- Browser-use step broadcasting — `on_step` callback now fires during step extraction
- Notepad "Don't Save" step being stripped during recording (volatile window title detection improved)
- Telegram replay failing due to volatile chat window titles (multi-strategy detection added)
- Parameterized replay not opening target app (missing `process_name` field on save)
- XSS: DOMPurify fallback changed from raw HTML to `esc()`
