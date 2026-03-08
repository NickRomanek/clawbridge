## Pre-Release Security Scan

Run this before `/deploy` to catch security issues. Three-step process: scan, triage, report.

### Step 1: Run Semgrep locally

```bash
pip install semgrep 2>/dev/null
semgrep scan --config auto --config p/python --config p/secrets --config p/owasp-top-ten --severity WARNING clawbridge.py clawbridge_mcp.py
```

If Semgrep is not installed, install it first. Parse the output and categorize findings by severity.

### Step 2: Run the security-auditor agent

After Semgrep completes, launch the `security-auditor` subagent to do a deeper review focusing on:
- Any Semgrep findings that need human judgment (true positive vs false positive)
- Memory/context poisoning paths
- Prompt injection vectors
- Network exposure (WebSocket, CORS, rate limiting)
- Subprocess security (engine launches, key handling)
- Dashboard XSS (especially in dynamically rendered content)

### Step 3: Report

Present a summary table with:
- CRITICAL/HIGH findings that MUST be fixed before deploy
- MEDIUM findings that should be tracked
- LOW/informational findings to note
- False positives to ignore (explain why)

### Past findings to watch for

- **v0.5.5**: `--host 127.0.0.1` was not a valid OpenClaw flag — broke the gateway silently. Always verify CLI flags against `--help`.
- **v0.5.5**: Python `\n` in JS regex broke entire dashboard script block. Semgrep won't catch this — it's a Python-in-JS escaping issue.
- **v0.5.3**: Engine error messages leaked API keys before `safety_redact()` was applied.
- **Ongoing**: No CSP header on dashboard. Memory poisoning via task result previews in daily logs. WebSocket accepts missing Origin header when no auth is set.

### Decision guide

- **0 CRITICAL/HIGH** → Safe to `/deploy`
- **Any CRITICAL** → Fix before deploying, no exceptions
- **HIGH only** → Fix if quick (<30 min), otherwise document and track for next release
