"""ClawBridge entry point.

Usage:
    python -m clawbridge

Starts the local ClawBridge service with all configured engines,
serves the web dashboard, and opens the browser.
"""

from __future__ import annotations

import sys
import webbrowser
import logging

import uvicorn

from clawbridge.config import get_settings
from clawbridge.telemetry.logger import setup_logging


def main() -> None:
    """Start the ClawBridge service."""
    # Load config first
    settings = get_settings()

    # Set up logging (structured, no secrets)
    setup_logging()
    logger = logging.getLogger("clawbridge")

    # Print banner
    print()
    print("  ╔═══════════════════════════════════════╗")
    print("  ║         ClawBridge v0.1.0             ║")
    print("  ║  Bridging AI Agents to Your Machine   ║")
    print("  ╚═══════════════════════════════════════╝")
    print()

    if not settings.has_any_key:
        print("  [!] No API keys configured.")
        print("      Edit .env and set ANTHROPIC_API_KEY or OPENAI_API_KEY")
        print()

    url = f"http://{settings.host}:{settings.port}"
    print(f"  Dashboard: {url}")
    print(f"  Engines:   {settings.enabled_engines}")
    print(f"  Policy:    {settings.policy_mode.value}")
    print()

    # Open dashboard in default browser (after a short delay for server startup)
    import threading
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    # Start the server
    uvicorn.run(
        "clawbridge.server.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
