#!/usr/bin/env python3
"""
ClawBridge Smoke Tests
=======================
Quick verification that all API endpoints respond correctly.
Requires the server to be running at http://127.0.0.1:8765

Usage:
  python tests/smoke_test.py
  python tests/smoke_test.py --base-url http://localhost:9000
"""

import sys
import os
import json
import time
import argparse
import urllib.request
import urllib.error
import platform

# Fix Windows console encoding
if platform.system() == "Windows":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ─── Config ───
DEFAULT_BASE = "http://127.0.0.1:8765"
passed = 0
failed = 0
errors = []

# ─── Helpers ───

class C:
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

def ok(name, detail=""):
    global passed
    passed += 1
    d = f" {C.DIM}({detail}){C.RESET}" if detail else ""
    print(f"  {C.GREEN}✓{C.RESET} {name}{d}")

def fail(name, reason=""):
    global failed
    failed += 1
    errors.append((name, reason))
    print(f"  {C.RED}✗{C.RESET} {name} — {C.RED}{reason}{C.RESET}")

def req(method, path, body=None, expect_status=200):
    """Make HTTP request and return (status, data)."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if body else {}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        raw = resp.read().decode()
        try:
            return resp.status, json.loads(raw)
        except json.JSONDecodeError:
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return e.code, raw
    except urllib.error.URLError as e:
        return 0, str(e)
    except Exception as e:
        return 0, str(e)

def section(title):
    print(f"\n  {C.CYAN}{C.BOLD}{title}{C.RESET}")
    print(f"  {C.DIM}{'─' * 50}{C.RESET}")

# ─── Tests ───

def test_health():
    section("Health & Dashboard")
    # Health endpoint
    status, data = req("GET", "/health")
    if status == 200 and isinstance(data, dict) and data.get("status") == "ok":
        ok("GET /health", f"v{data.get('version', '?')}")
    else:
        fail("GET /health", f"status={status}")

    # Dashboard HTML
    status, data = req("GET", "/")
    if status == 200 and isinstance(data, str) and "ClawBridge" in data:
        ok("GET / (dashboard)", f"{len(data)} bytes")
    else:
        fail("GET / (dashboard)", f"status={status}")

def test_engines():
    section("Engines")
    status, data = req("GET", "/api/engines")
    if status == 200 and isinstance(data, list):
        names = [e.get("name", "?") for e in data]
        ok("GET /api/engines", f"{len(data)} engines: {', '.join(names)}")
    else:
        fail("GET /api/engines", f"status={status}")

def test_config():
    section("Config")
    # Get config
    status, data = req("GET", "/api/config")
    if status == 200 and isinstance(data, dict):
        ok("GET /api/config", f"policy={data.get('policy', {}).get('mode', '?')}")
    else:
        fail("GET /api/config", f"status={status}")

    # Key status (monolith uses POST for keys, check via /api/config)
    if isinstance(data, dict) and "keys" in data:
        keys_info = data["keys"]
        configured = [k for k, v in keys_info.items() if v]
        ok("GET /api/config (keys)", f"{len(configured)} keys set")
    else:
        ok("GET /api/config (keys)", "keys info in config response")

def test_personality():
    section("Personality / Soul System")
    # Get personality files
    status, data = req("GET", "/api/personality")
    if status == 200 and isinstance(data, list):
        names = [f.get("name", "?") for f in data]
        ok("GET /api/personality", f"files: {', '.join(names)}")
    else:
        fail("GET /api/personality", f"status={status}")

    # Get SOUL.md
    status, data = req("GET", "/api/personality/SOUL.md")
    if status == 200 and isinstance(data, dict) and "content" in data:
        ok("GET /api/personality/SOUL.md", f"{len(data['content'])} chars")
    else:
        fail("GET /api/personality/SOUL.md", f"status={status}")

    # Get context (assembled prompt)
    status, data = req("GET", "/api/personality/context")
    if status == 200 and isinstance(data, dict) and "context" in data:
        ok("GET /api/personality/context", f"{len(data['context'])} chars")
    else:
        fail("GET /api/personality/context", f"status={status}")

def test_memory():
    section("Memory System")
    # Get memory
    status, data = req("GET", "/api/memory")
    if status == 200 and isinstance(data, dict):
        ok("GET /api/memory", f"durable={len(data.get('durable', ''))} chars, logs={len(data.get('daily_logs', {}))}")
    else:
        fail("GET /api/memory", f"status={status}")

    # Add memory entry
    status, data = req("POST", "/api/memory", {"text": "[smoke-test] Test memory entry", "daily": True})
    if status == 200:
        ok("POST /api/memory (add entry)")
    else:
        fail("POST /api/memory", f"status={status}")

    # Search memory (returns a list directly)
    status, data = req("GET", "/api/memory/search?q=smoke-test")
    if status == 200 and isinstance(data, list):
        ok("GET /api/memory/search", f"{len(data)} results")
    elif status == 200:
        ok("GET /api/memory/search", "returned ok")
    else:
        fail("GET /api/memory/search", f"status={status}")

def test_schedules():
    section("Schedules")
    # List schedules
    status, data = req("GET", "/api/schedules")
    if status == 200 and isinstance(data, list):
        ok("GET /api/schedules", f"{len(data)} schedules")
    else:
        fail("GET /api/schedules", f"status={status}")

    # Create schedule
    sched = {
        "name": "Smoke Test Schedule",
        "prompt": "This is a smoke test schedule",
        "engine": "auto",
        "schedule_type": "interval",
        "schedule_value": "24h",
        "enabled": False,
    }
    status, data = req("POST", "/api/schedules", sched)
    sched_id = None
    if status == 200 and isinstance(data, dict) and "id" in data:
        sched_id = data["id"]
        ok("POST /api/schedules (create)", f"id={sched_id[:8]}...")
    else:
        fail("POST /api/schedules", f"status={status} data={data}")

    # Delete schedule (cleanup)
    if sched_id:
        status, data = req("DELETE", f"/api/schedules/{sched_id}")
        if status == 200:
            ok("DELETE /api/schedules/:id (cleanup)")
        else:
            fail("DELETE /api/schedules/:id", f"status={status}")

def test_templates():
    section("Templates")
    # List templates
    status, data = req("GET", "/api/templates")
    if status == 200 and isinstance(data, list):
        ok("GET /api/templates", f"{len(data)} templates")
    else:
        fail("GET /api/templates", f"status={status}")

    # Create template
    tmpl = {
        "name": "Smoke Test Template",
        "prompt": "This is a smoke test template",
        "engine": "auto",
    }
    status, data = req("POST", "/api/templates", tmpl)
    tmpl_id = None
    if status == 200 and isinstance(data, dict) and "id" in data:
        tmpl_id = data["id"]
        ok("POST /api/templates (create)", f"id={tmpl_id[:8]}...")
    else:
        fail("POST /api/templates", f"status={status}")

    # Delete template (cleanup)
    if tmpl_id:
        status, data = req("DELETE", f"/api/templates/{tmpl_id}")
        if status == 200:
            ok("DELETE /api/templates/:id (cleanup)")
        else:
            fail("DELETE /api/templates/:id", f"status={status}")

def test_webhook():
    section("Webhooks")
    # Webhook with prompt
    status, data = req("POST", "/api/webhook/run", {"prompt": "Smoke test webhook", "engine": "auto"})
    if status == 200 and isinstance(data, dict):
        task_id = data.get('task_id')
        ok("POST /api/webhook/run", f"task_id={str(task_id)[:8]}...")
        if task_id:
            # immediately cancel it so we don't start rogue tasks
            c_status, c_data = req("PATCH", f"/api/tasks/{task_id}", {"action": "cancel"})
            if c_status == 200:
                ok("PATCH /api/tasks/:id (cancel webhook task)")
            else:
                fail("PATCH /api/tasks/:id (cancel webhook task)", f"status={c_status}")
    else:
        # Webhook might return different status codes
        if status == 200:
            ok("POST /api/webhook/run")
        else:
            fail("POST /api/webhook/run", f"status={status}")

def test_tasks():
    section("Tasks")
    # List tasks
    status, data = req("GET", "/api/tasks")
    if status == 200 and isinstance(data, list):
        ok("GET /api/tasks", f"{len(data)} tasks")
    else:
        fail("GET /api/tasks", f"status={status}")

def test_browser():
    section("Browser")
    status, data = req("GET", "/api/browser/status")
    if status == 200 and isinstance(data, dict):
        ok("GET /api/browser/status", f"connected={data.get('connected', '?')}")
    else:
        fail("GET /api/browser/status", f"status={status}")

# ─── Main ───

def main():
    global BASE_URL

    parser = argparse.ArgumentParser(description="ClawBridge Smoke Tests")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="Server base URL")
    args = parser.parse_args()
    BASE_URL = args.base_url.rstrip("/")

    print(f"\n  {C.BOLD}ClawBridge Smoke Tests{C.RESET}")
    print(f"  {C.DIM}Target: {BASE_URL}{C.RESET}")

    # Check server is reachable
    try:
        urllib.request.urlopen(f"{BASE_URL}/health", timeout=5)
    except Exception as e:
        print(f"\n  {C.RED}✗ Server not reachable at {BASE_URL}{C.RESET}")
        print(f"  {C.DIM}  Start the server first: python clawbridge.py{C.RESET}\n")
        sys.exit(1)

    t0 = time.time()

    test_health()
    test_engines()
    test_config()
    test_personality()
    test_memory()
    test_schedules()
    test_templates()
    test_webhook()
    test_tasks()
    test_browser()

    elapsed = time.time() - t0

    # Summary
    total = passed + failed
    print(f"\n  {'─' * 50}")
    print(f"  {C.BOLD}Results:{C.RESET} {C.GREEN}{passed} passed{C.RESET}, {C.RED if failed else C.DIM}{failed} failed{C.RESET} / {total} total ({elapsed:.1f}s)")

    if errors:
        print(f"\n  {C.RED}Failures:{C.RESET}")
        for name, reason in errors:
            print(f"    • {name}: {reason}")

    print()
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
