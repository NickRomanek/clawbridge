#!/usr/bin/env python
"""Quick test runner. Minimal typing, no AI overhead, just pytest.

Usage:
    python test.py              # all e2e tests (default)
    python test.py replay       # recording/replay tests
    python test.py record       # recording flow tests
    python test.py routing      # auto-routing + replay routing
    python test.py browser      # browser engine tests
    python test.py computer     # computer engine tests
    python test.py openclaw     # openclaw engine tests
    python test.py dashboard    # dashboard + stop button
    python test.py workflow     # workflow CRUD + lifecycle
    python test.py cancel       # task cancel tests
    python test.py unit         # unit tests only (no server needed)
    python test.py smoke        # smoke tests (needs server)
    python test.py all          # unit + e2e + smoke (everything)
"""

import subprocess
import sys
import urllib.request

DEFAULT_TARGET = "e2e"

TARGETS = {
    "e2e": "tests/e2e/ --run-e2e",
    "replay": "tests/e2e/test_recording_replay.py --run-e2e",
    "record": "tests/e2e/test_recording_flow.py --run-e2e",
    "routing": (
        "tests/e2e/test_auto_routing.py "
        "tests/e2e/test_routing_consistency.py "
        "tests/e2e/test_replay_routing.py --run-e2e"
    ),
    "browser": (
        "tests/e2e/test_browser.py "
        "tests/e2e/test_browser_extraction.py --run-e2e"
    ),
    "computer": (
        "tests/e2e/test_computer.py "
        "tests/e2e/test_computer_focus.py "
        "tests/e2e/test_ultrawide.py --run-e2e"
    ),
    "openclaw": "tests/e2e/test_openclaw.py --run-e2e",
    "dashboard": (
        "tests/e2e/test_dashboard_integrity.py "
        "tests/e2e/test_stop_button_lifecycle.py --run-e2e"
    ),
    "workflow": "tests/e2e/test_workflow_lifecycle.py --run-e2e",
    "cancel": "tests/e2e/test_task_cancel.py --run-e2e",
    "unit": "tests/unit/ tests/integration/",
    "smoke": "tests/smoke_test.py",
    "all": "tests/ --run-e2e",
}

# Aliases for even less typing
ALIASES = {
    "r": "replay",
    "rec": "record",
    "b": "browser",
    "c": "computer",
    "o": "openclaw",
    "d": "dashboard",
    "w": "workflow",
    "u": "unit",
    "s": "smoke",
    "a": "all",
}


def check_server():
    """Quick check if ClawBridge server is reachable."""
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)
        return True
    except Exception:
        return False


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    target = ALIASES.get(target, target)

    if target == "help" or target == "-h" or target == "--help":
        print(__doc__)
        print("Aliases:", ", ".join(f"{k}={v}" for k, v in ALIASES.items()))
        sys.exit(0)

    if target not in TARGETS:
        print(f"Unknown target: {target!r}")
        print(f"Available: {', '.join(TARGETS)}")
        print(f"Aliases:   {', '.join(f'{k}={v}' for k, v in ALIASES.items())}")
        sys.exit(1)

    # Check server for e2e/smoke tests
    needs_server = target not in ("unit",)
    if needs_server and not check_server():
        print("WARNING: ClawBridge server not running on :8765")
        print("  Start it:  python clawbridge.py")
        if target != "unit":
            print("  Or run unit tests only:  python test.py unit")
            sys.exit(1)

    args = TARGETS[target].split()
    cmd = [sys.executable, "-m", "pytest"] + args + ["-v", "--tb=short"]

    # Pass through any extra pytest args (e.g., -k, -x, --pdb)
    if len(sys.argv) > 2:
        cmd.extend(sys.argv[2:])

    print(f"  {' '.join(cmd)}")
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
