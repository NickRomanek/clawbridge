# CLAWBRIDGE.AI MVP SPEC v0.1

**Document type:** Product + Technical Specification  
**Status:** Draft for implementation  
**Owner:** Nick | RomaTek AI  
**Date:** February 2026  
**Audience:** Founder, engineering contributors, AI coding agents

---

## 1) Purpose

This spec turns the original `clawbridge-implementation-plan.md` roadmap into an implementation-ready MVP blueprint that:

- Preserves the original strategic direction and architecture choices.
- Adds concrete engineering contracts and security requirements.
- Enables "let it run locally" user experience without over-restrictive friction.
- Keeps the system modular so complexity can be added safely over time.
- Is structured so an AI coding model can execute the build in phases.

---

## 2) Product Vision and Core Principles

### 2.1 Vision

ClawBridge is a dual-mode AI web agent platform:

- **Managed Cloud Browsing mode** for controlled, allowlisted browsing on platform infrastructure.
- **Local Bridge mode** for unrestricted browsing execution on the user's machine and IP.

### 2.2 Non-negotiable principles

1. **User-controlled execution:** Local mode runs on user hardware and user network identity.
2. **Structured results by default:** No raw HTML/screenshots leave local agent unless explicit opt-in.
3. **Secure-by-default, low-friction-by-default:** Safe unattended runs with prompts only for risky actions.
4. **Modular architecture:** Every major capability can evolve independently.
5. **Ship-first scope discipline:** MVP solves a narrow, high-value MSP workflow before broader expansion.

---

## 3) Original Plan Snapshot (Preserved Decisions)

The following decisions from the original roadmap remain in effect:

| Decision | Locked Choice |
|---|---|
| Day 1 audience | MSP technicians / IT professionals |
| Local bridge model | Tauri-based system tray agent |
| Transport | Cloudflare Tunnel + WebSocket |
| Launch scope | Managed cloud + local bridge both available |
| Managed policy | Tiered domain allowlist + hard blocklist |
| Key model | BYOK for LLM usage at launch |
| Product boundaries | ClawBridge and SasWatch stay separate |
| Prototype target | 2–4 week functional prototype |

Original roadmap content, SWOT, and risk register remain the baseline strategy and are retained in `clawbridge-implementation-plan.md`.

---

## 4) MVP Definition (What ships in v1)

### 4.1 Target user story

An MSP technician pastes a ticket/problem statement.  
ClawBridge researches docs and references, then returns a draft response with citations, via managed mode or local mode.

### 4.2 In-scope (MVP)

- Task intake in web dashboard.
- Mode selection: `Managed` or `Local Bridge`.
- Agent orchestration loop (prompt -> plan -> browse/extract -> synthesize).
- Managed browsing with tiered allowlist enforcement.
- Local agent with unattended execution for safe actions.
- Structured extraction pipeline and response synthesis.
- BYOK storage and validation.
- User-visible status, logs, and stop/pause controls.
- Basic usage metering (minutes, token estimates, run count).

### 4.3 Out-of-scope (defer)

- Enterprise SSO and full RBAC.
- Advanced plugin framework for SasWatch integration.
- Full browser replay/video stream.
- Multi-tenant enterprise governance controls.
- Broad consumer-facing workflow templates.

---

## 5) System Architecture (Implementation Form)

### 5.1 Components

| Component | Responsibility |
|---|---|
| `cloud/api` | Task APIs, auth, session management, orchestration entrypoints |
| `cloud/orchestrator` | LLM reasoning loop, tool routing, state transitions |
| `cloud/managed-browser` | Managed browsing provider adapter + allowlist gate |
| `cloud/bridge-gateway` | WebSocket command dispatch to local agents |
| `agent/runtime` | Tauri shell, tray UI, lifecycle, updater |
| `agent/tunnel` | Cloudflare Tunnel bootstrap and reconnection |
| `agent/browser` | Playwright execution and extraction |
| `agent/policy` | Local safety policy evaluation (prompt vs auto-run) |
| `web/dashboard` | Task UI, mode controls, activity stream, BYOK management |
| `shared/contracts` | Type-safe message schemas and command/result contracts |

### 5.2 Runtime modes

**Managed mode flow**  
User request -> orchestrator -> allowlist gate -> managed browser adapter -> structured extraction -> synthesis -> response.

**Local mode flow**  
User request -> orchestrator -> bridge gateway -> local agent command runner -> structured extraction only -> synthesis -> response.

---

## 6) Modularity and Expandability Strategy

Build around stable interfaces, not implementations:

- **Adapter pattern:** browser providers behind a common managed interface.
- **Policy engine:** action decisions through a single policy function.
- **Transport abstraction:** command envelope independent from Cloudflare-specific transport.
- **Extraction contract:** normalized result schema regardless of browsing mode.
- **Feature flags:** gate risky/non-essential capabilities by config.

### 6.1 Suggested monorepo structure

```text
/cloud
  /api
  /orchestrator
  /managed-browser
  /bridge-gateway
/agent
  /runtime
  /tunnel
  /browser
  /policy
/web
/shared
  /contracts
  /schemas
  /telemetry
```

---

## 7) Security Specification (Safe, Not Over-Restrictive)

### 7.1 Security goals

- Prevent unauthorized command execution.
- Minimize sensitive data exfiltration.
- Preserve unattended local usability for low-risk actions.
- Provide user-verifiable transparency.

### 7.2 Command trust model

Every cloud->agent command must include:

- `session_id`
- `command_id`
- `issued_at` + short `expires_at` (e.g., <= 60s)
- `nonce` (single-use)
- `signature` (server-signed envelope)
- `action` + typed payload

Agent validates signature, expiry, nonce uniqueness, and schema before execution.

### 7.3 Action classes

| Class | Examples | Default behavior |
|---|---|---|
| `safe_read` | navigate/read/extract/text summarize | Auto-run allowed |
| `sensitive_write` | click submit, type in forms | Prompt once per domain/session policy |
| `high_risk` | file upload/download, clipboard access, external app launch | Always prompt |

This allows unattended operation for normal research while still guarding risky behaviors.

### 7.4 Data egress policy

Default cloud return payload in local mode:

- extracted text snippets
- structured fields
- metadata (url, title, timestamp, confidence)

Not sent by default:

- full raw HTML
- full screenshots
- cookies/storage/session tokens

Optional **Debug Evidence Mode** can be enabled by user, time-limited, and clearly indicated.

### 7.5 Secrets and storage

- BYOK stored encrypted at rest.
- Per-request decryption only in memory.
- No API keys in logs.
- Agent local cache encrypted and short-lived.

### 7.6 Baseline controls checklist

- Input validation on all API and WebSocket payloads.
- Rate limiting by user + session.
- Replay protection via nonce tracking.
- Signed binaries / update verification for agent.
- Audit logs for auth and command execution events.

---

## 8) User Monitoring and Control Model

Goal: user can let local mode run unattended while retaining confidence and control.

### 8.1 Minimum UX controls

- Tray states: `Idle`, `Connected`, `Running`, `Needs attention`, `Error`, `Paused`.
- One-click controls: `Pause`, `Resume`, `Stop task`, `Disconnect`.
- Optional "Prompt me less" profile for trusted domains with clear boundaries.

### 8.2 Observability surfaces

- **Local activity feed:** recent commands, target domains, durations, outcomes.
- **Cloud task timeline:** plan/execution/result sequence.
- **Audit view:** which policy gate allowed or prompted each action.
- **Alerts:** repeated failures, auth errors, abnormal egress volume.

### 8.3 Retention defaults

- Local logs rolling 24–72h (configurable).
- Cloud execution metadata retained for support/debug window.
- Sensitive payload redaction by default.

---

## 9) API and Contract Blueprint (MVP level)

### 9.1 Core command schema (conceptual)

```json
{
  "session_id": "uuid",
  "command_id": "uuid",
  "issued_at": "iso8601",
  "expires_at": "iso8601",
  "nonce": "string",
  "signature": "base64",
  "action": "navigate|extract|click|type|screenshot",
  "payload": {},
  "policy_hint": "safe_read|sensitive_write|high_risk"
}
```

### 9.2 Core result schema (conceptual)

```json
{
  "command_id": "uuid",
  "status": "ok|error|blocked|needs_user_input",
  "url": "https://...",
  "title": "Page title",
  "extracted": {
    "summary": "...",
    "fields": {},
    "snippets": []
  },
  "metrics": {
    "duration_ms": 0
  },
  "error": null
}
```

Contracts should be codified in `shared/schemas` and validated both server-side and agent-side.

---

## 10) Tooling Evaluation (Alternatives)

### 10.1 Keep for MVP

- Cloudflare Workers + Durable Objects
- Cloudflare Tunnel
- Tauri + Playwright
- React dashboard

Reason: fastest path aligned with original plan and deployment simplicity.

### 10.2 Evaluate in parallel (do not block MVP)

| Concern | Primary choice | Alternative(s) | Notes |
|---|---|---|---|
| Workflow orchestration | In-house loop on Workers | Inngest, Temporal | Inngest easiest next step if workflows grow |
| Managed browser provider risk | Browserbase/Steel | fallback adapter to second provider | Avoid lock-in via adapter now |
| Networking model | CF Tunnel | Tailscale, WebRTC data channel | CF easiest; evaluate only if tunnel friction appears |
| Observability | basic app logs | OpenTelemetry + Sentry | Add as soon as MVP stable |
| Secret lifecycle | encrypted object storage | KMS-style envelope flow | Upgrade before larger beta |

---

## 11) Model-Driven Build Strategy

You can let a coding model build this incrementally if you constrain it with clear phases, contracts, and test gates.

### 11.1 Recommended execution mode

- **Default:** phased, modular delivery (recommended).
- **One-shot build:** only if model has full context, stable requirements, and strict review checkpoints.

Given risk and surface area, phased is safer and faster to correct.

### 11.2 Phase plan for AI-assisted implementation

1. **Phase A - Contracts first (1-2 days)**
   - Define shared schemas/types for command/result/task/policy events.
   - Build validation tests.
2. **Phase B - Managed mode baseline (2-4 days)**
   - Working task -> managed browse -> structured response path.
3. **Phase C - Local bridge baseline (3-5 days)**
   - Agent connect, signed command execution, structured extraction return.
4. **Phase D - Dashboard + controls (2-3 days)**
   - Mode toggle, task timeline, tray status, pause/stop.
5. **Phase E - Hardening (2-3 days)**
   - Security checks, observability, failure-mode polish.

### 11.3 Model guardrails (important)

- Require model to only edit within scoped module folders.
- Require all interfaces to be schema-validated.
- Require tests for each new endpoint/command.
- Require "no secrets in logs" checks in code review.
- Require a short architecture note with every major PR.

---

## 12) Testing and Release Gates

### 12.1 MVP acceptance criteria

- 3 MSP workflows run end-to-end in both modes.
- Local mode can run unattended for safe actions for an 8-hour window.
- User can pause/stop any task immediately.
- Every command has traceable audit metadata.
- No API keys or raw sensitive artifacts appear in logs.
- Basic cost telemetry available per session.

### 12.2 Test suites

- **Unit:** schema validation, policy decisions, allowlist checks.
- **Integration:** cloud->agent command lifecycle and retries.
- **Security:** signature replay tests, expiry tests, malformed payload tests.
- **UX smoke:** tray status transitions, reconnect behavior, prompt behavior.

---

## 13) Delivery Roadmap (Aligned to Original Timeline)

### Week 1

- Cloud foundations + managed browsing baseline + BYOK handling.
- Deliverable: one managed-mode scenario end-to-end.

### Week 2

- Local agent runtime + tunnel + signed command execution.
- Deliverable: local-mode scenario end-to-end with structured-only output.

### Week 3

- Dashboard + controls + telemetry.
- Deliverable: demo-ready flows with mode switch and monitoring.

### Week 4

- Security hardening + legal review + launch prep.
- Deliverable: prototype with explicit risk controls and beta readiness.

---

## 14) Open Decisions (Resolve Before Coding Sprint)

1. Playwright integration strategy in agent (`Node child process` vs `Rust bindings`).
2. Signed command implementation method and key rotation cadence.
3. Prompt policy defaults for `sensitive_write` actions.
4. Evidence/debug mode retention window and redaction policy.
5. Which managed browser provider is primary vs fallback.

---

## 15) Immediate Next Actions (Actionable)

1. Finalize `shared/contracts` JSON schema set.
2. Create monorepo skeleton with module folders from this spec.
3. Implement managed-mode thin slice first (single workflow).
4. Implement local bridge signed-command thin slice second.
5. Add observability hooks before broadening action surface.

---

## 16) Appendix: Source Plan Mapping

This spec incorporates and preserves the original sections from `clawbridge-implementation-plan.md`:

- Executive Summary
- System Architecture
- Managed Browsing Allowlist Strategy
- Implementation Roadmap (Phases 1-3)
- SWOT Analysis
- SasWatch Integration Recommendation
- Risk Register
- Day 1 Priority Checklist

Where this spec extends the original:

- explicit command/result contracts
- unattended-safe local policy model
- security trust envelope and action classes
- user monitoring/control requirements
- phased AI-assisted build guardrails

