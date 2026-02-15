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

## [Unreleased]

### Added

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
