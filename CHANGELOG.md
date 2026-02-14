# Changelog

All notable changes to ClawBridge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Fixed
- DPI awareness for consistent coordinate systems in computer-use engine
- Screenshot scaling and stale detection in computer-use engine

---

## [Unreleased]

### Planned
- Code signing certificate for Windows installer
- Auto-update mechanism
- macOS build support
- Cloud bridge service
- Discord community for user support
