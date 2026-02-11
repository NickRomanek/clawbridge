# CLAWBRIDGE.AI

## Implementation Roadmap & Architecture Plan

**Bridging Open-Source AI Agents to Your Machine**

- **Prepared for:** Nick | RomaTek AI  
- **Date:** February 2026  
- **Classification:** Internal — Strategic Planning  
- **Target:** Working Prototype in 2–4 Weeks

---

## 1. Executive Summary

ClawBridge.ai is a dual-mode AI agent platform that offers both cloud-hosted managed browsing and a local browser bridge for users who need unrestricted web access. The platform is built on Cloudflare’s edge compute infrastructure (Moltworker framework) with a Tauri-based desktop agent for local execution.

The product targets MSP technicians and IT professionals as the Day 1 audience, expanding to power users and eventually non-technical consumers. The local bridge architecture solves the critical IP reputation and EULA compliance problem by shifting web browsing execution to the user’s own machine and IP address, while the cloud backend handles AI reasoning, task orchestration, and state management.

The local agent is a standalone Tauri desktop application. SasWatch remains a separate product; the two may share infrastructure components later if market demand warrants it, but are architecturally independent for now.

### Key Decisions Locked In

| Decision | Choice |
|---|---|
| Day 1 Audience | MSP technicians / IT professionals |
| Local Bridge Model | Tauri-based system tray agent (cross-platform, ~10MB) |
| Communication Layer | Cloudflare Tunnel + WebSocket upgrade for real-time commands |
| Launch Scope | Both managed cloud + local bridge at launch |
| Managed Browsing Policy | Curated domain allowlist (tiered: default + categories + custom) |
| Local Bridge Liability | Pending legal review ($750 SaaS attorney consult before launch) |
| SasWatch Integration | Separate products — ClawBridge and SasWatch are independent, potential shared tech later |
| Billing Model | BYOK (Bring Your Own Key) at launch |
| Timeline | 2–4 weeks to working prototype (aggressive, nights & weekends) |

---

## 2. System Architecture

### 2.1 High-Level Data Flow

The platform operates in two distinct modes, both orchestrated by the same cloud backend.

**Mode A: Managed Cloud Browsing**  
User Request -> Cloudflare Worker (Agent Brain) -> Headless Browser Pool (Browserbase/Steel) -> Allowlisted Domains Only -> Structured Results -> AI Processing -> Response to User.

All browsing happens on platform infrastructure using residential proxy IPs. Domain access is restricted to the curated allowlist. User pays platform subscription + BYOK for LLM tokens.

**Mode B: Local Bridge Browsing**  
User Request -> Cloudflare Worker (Agent Brain) -> Cloudflare Tunnel -> ClawBridge Local Agent (user’s machine) -> Local Headless Browser (user’s IP, cookies, sessions) -> Structured Results Only sent back to cloud -> AI Processing -> Response to User.

Browsing execution happens entirely on the user’s machine. Only structured/summarized data returns to the cloud. No raw HTML or screenshots traverse the tunnel by default.

### 2.2 Component Stack

| Layer | Technology | Purpose |
|---|---|---|
| Agent Brain | Cloudflare Workers + Durable Objects | Task orchestration, AI reasoning, state management, session persistence |
| LLM Interface | BYOK (Anthropic/OpenAI) | User’s own API keys, encrypted at rest in R2, never logged |
| Managed Browsing | Browserbase or Steel.dev | Headless browser pool for cloud-mode browsing at ~$0.01/min |
| Local Bridge | Tauri + Rust + Playwright | System tray agent controlling local headless/visible browser |
| Tunnel | Cloudflare Tunnel (cloudflared) | Encrypted, NAT-traversing connection; no open inbound ports |
| Real-time Comms | WebSocket over CF Tunnel | Sub-100ms command latency for browse/click/extract actions |
| Storage | Cloudflare R2 + Durable Objects | User workspaces, session state, encrypted API keys |
| Proxy (Managed) | Bright Data / SmartProxy | Residential IPs for managed browsing tier to avoid blocks |
| Frontend | React + Cloudflare Pages | Web dashboard for task management, results, agent interaction |

### 2.3 ClawBridge Local Agent Architecture (Tauri)

The ClawBridge local agent is a focused, single-purpose Tauri application with clean internal architecture.

| Module | Responsibility |
|---|---|
| Core Runtime | Tauri shell, system tray icon, auto-update, Cloudflare Tunnel lifecycle management, health monitoring |
| Browser Control Module | WebSocket command handler, local Playwright browser management, structured data extraction, screenshot capture (local only) |
| Tunnel Management Module | Application usage monitoring, telemetry collection, license audit data transmission (shares the same CF Tunnel) |
| Settings UI | Local web UI for configuration, module enable/disable, tunnel status, browsing preferences |

---

## 3. Managed Browsing: Domain Allowlist Strategy

The managed cloud browsing tier uses a three-tier domain allowlist system designed to cover 80%+ of MSP research tasks while protecting platform IP reputation.

### 3.1 Tier Structure

| Tier | Access Model | Example Domains | Est. Domain Count |
|---|---|---|---|
| Tier 1: Default | Pre-loaded, always on | learn.microsoft.com, github.com, stackoverflow.com, google.com, wikipedia.org | 200–300 domains |
| Tier 2: Categories | User opts in per bundle | News bundle, Gov/regulatory, Cloud consoles (read-only), Developer tools | 50–100 per bundle |
| Tier 3: Custom | User adds manually | Internal wikis, niche vendor sites, custom portals | Free: 50, Pro: 200 |
| Hard Block | Never accessible | LinkedIn, Facebook, Instagram, X/Twitter, banking sites, healthcare portals | Permanent blocklist |

Key principle: if a user needs to access a hard-blocked domain (LinkedIn, social media), they use the local bridge. This is the primary conversion driver from managed-only to local bridge installation.

---

## 4. Implementation Roadmap

Based on the 2–4 week aggressive prototype timeline, the plan is divided into three phases. Phase 1 is the prototype. Phases 2 and 3 extend into months 2–6.

### 4.1 Phase 1: Working Prototype (Weeks 1–4)

Goal: a functional end-to-end demo where an MSP technician can paste a support ticket and the agent researches the issue, browses relevant docs (via both managed and local modes), and returns a drafted response.

#### Week 1: Cloud Backend + Managed Browsing

| Day | Task | Deliverable |
|---|---|---|
| 1–2 | Set up Cloudflare Worker project with Moltworker framework. Configure R2 bucket for user workspace storage. Deploy basic Durable Object for session state. | Worker responds to API requests, creates/reads user workspaces in R2 |
| 3–4 | Integrate Browserbase/Steel.dev SDK for managed headless browsing. Implement domain allowlist filter (Tier 1 default list). Build egress proxy layer that routes all browse requests through allowlist check. | Agent can browse allowlisted sites via managed pool and return page content |
| 5–6 | Wire up BYOK key management: encrypted storage in R2, key validation endpoint, per-request decryption. Build agent orchestration loop: user prompt -> LLM reasoning -> tool selection -> browse/extract -> synthesize response. | End-to-end managed browsing: user sends task, agent browses and responds using user’s API key |
| 7 | Testing, bug fixes, cost measurement. Run 10 realistic agent sessions and log Cloudflare billing to validate unit economics. | Actual cost-per-session data for managed mode |

#### Week 2: ClawBridge Local Agent (Tauri)

| Day | Task | Deliverable |
|---|---|---|
| 8–9 | Scaffold Tauri project with Rust backend. Implement system tray icon with status indicator. Embed cloudflared binary for tunnel creation. Build tunnel lifecycle management (start/stop/reconnect). | Installable system tray app that creates a Cloudflare Tunnel on launch |
| 10–11 | Integrate Playwright (Node.js child process or Rust binding) for local headless browser control. Build WebSocket command handler: receive browse commands from cloud, execute locally, return structured results. | Cloud can send "navigate to X, extract Y" commands that execute on user’s machine |
| 12–13 | Build structured data extraction layer: local agent parses pages and returns only summarized/structured data to cloud (not raw HTML). Implement the "structured results only" pattern for legal protection. | Local bridge sends clean JSON responses, never raw page content |
| 14 | End-to-end integration test: task submitted via web UI -> cloud agent decides to browse -> routes to local bridge -> executes on user machine -> structured results return -> AI synthesizes response. | Full local bridge flow working end-to-end |

#### Week 3: Web Dashboard + Mode Switching

| Day | Task | Deliverable |
|---|---|---|
| 15–17 | Build React web dashboard on Cloudflare Pages. Task input interface, conversation thread display, results panel. Mode toggle: Managed Cloud vs. Local Bridge (with connection status). BYOK key management UI (add/rotate/delete keys). | Functional web UI with task submission and mode selection |
| 18–19 | Implement domain allowlist management UI for managed mode. Build local bridge status page (tunnel connected, last activity, browsing history). Add usage metering display (browsing minutes, LLM tokens consumed). | User can see and manage their allowlist, monitor local agent status |
| 20–21 | Polish, bug fixes, edge case handling. Write 3 demo scenarios for MSP use cases (ticket research, vendor comparison, incident report draft). Record demo video for internal validation. | Demo-ready prototype with 3 MSP-focused workflows |

#### Week 4 (Buffer): Hardening + Legal

| Day | Task | Deliverable |
|---|---|---|
| 22–23 | Security audit: API key encryption verification, tunnel auth hardening, WebSocket message validation, input sanitization. | Security checklist completed |
| 24–25 | SaaS attorney consultation ($750 budget). Review TOS draft for local bridge liability. Finalize "structured results only" architecture with legal sign-off. | Legal-reviewed TOS and privacy policy |
| 26–28 | Build landing page targeting MSPs. Set up waitlist with 50 beta slots. Prep launch content for LinkedIn, r/msp, and Casual Intelligence podcast. | Public waitlist live, launch content drafted |

### 4.2 Phase 2: Beta + Revenue (Months 2–3)

| Milestone | Details |
|---|---|
| Beta Launch | 50 MSP beta users. Onboard via direct outreach from LinkedIn network and r/msp community. Free access in exchange for weekly feedback. |
| Pricing Validation | Test $29/month (managed only) and $49/month (managed + local bridge) tiers. Measure conversion and usage patterns. |
| SasWatch Module | Evaluate whether SasWatch and ClawBridge should share any infrastructure components (e.g., Cloudflare Tunnel, local agent framework). Products remain separate but may share learnings and code libraries. |
| Power User Expansion | Open to power users via Product Hunt, Hacker News launch. Add non-IT use cases: research assistant, content creation, data analysis. |
| Usage Analytics | Instrument every session: browsing minutes, LLM tokens, mode preference (managed vs. local), most-used domains. This data drives Phase 3 pricing. |

### 4.3 Phase 3: Scale + Monetize (Months 4–6)

| Milestone | Details |
|---|---|
| Managed Credits (Optional) | If usage data supports it, introduce "Simple Mode" with managed credits for non-technical users who don’t have API keys. Premium pricing ($79–$99/month) to cover LLM token costs + margin. |
| SasWatch Cross-sell | MSPs using ClawBridge are natural prospects for SasWatch. Cross-sell via shared audience (LinkedIn, r/msp, podcast). Consider bundle pricing if both products have traction. |
| Vertical Templates | Pre-built agent workflows for MSP use cases: automated ticket research, vendor quote comparison, compliance audit drafts, client communication templates. |
| Enterprise Tier | Multi-user accounts, audit logging, SSO, custom domain allowlists, dedicated proxy pools. Target: MSPs with 10+ technicians at $99/seat/month. |

---

## 5. SWOT Analysis

| Strengths | Weaknesses |
|---|---|
| Dual-mode architecture solves IP/EULA problem that competitors ignore | Solo founder bandwidth — maintaining cloud + local agent + dashboard simultaneously |
| "Structured results only" pattern provides strong legal defensibility | Tauri local agent adds significant development/testing surface area |
| BYOK model eliminates LLM token subsidy risk for solo founder | Browser rendering costs unpredictable and potentially high at scale |
| Deep IT/MSP domain expertise provides credibility competitors can’t fake | No existing user base specifically for agent product |
| Cloudflare edge compute provides genuine per-user isolation at low cost | Dependency on multiple third-party services (Cloudflare, Browserbase, proxy providers) |
| Shared MSP audience creates natural cross-sell path between ClawBridge and SasWatch | 2–4 week prototype timeline is aggressive for dual-mode architecture |

| Opportunities | Threats |
|---|---|
| MSP vertical is massively underserved by AI agent tooling | Cloudflare could build native agent hosting (AI Workers investment ongoing) |
| Open-source agent ecosystem exploding but deployment remains painful | Anthropic/OpenAI offering hosted agents directly (Computer Use, Operator) |
| Privacy/data sovereignty concerns growing — local bridge addresses this directly | IP blocking/scraping arms race intensifying across major platforms |
| Cross-sell flywheel: SasWatch <-> ClawBridge <-> RomaTek consulting <-> Casual Intelligence podcast | Platform risk: Moltworker pricing changes or deprecation |
| Casual Intelligence podcast provides built-in distribution channel | Residential proxy costs could spike if providers consolidate |
| Potential to white-label for MSP tool vendors (ConnectWise, Datto ecosystem) | Legal landscape for AI web scraping still evolving rapidly |

---

## 6. SasWatch Integration: Recommendation

**Verdict: Option B — Shared Tech Layer**

The recommended approach is to keep ClawBridge and SasWatch as separate products with independent codebases. The Tauri agent contains two core modules: the Tunnel Management module (Cloudflare Tunnel lifecycle, WebSocket connection) and the Browser Control module (Playwright automation, screenshot capture, command execution). SasWatch remains a completely separate product.

This avoids architectural coupling, lets each product ship on its own timeline, and means a bug in one never impacts the other. If both gain traction with the same MSP audience, a shared infrastructure layer can be introduced later without rearchitecting either product.

### What This Means for the Prototype

During weeks 1–4, you build the Tauri agent as a standalone ClawBridge application. The architecture is clean and focused: Cloudflare Tunnel management, WebSocket command channel, Playwright browser control, and screenshot streaming. No plugin abstraction layer is needed, which saves 2–3 days of design work and keeps the codebase simple.

### Brand Architecture

| Entity | Role |
|---|---|
| RomaTek AI | Parent company. Consulting arm. Podcast host entity. |
| ClawBridge Agent | The local agent platform. "One install, all capabilities." Neutral brand that doesn’t lock into any single product vertical. |
| ClawBridge | AI agent platform. Tauri local agent + cloud brain. Standalone product with own codebase. |
| SasWatch | License intelligence product. Separate codebase. Targets same MSP audience for cross-sell potential. |

---

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Browser rendering costs exceed projections | High | High | Use Browserbase/Steel (not CF native). Hard cap browsing minutes per user. Monitor costs weekly during beta. |
| Cloudflare changes Moltworker pricing or deprecates features | Medium | High | Abstract infrastructure layer so backend can migrate to AWS Lambda@Edge or Deno Deploy if needed. Avoid deep CF-specific APIs where alternatives exist. |
| Legal challenge re: local bridge scraping liability | Low | High | Attorney consultation before launch. "Structured results only" architecture. Clear TOS with liability shift. Precedent from VPN/RPA industry. |
| Solo founder burnout / scope creep | High | Medium | Strict phase gating. No SasWatch integration until Phase 2. No consumer features until Phase 3. Prototype must ship before any optimization. |
| MSP adoption slower than expected | Medium | Medium | Pivot to power user market (already planned for Phase 2). Use podcast and LinkedIn for organic distribution. 50-slot beta keeps risk contained. |
| Tauri agent installation friction on enterprise-managed machines | Medium | Medium | Provide MSI installer for enterprise deployment via Intune/SCCM. Managed-only mode works without any local install as fallback. |

---

## 8. Day 1 Priority Checklist

Actions to take before writing any code:

| # | Action | Why |
|---|---|---|
| 1 | Create Cloudflare account (if not existing) with Workers Paid plan ($5/month). Create R2 bucket. Deploy a hello-world Worker. | Validate your billing and deployment pipeline before building anything |
| 2 | Sign up for Browserbase or Steel.dev. Run 5 test browsing sessions manually. Measure latency and cost per session. | Confirm managed browsing cost assumptions before committing to architecture |
| 3 | Install Tauri CLI and scaffold a basic system tray app. Confirm it runs on Windows. Embed cloudflared and verify tunnel creation. | De-risk the local agent build — this is the most uncertain component |
| 4 | Define the WebSocket command protocol between cloud and local agent. Document the message format for browsing commands (navigate, click, type, screenshot) and responses. | 2–3 hours of upfront design prevents weeks of rework when adding SasWatch later |
| 5 | Create GitHub repo with monorepo structure: `/cloud` (Workers), `/agent` (Tauri), `/web` (React dashboard), `/shared` (types and interfaces). | Clean codebase structure from day one. You’ll thank yourself in month 2. |
| 6 | Draft initial Tier 1 domain allowlist (200 domains). Focus on: Microsoft docs, vendor KBs, search engines, GitHub, Stack Overflow, major cloud provider docs. | This list defines the managed browsing experience and can’t be an afterthought |
| 7 | Book SaaS attorney consultation for week 3–4. Send them the "structured results only" architecture brief and draft TOS in advance. | Legal review on the local bridge liability question must happen before public beta |
| 8 | Record a 5-minute Casual Intelligence segment explaining the concept. Use listener feedback as early market validation. | Free market research from your existing audience |

---

**End of Plan**  
RomaTek AI | ClawBridge.ai | Confidential
