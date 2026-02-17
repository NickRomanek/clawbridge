# Changelog

All notable changes to ClawBridge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

## [Unreleased]

### Added

#### Security Hardening
- **WebSocket authentication**: Token checked before `accept()` using `hmac.compare_digest`, mirrors HTTP middleware logic
- **CSRF protection**: Token generated per session, injected into dashboard via `__PRELOAD__`, validated on cookie-based POST/PUT/PATCH/DELETE requests. API clients using Authorization header or query param are exempt.
- **HttpOnly cookie**: New `POST /api/auth/login` endpoint sets session cookie server-side with `httponly=True` and `samesite=strict`. Login form no longer sets cookie via JavaScript.
- **Path traversal protection**: `PUT /api/personality/{filename}` validates against `..`, `/`, `\` in filename (defense-in-depth on top of existing whitelist)
- **Memory injection filtering**: `safety_redact()` now strips prompt injection patterns (`[FILTERED]`) in addition to credentials and PII. Also applied to `POST /api/memory` input.
- **Expanded injection detection**: 11 patterns (up from 6) including admin/debug mode, execute command, `[SYSTEM]`/`[ADMIN]`/`[OVERRIDE]` tags, and broader instruction override variants
- **Remote bridge validation**: Requires HTTPS for non-localhost URLs and requires `REMOTE_AUTH_TOKEN` to be set
- **XSS fix**: DOMPurify fallback changed from raw HTML to `esc()` (safe text encoding)
- **Recorder/perception graceful degradation**: `start_recording()`, `stop_recording()`, and `_replay_single_action()` now handle missing `clawbridge.recorder` / `clawbridge.perception` packages with try/except ImportError

#### MCP Server Improvements
- **Auth token passthrough**: MCP proxy reads `DASHBOARD_TOKEN` from env and sends as Bearer header to ClawBridge API
- **Error handling**: All 15 MCP tools wrapped in try/except with structured error dicts for `HTTPStatusError`, `ConnectError`, and generic exceptions
- **`create_schedule` fix**: Parameters now match monolith API (`name`, `schedule_type`, `schedule_value` instead of `interval_minutes`/`cron`)
- **Health check timeout**: Reduced from 600s to 5s to prevent blocking

### Fixed
- Computer-use engine post-action re-focus race condition — dialogs/popups opened by actions are no longer hidden by immediate re-focus. Pre-action sleep reduced from 0.5s to 0.3s.
- Browser-use engine step broadcasting — `on_step` callback now fires during step extraction, dashboard shows step count and details for browser-use tasks
- `pyautogui` dependency now has `sys_platform == 'win32'` marker in requirements.txt

#### Licensing & Activation System
- **Activation Backend** (`website/backend/`): Cloudflare Worker with D1 database for license management
  - Stripe webhook integration for payment processing
  - OpenRouter Management API integration for provisioned API keys
  - Activation code generation (CB-XXXX-XXXX-XXXX format)
  - AES-256-GCM encryption for stored API keys
  - License status and credit balance endpoints
  - Top-up flow with Stripe Checkout
  - Transactional emails via Resend
- **Dashboard Activation Modal**: First-launch flow for activation code entry or BYOK setup
- **License Badge**: Header badge showing PRO/BYOK/FREE status
- **Credit Balance Widget**: Real-time credit tracking with visual progress bar and top-up button
- **Install Wizard**: New "Activate ClawBridge" step with three options (activation code, BYOK, purchase)
- **MCP Tool**: `get_license_info()` for querying license status from Claude Code
- **Settings**: New `activation_code`, `activation_backend_url`, `license_tier` configuration options
- **API Endpoints**: `/api/license/activate` and `/api/license/status` for license management

#### Website (`website/frontend/`)
- Astro-based static site for clawbridge.ai
- Landing page with features and value proposition
- Pricing page with Starter ($9.99) and BYOK (free) tiers
- Download page with quick start guide
- Account dashboard for credit management and top-ups
- Documentation pages including BYOK setup guide

### Changed
- Updated installer.iss AppURL to https://clawbridge.ai
- Install wizard now has 8 steps (added activation step)

### Planned
- Stripe Checkout integration on pricing page
- Code signing certificate for Windows installer
- Auto-update mechanism
- macOS build support
- Discord community for user support
