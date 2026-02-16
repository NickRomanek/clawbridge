#!/usr/bin/env python3
"""
ClawBridge - Single-file runnable.
Bridging Open-Source AI Agents to Your Machine.

Usage:
    python clawbridge.py

On first run, missing dependencies are installed automatically. Then open http://127.0.0.1:8765
Optional: create .env with ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY (BYOK).
"""
from __future__ import annotations

__version__ = "0.2.0"

import hmac
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# Redirect stdout/stderr for pythonw.exe (no console, writes would crash)
# ---------------------------------------------------------------------------
if not sys.stdout or sys.executable.endswith('pythonw.exe'):
    _log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(_log_dir, exist_ok=True)
    sys.stdout = open(os.path.join(_log_dir, 'clawbridge.log'), 'w', encoding='utf-8')
    sys.stderr = sys.stdout

# ---------------------------------------------------------------------------
# Early loading server — starts BEFORE dependency install using only stdlib.
# Provides real-time startup progress via /startup-status JSON endpoint.
# ---------------------------------------------------------------------------
import threading
import json as _json
from http.server import HTTPServer, BaseHTTPRequestHandler

_startup_status: dict = {"stage": "Starting...", "detail": "", "progress": 0}
_loading_server = None  # type: HTTPServer | None

_LOADING_PAGE_HTML = b'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ClawBridge</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e4e4e7;display:flex;justify-content:center;
     align-items:center;height:100vh;font-family:-apple-system,BlinkMacSystemFont,
     "Segoe UI",Roboto,sans-serif}
.container{text-align:center;max-width:420px;padding:40px}
.logo{font-size:32px;font-weight:700;color:#fff;margin-bottom:8px;letter-spacing:-0.5px}
.logo span{color:#6366f1}
.sub{color:#71717a;font-size:14px;margin-bottom:32px}
.progress-wrap{background:#18181b;border-radius:8px;height:8px;overflow:hidden;
               margin-bottom:20px;border:1px solid #27272a}
.progress-bar{height:100%;background:linear-gradient(90deg,#6366f1,#818cf8);
              border-radius:8px;width:0%;transition:width 0.5s ease}
.stage{color:#a1a1aa;font-size:15px;font-weight:500;min-height:22px}
.detail{color:#52525b;font-size:13px;min-height:18px;margin-top:4px}
.ready{display:none;margin-top:24px}
.ready .check{font-size:36px;color:#22c55e;margin-bottom:8px}
.ready .msg{color:#22c55e;font-size:16px;font-weight:600}
</style>
</head>
<body>
<div class="container">
  <div class="logo">Claw<span>Bridge</span></div>
  <div class="sub">Desktop &amp; Browser Automation</div>
  <div class="progress-wrap"><div class="progress-bar" id="bar"></div></div>
  <div class="stage" id="stage">Starting...</div>
  <div class="detail" id="detail"></div>
  <div class="ready" id="ready">
    <div class="check">&#10003;</div>
    <div class="msg">Ready!</div>
  </div>
</div>
<script>
(function(){
  var bar=document.getElementById("bar"),
      stage=document.getElementById("stage"),
      detail=document.getElementById("detail"),
      ready=document.getElementById("ready"),
      done=false;

  function pollStatus(){
    if(done) return;
    fetch("/startup-status").then(function(r){return r.json()}).then(function(d){
      bar.style.width=d.progress+"%";
      stage.textContent=d.stage;
      detail.textContent=d.detail||"";
      if(d.progress>=100){
        done=true;
        stage.textContent="Starting dashboard...";
        detail.textContent="";
        setTimeout(pollHealth,400);
      } else {
        setTimeout(pollStatus,600);
      }
    }).catch(function(){setTimeout(pollStatus,600)});
  }

  function pollHealth(){
    fetch("/health").then(function(r){return r.json()}).then(function(d){
      if(d.status==="ok"){
        stage.style.display="none";
        detail.style.display="none";
        bar.style.width="100%";
        ready.style.display="block";
        setTimeout(function(){window.location.replace("/")},400);
      } else {
        setTimeout(pollHealth,300);
      }
    }).catch(function(){setTimeout(pollHealth,300)});
  }

  pollStatus();
})();
</script>
</body>
</html>'''


class _LoadingHandler(BaseHTTPRequestHandler):
    """Minimal handler for early loading server. Only serves loading page + status."""

    def do_GET(self):
        if self.path == "/startup-status":
            body = _json.dumps(_startup_status).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            body = b'{"status":"loading"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(_LOADING_PAGE_HTML)))
            self.end_headers()
            self.wfile.write(_LOADING_PAGE_HTML)

    def log_message(self, *args):
        pass  # silent


def _read_port_from_env() -> int:
    """Read port from env var or .env file, using only stdlib."""
    port = os.environ.get("CLAWBRIDGE_PORT", "").strip()
    if port:
        try:
            return int(port)
        except ValueError:
            pass
    # Try reading from .env file directly (no dotenv yet)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("CLAWBRIDGE_PORT="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        return int(val)
        except (OSError, ValueError):
            pass
    return 8765


# Start the loading server immediately
_loading_port = _read_port_from_env()
try:
    # Probe whether port is genuinely free (SO_REUSEADDR masks conflicts on Windows)
    import socket as _socket
    _probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    _probe.settimeout(0.2)
    if _probe.connect_ex(("127.0.0.1", _loading_port)) == 0:
        _probe.close()
        raise OSError("port already in use")
    _probe.close()
    _loading_server = HTTPServer(("127.0.0.1", _loading_port), _LoadingHandler)
    threading.Thread(target=_loading_server.serve_forever, daemon=True).start()
    print(f"  Loading page active on http://127.0.0.1:{_loading_port}")
except OSError:
    _loading_server = None  # Port in use — skip (uvicorn will report the error later)

# Auto-open browser if requested (set by ClawBridge.bat windowless launcher)
if os.environ.get("CLAWBRIDGE_OPEN_BROWSER") == "1" and _loading_server is not None:
    import webbrowser as _wb
    _wb.open(f"http://127.0.0.1:{_loading_port}")

# ---------------------------------------------------------------------------
# Auto-install dependencies if missing (run once, then exit; user runs again)
# ---------------------------------------------------------------------------

def _ensure_dependencies() -> None:
    _startup_status.update({"stage": "Checking dependencies...", "progress": 5})
    required = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "python-dotenv",
        "httpx",
        "websockets",
        "browser-use",
        "playwright",
        "langchain-anthropic",
        "langchain-openai",
        "anthropic",
        "pyautogui",
        "Pillow",
        "mss",
        "pystray",
        "pywinauto",
        "pynput",
    ]
    # Map pip package names to their actual import names where they differ
    import_names = {"python-dotenv": "dotenv", "Pillow": "PIL"}
    missing = []
    for pkg in required:
        mod = import_names.get(pkg, pkg.replace("-", "_").split("[")[0])
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        _startup_status.update({"stage": "Dependencies OK", "progress": 60})
        return
    print("Installing missing dependencies (one-time setup)...")
    print(f"  Missing: {', '.join(missing)}")
    print()
    _startup_status.update({
        "stage": "Installing packages...",
        "detail": ", ".join(missing[:5]) + ("..." if len(missing) > 5 else ""),
        "progress": 15,
    })
    # Use --user if system Python site-packages is not writable
    pip_cmd = [sys.executable, "-m", "pip", "install", "-q"]
    import site as _site
    site_dir = _site.getsitepackages()[0] if _site.getsitepackages() else None
    if site_dir and not os.access(site_dir, os.W_OK):
        pip_cmd.append("--user")
        print("  (using --user install -- system Python detected)")
    subprocess.run(pip_cmd + required, check=True)
    _startup_status.update({
        "stage": "Installing browser engine...",
        "detail": "Downloading Chromium",
        "progress": 50,
    })
    print("Installing Chromium for browser automation...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    print()
    print("Dependencies installed! Continuing startup...")
    print()
    _startup_status.update({"stage": "Loading modules...", "detail": "", "progress": 60})
    # Refresh importlib so freshly installed packages are importable
    import importlib
    importlib.invalidate_caches()
    # Refresh sys.path to pick up newly installed packages
    if site_dir and site_dir not in sys.path:
        sys.path.insert(0, site_dir)
    # Also try user site-packages
    user_site = _site.getusersitepackages() if hasattr(_site, 'getusersitepackages') else None
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)

_ensure_dependencies()

_startup_status.update({"stage": "Loading modules...", "detail": "", "progress": 65})

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Rest of imports (now guaranteed present)
import asyncio
import base64
import dataclasses
import io
import json
import logging
import re
import sqlite3
import time
import uuid
import webbrowser
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field, PrivateAttr
import uvicorn

_startup_status.update({"stage": "Modules loaded", "detail": "", "progress": 70})

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

class Settings:
    host = _env("CLAWBRIDGE_HOST", "127.0.0.1")
    port = int(_env("CLAWBRIDGE_PORT", "8765"))
    anthropic_api_key = _env("ANTHROPIC_API_KEY")
    openai_api_key = _env("OPENAI_API_KEY")
    openrouter_api_key = _env("OPENROUTER_API_KEY")
    default_model = _env("DEFAULT_MODEL", "gpt-4o")
    enabled_engines = _env("ENABLED_ENGINES", "browser_use,openclaw,computer_use")
    browser_headless = _env("BROWSER_HEADLESS", "true").lower() in ("1", "true", "yes")
    browser_mode = _env("BROWSER_MODE", "default")  # "default" | "cdp" | "user_data_dir"
    browser_cdp_url = _env("BROWSER_CDP_URL", "http://localhost:9222")
    browser_user_data_dir = _env("BROWSER_USER_DATA_DIR", "")
    # Computer-use engine settings
    computer_use_model = _env("COMPUTER_USE_MODEL", "anthropic/claude-sonnet-4.5")
    computer_use_max_screen_width = int(_env("COMPUTER_USE_MAX_SCREEN_WIDTH", "1920"))
    computer_use_max_screen_height = int(_env("COMPUTER_USE_MAX_SCREEN_HEIGHT", "1080"))
    computer_use_action_delay_ms = int(_env("COMPUTER_USE_ACTION_DELAY_MS", "500"))
    # OpenClaw engine settings
    openclaw_gateway_port = int(_env("OPENCLAW_GATEWAY_PORT", "18789"))
    openclaw_api_key = _env("OPENCLAW_API_KEY", "")  # Optional bearer token for gateway auth
    openclaw_model = _env("OPENCLAW_MODEL", "")  # Model for OpenClaw (e.g. openrouter/anthropic/claude-sonnet-4). Empty = use gateway default.
    policy_mode = _env("POLICY_MODE", "guarded")
    automation_mode = _env("AUTOMATION_MODE", "supervised")  # "supervised" (asks approval) | "autonomous" (runs freely)
    dashboard_token = _env("DASHBOARD_TOKEN", "")  # Optional: set to require auth for dashboard access
    max_concurrent_tasks = int(_env("MAX_CONCURRENT_TASKS", "3"))
    max_actions_per_task = int(_env("MAX_ACTIONS_PER_TASK", "50"))
    max_task_retries = int(_env("MAX_TASK_RETRIES", "2"))  # Auto-retry failed tasks (0=disabled)
    retry_base_delay = float(_env("RETRY_BASE_DELAY", "2.0"))  # Base delay in seconds for exponential backoff
    log_level = _env("LOG_LEVEL", "INFO")
    db_path = _env("CLAWBRIDGE_DB", "clawbridge.db")
    remote_bridge_url = _env("REMOTE_BRIDGE_URL", "")
    remote_auth_token = _env("REMOTE_AUTH_TOKEN", "")
    # Licensing / Activation
    activation_code = _env("CLAWBRIDGE_ACTIVATION_CODE", "")
    activation_backend_url = _env("ACTIVATION_BACKEND_URL", "https://api.clawbridge.ai")
    license_tier = _env("LICENSE_TIER", "")  # "starter" | "byok" | ""

    @classmethod
    def has_anthropic_key(cls) -> bool:
        return bool(cls.anthropic_api_key)

    @classmethod
    def has_openai_key(cls) -> bool:
        return bool(cls.openai_api_key)

    @classmethod
    def has_openrouter_key(cls) -> bool:
        return bool(cls.openrouter_api_key)

    @classmethod
    def has_any_key(cls) -> bool:
        return cls.has_anthropic_key() or cls.has_openai_key() or cls.has_openrouter_key()

    @classmethod
    def enabled_engine_list(cls) -> list[str]:
        return [x.strip().lower() for x in cls.enabled_engines.split(",") if x.strip()]

def get_settings() -> type:
    return Settings

def get_machine_id() -> str:
    """Load or generate a unique machine ID."""
    id_file = Path("clawbridge.id")
    if id_file.exists():
        return id_file.read_text().strip()
    mid = str(uuid.uuid4())
    id_file.write_text(mid)
    return mid

# ---------------------------------------------------------------------------
# Safety / Policy Engine (inline — adapted from clawbridge/policy/safety.py)
# ---------------------------------------------------------------------------

# Credential patterns — detect but never extract/return actual values
_CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),           # OpenAI-style keys
    re.compile(r"sk-ant-[a-zA-Z0-9-]{20,}"),       # Anthropic keys
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),            # GitHub PATs
    re.compile(r"xox[bsapr]-[a-zA-Z0-9-]+"),      # Slack tokens
]
_PII_PATTERNS = [
    re.compile(r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b"),                    # SSN
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),      # Credit card
]
_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(previous|above|all)\s+(instructions?|prompts?|rules?)"),
    re.compile(r"(?i)you\s+are\s+now\s+"),
    re.compile(r"(?i)forget\s+(everything|all|your)\s+"),
    re.compile(r"(?i)disregard\s+(previous|above|all)\s+"),
    re.compile(r"(?i)new\s+instructions?\s*:"),
    re.compile(r"(?i)override\s+(previous|system)\s+"),
]


def safety_scan_prompt(text: str) -> dict:
    """Scan a task prompt for credentials, PII, and prompt injection.
    Returns {credentials: bool, pii: bool, injection_flags: list[str], clean: bool}.
    Designed to flag — not block — so guardrails aren't too restrictive.
    """
    creds = any(p.search(text) for p in _CREDENTIAL_PATTERNS)
    pii = any(p.search(text) for p in _PII_PATTERNS)
    injections = [p.pattern[:50] for p in _INJECTION_PATTERNS if p.search(text)]
    return {
        "credentials": creds,
        "pii": pii,
        "injection_flags": injections,
        "clean": not creds and not pii and not injections,
    }


def safety_redact(text: str) -> str:
    """Redact credentials and PII from text before logging/storing."""
    result = text
    for p in _CREDENTIAL_PATTERNS:
        result = p.sub("[REDACTED_CREDENTIAL]", result)
    for p in _PII_PATTERNS:
        result = p.sub("[REDACTED_PII]", result)
    return result


# ---------------------------------------------------------------------------
# Licensing / Activation System
# ---------------------------------------------------------------------------

class LicenseStatus(Enum):
    NOT_ACTIVATED = "not_activated"
    ACTIVATED = "activated"
    BYOK = "byok"
    REVOKED = "revoked"
    ERROR = "error"


@dataclasses.dataclass
class LicenseInfo:
    status: LicenseStatus
    tier: str = ""
    credit_limit_usd: float = 0.0
    credit_used_usd: float = 0.0
    credit_remaining_usd: float = 0.0
    topup_url: str = ""
    error: str = ""


# Cache for license status (5-minute TTL)
_license_cache: dict[str, Any] = {"info": None, "expires": 0}
_LICENSE_CACHE_TTL = 300  # 5 minutes


def _update_env(updates: dict[str, str]) -> None:
    """Update .env file with new key-value pairs."""
    env_path = Path(".env")
    lines: list[str] = []
    existing_keys: set[str] = set()

    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    key = stripped.split("=", 1)[0]
                    if key in updates:
                        lines.append(f"{key}={updates[key]}\n")
                        existing_keys.add(key)
                        continue
                lines.append(line)

    # Append any new keys not already in file
    for key, value in updates.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Also update environment variables in current process
    for key, value in updates.items():
        os.environ[key] = value


def get_license_status() -> LicenseInfo:
    """Get current license status, either from cache or backend."""
    settings = get_settings()

    # BYOK mode: user has their own API key, no activation needed
    if not settings.activation_code and settings.has_any_key():
        return LicenseInfo(status=LicenseStatus.BYOK, tier="byok")

    # Not activated and no keys
    if not settings.activation_code:
        return LicenseInfo(status=LicenseStatus.NOT_ACTIVATED)

    # Check cache
    now = time.time()
    if _license_cache["info"] and _license_cache["expires"] > now:
        return _license_cache["info"]

    # Fetch from backend
    try:
        info = _fetch_license_status()
        _license_cache["info"] = info
        _license_cache["expires"] = now + _LICENSE_CACHE_TTL
        return info
    except Exception as e:
        # Offline fallback: if we have an activation code, assume activated
        logging.warning(f"Failed to fetch license status: {e}")
        if settings.activation_code:
            return LicenseInfo(
                status=LicenseStatus.ACTIVATED,
                tier=settings.license_tier or "starter",
                error="Offline - using cached status"
            )
        return LicenseInfo(status=LicenseStatus.ERROR, error=str(e))


def _fetch_license_status() -> LicenseInfo:
    """Fetch license status from activation backend."""
    settings = get_settings()
    machine_id = get_machine_id()

    import urllib.request
    import urllib.error

    url = f"{settings.activation_backend_url}/api/license/status"
    req = urllib.request.Request(url, method="GET")
    req.add_header("X-Activation-Code", settings.activation_code)
    req.add_header("X-Machine-ID", machine_id)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return LicenseInfo(status=LicenseStatus.NOT_ACTIVATED, error="Code not found")
        elif e.code == 403:
            body = e.read().decode("utf-8")
            if "revoked" in body.lower():
                return LicenseInfo(status=LicenseStatus.REVOKED, error="License revoked")
            return LicenseInfo(status=LicenseStatus.ERROR, error="Access denied")
        raise

    status_map = {
        "active": LicenseStatus.ACTIVATED,
        "revoked": LicenseStatus.REVOKED,
        "expired": LicenseStatus.REVOKED,
    }

    return LicenseInfo(
        status=status_map.get(data.get("status", ""), LicenseStatus.ERROR),
        tier=data.get("tier", ""),
        credit_limit_usd=data.get("credit_limit_usd", 0),
        credit_used_usd=data.get("credit_used_usd", 0),
        credit_remaining_usd=data.get("credit_remaining_usd", 0),
        topup_url=data.get("topup_url", ""),
    )


def activate_license(activation_code: str) -> tuple[bool, str]:
    """Activate a license with the given code. Returns (success, message)."""
    settings = get_settings()
    machine_id = get_machine_id()

    import urllib.request
    import urllib.error

    url = f"{settings.activation_backend_url}/api/activate"
    payload = json.dumps({
        "activation_code": activation_code.strip().upper(),
        "machine_id": machine_id,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            err_data = json.loads(body)
            return False, err_data.get("error", f"Activation failed: {e.code}")
        except Exception:
            return False, f"Activation failed: {e.code}"
    except Exception as e:
        return False, f"Network error: {e}"

    if not data.get("success"):
        return False, data.get("error", "Activation failed")

    # Store the API key and update settings
    api_key = data.get("api_key", "")
    tier = data.get("tier", "starter")

    _update_env({
        "CLAWBRIDGE_ACTIVATION_CODE": activation_code.strip().upper(),
        "OPENROUTER_API_KEY": api_key,
        "LICENSE_TIER": tier,
    })

    # Update Settings class
    Settings.activation_code = activation_code.strip().upper()
    Settings.openrouter_api_key = api_key
    Settings.license_tier = tier

    # Clear license cache
    _license_cache["info"] = None
    _license_cache["expires"] = 0

    return True, f"Activated! Tier: {tier}, Credits: ${data.get('credit_limit_usd', 5):.2f}"


# ---------------------------------------------------------------------------
# Supervised Mode: High-Risk Action Detection & Approval
# ---------------------------------------------------------------------------

# Sensitive domains that trigger approval in supervised mode
SENSITIVE_DOMAINS = [
    # Banking & Finance
    "bank", "chase", "wellsfargo", "bankofamerica", "citibank", "capitalone",
    "paypal", "venmo", "stripe", "square", "coinbase", "binance", "kraken",
    # Shopping & Purchases
    "amazon", "ebay", "walmart", "target", "bestbuy", "etsy", "shopify",
    "checkout", "cart", "payment", "billing",
    # Email & Communication
    "gmail", "outlook", "mail", "email", "slack", "discord", "teams",
    # Cloud & Admin
    "aws.amazon", "console.cloud", "azure", "portal.office", "admin",
    # Social Media (posting)
    "twitter", "x.com", "facebook", "instagram", "linkedin", "tiktok",
]

# High-risk action patterns (in action descriptions or UI elements)
HIGH_RISK_PATTERNS = [
    re.compile(r"(?i)\b(buy|purchase|order|checkout|pay|submit\s*order)\b"),
    re.compile(r"(?i)\b(send|post|publish|tweet|share|reply|comment)\b"),
    re.compile(r"(?i)\b(delete|remove|erase|clear|destroy)\b"),
    re.compile(r"(?i)\b(transfer|withdraw|deposit|wire)\b"),
    re.compile(r"(?i)\b(sign\s*in|log\s*in|login|sign\s*up|register)\b"),
    re.compile(r"(?i)\b(confirm|agree|accept|approve|authorize)\b"),
    re.compile(r"(?i)\b(download|install|run|execute)\b"),
    re.compile(r"(?i)\b(unsubscribe|cancel|terminate|close\s*account)\b"),
]

# Actions that always need approval (regardless of context)
ALWAYS_APPROVE_ACTIONS = [
    "purchase", "buy", "checkout", "pay", "send_money", "transfer",
    "delete_file", "format", "uninstall", "send_email", "post_message",
]


def is_high_risk_action(action: str, context: str = "", url: str = "") -> tuple[bool, str]:
    """Check if an action requires approval in supervised mode.

    Returns (is_high_risk, reason).
    """
    action_lower = action.lower()
    context_lower = context.lower() if context else ""
    url_lower = url.lower() if url else ""

    # Check sensitive domains
    for domain in SENSITIVE_DOMAINS:
        if domain in url_lower:
            return True, f"Sensitive site detected: {domain}"

    # Check high-risk patterns in action
    for pattern in HIGH_RISK_PATTERNS:
        if pattern.search(action_lower) or pattern.search(context_lower):
            match = pattern.pattern.replace("(?i)", "").replace("\\b", "")[:30]
            return True, f"High-risk action: {match}"

    # Check always-approve actions
    for keyword in ALWAYS_APPROVE_ACTIONS:
        if keyword in action_lower:
            return True, f"Action requires approval: {keyword}"

    return False, ""


class ApprovalManager:
    """Manages pending approval requests for supervised mode."""

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}
        self._timeout_seconds = 120  # 2 minute timeout for approval

    async def request_approval(
        self,
        task_id: str,
        action: str,
        reason: str,
        details: dict = None,
        broadcast_fn: Callable = None,
    ) -> bool:
        """Request user approval for an action.

        Sends approval request via WebSocket and waits for response.
        Returns True if approved, False if denied or timeout.
        """
        request_id = f"{task_id}_{uuid.uuid4().hex[:8]}"

        # Create future to wait for response
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending[request_id] = future

        # Broadcast approval request to dashboard
        if broadcast_fn:
            await broadcast_fn({
                "type": "approval_request",
                "payload": {
                    "request_id": request_id,
                    "task_id": task_id,
                    "action": action,
                    "reason": reason,
                    "details": details or {},
                    "timestamp": datetime.utcnow().isoformat(),
                },
            })

        logging.info(f"Approval requested: {action} (reason: {reason})")

        try:
            # Wait for response with timeout
            approved = await asyncio.wait_for(future, timeout=self._timeout_seconds)
            return approved
        except asyncio.TimeoutError:
            logging.warning(f"Approval request {request_id} timed out after {self._timeout_seconds}s")
            return False
        finally:
            self._pending.pop(request_id, None)

    def respond(self, request_id: str, approved: bool) -> bool:
        """Handle approval response from dashboard.

        Returns True if the request was found and handled.
        """
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(approved)
            logging.info(f"Approval response: {request_id} -> {'approved' if approved else 'denied'}")
            return True
        return False

    def cancel_all(self, task_id: str):
        """Cancel all pending approvals for a task."""
        to_remove = [k for k in self._pending if k.startswith(task_id)]
        for key in to_remove:
            future = self._pending.pop(key, None)
            if future and not future.done():
                future.set_result(False)


# Global approval manager
_approval_manager: ApprovalManager | None = None

def get_approval_manager() -> ApprovalManager:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager


# ---------------------------------------------------------------------------
# Workspace directory (personality files, memory, templates, schedules)
# ---------------------------------------------------------------------------

WORKSPACE_DIR = Path(os.environ.get("CLAWBRIDGE_WORKSPACE", "workspace"))

# Personality/Soul files — inspired by OpenClaw's programmable soul
PERSONALITY_FILES = {
    "SOUL.md": {
        "description": "Core identity and worldview — who the agent IS",
        "default": """# Soul

## Core Truths
- I prioritize genuine helpfulness over performative compliance
- I develop authentic perspective rather than defaulting to generic responses
- I solve problems independently before asking for help
- I build credibility through competent, reliable action

## Boundaries
- I protect user privacy — never share data without explicit permission
- I request permission before taking risky or irreversible actions
- I maintain appropriate agent-user distinction

## Vibe
- Direct, concise, no corporate fluff
- Technical when needed, plain when possible
- I show my reasoning, not just my conclusions
"""
    },
    "IDENTITY.md": {
        "description": "Public-facing identity — name, role, capabilities",
        "default": """# Identity

**Name:** ClawBridge Agent
**Role:** Desktop & browser automation assistant
**Capabilities:** Web browsing, form filling, data extraction, desktop control, scheduled tasks
**Style:** Efficient, task-focused, transparent about actions taken
"""
    },
    "USER.md": {
        "description": "Information about the user — preferences, context, projects",
        "default": """# User

## Preferences
- Timezone: (auto-detected)
- Language: English

## Projects
- (Add your active projects here)

## Notes
- (Add any context the agent should remember about you)
"""
    },
}

def _ensure_workspace():
    """Create workspace directory and default personality files if missing."""
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    (WORKSPACE_DIR / "memory").mkdir(exist_ok=True)
    (WORKSPACE_DIR / "templates").mkdir(exist_ok=True)
    (WORKSPACE_DIR / "schedules").mkdir(exist_ok=True)
    (WORKSPACE_DIR / "workflows").mkdir(exist_ok=True)
    for filename, meta in PERSONALITY_FILES.items():
        fpath = WORKSPACE_DIR / filename
        if not fpath.exists():
            fpath.write_text(meta["default"], encoding="utf-8")
    # Create MEMORY.md if missing
    mem_path = WORKSPACE_DIR / "MEMORY.md"
    if not mem_path.exists():
        mem_path.write_text("# Memory\n\nDurable long-term knowledge. Max ~100 lines.\n\n", encoding="utf-8")

_ensure_workspace()

# ---------------------------------------------------------------------------
# Personality / Soul System
# ---------------------------------------------------------------------------

class PersonalityManager:
    """Manages personality files (SOUL.md, IDENTITY.md, USER.md) and memory."""

    def __init__(self, workspace: Path = WORKSPACE_DIR):
        self.workspace = workspace

    def get_file(self, name: str) -> str:
        """Read a personality file."""
        fpath = self.workspace / name
        if fpath.exists():
            return fpath.read_text(encoding="utf-8")
        return ""

    def save_file(self, name: str, content: str) -> None:
        """Write a personality file."""
        fpath = self.workspace / name
        fpath.write_text(content, encoding="utf-8")

    def list_files(self) -> list[dict]:
        """List all personality files with metadata."""
        result = []
        for name, meta in PERSONALITY_FILES.items():
            fpath = self.workspace / name
            result.append({
                "name": name,
                "description": meta["description"],
                "exists": fpath.exists(),
                "size": fpath.stat().st_size if fpath.exists() else 0,
                "modified": datetime.fromtimestamp(fpath.stat().st_mtime).isoformat() if fpath.exists() else None,
            })
        return result

    def get_system_context(self) -> str:
        """Build the full personality context string for injection into engine prompts."""
        parts = []
        for name in PERSONALITY_FILES:
            content = self.get_file(name)
            if content.strip():
                parts.append(f"--- {name} ---\n{content.strip()}")
        # Include durable memory
        mem = self.get_file("MEMORY.md")
        if mem.strip():
            parts.append(f"--- MEMORY.md ---\n{mem.strip()}")
        # Include today's daily log
        today_log = self._get_daily_log()
        if today_log.strip():
            parts.append(f"--- Daily Log ({datetime.now().strftime('%Y-%m-%d')}) ---\n{today_log.strip()}")
        return "\n\n".join(parts)

    def _get_daily_log(self, date_str: str | None = None) -> str:
        """Get a daily memory log."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        fpath = self.workspace / "memory" / f"{date_str}.md"
        if fpath.exists():
            return fpath.read_text(encoding="utf-8")
        return ""

    def append_memory(self, text: str, daily: bool = True) -> None:
        """Append to daily log or durable memory."""
        ts = datetime.now().strftime("%H:%M")
        entry = f"- [{ts}] {text}\n"
        if daily:
            date_str = datetime.now().strftime("%Y-%m-%d")
            fpath = self.workspace / "memory" / f"{date_str}.md"
            if not fpath.exists():
                fpath.write_text(f"# Daily Log — {date_str}\n\n", encoding="utf-8")
            with open(fpath, "a", encoding="utf-8") as f:
                f.write(entry)
        else:
            fpath = self.workspace / "MEMORY.md"
            with open(fpath, "a", encoding="utf-8") as f:
                f.write(entry)

    def get_memory(self) -> dict:
        """Get all memory data — durable + recent daily logs."""
        durable = self.get_file("MEMORY.md")
        mem_dir = self.workspace / "memory"
        daily_logs = {}
        if mem_dir.exists():
            for f in sorted(mem_dir.glob("*.md"), reverse=True)[:7]:  # Last 7 days
                daily_logs[f.stem] = f.read_text(encoding="utf-8")
        return {"durable": durable, "daily_logs": daily_logs}

    def search_memory(self, query: str) -> list[dict]:
        """Simple keyword search across all memory files."""
        results = []
        query_lower = query.lower()
        # Search durable memory
        durable = self.get_file("MEMORY.md")
        for i, line in enumerate(durable.splitlines()):
            if query_lower in line.lower():
                results.append({"source": "MEMORY.md", "line": i + 1, "text": line.strip()})
        # Search daily logs
        mem_dir = self.workspace / "memory"
        if mem_dir.exists():
            for f in sorted(mem_dir.glob("*.md"), reverse=True)[:30]:
                content = f.read_text(encoding="utf-8")
                for i, line in enumerate(content.splitlines()):
                    if query_lower in line.lower():
                        results.append({"source": f"memory/{f.name}", "line": i + 1, "text": line.strip()})
        return results[:50]  # Cap results

_personality = PersonalityManager()

def get_personality() -> PersonalityManager:
    return _personality

# ---------------------------------------------------------------------------
# Scheduled Tasks (Cron / Interval / One-shot)
# ---------------------------------------------------------------------------

class ScheduleType(str, Enum):
    ONCE = "once"        # Run at a specific time
    INTERVAL = "interval"  # Run every N seconds/minutes/hours
    CRON = "cron"        # Cron expression

class ScheduledTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    prompt: str = ""
    engine: str = "auto"
    schedule_type: str = "interval"  # once, interval, cron
    schedule_value: str = ""  # ISO datetime for once, seconds for interval, cron expr
    enabled: bool = True
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_run: str | None = None
    next_run: str | None = None
    run_count: int = 0
    last_result: str | None = None

class ScheduleManager:
    """Manages scheduled/recurring tasks."""

    def __init__(self, workspace: Path = WORKSPACE_DIR):
        self.workspace = workspace
        self.schedules_dir = workspace / "schedules"
        self.schedules_dir.mkdir(parents=True, exist_ok=True)
        self._schedules: dict[str, ScheduledTask] = {}
        self._running = False
        self._task_callback: Callable | None = None
        self._load_schedules()

    def _load_schedules(self):
        """Load all schedules from disk."""
        for f in self.schedules_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sched = ScheduledTask(**data)
                self._schedules[sched.id] = sched
            except Exception as e:
                logging.warning("Failed to load schedule %s: %s", f.name, e)

    def _save_schedule(self, sched: ScheduledTask):
        """Save a schedule to disk."""
        fpath = self.schedules_dir / f"{sched.id}.json"
        fpath.write_text(json.dumps(sched.model_dump(), indent=2), encoding="utf-8")

    def _delete_schedule_file(self, sched_id: str):
        """Remove schedule file from disk."""
        fpath = self.schedules_dir / f"{sched_id}.json"
        if fpath.exists():
            fpath.unlink()

    def create(self, name: str, prompt: str, engine: str, schedule_type: str, schedule_value: str) -> ScheduledTask:
        """Create a new scheduled task."""
        sched = ScheduledTask(
            name=name,
            prompt=prompt,
            engine=engine,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
        )
        # Calculate next_run
        sched.next_run = self._calc_next_run(sched)
        self._schedules[sched.id] = sched
        self._save_schedule(sched)
        return sched

    def update(self, sched_id: str, updates: dict) -> ScheduledTask | None:
        """Update a scheduled task."""
        sched = self._schedules.get(sched_id)
        if not sched:
            return None
        for k, v in updates.items():
            if hasattr(sched, k):
                setattr(sched, k, v)
        sched.next_run = self._calc_next_run(sched)
        self._save_schedule(sched)
        return sched

    def delete(self, sched_id: str) -> bool:
        """Delete a scheduled task."""
        if sched_id in self._schedules:
            del self._schedules[sched_id]
            self._delete_schedule_file(sched_id)
            return True
        return False

    def list_all(self) -> list[ScheduledTask]:
        """List all scheduled tasks."""
        return sorted(self._schedules.values(), key=lambda s: s.created_at, reverse=True)

    def get(self, sched_id: str) -> ScheduledTask | None:
        return self._schedules.get(sched_id)

    def _calc_next_run(self, sched: ScheduledTask) -> str | None:
        """Calculate when this schedule should next run."""
        now = datetime.utcnow()
        if sched.schedule_type == "once":
            try:
                run_at = datetime.fromisoformat(sched.schedule_value)
                if run_at > now:
                    return run_at.isoformat()
                return None  # Already past
            except Exception:
                return None
        elif sched.schedule_type == "interval":
            try:
                seconds = self._parse_interval(sched.schedule_value)
                if sched.last_run:
                    last = datetime.fromisoformat(sched.last_run)
                    return (last + __import__("datetime").timedelta(seconds=seconds)).isoformat()
                return now.isoformat()  # Run immediately first time
            except Exception:
                return None
        elif sched.schedule_type == "cron":
            return self._next_cron_run(sched.schedule_value)
        return None

    def _parse_interval(self, value: str) -> int:
        """Parse interval like '30m', '2h', '300s', '1d' into seconds."""
        value = value.strip().lower()
        if value.endswith("d"):
            return int(value[:-1]) * 86400
        elif value.endswith("h"):
            return int(value[:-1]) * 3600
        elif value.endswith("m"):
            return int(value[:-1]) * 60
        elif value.endswith("s"):
            return int(value[:-1])
        return int(value)  # Assume seconds

    def _next_cron_run(self, cron_expr: str) -> str | None:
        """Simple cron expression parser (minute hour day month weekday).
        Supports: *, specific numbers, */N for step values.
        """
        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return None
            now = datetime.utcnow()
            # Simple: find next matching minute within the next 24 hours
            from datetime import timedelta
            check = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            for _ in range(1440):  # Check every minute for 24 hours
                if self._cron_matches(parts, check):
                    return check.isoformat()
                check += timedelta(minutes=1)
            return None
        except Exception:
            return None

    def _cron_matches(self, parts: list[str], dt: datetime) -> bool:
        """Check if a datetime matches a cron expression."""
        fields = [dt.minute, dt.hour, dt.day, dt.month, dt.weekday()]
        ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
        for part, val, (lo, hi) in zip(parts, fields, ranges):
            if part == "*":
                continue
            if "/" in part:
                base, step = part.split("/", 1)
                step = int(step)
                if base == "*":
                    base = lo
                else:
                    base = int(base)
                if (val - base) % step != 0 or val < base:
                    return False
            elif "," in part:
                if val not in [int(x) for x in part.split(",")]:
                    return False
            else:
                if val != int(part):
                    return False
        return True

    async def run_loop(self, submit_fn: Callable):
        """Background loop that checks and runs scheduled tasks."""
        self._task_callback = submit_fn
        self._running = True
        logging.info("Schedule manager started (%d schedules loaded)", len(self._schedules))
        while self._running:
            now = datetime.utcnow()
            for sched in list(self._schedules.values()):
                if not sched.enabled:
                    continue
                if not sched.next_run:
                    continue
                try:
                    next_run = datetime.fromisoformat(sched.next_run)
                except Exception:
                    continue
                if now >= next_run:
                    logging.info("Scheduled task firing: %s (%s)", sched.name, sched.id[:8])
                    # Create and submit task
                    try:
                        task = Task(
                            prompt=sched.prompt,
                            engine=EngineName(sched.engine) if sched.engine != "auto" else EngineName.AUTO,
                        )
                        if self._task_callback:
                            await self._task_callback(task)
                        sched.last_run = now.isoformat()
                        sched.run_count += 1
                        sched.last_result = f"Submitted task {task.id[:8]}"
                        # Recalculate next run
                        if sched.schedule_type == "once":
                            sched.enabled = False  # One-shot, disable after run
                            sched.next_run = None
                        else:
                            sched.next_run = self._calc_next_run(sched)
                        self._save_schedule(sched)
                        # Log to memory
                        get_personality().append_memory(
                            f"Scheduled task '{sched.name}' ran (run #{sched.run_count})", daily=True
                        )
                    except Exception as e:
                        logging.error("Failed to run scheduled task %s: %s", sched.id, e)
                        sched.last_result = f"Error: {e}"
                        self._save_schedule(sched)
            await asyncio.sleep(30)  # Check every 30 seconds

    def stop(self):
        self._running = False

_schedule_mgr: ScheduleManager | None = None

def get_schedule_manager() -> ScheduleManager:
    global _schedule_mgr
    if _schedule_mgr is None:
        _schedule_mgr = ScheduleManager()
    return _schedule_mgr

# ---------------------------------------------------------------------------
# Task Templates
# ---------------------------------------------------------------------------

class TaskTemplate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    prompt: str = ""
    engine: str = "auto"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    use_count: int = 0

class TemplateManager:
    """Manages reusable task templates."""

    def __init__(self, workspace: Path = WORKSPACE_DIR):
        self.templates_dir = workspace / "templates"
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._templates: dict[str, TaskTemplate] = {}
        self._load_templates()

    def _load_templates(self):
        for f in self.templates_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                tmpl = TaskTemplate(**data)
                self._templates[tmpl.id] = tmpl
            except Exception as e:
                logging.warning("Failed to load template %s: %s", f.name, e)

    def _save_template(self, tmpl: TaskTemplate):
        fpath = self.templates_dir / f"{tmpl.id}.json"
        fpath.write_text(json.dumps(tmpl.model_dump(), indent=2), encoding="utf-8")

    def create(self, name: str, prompt: str, engine: str = "auto") -> TaskTemplate:
        tmpl = TaskTemplate(name=name, prompt=prompt, engine=engine)
        self._templates[tmpl.id] = tmpl
        self._save_template(tmpl)
        return tmpl

    def delete(self, tmpl_id: str) -> bool:
        if tmpl_id in self._templates:
            del self._templates[tmpl_id]
            fpath = self.templates_dir / f"{tmpl_id}.json"
            if fpath.exists():
                fpath.unlink()
            return True
        return False

    def list_all(self) -> list[TaskTemplate]:
        return sorted(self._templates.values(), key=lambda t: t.created_at, reverse=True)

    def get(self, tmpl_id: str) -> TaskTemplate | None:
        return self._templates.get(tmpl_id)

    def use(self, tmpl_id: str) -> TaskTemplate | None:
        """Mark a template as used (increment counter)."""
        tmpl = self._templates.get(tmpl_id)
        if tmpl:
            tmpl.use_count += 1
            self._save_template(tmpl)
        return tmpl

_template_mgr: TemplateManager | None = None

def get_template_manager() -> TemplateManager:
    global _template_mgr
    if _template_mgr is None:
        _template_mgr = TemplateManager()
    return _template_mgr


class WorkflowManager:
    """Manages recorded workflow templates — file-based persistence in workspace/workflows/."""

    def __init__(self, workspace: Path = WORKSPACE_DIR):
        self.workflows_dir = workspace / "workflows"
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self._workflows: dict[str, WorkflowTemplate] = {}
        self._load_workflows()

    def _load_workflows(self):
        for f in self.workflows_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                wf = WorkflowTemplate(**data)
                self._workflows[wf.id] = wf
            except Exception as e:
                logging.warning("Failed to load workflow %s: %s", f.name, e)

    def _save_workflow(self, wf: WorkflowTemplate):
        fpath = self.workflows_dir / f"{wf.id}.json"
        fpath.write_text(json.dumps(wf.model_dump(mode="json"), indent=2, default=str), encoding="utf-8")

    def create(self, name: str, description: str, actions: list[dict],
               target_app: str = "", tags: list[str] | None = None) -> WorkflowTemplate:
        parsed_actions = [RecordedAction(**a) for a in actions]
        wf = WorkflowTemplate(
            name=name,
            description=description,
            actions=parsed_actions,
            target_app=target_app,
            tags=tags or [],
        )
        self._workflows[wf.id] = wf
        self._save_workflow(wf)
        return wf

    def get(self, wf_id: str) -> WorkflowTemplate | None:
        return self._workflows.get(wf_id)

    def get_by_name(self, name: str) -> WorkflowTemplate | None:
        for wf in self._workflows.values():
            if wf.name == name:
                return wf
        return None

    def delete(self, wf_id: str) -> bool:
        if wf_id in self._workflows:
            del self._workflows[wf_id]
            fpath = self.workflows_dir / f"{wf_id}.json"
            if fpath.exists():
                fpath.unlink()
            return True
        return False

    def list_all(self) -> list[WorkflowTemplate]:
        return sorted(self._workflows.values(), key=lambda w: w.created_at, reverse=True)

    def mark_replayed(self, wf_id: str):
        wf = self._workflows.get(wf_id)
        if wf:
            wf.replay_count += 1
            wf.last_replayed = datetime.utcnow()
            self._save_workflow(wf)


_workflow_mgr: WorkflowManager | None = None

def get_workflow_manager() -> WorkflowManager:
    global _workflow_mgr
    if _workflow_mgr is None:
        _workflow_mgr = WorkflowManager()
    return _workflow_mgr


def init_db():
    """Initialize SQLite database for task persistence."""
    conn = sqlite3.connect(Settings.db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (id TEXT PRIMARY KEY, prompt TEXT, engine TEXT, status TEXT,
                  result TEXT, error TEXT, created_at TEXT, updated_at TEXT)''')
    # Step traces for task replay
    c.execute('''CREATE TABLE IF NOT EXISTS task_steps
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  task_id TEXT NOT NULL,
                  step_num INTEGER NOT NULL,
                  max_steps INTEGER DEFAULT 0,
                  action TEXT DEFAULT '',
                  detail TEXT DEFAULT '',
                  reasoning TEXT DEFAULT '',
                  tokens_in INTEGER DEFAULT 0,
                  tokens_out INTEGER DEFAULT 0,
                  timestamp TEXT NOT NULL,
                  FOREIGN KEY (task_id) REFERENCES tasks(id))''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id)')
    # Persistent audit log
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log
                 (id TEXT PRIMARY KEY,
                  task_id TEXT DEFAULT '',
                  event_type TEXT DEFAULT '',
                  detail TEXT DEFAULT '',
                  timestamp TEXT NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_audit_task_id ON audit_log(task_id)')
    # Workflow recordings
    c.execute('''CREATE TABLE IF NOT EXISTS workflows
                 (id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  description TEXT DEFAULT '',
                  actions TEXT DEFAULT '[]',
                  target_app TEXT DEFAULT '',
                  tags TEXT DEFAULT '[]',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  replay_count INTEGER DEFAULT 0,
                  last_replayed TEXT DEFAULT '')''')
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------------------------
# Schemas (Pydantic)
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"
    PAUSED = "paused"
    CANCELLED = "cancelled"

class EngineName(str, Enum):
    BROWSER_USE = "browser_use"
    OPENCLAW = "openclaw"
    COMPUTER_USE = "computer_use"
    AUTO = "auto"

class EngineStatus(str, Enum):
    AVAILABLE = "available"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    NOT_INSTALLED = "not_installed"
    NO_API_KEY = "no_api_key"

class Citation(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""

class TaskResult(BaseModel):
    summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    total_steps: int = 0
    total_duration_ms: int = 0
    engine_used: str = "auto"
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0

class Task(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = ""
    engine: EngineName = EngineName.AUTO
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    result: TaskResult | None = None
    error: str | None = None
    _personality_context: str = PrivateAttr(default="")  # injected at runtime, not serialized

class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    task_id: str = ""
    event_type: str = ""
    detail: str = ""

class RecordedAction(BaseModel):
    """A single recorded user action (click, type, scroll, key)."""
    timestamp: float = 0.0
    action_type: str = ""  # click, type, scroll, key
    x: int = 0
    y: int = 0
    button: str = ""  # left, right, middle
    text: str = ""
    key: str = ""
    scroll_amount: int = 0
    element_type: str = ""
    element_name: str = ""
    element_automation_id: str = ""
    element_parent_name: str = ""
    window_title: str = ""

class WorkflowTemplate(BaseModel):
    """A saved workflow recording that can be replayed."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    actions: list[RecordedAction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    replay_count: int = 0
    last_replayed: datetime | None = None
    target_app: str = ""
    tags: list[str] = Field(default_factory=list)

class ReplayState(BaseModel):
    """Tracks the state of a workflow replay in progress."""
    workflow_id: str = ""
    workflow_name: str = ""
    current_step: int = 0
    total_steps: int = 0
    status: str = "pending"  # pending, running, complete, error
    llm_fallback_steps: int = 0
    error: str = ""

# ---------------------------------------------------------------------------
# Audit logger (in-memory + optional file)
# ---------------------------------------------------------------------------

class AuditLogger:
    def __init__(self, maxlen: int = 500):
        self._buffer: deque[AuditEvent] = deque(maxlen=maxlen)
        self._on_log: Callable[[AuditEvent], Any] | None = None

    def log(self, event: AuditEvent) -> None:
        self._buffer.append(event)
        # Persist to SQLite
        try:
            conn = sqlite3.connect(Settings.db_path)
            conn.execute(
                "INSERT OR IGNORE INTO audit_log (id, task_id, event_type, detail, timestamp) VALUES (?, ?, ?, ?, ?)",
                (event.id, event.task_id, event.event_type, event.detail, event.timestamp.isoformat())
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        if self._on_log:
            try:
                self._on_log(event)
            except Exception:
                pass

    def recent(self, limit: int = 50, task_id: str | None = None) -> list[AuditEvent]:
        # Try DB first for fuller history, fall back to buffer
        try:
            conn = sqlite3.connect(Settings.db_path)
            if task_id:
                rows = conn.execute(
                    "SELECT id, task_id, event_type, detail, timestamp FROM audit_log WHERE task_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (task_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, task_id, event_type, detail, timestamp FROM audit_log ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            conn.close()
            return [AuditEvent(id=r[0], task_id=r[1], event_type=r[2], detail=r[3], timestamp=datetime.fromisoformat(r[4])) for r in reversed(rows)]
        except Exception:
            events = list(self._buffer)
            if task_id:
                events = [e for e in events if e.task_id == task_id]
            return events[-limit:]

_audit = AuditLogger()

def get_audit() -> AuditLogger:
    return _audit

# ---------------------------------------------------------------------------
# Step persistence (for task replay)
# ---------------------------------------------------------------------------

def save_step_to_db(step_data: dict) -> None:
    """Persist a single step to the task_steps table."""
    try:
        conn = sqlite3.connect(Settings.db_path)
        conn.execute(
            """INSERT INTO task_steps (task_id, step_num, max_steps, action, detail, reasoning, tokens_in, tokens_out, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                step_data.get("task_id", ""),
                step_data.get("step", 0),
                step_data.get("max_steps", 0),
                step_data.get("action", ""),
                step_data.get("detail", "")[:500],
                step_data.get("reasoning", "")[:1000],
                step_data.get("tokens_in", 0),
                step_data.get("tokens_out", 0),
                datetime.utcnow().isoformat(),
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.debug("Failed to save step: %s", e)


def get_steps_for_task(task_id: str) -> list[dict]:
    """Retrieve all persisted steps for a task."""
    try:
        conn = sqlite3.connect(Settings.db_path)
        rows = conn.execute(
            "SELECT step_num, max_steps, action, detail, reasoning, tokens_in, tokens_out, timestamp FROM task_steps WHERE task_id = ? ORDER BY step_num",
            (task_id,)
        ).fetchall()
        conn.close()
        return [
            {"step": r[0], "max_steps": r[1], "action": r[2], "detail": r[3],
             "reasoning": r[4], "tokens_in": r[5], "tokens_out": r[6], "timestamp": r[7]}
            for r in rows
        ]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Engines (browser-use only in single-file; OpenClaw stubbed)
# ---------------------------------------------------------------------------

class EngineBase:
    name: EngineName = EngineName.AUTO
    display_name: str = ""
    _status: EngineStatus = EngineStatus.STOPPED
    _error_hint: str = ""

    async def initialize(self) -> None:
        raise NotImplementedError

    async def run_task(self, task: Task) -> Task:
        raise NotImplementedError

    async def get_status(self) -> EngineStatus:
        return self._status

    async def get_info(self) -> dict:
        return {
            "name": self.name.value,
            "display_name": self.display_name,
            "status": self._status.value,
            "description": "",
            "error_hint": self._error_hint,
        }

def _find_chrome_exe() -> str | None:
    """Find the real Chrome/Edge executable on this platform."""
    import glob
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    for c in candidates:
        for p in glob.glob(c):
            if os.path.isfile(p):
                return p
    for name in ("chrome", "google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None

class BrowserUseEngine(EngineBase):
    name = EngineName.BROWSER_USE
    display_name = "browser-use"
    on_screenshot: Callable[[str], Any] | None = None  # receives base64 image string
    on_step: Callable[[dict], Any] | None = None  # receives step metadata dict

    async def initialize(self) -> None:
        try:
            from browser_use import Agent, Browser, BrowserProfile
            from browser_use.browser.profile import ViewportSize
            self._Agent = Agent
            self._Browser = Browser
            settings = get_settings()
            vp = ViewportSize(width=1280, height=900)
            mode = settings.browser_mode
            if mode == "cdp":
                profile = BrowserProfile(
                    cdp_url=settings.browser_cdp_url,
                    viewport=vp,
                    window_size=vp,
                )
                logging.info("browser-use: connecting via CDP to %s", settings.browser_cdp_url)
            elif mode == "user_data_dir" and settings.browser_user_data_dir:
                # Find real Chrome executable so Google doesn't block Playwright's Chromium
                chrome_exe = _find_chrome_exe()
                profile = BrowserProfile(
                    user_data_dir=settings.browser_user_data_dir,
                    executable_path=chrome_exe,
                    headless=settings.browser_headless,
                    viewport=vp,
                    window_size=vp,
                )
                logging.info("browser-use: user data dir %s, chrome=%s", settings.browser_user_data_dir, chrome_exe)
            else:
                profile = BrowserProfile(
                    headless=settings.browser_headless,
                    viewport=vp,
                    window_size=vp,
                )
            self._browser = Browser(browser_profile=profile)
            if settings.has_anthropic_key():
                from browser_use.llm import ChatAnthropic
                self._llm = ChatAnthropic(model=settings.default_model, api_key=settings.anthropic_api_key)
            elif settings.has_openai_key():
                from browser_use.llm import ChatOpenAI
                self._llm = ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)
            elif settings.has_openrouter_key():
                from browser_use.llm import ChatOpenRouter
                self._llm = ChatOpenRouter(
                    model=settings.default_model,
                    api_key=settings.openrouter_api_key,
                )
            else:
                self._status = EngineStatus.NO_API_KEY
                self._error_hint = "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in .env"
                return
            self._status = EngineStatus.AVAILABLE
        except ImportError:
            self._status = EngineStatus.NOT_INSTALLED
            self._error_hint = "Run: pip install browser-use"
        except Exception as e:
            logging.warning("browser-use init failed: %s", e)
            self._status = EngineStatus.ERROR
            self._error_hint = str(e)

    async def run_task(self, task: Task) -> Task:
        if self._status != EngineStatus.AVAILABLE:
            task.status = TaskStatus.ERROR
            task.error = "browser-use engine not available"
            return task
        self._status = EngineStatus.RUNNING
        try:
            # ── Inject personality/memory context into prompt ────────────
            prompt_text = task.prompt
            personality_ctx = getattr(task, '_personality_context', '')
            if personality_ctx:
                prompt_text = f"[AGENT CONTEXT]\n{personality_ctx}\n[END AGENT CONTEXT]\n\nTask: {task.prompt}"
            agent = self._Agent(task=prompt_text, llm=self._llm, browser=self._browser)
            import time
            import base64

            async def on_step_end(agent_instance):
                """Capture and broadcast screenshot after each step for in-app live view."""
                if not self.on_screenshot:
                    return
                b64_img = None
                try:
                    from browser_use.browser.events import ScreenshotEvent
                    event = agent_instance.browser_session.event_bus.dispatch(
                        ScreenshotEvent(full_page=False)
                    )
                    await event
                    result = await event.event_result(raise_if_any=False, raise_if_none=False)
                    if result is not None:
                        if isinstance(result, bytes):
                            b64_img = base64.b64encode(result).decode("utf-8")
                        elif isinstance(result, str):
                            b64_img = result
                        else:
                            b64_img = getattr(result, "image", None) or (base64.b64encode(result).decode("utf-8") if result else None)
                except Exception as e:
                    logging.debug("Live view ScreenshotEvent: %s", e)
                # Fallback: CDP Page.captureScreenshot directly
                if not b64_img:
                    try:
                        from cdp_use.cdp.page import CaptureScreenshotParameters
                        session = agent_instance.browser_session
                        t = session.get_focused_target()
                        if not t or getattr(t, "target_type", "") not in ("page", "tab"):
                            page_targets = session.get_page_targets()
                            t = page_targets[-1] if page_targets else None
                        if t:
                            cdp = await session.get_or_create_cdp_session(t.target_id, focus=True)
                            params = CaptureScreenshotParameters(format="png", captureBeyondViewport=False)
                            r = await cdp.cdp_client.send.Page.captureScreenshot(params=params, session_id=cdp.session_id)
                            if r and r.get("data"):
                                b64_img = r["data"]
                    except Exception as e:
                        logging.debug("Live view CDP fallback: %s", e)
                if b64_img:
                    self.on_screenshot(b64_img)

            t0 = time.monotonic()
            logging.info("browser-use: starting agent for task '%s'", task.prompt[:80])
            history = await agent.run(
                max_steps=min(get_settings().max_actions_per_task, 25),
                on_step_end=on_step_end,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)

            # Extract final result — browser-use returns None for action tasks
            final = None
            try:
                fr = getattr(history, "final_result", None)
                if callable(fr):
                    final = fr()
                elif fr is not None:
                    final = fr
            except Exception:
                pass

            # Extract token usage and step details from browser-use history
            total_in = 0; total_out = 0; n_steps = 0
            step_summaries = []
            try:
                steps = getattr(history, "history", []) or []
                n_steps = len(steps)
                for i, step in enumerate(steps):
                    usage = getattr(step, "token_usage", None) or getattr(step, "usage", None)
                    if usage:
                        total_in += getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0
                        total_out += getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0
                    # Log each step's action for debugging
                    action = getattr(step, "action", None)
                    result = getattr(step, "result", None)
                    action_str = str(action)[:200] if action else "?"
                    result_str = str(result)[:200] if result else ""
                    logging.info("browser-use step %d/%d: %s -> %s", i+1, n_steps, action_str, result_str)
                    # Build human-readable step summary
                    if action:
                        step_summaries.append(f"Step {i+1}: {action_str}")
            except Exception as e:
                logging.debug("browser-use step extraction error: %s", e)

            # Build final summary — if final_result is None, summarize what steps were taken
            if final and str(final).strip() and str(final).strip() != "None":
                summary_text = str(final)
            elif step_summaries:
                summary_text = f"Completed {n_steps} steps:\n" + "\n".join(step_summaries[-5:])  # show last 5 steps
                if n_steps > 5:
                    summary_text = f"Completed {n_steps} steps (showing last 5):\n" + "\n".join(step_summaries[-5:])
            else:
                summary_text = f"Task completed in {n_steps} steps ({duration_ms}ms)"

            logging.info("browser-use: finished in %d steps, %dms. Result: %s", n_steps, duration_ms, summary_text[:200])

            # Estimate cost: GPT-4o via OpenRouter ~$2.5/M in, ~$10/M out
            cost = (total_in * 2.5 / 1_000_000) + (total_out * 10.0 / 1_000_000)
            task.result = TaskResult(
                summary=summary_text[:5000],
                total_steps=n_steps,
                total_duration_ms=duration_ms,
                tokens_in=total_in,
                tokens_out=total_out,
                estimated_cost_usd=round(cost, 4),
                engine_used=self.name.value,
            )
            task.status = TaskStatus.COMPLETE
        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = str(e)
        finally:
            self._status = EngineStatus.AVAILABLE
        task.updated_at = datetime.utcnow()
        return task

class OpenClawEngine(EngineBase):
    name = EngineName.OPENCLAW
    display_name = "OpenClaw"

    def __init__(self):
        self._status = EngineStatus.STOPPED
        self._openclaw_bin = None
        self._http_client = None
        self._gateway_proc = None
        self._node_version = None

    async def initialize(self) -> None:
        import shutil
        self._openclaw_bin = shutil.which("openclaw") or shutil.which("openclaw.cmd")
        if not self._openclaw_bin:
            self._status = EngineStatus.NOT_INSTALLED
            self._error_hint = "Requires Node.js >= 22. Click Install or run: npm install -g openclaw@latest"
            return
        # Check Node.js version — OpenClaw requires >= 22
        try:
            import subprocess as _sp
            node_out = _sp.check_output(["node", "--version"], timeout=5, text=True, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)).strip()
            self._node_version = node_out
            major = int(node_out.lstrip("v").split(".")[0])
            if major < 22:
                self._status = EngineStatus.ERROR
                self._error_hint = f"OpenClaw requires Node.js >= 22, found {node_out}. Update Node.js to use this engine."
                logging.warning("OpenClaw: Node.js %s too old (need >= 22)", node_out)
                return
        except Exception as e:
            self._status = EngineStatus.ERROR
            self._error_hint = f"Cannot check Node.js version: {e}"
            return
        settings = get_settings()
        port = settings.openclaw_gateway_port
        import httpx
        self._http_client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=180.0)
        self._status = EngineStatus.AVAILABLE
        self._error_hint = ""
        logging.info("OpenClaw engine initialized (binary=%s, node=%s, port=%d)", self._openclaw_bin, self._node_version, port)

    async def _ensure_gateway(self) -> bool:
        """Check if OpenClaw gateway is running; start it if not."""
        if not self._http_client:
            return False
        # Try connecting to the gateway root (serves web UI)
        try:
            resp = await self._http_client.get("/", timeout=3.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        # Try the /v1 endpoint as alternate health check
        try:
            resp = await self._http_client.get("/v1/models", timeout=3.0)
            if resp.status_code in (200, 401):  # 401 = running but needs auth
                return True
        except Exception:
            pass
        # Gateway not running — try to start it
        if not self._openclaw_bin:
            return False
        import subprocess
        settings = get_settings()
        env = os.environ.copy()
        if settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        if settings.openai_api_key:
            env["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.openrouter_api_key:
            env["OPENROUTER_API_KEY"] = settings.openrouter_api_key
        try:
            logging.info("Starting OpenClaw gateway...")
            self._gateway_proc = subprocess.Popen(
                [self._openclaw_bin, "gateway", "run", "--host", "127.0.0.1", "--port", str(settings.openclaw_gateway_port)],
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Poll for gateway readiness
            for _ in range(30):
                await asyncio.sleep(1)
                try:
                    resp = await self._http_client.get("/", timeout=3.0)
                    if resp.status_code == 200:
                        logging.info("OpenClaw gateway started successfully")
                        return True
                except Exception:
                    continue
            logging.warning("OpenClaw gateway did not become ready after 30s")
        except Exception as e:
            logging.warning("Failed to start OpenClaw gateway: %s", e)
        return False

    async def run_task(self, task: Task) -> Task:
        if self._status in (EngineStatus.NOT_INSTALLED, EngineStatus.ERROR, EngineStatus.STOPPED):
            task.status = TaskStatus.ERROR
            task.error = f"OpenClaw engine not available ({self._error_hint or 'unknown'})"
            return task
        if not await self._ensure_gateway():
            task.status = TaskStatus.ERROR
            task.error = "OpenClaw gateway not responding. Start it with: openclaw gateway run"
            return task
        t0 = time.monotonic()
        try:
            settings = get_settings()
            headers = {}
            if settings.openclaw_api_key:
                headers["Authorization"] = f"Bearer {settings.openclaw_api_key}"
            # ── Inject personality/memory context ────────────────────
            personality_ctx = getattr(task, '_personality_context', '')
            messages = []
            if personality_ctx:
                messages.append({"role": "system", "content": personality_ctx})
            messages.append({"role": "user", "content": task.prompt})
            # Use OpenAI-compatible chat completions endpoint
            model = settings.openclaw_model or None  # None = use gateway's configured default model
            payload = {
                "messages": messages,
                "stream": False,
            }
            if model:
                payload["model"] = model
            resp = await self._http_client.post(
                "/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            # Parse OpenAI-compatible response
            content = "Task completed"
            total_in = 0
            total_out = 0
            try:
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", content)
                usage = data.get("usage", {})
                total_in = usage.get("prompt_tokens", 0)
                total_out = usage.get("completion_tokens", 0)
            except Exception:
                # Fallback: try flat format
                content = data.get("content", data.get("message", content))
            duration_ms = int((time.monotonic() - t0) * 1000)
            # Estimate cost (depends on which model OpenClaw uses internally)
            cost = (total_in * 3.0 / 1_000_000) + (total_out * 15.0 / 1_000_000)
            task.result = TaskResult(
                summary=str(content)[:5000],
                total_duration_ms=duration_ms,
                tokens_in=total_in,
                tokens_out=total_out,
                estimated_cost_usd=round(cost, 4),
                engine_used=self.name.value,
            )
            task.status = TaskStatus.COMPLETE
        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = str(e)
        finally:
            self._status = EngineStatus.AVAILABLE
        task.updated_at = datetime.utcnow()
        return task

    async def stop(self):
        if self._gateway_proc and self._gateway_proc.poll() is None:
            self._gateway_proc.terminate()
        if self._http_client:
            await self._http_client.aclose()
        self._status = EngineStatus.STOPPED

    async def get_status(self):
        return self._status

# ---------------------------------------------------------------------------
# Computer-use engine (desktop control via Anthropic computer-use tool)
# ---------------------------------------------------------------------------

DESKTOP_KEYWORDS = [
    # OS elements
    "desktop", "taskbar", "start menu", "system tray", "notification",
    "folder", "file manager", "explorer", "finder", "dock", "spotlight",
    "system preferences", "settings", "control panel",
    # Office / productivity
    "app", "application", "notepad", "excel", "word", "powerpoint",
    "libreoffice", "calc", "writer", "outlook", "onenote",
    # Terminal
    "terminal", "command prompt", "powershell", "cmd", "wsl", "bash",
    # Messaging / communication
    "telegram", "discord", "slack", "whatsapp", "signal", "skype",
    "teams", "zoom", "webex", "google meet",
    # Browsers (when referenced as desktop apps)
    "chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari",
    # Media
    "spotify", "vlc", "media player", "foobar", "winamp", "itunes",
    # Dev tools
    "vscode", "vs code", "visual studio", "intellij", "pycharm",
    "sublime", "atom", "cursor",
    # Gaming / misc
    "steam", "epic games", "obs", "obs studio",
    # Knowledge / notes
    "notion", "obsidian", "evernote", "todoist", "trello",
    # Window actions
    "drag", "window", "minimize", "maximize", "close window",
    "screenshot", "snipping tool", "paint",
]

# Keywords indicating the user wants to search the web (multi-word phrases to avoid false positives)
WEB_SEARCH_KEYWORDS = [
    "search google", "google for", "web search", "search the web",
    "look up online", "search online", "browse to", "go to website",
    "open website", "visit website", "find online", "check online",
    "search bing", "bing for", "search duckduckgo",
]

# Patterns in task results/errors that indicate a web search capability failure (case-insensitive)
WEB_SEARCH_FAILURE_PATTERNS = [
    "brave search api",
    "brave_api_key",
    "brave api key",
    "search api key",
    "subscription_token_invalid",
    "configure the api key",
    "set the brave",
    "need a brave",
    "search provider",
    "web search is not configured",
    "search tool is not available",
]

SYSTEM_PROMPT_TEMPLATE = """\
You are a desktop automation agent controlling a Windows PC.
The screen is {scaled_width}x{scaled_height} pixels.

================================================================
MANDATORY REASONING PROTOCOL
================================================================
Before choosing ANY action, you MUST write your reasoning in this format:

[OBSERVE] What I see on screen right now (list visible windows, apps, UI elements)
[GOAL] The specific sub-goal I need to accomplish next
[PLAN] Which decision path I will follow (reference the trees below)
[ACTION] The exact action I will take and why

Do NOT skip this reasoning. It makes your actions more accurate.

================================================================
DECISION TREE 1: FINDING OR SWITCHING TO AN APP
================================================================
For ANY app you need to interact with, follow this EXACT order.
STOP at the first level that succeeds.

LEVEL 1 — IS THE APP ALREADY VISIBLE ON SCREEN?
  Scan the entire screenshot for the app window. Visual fingerprints:

  Telegram:
    - Blue header bar with app name
    - Chat list on the left side
    - Message input at BOTTOM with placeholder "Write a message..."
    - If you see "Write a message..." anywhere, Telegram is open

  Discord:
    - Dark gray/purple UI
    - Channel sidebar on the left
    - Message box at bottom with "Message #channel" placeholder

  Slack:
    - Purple/white UI with channel sidebar
    - Message composer at bottom of conversation

  WhatsApp:
    - Green header bar
    - Chat list or conversation view

  Browser (Chrome / Edge / Firefox):
    - Tab bar at the very top
    - Address bar just below tabs
    - Webpage content area

  VS Code / Cursor:
    - Dark sidebar with file tree on left
    - Editor tabs across the top
    - Integrated terminal at the bottom

  File Explorer:
    - Navigation breadcrumb at top
    - Folder tree on left pane
    - File/folder list on right pane

  Spotify:
    - Dark UI with green accent color
    - Playlist sidebar on left
    - Playback controls at bottom

  -> If the app is VISIBLE: interact with it directly.
     DO NOT search for it, re-open it, or navigate to it.

LEVEL 2 — IS IT ON THE TASKBAR?
  Look at the BOTTOM of the screen. The Windows taskbar shows:
  - Pinned app icons (always visible)
  - Running app icons (have a thin line/underline beneath them)
  -> If ON TASKBAR: single-click the icon to bring app to foreground.
     Then WAIT for the next screenshot to confirm it appeared.

LEVEL 3 — USE WINDOWS SEARCH (LAST RESORT ONLY)
  -> Click the search icon on the taskbar or press the Windows key.
  -> Type the app name, wait for results, click the matching result.
  -> Only use this if the app is NOT visible AND NOT on the taskbar.

================================================================
DECISION TREE 2: MESSAGING APPS (Telegram, Discord, Slack, etc.)
================================================================
Once the messaging app is in the foreground:

Step 1: Is the correct conversation/chat already open?
  HOW TO CHECK: Read the FOREGROUND WINDOW line in the SYSTEM INFO section.
  The window title typically contains the chat/channel name.
  Examples:
    - "Agent intelligence – (351553)" means Telegram has "Agent intelligence" open
    - "$BOOTS Community – (351556)" means a DIFFERENT chat is open
    - "#general - Discord" means Discord has the #general channel open
  -> If the correct chat IS open in the window title: skip to Step 3
  -> If a DIFFERENT chat is open or you're unsure: go to Step 2

Step 2: Navigate to the correct conversation using SEARCH
  CRITICAL: NEVER click on chat items in the sidebar list — they are NOT in
  the INTERACTIVE ELEMENTS list and coordinate clicks WILL miss. You MUST
  use the search bar (look for the "Search" element in INTERACTIVE ELEMENTS):
  1. Use click_element on the "Search" Edit field
  2. Type the chat/channel name
  3. Wait for search results
  4. Click the first matching result

  For Telegram:
    1. Click the search bar at the top of Telegram (or press Escape first
       to clear any current state, then click the search field)
    2. Type the chat/group name
    3. Wait for search results to appear
    4. Click the FIRST matching result
    5. Wait for the conversation to load and verify via SYSTEM INFO

  For Discord:
    1. Press Ctrl+K to open Quick Switcher
    2. Type the channel name
    3. Click the matching result

  For Slack:
    1. Press Ctrl+K to open Quick Switcher
    2. Type the channel/person name
    3. Click the matching result

Step 3: Type and send the message
  - Click the message input field at the BOTTOM of the conversation
    (look for placeholder text like "Write a message...", "Type a message...",
     "Message #channel", etc.)
  - Type the message text
  - Press Enter to send (unless the task says NOT to send)

================================================================
DECISION TREE 3: BROWSER TASKS
================================================================
Step 1: Is a browser already open?
  -> If YES: click the address bar (or press Ctrl+L), type the URL, press Enter
  -> If NO: follow Decision Tree 1 to open a browser first

Step 2: Do NOT close or rearrange existing tabs unless the task requires it.

================================================================
HOW TO USE SYSTEM INFO
================================================================
Each tool result includes SYSTEM INFO from Windows accessibility APIs.
This is MORE RELIABLE than trying to read text from the screenshot.

- FOREGROUND WINDOW: Tells you the title of the currently focused window.
  Use this to determine WHICH app and WHICH chat/document is active.
- VISIBLE WINDOWS: Lists all open windows. Use this to determine what's available.
- RUNNING APPS: Lists running processes. Use this to know what's installed/running.

ALWAYS check SYSTEM INFO before deciding your next action.

================================================================
ANTI-PATTERNS — NEVER DO THESE
================================================================
- NEVER click on chat names in messaging app sidebars (Telegram, Discord, Slack).
  Sidebar chat items are NOT accessible UI elements and clicking by coordinates
  WILL hit the wrong chat. ALWAYS use the Search field instead (click_element on
  the "Search" element, then type the chat name).
- NEVER search for an app that is already visible on screen
- NEVER re-open an app that is already in the foreground
- NEVER type text without first clicking the target input field
- NEVER use the Start menu / search if the app icon is on the taskbar
- NEVER close, minimize, or move windows you don't need to touch
- NEVER take more than 3 actions to reach an input field already visible on screen
- NEVER repeat the same failed action — try a different approach
- NEVER request a "screenshot" action — you already receive a fresh screenshot
  after every action automatically

================================================================
CLICKING UI ELEMENTS — ACCESSIBILITY-FIRST
================================================================
Each tool result includes an INTERACTIVE ELEMENTS list showing clickable
UI elements discovered via the Windows accessibility API. Each element has:
  [id] Type: "Name" at (x,y)

ALWAYS PREFER using click_element over coordinate-based clicks:
  action="click_element", element_id=<id>

This is FAR MORE RELIABLE than guessing pixel coordinates from screenshots.
Use coordinate-based clicks (left_click) ONLY when:
  - The target is NOT in the INTERACTIVE ELEMENTS list
  - You need to click a specific pixel location (e.g., inside a canvas)

Example workflow for Telegram:
  1. See element [5] Edit: "Search" at (556,83)
  2. Use action="click_element", element_id=5
  3. Then action="type", text="Agent Intelligence"
  4. Wait for results, find the matching element, click_element again

================================================================
CORE RULES
================================================================
1. ONE action per turn. Examine the result screenshot before the next action.
2. PREFER click_element over coordinate clicks for ALL named UI elements.
3. Be efficient — take the FEWEST actions possible to complete the task.
4. If an action didn't work (screenshot looks the same), try a DIFFERENT approach.
5. When the task is complete, respond with a text summary (no tool call).
6. TRUST the SYSTEM INFO and INTERACTIVE ELEMENTS over what you see in screenshots.

================================================================
SCREENSHOT
================================================================
Each turn you receive ONE full-screen screenshot at {scaled_width}x{scaled_height}.
ALL coordinate-based actions (clicks, drags) use coordinates from this image.
Use the INTERACTIVE ELEMENTS list to read element names/text reliably.
"""

class ComputerUseEngine(EngineBase):
    def __init__(self):
        self._status = EngineStatus.STOPPED
        self._client = None
        self._model = ""
        self._screen_width = 0
        self._screen_height = 0
        self._scaled_width = 0
        self._scaled_height = 0
        self.on_screenshot = None
        self.on_step = None  # Callback: receives step metadata dict
        self._last_ui_elements: list[dict] = []  # cached element list for click_element
        self._cancel_requested = False
        self._broadcast_fn = None  # For approval requests in supervised mode
        self._current_task_id = ""  # Current task ID for approval context
        self._current_context = ""  # Current context (window title, etc.)
        self._recorder = None  # InputRecorder instance (lazy-loaded)
        self._recording_active = False
        self._replay_state: ReplayState | None = None

    @property
    def name(self) -> EngineName:
        return EngineName.COMPUTER_USE
    @property
    def display_name(self) -> str:
        return "computer-use"
    @property
    def description(self) -> str:
        return "Full desktop control via mouse, keyboard, and screenshots."
    def _capabilities(self) -> list[str]:
        return ["mouse", "keyboard", "screenshot", "desktop_control", "type", "click"]

    async def initialize(self) -> None:
        self._status = EngineStatus.STARTING
        if sys.platform != "win32":
            self._status = EngineStatus.NOT_INSTALLED
            logging.info("computer-use engine: not available on this platform (Windows only)")
            return
        settings = get_settings()
        try:
            import anthropic as _anth; import pyautogui; import mss as _mss; from PIL import Image as _img  # noqa
        except ImportError as e:
            self._status = EngineStatus.NOT_INSTALLED
            logging.warning(f"computer-use deps not installed: {e}")
            return
        try:
            import ctypes as _ct
            _ct.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
        try:
            self._screen_width, self._screen_height = pyautogui.size()
        except Exception as e:
            self._status = EngineStatus.ERROR
            logging.error(f"Cannot detect screen: {e}")
            return
        max_w, max_h = settings.computer_use_max_screen_width, settings.computer_use_max_screen_height
        scale = min(max_w / self._screen_width, max_h / self._screen_height, 1.0)
        self._scaled_width = int(self._screen_width * scale)
        self._scaled_height = int(self._screen_height * scale)
        self._model = settings.computer_use_model
        self._is_openrouter = False
        import anthropic
        if settings.has_anthropic_key():
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        elif settings.has_openrouter_key():
            # OpenRouter's "Anthropic Skin" -- base_url must be /api (not /api/v1)
            self._client = anthropic.Anthropic(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api")
            self._is_openrouter = True
            # OpenRouter uses its own model naming convention
            if "/" not in self._model:
                self._model = f"anthropic/{self._model}"
        else:
            self._status = EngineStatus.NO_API_KEY
            self._error_hint = "Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY in .env"
            logging.info("computer-use: no API key configured")
            return
        self._status = EngineStatus.AVAILABLE
        logging.info(f"computer-use engine initialized (model={self._model}, scaled={self._scaled_width}x{self._scaled_height})")

    async def _take_screenshot(self) -> str:
        import mss as mss_mod; from PIL import Image; import io as _io
        loop = asyncio.get_event_loop()
        def _cap():
            with mss_mod.mss() as sct:
                raw = sct.grab(sct.monitors[1])
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                if img.width > self._scaled_width or img.height > self._scaled_height:
                    img = img.resize((self._scaled_width, self._scaled_height), Image.LANCZOS)
                buf = _io.BytesIO()
                img.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("utf-8")
        return await loop.run_in_executor(None, _cap)

    async def _get_foreground_window_rect(self) -> tuple[int, int, int, int] | None:
        """Get the foreground window bounding box in raw screen pixels."""
        loop = asyncio.get_event_loop()
        def _get():
            import ctypes
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            try:
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if not hwnd: return None
                rect = RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)): return None
                left, top = max(0, rect.left), max(0, rect.top)
                right, bottom = min(self._screen_width, rect.right), min(self._screen_height, rect.bottom)
                w, h = right - left, bottom - top
                if w <= 0 or h <= 0: return None
                if w >= self._screen_width * 0.95 and h >= self._screen_height * 0.95: return None
                if w < 200 or h < 150: return None
                return (left, top, right, bottom)
            except Exception: return None
        try: return await loop.run_in_executor(None, _get)
        except Exception: return None

    async def _take_window_crop(self, rect: tuple[int, int, int, int], max_dim: int = 1280) -> str | None:
        """Capture the foreground window region at higher resolution."""
        import mss as mss_mod; from PIL import Image
        left, top, right, bottom = rect
        loop = asyncio.get_event_loop()
        def _capture():
            try:
                with mss_mod.mss() as sct:
                    monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
                    raw = sct.grab(monitor)
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                    w, h = img.size
                    if max(w, h) > max_dim:
                        scale = max_dim / max(w, h)
                        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    return base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception: return None
        try: return await loop.run_in_executor(None, _capture)
        except Exception: return None

    async def _get_ui_elements(self) -> list[dict]:
        """Enumerate interactive UI elements from the foreground window using Windows UIA."""
        loop = asyncio.get_event_loop()
        def _enumerate():
            try:
                import ctypes
                from pywinauto import Desktop
                d = Desktop(backend='uia')
                user32 = ctypes.windll.user32
                fg_hwnd = user32.GetForegroundWindow()
                if not fg_hwnd:
                    return []
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(fg_hwnd, buf, 512)
                fg_title = buf.value
                # Find matching pywinauto window
                target_win = None
                for w in d.windows():
                    try:
                        if w.window_text() == fg_title:
                            target_win = w
                            break
                    except Exception:
                        pass
                if not target_win:
                    # Fallback: try partial match
                    for w in d.windows():
                        try:
                            wt = w.window_text()
                            if wt and fg_title and fg_title[:20] in wt:
                                target_win = w
                                break
                        except Exception:
                            pass
                if not target_win:
                    return []
                elements = []
                clickable_types = {'Button', 'Edit', 'MenuItem', 'ListItem', 'TabItem',
                                   'ComboBox', 'CheckBox', 'RadioButton', 'Hyperlink',
                                   'TreeItem', 'DataItem'}
                for c in target_win.descendants(depth=8):
                    try:
                        ct = c.element_info.control_type
                        if ct not in clickable_types:
                            continue
                        r = c.rectangle()
                        if r.width() < 10 or r.height() < 10:
                            continue
                        name = (c.window_text() or '').strip()[:80]
                        if not name:
                            continue
                        # Convert to scaled coordinates
                        cx = (r.left + r.right) // 2
                        cy = (r.top + r.bottom) // 2
                        # Skip elements with invalid/offscreen coordinates
                        if cx <= 0 or cy <= 0 or cx >= self._screen_width or cy >= self._screen_height:
                            continue
                        # Scale if needed
                        sx = int(cx * self._scaled_width / self._screen_width) if self._screen_width != self._scaled_width else cx
                        sy = int(cy * self._scaled_height / self._screen_height) if self._screen_height != self._scaled_height else cy
                        elements.append({
                            'id': len(elements),
                            'type': ct,
                            'name': name,
                            'center_x': sx,
                            'center_y': sy,
                            'raw_x': cx,
                            'raw_y': cy,
                        })
                        if len(elements) >= 40:
                            break
                    except Exception:
                        pass
                return elements
            except Exception as exc:
                logging.debug("UI element enumeration failed: %s", exc)
                return []
        try:
            return await loop.run_in_executor(None, _enumerate)
        except Exception:
            return []

    def _format_ui_elements(self, elements: list[dict]) -> str:
        """Format UI element list as text for the model."""
        if not elements:
            return ""
        lines = ["INTERACTIVE ELEMENTS (use click_element action with element_id for reliable clicking):"]
        for el in elements:
            lines.append(f"  [{el['id']}] {el['type']}: \"{el['name']}\" at ({el['center_x']},{el['center_y']})")
        return "\n".join(lines)

    async def _execute_action(self, tool_input: dict, action_context: str = "") -> str:
        import pyautogui; loop = asyncio.get_event_loop()
        action = tool_input.get("action", "")

        # ── Supervised mode: check if action needs approval ──
        settings = get_settings()
        if settings.automation_mode == "supervised" and action not in ("screenshot", "cursor_position", "mouse_move"):
            # Build action description for approval
            action_desc = action
            if action in ("left_click", "right_click", "double_click", "click_element"):
                if action == "click_element" and "element_id" in tool_input:
                    eid = int(tool_input.get("element_id", 0))
                    if 0 <= eid < len(self._last_ui_elements):
                        el = self._last_ui_elements[eid]
                        action_desc = f"Click: [{el.get('type', 'element')}] \"{el.get('name', 'unknown')}\""
                else:
                    coord = tool_input.get("coordinate", [0, 0])
                    action_desc = f"Click at coordinates ({coord[0]}, {coord[1]})"
            elif action == "type":
                text = tool_input.get("text", "")
                preview = text[:50] + "..." if len(text) > 50 else text
                action_desc = f"Type text: \"{preview}\""
            elif action == "key":
                action_desc = f"Press key: {tool_input.get('text', '')}"
            elif action == "scroll":
                action_desc = f"Scroll {tool_input.get('amount', 0)} clicks"

            # Check if high-risk
            is_risky, reason = is_high_risk_action(action_desc, self._current_context)
            if is_risky:
                logging.info("High-risk action detected: %s (reason: %s)", action_desc, reason)
                # Request approval
                approved = await get_approval_manager().request_approval(
                    task_id=self._current_task_id,
                    action=action_desc,
                    reason=reason,
                    details={"context": self._current_context, "raw_action": action},
                    broadcast_fn=self._broadcast_fn,
                )
                if not approved:
                    logging.info("Action denied by user: %s", action_desc)
                    return "action_denied_by_user"
        def _sc(coord):
            x, y = coord
            sx = max(0, min(int(x * self._screen_width / self._scaled_width), self._screen_width - 1))
            sy = max(0, min(int(y * self._screen_height / self._scaled_height), self._screen_height - 1))
            return sx, sy
        if action == "screenshot":
            return "screenshot_taken"
        elif action == "mouse_move":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.moveTo(rx, ry, duration=0.3))
            return f"mouse_moved_{rx}_{ry}"
        elif action == "left_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.click(rx, ry))
            return f"clicked_{rx}_{ry}"
        elif action == "right_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.rightClick(rx, ry))
            return f"right_clicked_{rx}_{ry}"
        elif action == "double_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.doubleClick(rx, ry))
            return f"double_clicked_{rx}_{ry}"
        elif action == "middle_click":
            rx, ry = _sc(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.middleClick(rx, ry))
            return f"middle_clicked_{rx}_{ry}"
        elif action == "left_click_drag":
            start = _sc(tool_input["start_coordinate"]); end = _sc(tool_input["coordinate"])
            def _d():
                pyautogui.moveTo(start[0], start[1]); pyautogui.drag(end[0]-start[0], end[1]-start[1], duration=0.5)
            await loop.run_in_executor(None, _d)
            return f"dragged_{start}_to_{end}"
        elif action == "type":
            text = tool_input.get("text", "")
            def _t():
                if text.isascii(): pyautogui.write(text, interval=0.02)
                else:
                    import pyperclip; pyperclip.copy(text); pyautogui.hotkey("ctrl", "v")
            await loop.run_in_executor(None, _t)
            return f"typed_{len(text)}_chars"
        elif action == "key":
            kc = tool_input.get("text", "")
            def _k():
                keys = [k.strip() for k in kc.split("+")]
                pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
            await loop.run_in_executor(None, _k)
            return f"pressed_{kc}"
        elif action == "cursor_position":
            pos = pyautogui.position()
            return f"cursor_at_{pos.x}_{pos.y}"
        elif action == "scroll":
            rx, ry = _sc(tool_input.get("coordinate", [self._scaled_width//2, self._scaled_height//2]))
            clicks = tool_input.get("amount", 3)
            await loop.run_in_executor(None, lambda: pyautogui.scroll(clicks, x=rx, y=ry))
            return f"scrolled_{clicks}"
        elif action == "click_element":
            eid = tool_input.get("element_id")
            if eid is None:
                return "error: element_id required"
            eid = int(eid)
            if eid < 0 or eid >= len(self._last_ui_elements):
                return f"error: element_id {eid} out of range (0-{len(self._last_ui_elements)-1})"
            el = self._last_ui_elements[eid]
            rx, ry = el['raw_x'], el['raw_y']
            logging.info("click_element [%d] '%s' at raw (%d,%d)", eid, el['name'], rx, ry)
            await loop.run_in_executor(None, lambda: pyautogui.click(rx, ry))
            return f"clicked_element_{eid}_{el['name']}_at_{rx}_{ry}"
        return f"unknown_{action}"

    @staticmethod
    def _screenshots_similar(b64_a: str, b64_b: str, threshold: int = 5) -> bool:
        """Compare two base64 screenshots using average perceptual hash."""
        from PIL import Image
        def _avg_hash(b64):
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            img = img.resize((8, 8), Image.LANCZOS).convert("L")
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            return sum(1 << i for i, p in enumerate(pixels) if p >= avg)
        return bin(_avg_hash(b64_a) ^ _avg_hash(b64_b)).count("1") <= threshold

    async def _describe_screen(self) -> str:
        """Use Windows APIs to describe visible windows as text."""
        loop = asyncio.get_event_loop()
        def _gather():
            import subprocess as _sp
            lines = []
            try:
                ps = "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object ProcessName, MainWindowTitle | Format-Table -AutoSize -HideTableHeaders"
                out = _sp.check_output(["powershell", "-NoProfile", "-Command", ps], timeout=3, text=True, creationflags=_sp.CREATE_NO_WINDOW)
                windows = [w.strip() for w in out.strip().splitlines() if w.strip()]
                if windows:
                    lines.append("VISIBLE WINDOWS:")
                    for w in windows[:15]:
                        lines.append(f"  - {w}")
            except Exception: pass
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if buf.value:
                    lines.append(f"\nFOREGROUND WINDOW: {buf.value}")
            except Exception: pass
            try:
                ps2 = "Get-Process -Name Telegram,Discord,Slack,Spotify,chrome,msedge,firefox,Code,Telegram.Desktop -ErrorAction SilentlyContinue | Select-Object ProcessName -Unique | Format-Table -HideTableHeaders"
                out2 = _sp.check_output(["powershell", "-NoProfile", "-Command", ps2], timeout=3, text=True, creationflags=_sp.CREATE_NO_WINDOW)
                apps = [a.strip() for a in out2.strip().splitlines() if a.strip()]
                if apps:
                    lines.append(f"\nRUNNING APPS: {', '.join(apps)}")
            except Exception: pass
            return "\n".join(lines) if lines else ""
        try:
            return await loop.run_in_executor(None, _gather)
        except Exception:
            return ""

    async def _bring_app_to_foreground(self, app_keyword: str) -> bool:
        """Try to bring a window matching app_keyword to the foreground. Returns True if successful."""
        loop = asyncio.get_event_loop()
        def _focus():
            try:
                import ctypes
                from pywinauto import Desktop
                d = Desktop(backend='uia')
                for w in d.windows():
                    try:
                        title = w.window_text()
                        if app_keyword.lower() in title.lower():
                            w.set_focus()
                            import time as _t; _t.sleep(0.5)
                            return True
                    except Exception:
                        pass
                # Fallback: try win32 backend for apps like Telegram
                d2 = Desktop(backend='win32')
                for w in d2.windows():
                    try:
                        title = w.window_text()
                        if app_keyword.lower() in title.lower():
                            w.set_focus()
                            import time as _t; _t.sleep(0.5)
                            return True
                    except Exception:
                        pass
            except Exception as exc:
                logging.debug("Failed to bring %s to foreground: %s", app_keyword, exc)
            return False
        try:
            return await loop.run_in_executor(None, _focus)
        except Exception:
            return False

    def _detect_target_app(self, prompt: str) -> str | None:
        """Detect which app the task is targeting from the prompt text."""
        prompt_lower = prompt.lower()
        app_keywords = {
            'telegram': 'Telegram',
            'discord': 'Discord',
            'slack': 'Slack',
            'whatsapp': 'WhatsApp',
            'signal': 'Signal',
            'chrome': 'Chrome',
            'brave': 'Brave',
            'firefox': 'Firefox',
            'edge': 'Edge',
            'spotify': 'Spotify',
            'vs code': 'Code',
            'vscode': 'Code',
            'cursor': 'Cursor',
            'notepad': 'Notepad',
        }
        for keyword, app_name in app_keywords.items():
            if keyword in prompt_lower:
                return app_name
        return None

    def set_broadcast_fn(self, fn):
        """Set the broadcast function for approval requests."""
        self._broadcast_fn = fn

    # ── Recording / Replay Methods ──────────────────────────────────────────

    def start_recording(self) -> bool:
        """Start recording desktop input. Returns True if started, False if already recording."""
        if self._recording_active:
            return False
        from clawbridge.recorder.capture import InputRecorder
        self._recorder = InputRecorder()
        self._recorder.start()
        self._recording_active = True
        logging.info("ComputerUseEngine: recording started")
        return True

    async def stop_recording(self) -> list[dict]:
        """Stop recording and return enriched actions."""
        if not self._recording_active or not self._recorder:
            return []
        raw_events = self._recorder.stop()
        self._recording_active = False
        self._recorder = None
        if not raw_events:
            return []
        from clawbridge.recorder.processor import process_recording
        actions = await process_recording(raw_events)
        logging.info("ComputerUseEngine: recording stopped, %d actions captured", len(actions))
        return actions

    def _detect_target_from_actions(self, wf: WorkflowTemplate) -> str:
        """Auto-detect target app from recorded window titles.

        Finds the most common non-browser window title in the recorded actions
        and extracts the app name from it.
        """
        from collections import Counter
        browser_keywords = ("brave", "chrome", "firefox", "edge", "safari", "opera", "clawbridge dashboard")
        titles: list[str] = []
        for a in wf.actions:
            t = ""
            if hasattr(a, 'window_title'):
                t = a.window_title
            elif isinstance(a, dict):
                t = a.get("window_title", "")
            if t and not any(bk in t.lower() for bk in browser_keywords):
                titles.append(t)
        if not titles:
            return ""
        most_common = Counter(titles).most_common(1)[0][0]
        return most_common

    async def _focus_window_by_title(self, title: str) -> bool:
        """Focus a window by its (partial) title using pywinauto."""
        loop = asyncio.get_running_loop()
        def _focus():
            try:
                from pywinauto import Desktop
                d = Desktop(backend='uia')
                for w in d.windows():
                    try:
                        wt = w.window_text()
                        if wt and title and (title in wt or wt in title or title.split(" - ")[0] in wt):
                            w.set_focus()
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
            return False
        try:
            return await loop.run_in_executor(None, _focus)
        except Exception:
            return False

    async def replay_workflow(self, wf: WorkflowTemplate, task: Task) -> Task:
        """Replay a saved workflow, using element matching with LLM fallback."""
        import pyautogui

        self._status = EngineStatus.RUNNING
        self._current_task_id = task.id
        task.status = TaskStatus.RUNNING
        start = time.monotonic()
        replay = ReplayState(
            workflow_id=wf.id,
            workflow_name=wf.name,
            total_steps=len(wf.actions),
            status="running",
        )
        self._replay_state = replay
        llm_fallbacks = 0
        completed_steps = 0

        # Auto-detect target app from recorded window titles
        target_app = wf.target_app or self._detect_target_from_actions(wf)
        logging.info("Replay starting: workflow='%s', %d actions, target='%s'",
                     wf.name, len(wf.actions), target_app or "(none)")

        try:
            # Pre-action: bring target app to foreground — but skip if
            # the workflow starts with a Win key press (user is launching the app)
            first_action = wf.actions[0] if wf.actions else None
            first_is_launch = False
            if first_action:
                fa = first_action.model_dump() if hasattr(first_action, 'model_dump') else first_action
                first_is_launch = fa.get("action_type") == "key" and fa.get("key") in ("cmd", "cmd_r")
            if target_app and not first_is_launch:
                focused = await self._bring_app_to_foreground(target_app)
                if not focused:
                    focused = await self._focus_window_by_title(target_app)
                if focused:
                    logging.info("Replay: focused target app '%s'", target_app)
                    await asyncio.sleep(1.0)
                else:
                    logging.warning("Replay: could not focus target app '%s'", target_app)
            elif first_is_launch:
                logging.info("Replay: skipping pre-focus (workflow starts with app launch)")

            for i, action in enumerate(wf.actions):
                replay.current_step = i + 1
                action_dict = action.model_dump() if hasattr(action, 'model_dump') else action
                atype = action_dict.get('action_type', '?')
                adetail = action_dict.get('element_name') or action_dict.get('text') or action_dict.get('key') or ''
                logging.info("Replay step %d/%d: %s %s", i + 1, len(wf.actions), atype, adetail[:40])

                # Broadcast step progress
                if self.on_step:
                    try:
                        self.on_step({
                            "task_id": task.id,
                            "step": i + 1,
                            "max_steps": len(wf.actions),
                            "action": f"replay:{atype}",
                            "reasoning": f"Replaying step {i+1}/{len(wf.actions)}: {atype} {adetail}".strip(),
                        })
                    except Exception:
                        pass

                success = await self._replay_single_action(action_dict, task, target_app)
                if not success:
                    # LLM fallback
                    logging.info("Replay step %d: element match failed, trying LLM fallback", i + 1)
                    fallback_ok = await self._llm_fallback_for_step(action_dict, task)
                    llm_fallbacks += 1
                    if not fallback_ok:
                        replay.status = "error"
                        replay.error = f"Failed at step {i+1}: could not match or LLM-complete action"
                        task.status = TaskStatus.ERROR
                        task.error = replay.error
                        break

                completed_steps += 1
                # Delay between actions to let UI settle
                delay = 0.5 if atype in ("click", "key") else 0.15
                await asyncio.sleep(delay)

            if task.status != TaskStatus.ERROR:
                replay.status = "complete"
                replay.llm_fallback_steps = llm_fallbacks
                task.status = TaskStatus.COMPLETE
                elapsed = int((time.monotonic() - start) * 1000)
                task.result = TaskResult(
                    summary=f"Replayed workflow '{wf.name}': {completed_steps}/{len(wf.actions)} steps completed"
                            + (f" ({llm_fallbacks} LLM fallbacks)" if llm_fallbacks else ""),
                    total_steps=completed_steps,
                    total_duration_ms=elapsed,
                    engine_used="computer_use",
                )
                get_workflow_manager().mark_replayed(wf.id)
                logging.info("Replay complete: %d/%d steps, %d fallbacks, %dms",
                             completed_steps, len(wf.actions), llm_fallbacks, elapsed)

        except Exception as exc:
            logging.error("Workflow replay error: %s", exc, exc_info=True)
            replay.status = "error"
            replay.error = str(exc)
            task.status = TaskStatus.ERROR
            task.error = f"Replay error: {exc}"
        finally:
            self._status = EngineStatus.AVAILABLE
            self._replay_state = None

        return task

    async def _replay_single_action(self, action: dict, task: Task, target_app: str = "") -> bool:
        """Replay one action. Re-focuses target app before click/type actions."""
        import pyautogui
        from clawbridge.perception.accessibility import (
            get_accessibility_tree, find_matching_element, ElementSnapshot,
        )

        action_type = action.get("action_type", "")
        loop = asyncio.get_running_loop()

        # Key mapping: pynput names → pyautogui names
        KEY_MAP = {
            "cmd": "win", "cmd_r": "winright",
            "ctrl_l": "ctrlleft", "ctrl_r": "ctrlright",
            "alt_l": "altleft", "alt_r": "altright",
            "shift_r": "shiftright",
            "return": "enter",
            "caps_lock": "capslock",
        }

        if action_type == "type":
            text = action.get("text", "")
            if text:
                logging.info("Replay type: '%s'", text[:60])
                await loop.run_in_executor(None, lambda: pyautogui.typewrite(text, interval=0.03) if text.isascii() else pyautogui.write(text))
            return True

        if action_type == "key":
            key = action.get("key", "")
            if key:
                mapped = KEY_MAP.get(key, key)
                logging.info("Replay key: '%s' -> '%s'", key, mapped)
                await loop.run_in_executor(None, lambda: pyautogui.press(mapped))
                # After pressing Win or Enter, wait for UI to react
                if mapped in ("win", "enter"):
                    await asyncio.sleep(1.0)
            return True

        if action_type == "scroll":
            amount = action.get("scroll_amount", 0)
            x, y = action.get("x", 0), action.get("y", 0)
            if amount:
                await loop.run_in_executor(None, lambda: pyautogui.scroll(amount, x=x, y=y))
            return True

        if action_type == "click":
            # Re-focus target app before clicking (Windows steals focus)
            if target_app:
                await self._focus_window_by_title(target_app)
                await asyncio.sleep(0.2)

            el_name = action.get("element_name", "")
            el_type = action.get("element_type", "")
            el_auto_id = action.get("element_automation_id", "")
            el_parent = action.get("element_parent_name", "")

            if el_name or el_auto_id:
                target = ElementSnapshot(
                    control_type=el_type,
                    name=el_name,
                    automation_id=el_auto_id,
                    parent_name=el_parent,
                    center_x=action.get("x", 0),
                    center_y=action.get("y", 0),
                )
                tree = await get_accessibility_tree(max_depth=8, max_elements=60)
                match, confidence = find_matching_element(target, tree, threshold=0.7)
                if match:
                    logging.info("Replay click: matched '%s' (confidence %.2f) at (%d, %d)",
                                 match.name, confidence, match.center_x, match.center_y)
                    btn = action.get("button", "left")
                    await loop.run_in_executor(None, lambda: pyautogui.click(
                        match.center_x, match.center_y,
                        button=btn if btn in ("left", "right", "middle") else "left"
                    ))
                    return True
                else:
                    logging.info("Replay click: no a11y match for '%s' (type=%s), using raw coords", el_name, el_type)
                    # Fall through to raw coordinates
            # Use raw coordinates
            x, y = action.get("x", 0), action.get("y", 0)
            if x > 0 and y > 0:
                logging.info("Replay click: raw coords (%d, %d)", x, y)
                btn = action.get("button", "left")
                await loop.run_in_executor(None, lambda: pyautogui.click(
                    x, y, button=btn if btn in ("left", "right", "middle") else "left"
                ))
                return True
            return False

        # Unknown action type — skip
        logging.info("Replay: skipping unknown action type '%s'", action_type)
        return True

    async def _llm_fallback_for_step(self, action: dict, task: Task) -> bool:
        """Ask the LLM to complete an action that element matching couldn't resolve."""
        action_type = action.get("action_type", "click")
        el_name = action.get("element_name", "")
        el_type = action.get("element_type", "")
        window_title = action.get("window_title", "")

        desc = f"Click on the {el_type} element named '{el_name}'" if el_name else f"Perform a {action_type} action"
        if window_title:
            desc += f" in the '{window_title}' window"

        # Create a mini-task for a single LLM step
        mini_prompt = (
            f"IMPORTANT: Complete this single UI action and then STOP.\n"
            f"Action: {desc}\n"
            f"After completing this one action, respond with 'DONE'."
        )
        mini_task = Task(prompt=mini_prompt, engine=EngineName.COMPUTER_USE)
        mini_task._personality_context = getattr(task, '_personality_context', '')

        try:
            # Run with very limited steps
            settings = get_settings()
            original_max = settings.max_actions_per_task
            settings.max_actions_per_task = 3  # Only allow 3 steps for fallback
            result = await self.run_task(mini_task)
            settings.max_actions_per_task = original_max
            return result.status == TaskStatus.COMPLETE
        except Exception as exc:
            logging.error("LLM fallback failed: %s", exc)
            return False

    def _find_matching_workflow(self, prompt: str) -> WorkflowTemplate | None:
        """Safe workflow matching — no substring matching to avoid false positives.

        Matches:
        - Explicit prefix: "replay: Workflow Name" → exact name match
        - Short prompt (<=80 chars) exact name match only
        """
        stripped = prompt.strip()

        # Explicit prefix match: "replay: <name>"
        if stripped.lower().startswith("replay:"):
            name = stripped[7:].strip()
            if name:
                return get_workflow_manager().get_by_name(name)

        # Short prompt exact name match only
        if len(stripped) <= 80:
            return get_workflow_manager().get_by_name(stripped)

        return None

    async def run_task(self, task: Task) -> Task:
        # ── Check for workflow replay before normal task execution ──
        wf = self._find_matching_workflow(task.prompt)
        if wf and wf.actions:
            return await self.replay_workflow(wf, task)

        if self._status != EngineStatus.AVAILABLE:
            task.status = TaskStatus.ERROR; task.error = "computer-use engine not available"; return task
        self._status = EngineStatus.RUNNING
        self._current_task_id = task.id
        self._current_context = f"Task: {task.prompt[:100]}"
        self._cancel_requested = False
        start = time.monotonic()
        settings = get_settings()
        max_steps = min(settings.max_actions_per_task, 50)
        delay = settings.computer_use_action_delay_ms / 1000.0
        try:
            # Pre-action: bring target app to foreground automatically
            target_app = self._detect_target_app(task.prompt)
            focused = False
            if target_app:
                focused = await self._bring_app_to_foreground(target_app)
                if focused:
                    logging.info("Pre-action: brought '%s' to foreground", target_app)
                    await asyncio.sleep(1.0)  # Let Windows fully switch focus
                    # Focus again to be sure
                    await self._bring_app_to_foreground(target_app)
                    await asyncio.sleep(0.5)
                else:
                    logging.info("Pre-action: could not find '%s' window", target_app)
            init_ss = await self._take_screenshot()
            if self.on_screenshot:
                try: self.on_screenshot(init_ss)
                except Exception: pass
            screen_desc = await self._describe_screen()
            if screen_desc:
                logging.info("Screen description:\n%s", screen_desc)
            # Native Anthropic computer-use tool (direct API only)
            native_tool = [{"type": "computer_20241022", "name": "computer", "display_width_px": self._scaled_width, "display_height_px": self._scaled_height, "display_number": 1}]
            # Standard function tool for OpenRouter compatibility
            func_tool = [{"name": "computer", "description": f"Control the computer screen ({self._scaled_width}x{self._scaled_height}). Returns a screenshot and a list of interactive UI elements after every action. PREFER click_element over coordinate-based clicks for buttons, fields, and other named UI elements.", "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["screenshot", "mouse_move", "left_click", "right_click", "double_click", "middle_click", "left_click_drag", "type", "key", "cursor_position", "scroll", "click_element"], "description": "The action to perform. Use 'click_element' with 'element_id' to click a UI element by its ID from the INTERACTIVE ELEMENTS list — this is MORE RELIABLE than coordinate-based clicks."}, "coordinate": {"type": "array", "items": {"type": "integer"}, "description": "[x, y] pixel coordinates for mouse actions (not needed for click_element)"}, "start_coordinate": {"type": "array", "items": {"type": "integer"}, "description": "[x, y] start coordinates for drag"}, "text": {"type": "string", "description": "Text to type, or key combo like 'ctrl+c'"}, "amount": {"type": "integer", "description": "Scroll amount (positive=up, negative=down)"}, "element_id": {"type": "integer", "description": "ID of the UI element to click (from the INTERACTIVE ELEMENTS list). Use with action='click_element'."}}, "required": ["action"]}}]
            tools = native_tool if not self._is_openrouter else func_tool
            sys_prompt = SYSTEM_PROMPT_TEMPLATE.format(scaled_width=self._scaled_width, scaled_height=self._scaled_height)
            # ── Inject personality/memory context into system prompt ─────
            personality_ctx = getattr(task, '_personality_context', '')
            if personality_ctx:
                sys_prompt += f"\n\n================================================================\nAGENT IDENTITY & MEMORY\n================================================================\n{personality_ctx}\n"
            ctx = ""
            if target_app and focused:
                ctx += f"IMPORTANT: {target_app} has ALREADY been brought to the foreground for you. It is the active window. Do NOT click the taskbar or try to switch to it — just interact with its UI elements directly.\n\n"
            if screen_desc:
                ctx += f"SYSTEM INFO (from Windows accessibility APIs):\n{screen_desc}\n\nUse this info to understand what is ALREADY open. If the target app is listed in VISIBLE WINDOWS or FOREGROUND WINDOW, it is already on screen — interact with it directly."
            # Enumerate interactive UI elements
            self._last_ui_elements = await self._get_ui_elements()
            ui_text = self._format_ui_elements(self._last_ui_elements)
            if ui_text:
                ctx += f"\n\n{ui_text}"
                logging.info("UI elements found: %d", len(self._last_ui_elements))
            ctx += "\n\nComplete the task. PREFER click_element over coordinate-based clicks."
            content_blocks = [
                {"type": "text", "text": task.prompt},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": init_ss}},
                {"type": "text", "text": ctx},
            ]
            messages = [{"role": "user", "content": content_blocks}]
            step_count = 0; total_in = 0; total_out = 0; final_text = ""; prev_ss = init_ss
            while step_count < max_steps:
                if self._cancel_requested:
                    logging.info("Task cancelled by user at step %d", step_count)
                    final_text = f"Task stopped by user after {step_count} steps."
                    break
                api_kwargs = dict(model=self._model, max_tokens=4096, system=sys_prompt, tools=tools, messages=messages)
                if not self._is_openrouter:
                    api_kwargs["betas"] = ["computer-use-2024-10-22"]
                logging.info("Calling API (step %d, messages=%d)...", step_count + 1, len(messages))
                try:
                    resp = self._client.messages.create(**api_kwargs)
                except Exception as api_err:
                    logging.error("API call failed: %s", api_err)
                    raise
                total_in += resp.usage.input_tokens; total_out += resp.usage.output_tokens
                logging.info("API response: stop=%s, tokens_in=%d, tokens_out=%d", resp.stop_reason, total_in, total_out)
                tu_blocks = [b for b in resp.content if b.type == "tool_use"]
                txt_blocks = [b.text for b in resp.content if b.type == "text"]
                if txt_blocks:
                    final_text = "\n".join(txt_blocks)
                    for _tb in txt_blocks:
                        logging.info("computer-use reasoning (step %d): %s", step_count + 1, _tb[:500])
                if not tu_blocks: break
                tool_results = []
                for tb in tu_blocks:
                    action_name = tb.input.get("action", "")
                    is_ss_only = action_name == "screenshot"
                    if not is_ss_only:
                        step_count += 1
                    logging.info("computer-use step %d/%d: %s%s", step_count, max_steps, action_name or "?", " (free)" if is_ss_only else "")
                    if not is_ss_only:
                        # Re-focus target app before every action to prevent wrong-window clicks
                        if target_app and action_name in ("left_click", "right_click", "double_click", "click_element", "type", "key"):
                            await self._bring_app_to_foreground(target_app)
                            await asyncio.sleep(0.5)
                        await self._execute_action(tb.input)
                        await asyncio.sleep(delay)
                    # Re-focus target before screenshot so the model sees the right window
                    if target_app:
                        await self._bring_app_to_foreground(target_app)
                        await asyncio.sleep(0.5)
                    ss = await self._take_screenshot()
                    if self.on_screenshot:
                        try: self.on_screenshot(ss)
                        except Exception: pass
                    # ── Broadcast step update to dashboard ────────────
                    if self.on_step and not is_ss_only:
                        try:
                            reasoning = ""
                            if txt_blocks:
                                reasoning = txt_blocks[-1][:300]
                            self.on_step({
                                "task_id": task.id,
                                "step": step_count,
                                "max_steps": max_steps,
                                "action": action_name,
                                "detail": json.dumps(tb.input)[:200] if hasattr(tb, 'input') else "",
                                "reasoning": reasoning,
                                "tokens_in": total_in,
                                "tokens_out": total_out,
                            })
                        except Exception: pass
                    step_desc = await self._describe_screen()
                    # Refresh UI elements after each action
                    self._last_ui_elements = await self._get_ui_elements()
                    ui_text = self._format_ui_elements(self._last_ui_elements)
                    hint = f"[Step {step_count} of {max_steps}]"
                    if step_desc:
                        hint += f"\n\nCURRENT SYSTEM STATE:\n{step_desc}"
                    if ui_text:
                        hint += f"\n\n{ui_text}"
                    rc = [{"type": "text", "text": hint}]
                    if not is_ss_only and prev_ss and self._screenshots_similar(prev_ss, ss):
                        rc.append({"type": "text", "text": "WARNING: The screenshot appears unchanged after your last action. The action may have had no effect. Consider trying a different approach."})
                        logging.warning("Stale screenshot detected at step %d", step_count)
                    rc.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ss}})
                    tool_results.append({"type": "tool_result", "tool_use_id": tb.id, "content": rc})
                    prev_ss = ss
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                if not final_text: final_text = f"Reached max step limit ({max_steps})."
            dur = int((time.monotonic() - start) * 1000)
            # Estimate cost: Sonnet 4 via OpenRouter ~$3/M in, ~$15/M out
            cost = (total_in * 3.0 / 1_000_000) + (total_out * 15.0 / 1_000_000)
            task.result = TaskResult(
                summary=(final_text or "Task completed.")[:5000],
                engine_used=EngineName.COMPUTER_USE.value,
                total_steps=step_count,
                total_duration_ms=dur,
                tokens_in=total_in,
                tokens_out=total_out,
                estimated_cost_usd=round(cost, 4),
            )
            task.status = TaskStatus.CANCELLED if self._cancel_requested else TaskStatus.COMPLETE
        except Exception as e:
            task.status = TaskStatus.ERROR; task.error = str(e)
        finally:
            self._status = EngineStatus.AVAILABLE
        task.updated_at = datetime.utcnow()
        return task

    async def execute_step(self, task, step):
        micro = Task(prompt=f"{step.action}: {step.target}", engine=EngineName.COMPUTER_USE)
        r = await self.run_task(micro)
        return {"summary": r.result.summary if r.result else "Done", "duration_ms": 0}
    def request_cancel(self):
        """Signal the running task to stop at the next loop iteration."""
        self._cancel_requested = True
        logging.info("Cancel requested for computer-use engine")
    async def stop(self):
        self._client = None; self._status = EngineStatus.STOPPED
    async def get_status(self):
        return self._status

# ---------------------------------------------------------------------------
# Task manager
# ---------------------------------------------------------------------------

class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._engines: dict[EngineName, EngineBase] = {}
        self._running = 0
        self._futures: dict[str, asyncio.Task] = {}
        self._broadcast: Callable | None = None
        self._load_tasks_from_db()

    def _load_tasks_from_db(self):
        try:
            conn = sqlite3.connect(Settings.db_path)
            c = conn.cursor()
            c.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100")
            for row in c.fetchall():
                res_val = json.loads(row[4]) if row[4] else None
                t = Task(
                    id=row[0], prompt=row[1], engine=row[2], 
                    status=TaskStatus(row[3]),
                    result=TaskResult(**res_val) if res_val else None,
                    error=row[5],
                    created_at=datetime.fromisoformat(row[6]),
                    updated_at=datetime.fromisoformat(row[7])
                )
                self._tasks[t.id] = t
            conn.close()
        except Exception as e:
            logging.error(f"Failed to load tasks from DB: {e}")

    def _save_task_to_db(self, task: Task):
        try:
            conn = sqlite3.connect(Settings.db_path)
            c = conn.cursor()
            res_json = json.dumps(task.result.model_dump()) if task.result else None
            c.execute("""INSERT OR REPLACE INTO tasks 
                         (id, prompt, engine, status, result, error, created_at, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                      (task.id, task.prompt, task.engine, task.status.value, 
                       res_json, task.error, task.created_at.isoformat(), task.updated_at.isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Failed to save task to DB: {e}")

    def _make_on_step(self):
        """Create an on_step callback that broadcasts AND persists step data."""
        def on_step(s):
            save_step_to_db(s)  # persist to SQLite
            if self._broadcast:
                asyncio.create_task(self._broadcast({"type": "step_update", "payload": s}))
        return on_step

    async def init_engines(self) -> None:
        on_step_cb = self._make_on_step()
        for name in get_settings().enabled_engine_list():
            if name == EngineName.BROWSER_USE.value or name == "browser_use":
                e = BrowserUseEngine()
                e.on_screenshot = lambda img: asyncio.create_task(self._broadcast({"type": "live_view", "payload": {"image": img}})) if self._broadcast else None
                e.on_step = on_step_cb
                await e.initialize()
                self._engines[EngineName.BROWSER_USE] = e
            elif name == EngineName.OPENCLAW.value or name == "openclaw":
                e = OpenClawEngine()
                await e.initialize()
                self._engines[EngineName.OPENCLAW] = e
            elif name == EngineName.COMPUTER_USE.value or name == "computer_use":
                e = ComputerUseEngine()
                e.on_screenshot = lambda img: asyncio.create_task(self._broadcast({"type": "live_view", "payload": {"image": img}})) if self._broadcast else None
                e.on_step = on_step_cb
                e.set_broadcast_fn(lambda msg: self._broadcast(msg) if self._broadcast else None)
                await e.initialize()
                self._engines[EngineName.COMPUTER_USE] = e

    def _engine_for(self, preferred: EngineName, prompt: str = "", exclude: list[EngineName] | None = None) -> EngineBase | None:
        """Select the best available engine for a task.

        Smart default priority:
        - Web search tasks: browser-use → openclaw → computer-use
        - Desktop tasks: computer-use → browser-use → openclaw
        - Non-desktop tasks: openclaw (when available) → browser-use → computer-use

        OpenClaw is preferred for non-desktop tasks because it has memory/skills support.
        browser-use is preferred for web search because it can navigate real browsers.
        """
        exclude = exclude or []

        # Explicit engine selection (not AUTO) — still respect exclude list
        if preferred != EngineName.AUTO and preferred in self._engines and preferred not in exclude:
            engine = self._engines[preferred]
            logging.info("Engine selected: %s (explicit)", engine.display_name)
            return engine

        # Determine priority order based on task type
        prompt_lower = prompt.lower() if prompt else ""
        is_desktop = prompt_lower and any(kw in prompt_lower for kw in DESKTOP_KEYWORDS)
        is_web_search = prompt_lower and any(kw in prompt_lower for kw in WEB_SEARCH_KEYWORDS)

        if is_web_search and not is_desktop:
            # Web search tasks: prefer browser-use (can open a real browser and search)
            priority = [EngineName.BROWSER_USE, EngineName.OPENCLAW, EngineName.COMPUTER_USE]
            reason = "web search task detected"
        elif is_desktop:
            # Desktop tasks: prefer computer-use for native app control
            priority = [EngineName.COMPUTER_USE, EngineName.BROWSER_USE, EngineName.OPENCLAW]
            reason = "desktop task detected"
        else:
            # Non-desktop tasks: prefer OpenClaw (has memory/skills), then browser-use
            priority = [EngineName.OPENCLAW, EngineName.BROWSER_USE, EngineName.COMPUTER_USE]
            reason = "smart default (OpenClaw preferred when available)"

        # Remove excluded engines (already tried and failed)
        priority = [n for n in priority if n not in exclude]

        # Find first available engine in priority order
        for name in priority:
            if name in self._engines:
                engine = self._engines[name]
                if engine._status == EngineStatus.AVAILABLE:
                    logging.info("Engine selected: %s (%s)", engine.display_name, reason)
                    return engine

        # Fallback: return any engine even if not fully available (let run_task handle errors)
        for name in priority:
            if name in self._engines:
                engine = self._engines[name]
                logging.warning("Engine selected: %s (fallback, status=%s)", engine.display_name, engine._status.value)
                return engine

        logging.error("No engines available for task")
        return None

    async def submit(self, task: Task) -> Task:
        get_audit().log(AuditEvent(task_id=task.id, event_type="task_created", detail=task.prompt[:100]))
        self._tasks[task.id] = task
        if self._running < get_settings().max_concurrent_tasks:
            fut = asyncio.create_task(self._run(task))
            self._futures[task.id] = fut
        else:
            task.status = TaskStatus.PENDING
        self._save_task_to_db(task)
        return task

    async def _run(self, task: Task) -> None:
        self._running += 1
        task.status = TaskStatus.RUNNING
        task.updated_at = datetime.utcnow()
        self._save_task_to_db(task)
        if self._broadcast:
            await self._broadcast({"type": "task_update", "payload": task.model_dump(mode="json")})

        # ── Safety screening ─────────────────────────────────────────────
        original_prompt = task.prompt  # preserve for logging
        try:
            scan = safety_scan_prompt(task.prompt)
            policy = get_settings().policy_mode
            if not scan["clean"]:
                flags = []
                if scan["credentials"]: flags.append("credentials detected")
                if scan["pii"]: flags.append("PII detected")
                if scan["injection_flags"]: flags.append(f"injection patterns: {len(scan['injection_flags'])}")
                flag_str = ", ".join(flags)
                logging.warning("Safety scan for task %s: %s (policy=%s)", task.id[:8], flag_str, policy)
                get_audit().log(AuditEvent(task_id=task.id, event_type="safety_flag", detail=flag_str))
                if self._broadcast:
                    await self._broadcast({"type": "safety_warning", "payload": {"task_id": task.id, "flags": flags, "policy": policy}})
                # In strict mode, block tasks containing credentials
                if policy == "strict" and scan["credentials"]:
                    task.status = TaskStatus.ERROR
                    task.error = "Blocked by safety policy: credentials detected in prompt. Remove credentials and retry, or switch to 'guarded' policy mode."
                    self._running -= 1
                    self._save_task_to_db(task)
                    if self._broadcast:
                        await self._broadcast({"type": "task_update", "payload": task.model_dump(mode="json")})
                    return
        except Exception as e:
            logging.warning("Safety scan error: %s", e)

        # ── Inject personality + memory context into task ────────────────
        try:
            personality_ctx = get_personality().get_system_context()
            if personality_ctx.strip():
                # Store context separately so engines can use it as system prompt OR prepend
                task._personality_context = personality_ctx
                logging.info("Injected personality/memory context (%d chars) into task %s", len(personality_ctx), task.id[:8])
            else:
                task._personality_context = ""
        except Exception as e:
            logging.warning("Failed to load personality context: %s", e)
            task._personality_context = ""

        engine = self._engine_for(task.engine, prompt=task.prompt)
        if not engine:
            task.status = TaskStatus.ERROR
            task.error = "No engine available"
        else:
            task.engine = engine.name
            get_audit().log(AuditEvent(task_id=task.id, event_type="task_started", detail=engine.display_name))
            # ── Reset live view for visual engines ────────────────────
            if self._broadcast and engine.name in (EngineName.BROWSER_USE, EngineName.COMPUTER_USE):
                await self._broadcast({"type": "live_view_clear", "payload": {"task_id": task.id, "engine": engine.display_name}})
            # ── Execute with retry + engine fallback logic ────────────
            max_retries = get_settings().max_task_retries
            base_delay = get_settings().retry_base_delay
            attempt = 0
            tried_engines: list[EngineName] = []  # track engines we've already tried
            while True:
                try:
                    task = await engine.run_task(task)
                except asyncio.CancelledError:
                    task.status = TaskStatus.CANCELLED
                    task.error = None
                    logging.info("Task %s cancelled", task.id)
                    break
                except Exception as run_err:
                    task.status = TaskStatus.ERROR
                    task.error = safety_redact(str(run_err))[:500]
                    logging.error("Task %s engine error: %s", task.id[:8], run_err)

                # ── Detect web-search soft failures ───────────────────
                # OpenClaw may return 200 OK with "I need a Brave Search API key" in the content.
                # Detect this and treat as a failure eligible for engine fallback.
                web_search_soft_fail = False
                if task.status == TaskStatus.COMPLETE and task.result and task.result.summary:
                    summary_lower = task.result.summary.lower()
                    if any(pat in summary_lower for pat in WEB_SEARCH_FAILURE_PATTERNS):
                        web_search_soft_fail = True
                        logging.info("Task %s: web search soft failure detected in result from %s",
                                     task.id[:8], engine.display_name)

                # ── Engine fallback: try a different engine ───────────
                if web_search_soft_fail or task.status == TaskStatus.ERROR:
                    tried_engines.append(engine.name)
                    fallback_engine = self._engine_for(task.engine, prompt=task.prompt, exclude=tried_engines)
                    if fallback_engine and fallback_engine.name not in tried_engines:
                        old_name = engine.display_name
                        engine = fallback_engine
                        task.engine = engine.name
                        task.status = TaskStatus.RUNNING
                        task.error = None
                        task.result = None
                        logging.info("Task %s: engine fallback %s → %s", task.id[:8], old_name, engine.display_name)
                        get_audit().log(AuditEvent(task_id=task.id, event_type="engine_fallback",
                                                   detail=f"{old_name} → {engine.display_name}"))
                        if self._broadcast:
                            await self._broadcast({"type": "engine_fallback", "payload": {
                                "task_id": task.id, "from": old_name, "to": engine.display_name,
                            }})
                            if engine.name in (EngineName.BROWSER_USE, EngineName.COMPUTER_USE):
                                await self._broadcast({"type": "live_view_clear", "payload": {"task_id": task.id, "engine": engine.display_name}})
                            await self._broadcast({"type": "task_update", "payload": task.model_dump(mode="json")})
                        continue

                # ── Standard retry (same engine) ──────────────────────
                if task.status == TaskStatus.ERROR and attempt < max_retries:
                    attempt += 1
                    delay = base_delay * (2 ** (attempt - 1))  # exponential backoff: 2s, 4s, 8s...
                    logging.info("Task %s failed (attempt %d/%d), retrying in %.1fs: %s",
                                 task.id[:8], attempt, max_retries + 1, delay, task.error)
                    get_audit().log(AuditEvent(task_id=task.id, event_type="task_retry",
                                               detail=f"Attempt {attempt + 1}/{max_retries + 1} after {delay:.0f}s delay: {task.error[:100]}"))
                    if self._broadcast:
                        await self._broadcast({"type": "task_update", "payload": {
                            **task.model_dump(mode="json"),
                            "status": "retrying",
                            "_retry_attempt": attempt,
                            "_retry_max": max_retries + 1,
                            "_retry_delay": delay,
                        }})
                    await asyncio.sleep(delay)
                    task.status = TaskStatus.RUNNING
                    task.error = None
                    continue
                break  # success, cancelled, or max retries exhausted

            get_audit().log(AuditEvent(task_id=task.id, event_type="task_completed" if task.status == TaskStatus.COMPLETE else "task_cancelled" if task.status == TaskStatus.CANCELLED else "task_error", detail=task.error or "ok"))
            # ── Auto-log task to daily memory ────────────────────────────
            try:
                status_str = task.status.value if hasattr(task.status, 'value') else str(task.status)
                retry_note = f" (after {attempt + 1} attempts)" if attempt > 0 else ""
                fallback_note = f" (fallback from {tried_engines[0].value})" if tried_engines and engine.name != tried_engines[0] else ""
                summary = safety_redact(original_prompt[:120].replace('\n', ' '))
                result_preview = ""
                if task.result and task.result.summary:
                    result_preview = f" → {safety_redact(task.result.summary[:80].replace(chr(10), ' '))}"
                get_personality().append_memory(
                    f"Task [{status_str}] via {engine.display_name}{fallback_note}{retry_note}: {summary}{result_preview}",
                    daily=True
                )
            except Exception as e:
                logging.warning("Failed to auto-log task to memory: %s", e)

        self._running -= 1
        self._futures.pop(task.id, None)
        self._save_task_to_db(task)
        if self._broadcast:
            await self._broadcast({"type": "task_update", "payload": task.model_dump(mode="json")})

    async def remote_bridge_loop(self):
        """Background loop to poll for remote tasks from clawbridge.ai or custom URL."""
        if not Settings.remote_bridge_url:
            logging.info("Remote Bridge URL not set, skipping polling.")
            return

        logging.info(f"Starting Remote Bridge polling for Machine ID: {get_machine_id()}")
        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{Settings.remote_bridge_url}/api/bridge/tasks",
                        headers={
                            "X-Machine-ID": get_machine_id(),
                            "Authorization": f"Bearer {Settings.remote_auth_token}"
                        },
                        timeout=30
                    )
                    if resp.status_code == 200:
                        tasks_data = resp.json()
                        for t_data in tasks_data:
                            task = Task(
                                id=str(uuid.uuid4()),
                                prompt=t_data["prompt"],
                                engine=EngineName(t_data.get("engine", "auto")),
                                created_at=datetime.utcnow(),
                                updated_at=datetime.utcnow()
                            )
                            await self.submit(task)
            except Exception as e:
                logging.debug(f"Remote Bridge poll failed: {e}")
            
            await asyncio.sleep(10) # Poll every 10 seconds

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        def _sort_key(t: Task):
            dt = t.created_at
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        return sorted(self._tasks.values(), key=_sort_key, reverse=True)

    async def clear_tasks(self) -> int:
        """Remove all non-running tasks and clear them from the DB. Returns count removed."""
        to_remove = [tid for tid, t in self._tasks.items() if t.status not in (TaskStatus.RUNNING,)]
        for tid in to_remove:
            fut = self._futures.pop(tid, None)
            if fut:
                fut.cancel()
            del self._tasks[tid]
        # Clear DB
        try:
            conn = sqlite3.connect(Settings.db_path)
            conn.execute("DELETE FROM tasks WHERE status != 'running'")
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Failed to clear tasks from DB: {e}")
        return len(to_remove)

    async def engine_infos(self) -> list[dict]:
        return [await e.get_info() for e in self._engines.values()]

    async def pause(self, task_id: str) -> Task | None:
        t = self._tasks.get(task_id)
        if t and t.status == TaskStatus.RUNNING:
            fut = self._futures.get(task_id)
            if fut:
                fut.cancel()
            t.status = TaskStatus.PAUSED
            t.updated_at = datetime.utcnow()
        return t

    async def cancel(self, task_id: str) -> Task | None:
        t = self._tasks.get(task_id)
        if t and t.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED):
            # Signal the engine to stop gracefully
            if t.engine in self._engines:
                eng = self._engines[t.engine]
                if hasattr(eng, 'request_cancel'):
                    eng.request_cancel()
            fut = self._futures.get(task_id)
            if fut:
                fut.cancel()
            t.status = TaskStatus.CANCELLED
            t.updated_at = datetime.utcnow()
        return t

_manager: TaskManager | None = None

def get_manager() -> TaskManager:
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager

# ---------------------------------------------------------------------------
# Embedded dashboard (HTML + CSS + JS in one response)
# ---------------------------------------------------------------------------

def _dashboard_html() -> str:
    # Inline CSS (enhanced for chat-like experience)
    css = """
:root{--bg:#0f1117;--card:#1e2130;--border:#2d3148;--text:#e4e6f0;--fg:#e4e6f0;--muted:#a0aec0;--accent:#6366f1;--ok:#22c55e;--err:#ef4444;--warn:#f59e0b;}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{overflow:hidden;width:100%;height:100%;}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column;}
*::-webkit-scrollbar{width:6px;height:0px;}
*::-webkit-scrollbar-track{background:transparent;}
*::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.15);border-radius:3px;}
*::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.25);}
.header{display:flex;justify-content:space-between;align-items:center;padding:12px 24px;border-bottom:1px solid var(--border);flex-shrink:0;}
.logo{font-weight:700;color:var(--accent);font-size:1.2rem;}
/* Layout & Sidebars */
.layout{display:grid;grid-template-columns:300px 1fr;gap:0;flex:1;overflow:hidden;max-width:100%;transition:grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);}
.layout.left-collapsed{grid-template-columns:52px 1fr;}

aside{border-right:1px solid var(--border);padding:16px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;position:relative;transition:all 0.3s;}

.collapsed-icons{display:none;flex-direction:column;align-items:center;gap:12px;padding-top:16px;}
aside.collapsed .collapsed-icons{display:flex;}
aside.collapsed .card, aside.collapsed .btn, aside.collapsed h2, aside.collapsed .sidebar-section-label, aside.collapsed .sidebar-nav-item{display:none;}
.sidebar-section-label{font-size:9px;text-transform:uppercase;color:rgba(160,174,192,0.5);letter-spacing:1.2px;font-weight:700;margin:14px 0 6px 4px;}
.sidebar-section-label:first-of-type{margin-top:0;}
.sidebar-nav-item{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600;color:var(--muted);transition:all 0.15s;position:relative;}
.sidebar-nav-item:hover{background:rgba(255,255,255,0.05);color:var(--text);}
.sidebar-nav-item.active{background:rgba(99,102,241,0.12);color:var(--accent);}
.sidebar-nav-item .icon-svg{width:14px;height:14px;flex-shrink:0;}
.nav-badge{background:var(--accent);color:#fff;font-size:9px;font-weight:700;padding:2px 5px;border-radius:10px;min-width:16px;text-align:center;line-height:1;margin-left:auto;}
aside.collapsed{padding:10px;overflow:hidden;min-width:52px;}

.toggle-btn{background:none;border:none;color:var(--muted);cursor:pointer;padding:8px;z-index:10;transition:color 0.2s;display:flex;align-items:center;justify-content:center;border-radius:8px;}
.toggle-btn:hover{color:var(--accent);background:rgba(255,255,255,0.05);}
.toggle-btn svg{width:20px;height:20px;}
aside.collapsed .toggle-btn svg{transform:rotate(180deg);}

/* Expandable sidebar sections */
.expandable-header{cursor:pointer;user-select:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0;}
.expandable-header:hover{color:var(--accent);}
.expandable-header .chevron{width:14px;height:14px;color:var(--muted);transition:transform 0.2s;}
.expandable-header .chevron.collapsed{transform:rotate(-90deg);}
.expandable-content{overflow:hidden;transition:max-height 0.25s ease;max-height:600px;}
.expandable-content.collapsed{max-height:0 !important;overflow:hidden;padding-top:0 !important;margin-top:0 !important;padding-bottom:0 !important;margin-bottom:0 !important;}
.card.expandable .expandable-content:not(.collapsed){margin-top:12px;}
.card.expandable{padding:12px 16px;}

.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;}
.card h2{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
.icon-svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;}
.sidebar-icon-large{width:20px;height:20px;color:var(--muted);cursor:pointer;transition:color 0.2s;}
.sidebar-icon-large:hover{color:var(--accent);}
textarea,select,input{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:10px 14px;font-size:14px;outline:none;transition:border-color 0.2s,box-shadow 0.2s;}
textarea:focus,select:focus,input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(99,102,241,0.15);}
select{width:auto !important;min-width:0;padding:8px 32px 8px 12px;font-size:13px;font-weight:500;border-radius:10px;cursor:pointer;appearance:none;-webkit-appearance:none;background:var(--bg) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23a0aec0' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E") no-repeat right 10px center;}
select option{background:#1e2130;color:#e4e6f0;padding:8px 12px;}
textarea{min-height:44px;max-height:120px;resize:none;line-height:1.4;flex:1;}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:10px 20px;border:none;border-radius:10px;font-weight:600;font-size:14px;cursor:pointer;background:var(--accent);color:#fff;transition:all 0.2s;white-space:nowrap;}
.mode-btn{flex-direction:column;align-items:center;background:#2d3748;border:1px solid var(--border);transition:all 0.2s;}.mode-btn:hover{background:rgba(99,102,241,0.15);}
.btn:hover{opacity:.9;transform:translateY(-1px);box-shadow:0 4px 12px rgba(99,102,241,0.3);}
.btn:active{transform:translateY(0);}
.btn:disabled{background:var(--muted);cursor:not-allowed;transform:none;box-shadow:none;}

/* Chat Area */
main{display:flex;flex-direction:column;height:100%;overflow:hidden;max-width:100%;background:rgba(0,0,0,0.2);}
.chat-header{padding:10px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-shrink:0;}
.task-list{flex:1;overflow-y:auto;overflow-x:hidden;padding:16px 0;display:flex;flex-direction:column;gap:0;}
.input-area{padding:12px 20px 16px;background:var(--bg);border-top:1px solid var(--border);flex-shrink:0;}
.input-container{display:flex;gap:8px;align-items:flex-end;max-width:800px;margin:0 auto;width:100%;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:6px;transition:border-color 0.2s,box-shadow 0.2s;}
.input-container:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px rgba(99,102,241,0.1);}
.input-container select{border:1px solid var(--border);background:var(--bg) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' fill='%23a0aec0' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E") no-repeat right 8px center;padding:8px 28px 8px 10px;font-size:12px;font-weight:600;border-radius:8px;color:var(--text);letter-spacing:0.3px;}
.input-container select:focus{box-shadow:none;outline:none;border-color:var(--accent);}
.input-container select option{background:#1e2130;color:#e4e6f0;padding:8px 12px;font-weight:500;}
.input-container textarea{border:none;background:transparent;padding:8px 8px;min-height:36px;border-radius:0;font-size:14px;}
.input-container textarea:focus{box-shadow:none;border:none;}
.input-container .btn{border-radius:10px;padding:8px 18px;font-size:13px;flex-shrink:0;}

/* Chat message groups - like Claude/ChatGPT */
.msg-group{max-width:800px;margin:0 auto;width:100%;padding:0 24px;}
.msg-user{padding:16px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
.msg-user-bubble{display:flex;justify-content:flex-end;}
.msg-user-inner{background:var(--accent);color:#fff;padding:10px 16px;border-radius:18px 18px 4px 18px;max-width:75%;font-size:14px;line-height:1.5;word-break:break-word;}
.msg-assistant{padding:16px 0;border-bottom:1px solid rgba(255,255,255,0.04);position:relative;}
.msg-info-wrap{position:relative;display:inline-block;margin-bottom:6px;}
.msg-info-btn{width:18px;height:18px;border-radius:50%;border:1.5px solid rgba(255,255,255,0.15);background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:10px;font-weight:700;font-style:italic;font-family:Georgia,serif;transition:all 0.2s;line-height:1;}
.msg-info-btn:hover{border-color:var(--accent);color:var(--accent);background:rgba(99,102,241,0.08);}
.msg-info-btn.status-running{border-color:rgba(245,158,11,0.5);color:#f59e0b;animation:pulse 1.5s ease-in-out infinite;}
.msg-info-btn.status-error{border-color:rgba(239,68,68,0.4);color:var(--err);}
.msg-info-tip{display:none;position:absolute;left:24px;top:-4px;background:var(--card);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:10px 14px;font-size:11px;color:var(--text);white-space:nowrap;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,0.4);min-width:160px;}
.msg-info-wrap:hover .msg-info-tip,.msg-info-wrap:focus-within .msg-info-tip{display:block;}
.msg-info-tip .tip-row{display:flex;justify-content:space-between;gap:16px;padding:2px 0;}
.msg-info-tip .tip-label{color:var(--muted);}
.msg-info-tip .tip-val{font-weight:600;}
.msg-info-tip .tip-val.status-running{color:#f59e0b;}
.msg-info-tip .tip-val.status-complete{color:var(--ok);}
.msg-info-tip .tip-val.status-error{color:var(--err);}
.msg-info-tip .tip-val.status-cancelled,.msg-info-tip .tip-val.status-pending{color:var(--muted);}
.msg-info-tip .tip-val.status-retrying{color:#f59e0b;}
.msg-info-tip .tip-divider{border-top:1px solid rgba(255,255,255,0.06);margin:4px 0;}
.msg-icon-row{display:flex;align-items:center;gap:6px;margin-bottom:6px;}
.msg-icon-btn{width:18px;height:18px;border-radius:50%;border:1.5px solid rgba(255,255,255,0.1);background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--muted);transition:all 0.2s;padding:0;}
.msg-icon-btn:hover{border-color:var(--accent);color:var(--accent);background:rgba(99,102,241,0.08);}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.5;}}
@keyframes msgSlideUp{0%{opacity:0;transform:translateY(18px);}60%{opacity:1;transform:translateY(-2px);}100%{opacity:1;transform:translateY(0);}}
.msg-group.msg-enter{animation:msgSlideUp 0.35s cubic-bezier(0.16,1,0.3,1) both;}
.msg-assistant.msg-enter{animation:msgSlideUp 0.35s cubic-bezier(0.16,1,0.3,1) 0.05s both;}
.msg-body{font-size:14px;line-height:1.6;color:var(--text);word-break:break-word;overflow-wrap:break-word;}
.msg-body h1,.msg-body h2,.msg-body h3{color:var(--text);margin:12px 0 6px;font-weight:600;}
.msg-body h1{font-size:1.4em;border-bottom:1px solid var(--border);padding-bottom:4px;}
.msg-body h2{font-size:1.2em;}
.msg-body h3{font-size:1.05em;}
.msg-body code{background:rgba(99,102,241,0.1);padding:2px 6px;border-radius:4px;font-family:monospace;font-size:0.9em;color:var(--accent);}
.msg-body pre{background:rgba(0,0,0,0.3);padding:12px;border-radius:8px;overflow-x:auto;margin:10px 0;border:1px solid var(--border);}
.msg-body pre code{background:none;padding:0;color:var(--text);}
.msg-body ul,.msg-body ol{margin:8px 0 8px 20px;}
.msg-body li{margin:4px 0;line-height:1.6;}
.msg-body strong{font-weight:600;color:var(--text);}
.msg-body em{font-style:italic;}
.msg-body a{color:var(--accent);text-decoration:underline;text-decoration-style:dotted;}
.msg-body a:hover{text-decoration-style:solid;}
.msg-body blockquote{border-left:3px solid var(--accent);padding-left:12px;margin:10px 0;color:var(--muted);font-style:italic;}
.msg-body hr{border:none;border-top:1px solid var(--border);margin:12px 0;}
.msg-body table{border-collapse:collapse;width:100%;margin:10px 0;}
.msg-body th,.msg-body td{border:1px solid var(--border);padding:6px 10px;text-align:left;}
.msg-body th{background:rgba(99,102,241,0.1);font-weight:600;}
.msg-body p{margin:6px 0;}
.msg-actions{margin-top:8px;}
.msg-actions .btn{padding:4px 12px;font-size:11px;}
.msg-error{margin-top:8px;padding:8px 12px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.2);border-radius:8px;color:var(--err);font-size:13px;word-break:break-word;}
.step-stream{margin-top:4px;transition:all 0.3s ease;}

.activity-feed{font-size:11px;}
.activity-item{padding:8px 10px;background:rgba(255,255,255,0.02);border-radius:8px;margin-bottom:6px;border-left:3px solid var(--border);transition:background 0.15s;}
.activity-item:hover{background:rgba(255,255,255,0.04);}
.activity-item.ev-task_completed,.activity-item.ev-complete{border-left-color:var(--ok);}
.activity-item.ev-task_failed,.activity-item.ev-error,.activity-item.ev-safety_flag{border-left-color:var(--err);}
.activity-item.ev-task_retry,.activity-item.ev-install,.activity-item.ev-warning,.activity-item.ev-safety{border-left-color:var(--warn);}
.activity-item.ev-task_created,.activity-item.ev-task_started,.activity-item.ev-step{border-left-color:var(--accent);}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--muted);display:inline-block;flex-shrink:0;}
.status-dot.connected{background:var(--ok);}
.status-dot.error{background:var(--err);}
.muted{color:var(--muted);}
.system-health{position:relative;font-size:12px;display:flex;align-items:center;gap:8px;cursor:pointer;padding:6px 12px;border-radius:8px;transition:background 0.2s;}
.system-health:hover{background:rgba(255,255,255,0.05);}
.system-health-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;transition:background 0.3s;}
.system-health-dot.sh-ok{background:var(--ok);}
.system-health-dot.sh-warn{background:var(--warn);}
.system-health-dot.sh-err{background:var(--err);}
.system-health-dropdown{display:none;position:absolute;top:100%;right:0;margin-top:8px;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;min-width:220px;box-shadow:0 8px 24px rgba(0,0,0,0.4);z-index:100;}
.system-health:hover .system-health-dropdown,.system-health:focus-within .system-health-dropdown{display:block;}
.health-row{display:flex;justify-content:space-between;padding:6px 0;font-size:11px;border-bottom:1px solid rgba(255,255,255,0.05);}
.health-row:last-child{border-bottom:none;}
.health-label{color:var(--muted);}
.health-value{font-weight:600;}
.health-value.h-ok{color:var(--ok);}.health-value.h-warn{color:var(--warn);}.health-value.h-err{color:var(--err);}
.config-chip{display:inline-block;padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;letter-spacing:0.3px;}
.config-chip.configured{background:rgba(34,197,94,0.15);color:var(--ok);border:1px solid rgba(34,197,94,0.2);}
.config-chip.not-set{background:rgba(160,174,192,0.08);color:var(--muted);border:1px solid rgba(160,174,192,0.15);}
.config-provider-primary{font-size:13px;font-weight:600;color:var(--accent);margin-bottom:12px;padding:8px 12px;background:rgba(99,102,241,0.08);border-radius:8px;border:1px solid rgba(99,102,241,0.15);}
.config-chip.clickable-chip{cursor:pointer;transition:all 0.15s;}
.config-chip.clickable-chip:hover{background:rgba(99,102,241,0.15);color:var(--accent);border-color:rgba(99,102,241,0.3);}
.config-provider-row{border-bottom:1px solid rgba(255,255,255,0.03);}
.config-provider-row:last-child{border-bottom:none;}
.history-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px;}
.history-table{width:100%;border-collapse:collapse;font-size:12px;}
.history-table thead{background:rgba(99,102,241,0.08);border-bottom:2px solid var(--border);}
.history-table th{text-align:left;padding:10px 12px;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:var(--muted);}
.history-table tbody tr{border-bottom:1px solid rgba(255,255,255,0.03);cursor:pointer;transition:background 0.15s;}
.history-table tbody tr:hover{background:rgba(99,102,241,0.05);}
.history-table td{padding:12px;}
.history-badge{display:inline-block;padding:3px 8px;border-radius:6px;font-size:10px;font-weight:600;text-transform:uppercase;}
.history-badge.complete{background:rgba(34,197,94,0.15);color:var(--ok);}
.history-badge.error{background:rgba(239,68,68,0.15);color:var(--err);}
.history-badge.running{background:rgba(245,158,11,0.15);color:var(--warn);}
.history-badge.pending,.history-badge.cancelled{background:rgba(160,174,192,0.15);color:var(--muted);}
.history-expanded{background:rgba(99,102,241,0.03)!important;}
.history-detail{padding:16px;border-top:1px solid var(--border);background:rgba(0,0,0,0.2);}
.history-result{font-size:12px;line-height:1.6;max-height:200px;overflow-y:auto;margin-bottom:12px;padding:12px;background:rgba(0,0,0,0.15);border-radius:8px;border:1px solid var(--border);}
.onboarding-card{background:linear-gradient(135deg,rgba(99,102,241,0.08) 0%,rgba(99,102,241,0.02) 100%);border:1px solid rgba(99,102,241,0.2);border-radius:12px;padding:20px;margin:16px 24px;max-width:760px;margin-left:auto;margin-right:auto;transition:all 0.3s;}
.onboarding-item{display:flex;align-items:center;gap:12px;padding:10px 12px;background:rgba(0,0,0,0.15);border-radius:8px;cursor:pointer;transition:all 0.15s;border:1px solid transparent;margin-bottom:8px;}
.onboarding-item:hover{background:rgba(0,0,0,0.25);border-color:rgba(99,102,241,0.3);}
.onboarding-item.done{opacity:0.6;cursor:default;}
.onboarding-item.done:hover{background:rgba(0,0,0,0.15);border-color:transparent;}
.onboarding-check{width:20px;height:20px;border:2px solid var(--border);border-radius:6px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all 0.2s;font-size:14px;font-weight:700;color:transparent;}
.onboarding-item.done .onboarding-check{background:var(--ok);border-color:var(--ok);color:#fff;}
.onboarding-progress-bar{flex:1;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden;}
.onboarding-progress-fill{height:100%;background:var(--ok);transition:width 0.3s;border-radius:2px;}

/* Live View in Sidebar */
.live-view-img-wrap{background:#0a0a0f;border-radius:8px;overflow:hidden;display:flex;align-items:center;justify-content:center;min-height:80px;}
#liveImage{max-width:100%;display:block;border-radius:8px;}
#livePlaceholder{color:var(--muted);font-size:11px;text-align:center;padding:16px;}
#liveImage[src=""]{display:none;}
#liveImage:not([src=""])~#livePlaceholder{display:none;}
@keyframes monitor-pulse{0%,100%{color:var(--ok);}50%{color:rgba(34,197,94,0.3);}}
.monitor-active{animation:monitor-pulse 2s ease-in-out infinite;}

/* View Tabs */
/* view-tab styles removed — views now in sidebar nav */
/* tab-badge/tab-tooltip styles removed — views now use sidebar nav-badge */

/* Soul Tabs */
.soul-tab.active{background:rgba(99,102,241,0.15)!important;color:var(--accent)!important;}
.soul-tab:hover{background:rgba(255,255,255,0.08)!important;color:var(--text)!important;}
/* License Badge */
.license-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;vertical-align:middle;margin-left:8px;text-transform:uppercase;letter-spacing:0.5px;}
.license-badge.pro{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;}
.license-badge.byok{background:#374151;color:#9ca3af;}
.license-badge.free{background:#f59e0b;color:#000;cursor:pointer;}
/* Activation Modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;z-index:1000;backdrop-filter:blur(4px);}
.modal-content{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:32px;max-width:500px;width:90%;max-height:90vh;overflow-y:auto;animation:modalIn 0.2s ease;}
@keyframes modalIn{from{opacity:0;transform:scale(0.95)}to{opacity:1;transform:scale(1)}}
.activation-option{box-sizing:border-box;overflow:hidden;}.activation-option:hover{border-color:var(--accent)!important;background:#374151!important;}
"""
    # Inline JS
    js = """
const state={ws:null,tasks:[],engines:[],connected:false,schedules:[],templates:[],workflows:[],activeView:'chat',wsRetryCount:0,wsRetryMax:20,bridgeActive:false,automationMode:'supervised',recording:false,recordingActions:null,recordingStartTime:null};
function updateSystemHealth(){
  const dot=document.getElementById("healthDot"),txt=document.getElementById("healthText");
  const wsEl=document.getElementById("healthWS"),engEl=document.getElementById("healthEngines"),brEl=document.getElementById("healthBridge");
  if(!dot)return;
  // WS
  if(state.connected){wsEl.textContent="Connected";wsEl.className="health-value h-ok";}
  else if(state.wsRetryCount>0){wsEl.textContent="Reconnecting ("+state.wsRetryCount+")...";wsEl.className="health-value h-warn";}
  else{wsEl.textContent="Disconnected";wsEl.className="health-value h-err";}
  // Bridge
  if(state.bridgeActive){brEl.textContent="Active";brEl.className="health-value h-ok";}
  else{brEl.textContent="Offline";brEl.className="health-value";brEl.style.color="var(--muted)";}
  // Engines
  const avail=state.engines.filter(e=>e.status==="available").length;
  const total=state.engines.length;
  engEl.textContent=avail+" / "+total;
  engEl.className=avail>0?"health-value h-ok":"health-value h-warn";
  // Overall
  if(state.connected&&(state.bridgeActive||avail>0)){dot.className="system-health-dot sh-ok";txt.textContent="Connected";}
  else if(state.connected||state.bridgeActive||avail>0){dot.className="system-health-dot sh-warn";txt.textContent="Partial";}
  else{dot.className="system-health-dot sh-err";txt.textContent="Disconnected";}
}
async function api(method,path,body=null){
  const r=await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):null});
  if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||r.statusText);
  return r.json();
}
function connect(){
  const wsUrl=(location.protocol==="https:"?"wss:":"ws:")+"//"+location.host+"/ws";
  console.log("[ClawBridge] Connecting WebSocket:",wsUrl);
  try{
    state.ws=new WebSocket(wsUrl);
  }catch(e){console.error("[ClawBridge] WebSocket create error:",e);return;}
  state.ws.onopen=()=>{
    console.log("[ClawBridge] WebSocket connected");
    state.connected=true;state.wsRetryCount=0;
    updateSystemHealth();
  };
  state.ws.onclose=(ev)=>{
    console.log("[ClawBridge] WebSocket closed, code:",ev.code,"reason:",ev.reason);
    state.connected=false;
    if(state.wsRetryCount<state.wsRetryMax){
      state.wsRetryCount++;
      const delay=Math.min(3000*Math.pow(1.5,state.wsRetryCount-1),60000);
      updateSystemHealth();
      setTimeout(connect,delay);
    }else{
      updateSystemHealth();
    }
  };
  state.ws.onerror=(ev)=>{console.error("[ClawBridge] WebSocket error:",ev);};
  state.ws.onmessage=e=>{
    try{
      const m=JSON.parse(e.data);
      if(m.type==="task_update")upsert(m.payload);
      else if(m.type==="task_list"){state.tasks=m.payload;settleAll(m.payload);render();}
      else if(m.type==="engine_status"){state.engines=m.payload;renderEngines();}
      else if(m.type==="audit_event")addActivity(m.payload);
      else if(m.type==="live_view")updateLiveView(m.payload);
      else if(m.type==="live_view_clear")clearLiveView(m.payload);
      else if(m.type==="engine_fallback")addActivity({timestamp:new Date().toISOString(),event_type:"engine_fallback",detail:m.payload.from+" → "+m.payload.to});
      else if(m.type==="step_update")handleStepUpdate(m.payload);
      else if(m.type==="safety_warning")handleSafetyWarning(m.payload);
      else if(m.type==="install_progress")addActivity({timestamp:new Date().toISOString(),event_type:"install",detail:m.payload.engine+": "+m.payload.message});
      else if(m.type==="tasks_cleared"){state.tasks=[];render();}
      else if(m.type==="schedule_update"){state.schedules=m.payload;renderSchedules();updateTabBadges();}
      else if(m.type==="template_update"){state.templates=m.payload;renderTemplates();}
      else if(m.type==="approval_request"){showApprovalModal(m.payload);}
      else if(m.type==="config_update"){if(m.payload.automation_mode){state.automationMode=m.payload.automation_mode;updateAutomationModeUI();}}
      else if(m.type==="workflow_update"){state.workflows=m.payload;renderWorkflows();updateTabBadges();}
      else if(m.type==="recording_status"){handleRecordingStatus(m.payload);}
      else if(m.type==="recording_result"){handleRecordingResult(m.payload);}
      else if(m.type==="workflow_saved"){addActivity({timestamp:new Date().toISOString(),event_type:"workflow",detail:"Saved workflow: "+(m.payload.name||"")});}
      else if(m.type==="replay_started"){addActivity({timestamp:new Date().toISOString(),event_type:"replay",detail:"Replaying workflow: "+(m.payload.workflow||"")});}
    }catch(err){console.error("[ClawBridge] WS message parse error:",err);}
  };
}
let _liveTimer=null;
function clearLiveView(p){
  const i=document.getElementById("liveImage");
  const ph=document.getElementById("livePlaceholder");
  const st=document.getElementById("liveStatus");
  const icon=document.getElementById("monitorIcon");
  if(i){i.src="";i.style.display="none";}
  if(ph)ph.style.display="flex";
  if(st){st.textContent="Starting "+(p&&p.engine||"task")+"...";st.style.color="var(--accent)";}
  if(icon)icon.classList.remove("monitor-active");
  clearTimeout(_liveTimer);
}
function updateLiveView(p){
  if(!p||!p.image)return;
  const i=document.getElementById("liveImage");
  const ph=document.getElementById("livePlaceholder");
  const st=document.getElementById("liveStatus");
  const icon=document.getElementById("monitorIcon");
  i.src="data:image/png;base64,"+p.image;
  i.style.display="block";
  if(ph)ph.style.display="none";
  if(st){st.textContent="Streaming";st.style.color="var(--ok)";}
  if(icon)icon.classList.add("monitor-active");
  localStorage.setItem("last_browser_session",new Date().toISOString());
  // Auto-expand the liveview section if collapsed
  const content=document.getElementById("liveviewContent");
  if(content&&content.classList.contains("collapsed")){
    toggleSection("liveview");
  }
  // Reset idle timer - collapse after 10s of no frames
  clearTimeout(_liveTimer);
  _liveTimer=setTimeout(()=>{
    if(st){st.textContent="Idle";st.style.color="var(--muted)";}
    if(icon)icon.classList.remove("monitor-active");
    showLastSession();
  },10000);
}
function showLastSession(){
  const el=document.getElementById("lastSessionTime");
  const ts=localStorage.getItem("last_browser_session");
  if(el&&ts){el.textContent="Last session: "+new Date(ts).toLocaleString();}
}
// ── Step-level streaming handler ────────────────────────────────────
function handleStepUpdate(p){
  if(!p||!p.task_id)return;
  // Update the running task's step info in the chat
  const el=document.getElementById("steps-"+p.task_id);
  if(el){
    el.innerHTML='<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:rgba(99,102,241,0.08);border-radius:8px;font-size:12px;margin-top:8px">'
      +'<span style="color:var(--accent);font-weight:600">Step '+p.step+'/'+p.max_steps+'</span>'
      +'<span style="color:var(--muted)">'+esc(p.action||"")+'</span>'
      +(p.reasoning?'<span style="color:var(--muted);font-style:italic;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(p.reasoning.substring(0,120))+'</span>':'')
      +'<span style="color:var(--muted);margin-left:auto;font-size:10px">'+(p.tokens_in+p.tokens_out)+' tokens</span>'
      +'</div>';
  }
  // Also add to activity feed
  addActivity({timestamp:new Date().toISOString(),event_type:"step",detail:"Step "+p.step+"/"+p.max_steps+": "+p.action});
}
// ── Task Replay Viewer ────────────────────────────────────────────
async function showReplay(taskId){
  try{
    const data=await api("GET","/api/tasks/"+taskId+"/steps");
    if(!data.steps||!data.steps.length){alert("No step data recorded for this task.");return;}
    const overlay=document.createElement("div");
    overlay.id="replayOverlay";
    overlay.style.cssText="position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center";
    const modal=document.createElement("div");
    modal.style.cssText="background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:700px;width:90%;max-height:80vh;overflow-y:auto";
    const task=state.tasks.find(t=>t.id===taskId);
    const title=task?task.prompt.substring(0,80):"Task";
    let html='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">'
      +'<h3 style="margin:0;font-size:16px;color:var(--fg)">Replay: '+esc(title)+'</h3>'
      +'<button onclick="document.getElementById(\\'replayOverlay\\').remove()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:18px">&times;</button></div>';
    html+='<div style="font-size:11px;color:var(--muted);margin-bottom:12px">'+data.steps.length+' steps recorded</div>';
    html+='<div style="display:flex;flex-direction:column;gap:8px">';
    data.steps.forEach((s,i)=>{
      const tok=(s.tokens_in||0)+(s.tokens_out||0);
      const tokStr=tok>0?' &middot; '+tok.toLocaleString()+' tok':'';
      const ts=s.timestamp?new Date(s.timestamp).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
      html+='<div style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.12);border-radius:8px;padding:10px 14px">'
        +'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
        +'<span style="color:var(--accent);font-weight:600;font-size:12px">Step '+s.step+'/'+s.max_steps+'</span>'
        +'<span style="color:var(--fg);font-size:12px;font-weight:500">'+esc(s.action||"unknown")+'</span>'
        +'<span style="color:var(--muted);font-size:10px;margin-left:auto">'+ts+tokStr+'</span>'
        +'</div>';
      if(s.reasoning){
        html+='<div style="color:var(--muted);font-size:11px;font-style:italic;margin-top:4px;line-height:1.4">'+esc(s.reasoning.substring(0,300))+'</div>';
      }
      if(s.detail&&s.detail!=='{}'){
        html+='<div style="color:var(--muted);font-size:10px;margin-top:4px;font-family:monospace;background:rgba(0,0,0,0.15);padding:4px 8px;border-radius:4px;overflow-x:auto">'+esc(s.detail.substring(0,200))+'</div>';
      }
      html+='</div>';
    });
    html+='</div>';
    modal.innerHTML=html;
    overlay.appendChild(modal);
    overlay.addEventListener("click",e=>{if(e.target===overlay)overlay.remove();});
    document.body.appendChild(overlay);
  }catch(e){console.error("Replay error:",e);alert("Failed to load replay data.");}
}
function handleSafetyWarning(p){
  if(!p)return;
  const flags=(p.flags||[]).join(", ");
  addActivity({timestamp:new Date().toISOString(),event_type:"safety",detail:"⚠ Safety: "+flags+" (policy: "+p.policy+")"});
}
// ── Approval Modal (Supervised Mode) ──────────────────────────────────
function showApprovalModal(p){
  if(!p||!p.request_id)return;
  addActivity({timestamp:new Date().toISOString(),event_type:"approval",detail:"⏸ Approval needed: "+p.action});

  // Remove any existing approval modal
  const existing=document.getElementById("approvalOverlay");
  if(existing)existing.remove();

  // Create overlay
  const overlay=document.createElement("div");
  overlay.id="approvalOverlay";
  overlay.style.cssText="position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:10000;display:flex;align-items:center;justify-content:center";

  // Create modal
  const modal=document.createElement("div");
  modal.style.cssText="background:var(--bg);border:2px solid #f59e0b;border-radius:16px;padding:28px;max-width:480px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.5)";

  const details=p.details||{};
  const urlInfo=details.url?'<div style="margin-top:8px;padding:8px 12px;background:rgba(255,255,255,0.05);border-radius:6px;font-family:monospace;font-size:11px;color:var(--muted);word-break:break-all">'+esc(details.url)+'</div>':'';
  const contextInfo=details.context?'<div style="margin-top:8px;font-size:12px;color:var(--muted);line-height:1.5">'+esc(details.context.substring(0,200))+'</div>':'';

  modal.innerHTML=
    '<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">'
    +'<div style="width:48px;height:48px;border-radius:50%;background:rgba(245,158,11,0.15);display:flex;align-items:center;justify-content:center;flex-shrink:0">'
    +'<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'
    +'</div>'
    +'<div>'
    +'<h3 style="margin:0;font-size:18px;font-weight:600;color:var(--fg)">Approval Required</h3>'
    +'<div style="font-size:12px;color:var(--muted);margin-top:2px">Supervised Mode</div>'
    +'</div>'
    +'</div>'
    +'<div style="margin-bottom:20px">'
    +'<div style="font-size:14px;color:var(--fg);font-weight:500;margin-bottom:6px">The agent wants to:</div>'
    +'<div style="font-size:15px;color:#f59e0b;font-weight:600;padding:12px 16px;background:rgba(245,158,11,0.1);border-radius:8px;border-left:3px solid #f59e0b">'+esc(p.action)+'</div>'
    +urlInfo
    +contextInfo
    +'</div>'
    +'<div style="font-size:12px;color:var(--muted);margin-bottom:20px;padding:10px 14px;background:rgba(99,102,241,0.08);border-radius:8px">'
    +'<strong>Reason:</strong> '+esc(p.reason)
    +'</div>'
    +'<div style="display:flex;gap:12px">'
    +'<button onclick="sendApprovalResponse(\\''+p.request_id+'\\',false)" style="flex:1;padding:14px;border:1px solid var(--border);border-radius:10px;background:#2d3748;color:var(--fg);font-size:14px;font-weight:600;cursor:pointer;transition:all 0.15s" onmouseenter="this.style.background=\\'rgba(239,68,68,0.2)\\';this.style.borderColor=\\'var(--err)\\'" onmouseleave="this.style.background=\\'#2d3748\\';this.style.borderColor=\\'var(--border)\\'">Deny</button>'
    +'<button onclick="sendApprovalResponse(\\''+p.request_id+'\\',true)" style="flex:1;padding:14px;border:none;border-radius:10px;background:var(--ok);color:#fff;font-size:14px;font-weight:600;cursor:pointer;transition:all 0.15s" onmouseenter="this.style.opacity=\\'0.85\\'" onmouseleave="this.style.opacity=\\'1\\'">Approve</button>'
    +'</div>'
    +'<div style="margin-top:16px;font-size:10px;color:var(--muted);text-align:center">Request will timeout in 2 minutes if no response</div>';

  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  // Focus the approve button
  modal.querySelector("button:last-child").focus();
}
function sendApprovalResponse(requestId,approved){
  if(!state.ws||state.ws.readyState!==1)return;
  state.ws.send(JSON.stringify({
    type:"approval_response",
    payload:{request_id:requestId,approved:approved}
  }));
  const overlay=document.getElementById("approvalOverlay");
  if(overlay){
    overlay.style.opacity="0";
    setTimeout(()=>overlay.remove(),200);
  }
  addActivity({timestamp:new Date().toISOString(),event_type:approved?"approved":"denied",detail:(approved?"✓ Approved":"✗ Denied")+": action request"});
}
function toggleSidebar(side){
  const l=document.getElementById("mainLayout");
  const a=l.querySelector('#leftSidebar');
  l.classList.toggle('left-collapsed');
  a.classList.toggle('collapsed');
  localStorage.setItem('sidebar_left', a.classList.contains('collapsed'));
}
function toggleSection(id){
  const card=document.getElementById('card-'+id);
  const content=document.getElementById(id+'Content');
  const chevron=card.querySelector('.chevron');
  const collapsed=content.classList.toggle('collapsed');
  chevron.classList.toggle('collapsed',collapsed);
  localStorage.setItem('section_'+id, collapsed?'1':'0');
}
function upsert(t){const i=state.tasks.findIndex(x=>x.id===t.id);if(i>=0)state.tasks[i]=t;else state.tasks.push(t);render();}
function scrollToBottom(){const el=document.getElementById("taskList");if(el)requestAnimationFrame(()=>el.scrollTop=el.scrollHeight);}
async function submit(){
  const prompt=document.getElementById("prompt").value.trim();if(!prompt)return;
  const engine=document.getElementById("engine").value;
  const btn=document.getElementById("submitBtn");btn.disabled=true;
  try {
    if(engine==="browser_use")await ensureBrowser();
    await api("POST","/api/tasks",{prompt,engine});
    document.getElementById("prompt").value="";
    document.getElementById("prompt").style.height = "auto";
    scrollToBottom();
    setTimeout(checkOnboarding,500);
  } catch(e) {
    addActivity({timestamp:new Date().toISOString(),event_type:"error",detail:"Task failed: "+e.message});
  } finally {
    btn.disabled=false;
  }
}
async function cancel(id,ev){
  const btn=ev&&ev.target?ev.target.closest('button'):null;
  if(btn){btn.disabled=true;btn.style.background='rgba(239,68,68,0.4)';btn.style.color='#fff';btn.textContent='Stopping...';}
  try{await api("PATCH","/api/tasks/"+id,{action:"cancel"});}catch(e){console.error(e);}
  if(btn){btn.style.background='rgba(160,174,192,0.3)';btn.textContent='Stopped';}
}
async function clearChat(){
  if(!state.tasks.length)return;
  try{await api("DELETE","/api/tasks");state.tasks=[];_settledTaskIds.clear();_settledReplyIds.clear();render();}catch(e){console.error("Clear failed:",e);}
}
function esc(s){if(!s)return"";const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function renderMarkdown(text){
  if(!text)return"";
  if(typeof marked==="undefined")return esc(text);
  try{marked.setOptions({breaks:true,gfm:true});var html=marked.parse(text);return typeof DOMPurify!=="undefined"?DOMPurify.sanitize(html):html;}
  catch(e){console.error("Markdown render error:",e);return esc(text);}
}
let _settledTaskIds=new Set();
let _settledReplyIds=new Set();
function settleAll(tasks){tasks.forEach(t=>{_settledTaskIds.add(t.id);if(t.result||t.error||t.status!=="pending")_settledReplyIds.add(t.id);});}
function render(){
  const c=document.getElementById("taskList");const n=document.getElementById("taskCount");
  // Calculate session totals
  let totalCost=0,totalTokens=0,completedTasks=0;
  state.tasks.forEach(t=>{if(t.result){totalCost+=t.result.estimated_cost_usd||0;totalTokens+=(t.result.tokens_in||0)+(t.result.tokens_out||0);if(t.status==="complete")completedTasks++;}});
  const costStr=totalCost>0?' · $'+totalCost.toFixed(4):'';
  const tokStr=totalTokens>0?' · '+totalTokens.toLocaleString()+' tok':'';
  n.textContent=state.tasks.length+" task(s)"+costStr+tokStr;
  if(!state.tasks.length){c.innerHTML='<p style="color:var(--muted);text-align:center;padding:40px">Send a message to start.</p>';return;}

  const items = [...state.tasks].sort((a,b)=>new Date(a.created_at)-new Date(b.created_at));

  c.innerHTML=items.map(t=>{
    const isNewMsg=!_settledTaskIds.has(t.id);
    const hasReply=(t.result&&t.result.summary)||t.error||t.status!=="pending";
    const isNewReply=hasReply&&!_settledReplyIds.has(t.id);
    if(isNewMsg)setTimeout(()=>_settledTaskIds.add(t.id),400);
    if(isNewReply)setTimeout(()=>_settledReplyIds.add(t.id),400);
    const time=new Date(t.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
    const hasResult=t.result&&t.result.summary;
    const hasError=t.error;
    let ctl="";
    if(t.status==="running")ctl='<div class="msg-actions"><button class="btn" onclick="cancel(\\''+t.id+'\\',event)">Stop</button></div>';

    let assistantHtml="";
    if(hasResult||hasError||t.status!=="pending"){
      // Build tooltip rows
      let tipRows='<div class="tip-row"><span class="tip-label">Status</span><span class="tip-val status-'+t.status+'">'+t.status+'</span></div>'
        +'<div class="tip-row"><span class="tip-label">Engine</span><span class="tip-val">'+esc(t.engine)+'</span></div>'
        +'<div class="tip-row"><span class="tip-label">Time</span><span class="tip-val">'+time+'</span></div>';
      if(t.result&&t.result.tokens_in){
        const ti=t.result.tokens_in;const to=t.result.tokens_out;const c=t.result.estimated_cost_usd;
        const steps=t.result.total_steps||0;const dur=t.result.total_duration_ms||0;
        const durStr=dur>=60000?(dur/60000).toFixed(1)+'m':(dur/1000).toFixed(1)+'s';
        tipRows+='<div class="tip-divider"></div>'
          +'<div class="tip-row"><span class="tip-label">Steps</span><span class="tip-val">'+steps+'</span></div>'
          +'<div class="tip-row"><span class="tip-label">Duration</span><span class="tip-val">'+durStr+'</span></div>'
          +'<div class="tip-row"><span class="tip-label">Tokens</span><span class="tip-val">'+(ti+to).toLocaleString()+'</span></div>'
          +'<div class="tip-row"><span class="tip-label">Cost</span><span class="tip-val">$'+c.toFixed(4)+'</span></div>';
      }
      const btnStatusCls=t.status==="running"?" status-running":t.status==="error"?" status-error":"";
      let inlineIcons='';
      if(t.status==="complete"&&hasResult){
        inlineIcons+='<button class="msg-icon-btn" onclick="copyResult(\\''+t.id+'\\',this)" title="Copy"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>';
        if(t.result&&t.result.total_steps>0)inlineIcons+='<button class="msg-icon-btn" onclick="showReplay(\\''+t.id+'\\')" title="Replay steps"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></button>';
      }
      assistantHtml='<div class="msg-assistant'+(isNewReply?' msg-enter':'')+'" data-reply="'+t.id+'">'
        +'<div class="msg-icon-row"><div class="msg-info-wrap"><button class="msg-info-btn'+btnStatusCls+'" tabindex="0">i</button>'
        +'<div class="msg-info-tip">'+tipRows+'</div></div>'+inlineIcons+'</div>';
      if(hasResult)assistantHtml+='<div class="msg-body">'+renderMarkdown(t.result.summary)+'</div>';
      if(hasError)assistantHtml+='<div class="msg-error">'+esc(t.error)+'</div>';
      // Step streaming container — shows live step info for running tasks
      if(t.status==="running")assistantHtml+='<div id="steps-'+t.id+'" class="step-stream"></div>';
      assistantHtml+=ctl+'</div>';
    }

    return '<div class="msg-group'+(isNewMsg?' msg-enter':'')+'" data-tid="'+t.id+'">'
      +'<div class="msg-user"><div class="msg-user-bubble"><div class="msg-user-inner">'+esc(t.prompt)+'</div></div></div>'
      +assistantHtml
      +'</div>';
  }).join("");
  scrollToBottom();
}
function renderEngines(){
  const c=document.getElementById("engineList");
  if(!state.engines.length){c.innerHTML='<p class="muted">No engines</p>';return;}
  c.innerHTML=state.engines.map(e=>{
    const sc=e.status==="available"?"color:var(--ok)":e.status==="no_api_key"?"color:#f59e0b":e.status==="error"?"color:var(--err)":"color:var(--muted)";
    let extra="";
    if(e.error_hint)extra+='<div style="font-size:10px;color:var(--muted);margin-top:2px">'+esc(e.error_hint)+'</div>';
    if(e.status==="not_installed"&&e.name==="openclaw")extra+='<button class="btn" style="font-size:10px;padding:4px 10px;margin-top:6px" onclick="installEngine(\\'openclaw\\',event)">Install</button>';
    return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03)"><div style="display:flex;justify-content:space-between"><span>'+esc(e.display_name)+'</span><span style="font-weight:600;'+sc+'">'+esc(e.status)+'</span></div>'+extra+'</div>';
  }).join("");
  updateSystemHealth();
}
async function installEngine(name,ev){
  const btn=ev&&ev.target?ev.target:null;if(btn){btn.disabled=true;btn.textContent="Installing...";}
  try{await api("POST","/api/engines/"+name+"/install");}
  catch(e){if(btn){btn.textContent="Retry";btn.disabled=false;}addActivity({timestamp:new Date().toISOString(),event_type:"install_error",detail:name+": "+e.message});}
}
function toggleInlineKey(provider){
  const el=document.getElementById("inline-key-"+provider);
  if(!el)return;
  ["anthropic","openai","openrouter"].forEach(p=>{
    if(p!==provider){const other=document.getElementById("inline-key-"+p);if(other)other.style.display="none";}
  });
  el.style.display=el.style.display==="none"?"block":"none";
  if(el.style.display==="block"){const inp=document.getElementById("key-input-"+provider);if(inp)inp.focus();}
}
async function saveInlineKey(provider){
  const input=document.getElementById("key-input-"+provider);
  const status=document.getElementById("key-status-"+provider);
  const key=input.value.trim();
  if(!key){status.textContent="Enter a key first";status.style.color="var(--err)";return;}
  status.textContent="Saving...";status.style.color="var(--muted)";
  try{
    await api("POST","/api/config/keys",{provider,key});
    status.textContent="Saved!";status.style.color="var(--ok)";
    input.value="";
    refreshConfig();checkOnboarding();
    setTimeout(()=>{status.textContent="";},2000);
  }catch(e){status.textContent=e.message;status.style.color="var(--err)";}
}
async function ensureBrowser(){
  try{
    const s=await api("GET","/api/browser/status");
    if(s.cdp_reachable)return true;
    addActivity({timestamp:new Date().toISOString(),event_type:"browser",detail:"Launching dedicated Chrome window..."});
    await api("POST","/api/browser/launch",{});
    checkBrowserStatus();
    return true;
  }catch(e){
    addActivity({timestamp:new Date().toISOString(),event_type:"browser_error",detail:"Failed to launch Chrome: "+e.message});
    return false;
  }
}
async function launchChrome(){
  if(!confirm("This will close any open Chrome windows and launch a dedicated ClawBridge Chrome profile with debug access.\\n\\nFirst time? You'll need to sign into your accounts once.\\nContinue?"))return;
  const btn=document.getElementById("launchChromeBtn");
  btn.disabled=true;btn.textContent="Closing Chrome & relaunching...";
  try{
    await api("POST","/api/browser/launch",{});
    checkBrowserStatus();
  }catch(e){alert("Failed to launch Chrome: "+e.message);}
  finally{btn.disabled=false;btn.textContent="Launch Chrome (with your logins)";}
}
async function stopChrome(){
  try{await api("POST","/api/browser/stop");}catch(e){}
  checkBrowserStatus();
}
async function checkBrowserStatus(){
  try{
    const s=await api("GET","/api/browser/status");
    const dot=document.getElementById("chromeStatusDot");
    const txt=document.getElementById("chromeStatusText");
    const mode=document.getElementById("chromeModeText");
    const launchBtn=document.getElementById("launchChromeBtn");
    const stopBtn=document.getElementById("stopChromeBtn");
    if(s.cdp_reachable){
      dot.style.background="var(--ok)";
      txt.textContent="Chrome connected (CDP)";txt.style.color="var(--ok)";
      mode.textContent="Tasks will use your signed-in browser";
      launchBtn.style.display="none";stopBtn.style.display="block";
    }else if(s.launched){
      dot.style.background="var(--warn)";
      txt.textContent="Chrome starting...";txt.style.color="var(--warn)";
      mode.textContent="Waiting for debug connection";
      launchBtn.style.display="none";stopBtn.style.display="block";
    }else{
      dot.style.background="var(--muted)";
      txt.textContent="Not connected";txt.style.color="var(--text)";
      mode.textContent=s.mode==="default"?"Using fresh Chromium (no logins)":"";
      launchBtn.style.display="block";stopBtn.style.display="none";
    }
  }catch(e){}
}
function renderConfigSummary(c){
  if(!c||!c.keys)return;
  const k=c.keys;
  let primary="None";
  if(k.openrouter_configured)primary="OpenRouter";
  else if(k.anthropic_configured)primary="Anthropic";
  else if(k.openai_configured)primary="OpenAI";
  function providerRow(name,pkey,isConfigured){
    const chipCls=isConfigured?"config-chip configured":"config-chip not-set clickable-chip";
    const chipText=isConfigured?"Configured":"Click to set";
    return '<div class="config-provider-row">'
      +'<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;cursor:pointer" onclick="toggleInlineKey(\\''+pkey+'\\')">'
      +'<span style="color:var(--muted)">'+esc(name)+'</span>'
      +'<span class="'+chipCls+'">'+chipText+'</span></div>'
      +'<div id="inline-key-'+pkey+'" style="display:none;padding:4px 0 8px">'
      +'<div style="display:flex;gap:6px">'
      +'<input type="password" id="key-input-'+pkey+'" placeholder="Paste '+esc(name)+' API key..." style="flex:1;font-size:12px;padding:6px 10px" onkeydown="if(event.key===\\'Enter\\')saveInlineKey(\\''+pkey+'\\')">'
      +'<button class="btn" style="font-size:11px;padding:6px 12px;white-space:nowrap" onclick="saveInlineKey(\\''+pkey+'\\')">Save</button>'
      +'</div>'
      +'<div id="key-status-'+pkey+'" style="font-size:10px;margin-top:4px"></div></div></div>';
  }
  document.getElementById("configSummary").innerHTML=
    '<div class="config-provider-primary">Active: '+esc(primary)+'</div>'
    +providerRow("Anthropic","anthropic",k.anthropic_configured)
    +providerRow("OpenAI","openai",k.openai_configured)
    +providerRow("OpenRouter","openrouter",k.openrouter_configured);
  // Update Machine ID in health dropdown
  const midEl=document.getElementById("healthMachineId");
  if(midEl&&c.machine_id)midEl.textContent=c.machine_id;
}
function refreshConfig(){
  api("GET","/api/config").then(c=>{
    renderConfigSummary(c);

    // Update remote bridge status
    state.bridgeActive=!!c.remote.configured;
    updateSystemHealth();
    // Show detected Chrome path
    if(c.browser){
      const cei=document.getElementById("chromeExeInfo");
      if(cei&&c.browser.chrome_exe&&c.browser.chrome_exe!=="not found")cei.textContent="Chrome: "+c.browser.chrome_exe;
    }
    // Update automation mode UI
    if(c.automation){
      state.automationMode=c.automation.mode||"supervised";
      updateAutomationModeUI();
    }
    checkBrowserStatus();
  }).catch(e=>{console.error("refreshConfig error:",e);document.getElementById("configSummary").innerHTML='<p class="muted" style="color:var(--err)">Failed to load config</p>';});
}
function updateAutomationModeUI(){
  const supBtn=document.getElementById("modeSupervised");
  const autoBtn=document.getElementById("modeAutonomous");
  const hint=document.getElementById("automationModeHint");
  if(!supBtn||!autoBtn)return;
  const isSupervised=state.automationMode==="supervised";
  supBtn.style.background=isSupervised?"rgba(99,102,241,0.2)":"#2d3748";
  supBtn.style.borderColor=isSupervised?"var(--accent)":"var(--border)";
  autoBtn.style.background=isSupervised?"#2d3748":"rgba(245,158,11,0.15)";
  autoBtn.style.borderColor=isSupervised?"var(--border)":"#f59e0b";
  if(hint){
    hint.innerHTML=isSupervised
      ?'<strong>Supervised:</strong> Pauses before high-risk actions (purchases, form submissions, sensitive sites). Recommended for learning the system.'
      :'<strong style="color:#f59e0b">Autonomous:</strong> Runs without interruption. Monitor the Live View! You are responsible for any actions taken.';
    hint.style.background=isSupervised?"rgba(99,102,241,0.08)":"rgba(245,158,11,0.1)";
  }
}
async function setAutomationMode(mode){
  try{
    await api("POST","/api/config/automation",{mode});
    state.automationMode=mode;
    updateAutomationModeUI();
    addActivity({timestamp:new Date().toISOString(),event_type:"config",detail:"Automation mode set to "+mode});
  }catch(e){
    console.error("Failed to set automation mode:",e);
  }
}
function activityIcon(t){const m={"task_completed":"\\u2713","complete":"\\u2713","task_failed":"\\u2715","error":"\\u2715","safety_flag":"\\u26A0","safety":"\\u26A0","warning":"\\u26A0","task_retry":"\\u21BB","install":"\\u2B07","task_created":"\\u2192","task_started":"\\u25B6","step":"\\u2022"};return m[t]||"\\u00B7";}
function addActivity(ev){
  const c=document.getElementById("activityFeed");
  if(c.querySelector(".muted"))c.innerHTML="";
  const evCls="activity-item ev-"+ev.event_type.replace(/_/g,"_");
  const time=new Date(ev.timestamp).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  // Make task events clickable to open history
  const isTaskEvent=ev.task_id&&ev.event_type.startsWith("task_");
  const clickAttr=isTaskEvent?'onclick="goToHistoryTask(\\''+ev.task_id+'\\')" style="cursor:pointer" title="View in History"':'';
  c.insertAdjacentHTML("afterbegin",
    '<div class="'+evCls+'" '+clickAttr+'>'
    +'<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">'
    +'<span style="font-size:12px">'+activityIcon(ev.event_type)+'</span>'
    +'<span style="font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:0.4px">'+esc(ev.event_type)+'</span>'
    +(isTaskEvent?'<span style="font-size:9px;color:var(--accent);opacity:0.6" title="Click to view in history">\\u2197</span>':'')
    +'<span style="color:rgba(160,174,192,0.6);font-size:9px;margin-left:auto">'+time+'</span>'
    +'</div>'
    +'<div style="color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px">'+esc(ev.detail)+'</div>'
    +'</div>');
  while(c.children.length>50)c.removeChild(c.lastChild);
}
function goToHistoryTask(taskId){
  // Switch to history view and scroll to/highlight the task
  switchView('history');
  renderHistory();
  setTimeout(()=>{
    const row=document.getElementById('hrow-'+taskId);
    if(row){
      row.scrollIntoView({behavior:'smooth',block:'center'});
      row.style.background='rgba(99,102,241,0.15)';
      setTimeout(()=>row.style.background='',2000);
      toggleHistoryRow(taskId);
    }
  },100);
}
// ── Schedule Management ──
function renderSchedules(){
  const c=document.getElementById("scheduleList");
  if(!c)return;
  if(!state.schedules.length){c.innerHTML='<p style="color:var(--muted);font-size:11px">No scheduled tasks</p>';return;}
  c.innerHTML=state.schedules.map(s=>{
    const sc=s.enabled?'color:var(--ok)':'color:var(--muted)';
    const typeLabel=s.schedule_type==='once'?'Once':s.schedule_type==='interval'?'Every '+s.schedule_value:'Cron: '+s.schedule_value;
    const lastRun=s.last_run?new Date(s.last_run).toLocaleString():'Never';
    return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03)">'
      +'<div style="display:flex;justify-content:space-between;align-items:center">'
      +'<span style="font-size:12px;font-weight:600">'+esc(s.name)+'</span>'
      +'<div style="display:flex;gap:4px">'
      +'<button onclick="toggleSchedule(\\''+s.id+'\\','+!s.enabled+')" style="background:none;border:none;cursor:pointer;font-size:10px;padding:2px 6px;border-radius:4px;'+(s.enabled?'color:var(--ok);background:rgba(34,197,94,0.1)':'color:var(--muted);background:rgba(255,255,255,0.05)')+'">'+(s.enabled?'ON':'OFF')+'</button>'
      +'<button onclick="deleteSchedule(\\''+s.id+'\\')" style="background:none;border:none;cursor:pointer;color:var(--err);font-size:10px;padding:2px 4px" title="Delete">✕</button>'
      +'</div></div>'
      +'<div style="font-size:10px;color:var(--muted)">'+typeLabel+' · Runs: '+s.run_count+' · Last: '+lastRun+'</div>'
      +'<div style="font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+esc(s.prompt)+'</div>'
      +'</div>';
  }).join("");
}
async function toggleSchedule(id,enabled){
  try{await api("PATCH","/api/schedules/"+id,{enabled});}catch(e){console.error(e);}
}
async function deleteSchedule(id){
  if(!confirm("Delete this scheduled task?"))return;
  try{await api("DELETE","/api/schedules/"+id);}catch(e){console.error(e);}
}
function showNewScheduleForm(){
  const d=document.getElementById("newScheduleForm");
  d.style.display=d.style.display==="none"?"block":"none";
}
async function createSchedule(){
  const name=document.getElementById("schedName").value.trim();
  const prompt=document.getElementById("schedPrompt").value.trim();
  const engine=document.getElementById("schedEngine").value;
  const type=document.getElementById("schedType").value;
  const value=document.getElementById("schedValue").value.trim();
  if(!name||!prompt||!value){alert("Fill in all fields");return;}
  try{
    await api("POST","/api/schedules",{name,prompt,engine,schedule_type:type,schedule_value:value});
    document.getElementById("schedName").value="";
    document.getElementById("schedPrompt").value="";
    document.getElementById("schedValue").value="";
    document.getElementById("newScheduleForm").style.display="none";
  }catch(e){alert("Error: "+e.message);}
}

// ── Template Management ──
function renderTemplates(){
  const c=document.getElementById("templateList");
  if(!c)return;
  if(!state.templates.length){c.innerHTML='<p style="color:var(--muted);font-size:11px">No templates yet. Save a task as a template to reuse it.</p>';return;}
  c.innerHTML=state.templates.map(t=>{
    return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03)">'
      +'<div style="display:flex;justify-content:space-between;align-items:center">'
      +'<span style="font-size:12px;font-weight:600">'+esc(t.name)+'</span>'
      +'<div style="display:flex;gap:4px">'
      +'<button onclick="runTemplate(\\''+t.id+'\\')" style="background:var(--accent);border:none;cursor:pointer;color:#fff;font-size:10px;padding:3px 8px;border-radius:4px">Run</button>'
      +'<button onclick="deleteTemplate(\\''+t.id+'\\')" style="background:none;border:none;cursor:pointer;color:var(--err);font-size:10px;padding:2px 4px" title="Delete">✕</button>'
      +'</div></div>'
      +'<div style="font-size:10px;color:var(--muted)">Used '+t.use_count+'x · '+esc(t.engine)+'</div>'
      +'<div style="font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+esc(t.prompt)+'</div>'
      +'</div>';
  }).join("");
}
async function runTemplate(id){
  try{await api("POST","/api/templates/"+id+"/use");scrollToBottom();}catch(e){alert("Error: "+e.message);}
}
async function deleteTemplate(id){
  if(!confirm("Delete this template?"))return;
  try{
    await api("DELETE","/api/templates/"+id);
    state.templates=state.templates.filter(t=>t.id!==id);
    renderTemplates();
  }catch(e){console.error(e);}
}
function showNewTemplateForm(){
  const d=document.getElementById("newTemplateForm");
  d.style.display=d.style.display==="none"?"block":"none";
}
async function createTemplate(){
  const name=document.getElementById("tmplName").value.trim();
  const prompt=document.getElementById("tmplPrompt").value.trim();
  const engine=document.getElementById("tmplEngine").value;
  if(!name||!prompt){alert("Fill in name and prompt");return;}
  try{
    const t=await api("POST","/api/templates",{name,prompt,engine});
    state.templates.push(t);
    renderTemplates();
    document.getElementById("tmplName").value="";
    document.getElementById("tmplPrompt").value="";
    document.getElementById("newTemplateForm").style.display="none";
  }catch(e){alert("Error: "+e.message);}
}
async function saveTaskAsTemplate(taskId){
  const t=state.tasks.find(x=>x.id===taskId);
  if(!t)return;
  const name=window.prompt("Template name:",t.prompt.substring(0,40));
  if(!name)return;
  try{
    const tmpl=await api("POST","/api/templates",{name,prompt:t.prompt,engine:t.engine});
    state.templates.push(tmpl);
    renderTemplates();
    addActivity({timestamp:new Date().toISOString(),event_type:"template",detail:"Saved template: "+name});
  }catch(e){alert("Error: "+e.message);}
}

// ── Output Routing ──
function copyResult(taskId,btn){
  const t=state.tasks.find(x=>x.id===taskId);
  if(!t||!t.result)return;
  const text=t.result.summary||t.error||"";
  navigator.clipboard.writeText(text).then(()=>{
    const orig=btn.innerHTML;btn.innerHTML='<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
    btn.style.color='var(--ok)';
    setTimeout(()=>{btn.innerHTML=orig;btn.style.color='var(--muted)';},1500);
  }).catch(()=>{
    const ta=document.createElement("textarea");ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);
    const orig=btn.innerHTML;btn.innerHTML='Copied!';btn.style.color='var(--ok)';
    setTimeout(()=>{btn.innerHTML=orig;btn.style.color='var(--muted)';},1500);
  });
}
function saveResultToFile(taskId){
  const t=state.tasks.find(x=>x.id===taskId);
  if(!t)return;
  let content="# ClawBridge Task Result\\n";
  content+="Date: "+new Date(t.created_at).toLocaleString()+"\\n";
  content+="Engine: "+t.engine+"\\n";
  content+="Status: "+t.status+"\\n";
  content+="Prompt: "+t.prompt+"\\n\\n";
  if(t.result){
    if(t.result.summary)content+="## Result\\n"+t.result.summary+"\\n\\n";
    if(t.result.total_steps)content+="Steps: "+t.result.total_steps+"\\n";
    if(t.result.total_duration_ms)content+="Duration: "+(t.result.total_duration_ms/1000).toFixed(1)+"s\\n";
    if(t.result.tokens_in)content+="Tokens: "+(t.result.tokens_in+t.result.tokens_out).toLocaleString()+"\\n";
    if(t.result.estimated_cost_usd)content+="Cost: $"+t.result.estimated_cost_usd.toFixed(4)+"\\n";
  }
  if(t.error)content+="## Error\\n"+t.error+"\\n";
  const blob=new Blob([content],{type:"text/markdown"});
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a");
  a.href=url;a.download="clawbridge-task-"+t.id.substring(0,8)+".md";
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

// ── Soul / Personality Editor ──
let _currentSoulFile=null;
async function switchView(view){
  state.activeView=view;
  document.getElementById("chatView").style.display=view==="chat"?"flex":"none";
  document.getElementById("soulView").style.display=view==="soul"?"flex":"none";
  document.getElementById("memoryView").style.display=view==="memory"?"flex":"none";
  document.getElementById("scheduleView").style.display=view==="schedules"?"flex":"none";
  const hv=document.getElementById("historyView");if(hv)hv.style.display=view==="history"?"flex":"none";
  const wv=document.getElementById("workflowsView");if(wv)wv.style.display=view==="workflows"?"flex":"none";
  // Update sidebar nav items
  document.querySelectorAll(".sidebar-nav-item").forEach(el=>{
    el.classList.toggle("active",el.id==="nav-"+view);
  });
  if(view==="soul"){if(!_currentSoulFile)loadSoulFile("SOUL.md");localStorage.setItem("onboarding_soul_customized","true");checkOnboarding();}
  if(view==="memory"){loadMemory();const mb=document.getElementById("memoryBadge");if(mb)mb.style.display="none";}
  if(view==="schedules")loadScheduleView();
  if(view==="history")renderHistory();
  if(view==="workflows")renderWorkflows();
}
function updateTabBadges(){
  // Schedule badge
  const activeScheds=state.schedules.filter(s=>s.enabled).length;
  const sb=document.getElementById("schedulesBadge");
  if(sb){if(activeScheds>0){sb.textContent=activeScheds;sb.style.display="block";}else{sb.style.display="none";}}
  // Workflows badge
  const wfCount=state.workflows?state.workflows.length:0;
  const wb=document.getElementById("workflowsBadge");
  if(wb){if(wfCount>0){wb.textContent=wfCount;wb.style.display="block";}else{wb.style.display="none";}}
}
// ── Workflow Recording & Replay ──
let _recordingInterval=null;
function toggleRecording(){
  if(state.recording){
    // Stop recording
    if(state.ws&&state.ws.readyState===1)state.ws.send(JSON.stringify({type:"recording_stop"}));
  }else{
    // Start recording
    if(state.ws&&state.ws.readyState===1)state.ws.send(JSON.stringify({type:"recording_start"}));
  }
}
function handleRecordingStatus(p){
  state.recording=!!p.active;
  const btn=document.getElementById("recordBtn");
  const btnText=document.getElementById("recordBtnText");
  const btnIcon=document.getElementById("recordBtnIcon");
  const timer=document.getElementById("recordingTimer");
  if(state.recording){
    if(btn)btn.style.background="#7f1d1d";
    if(btnText)btnText.textContent="Stop";
    if(btnIcon)btnIcon.style.background="#ef4444";
    state.recordingStartTime=Date.now();
    if(timer){timer.style.display="inline";timer.textContent="00:00";}
    _recordingInterval=setInterval(()=>{
      if(!state.recordingStartTime)return;
      const s=Math.floor((Date.now()-state.recordingStartTime)/1000);
      const mm=String(Math.floor(s/60)).padStart(2,"0");
      const ss=String(s%60).padStart(2,"0");
      if(timer)timer.textContent=mm+":"+ss;
    },1000);
  }else{
    if(btn)btn.style.background="#2d3748";
    if(btnText)btnText.textContent="Record";
    if(btnIcon)btnIcon.style.background="#ef4444";
    if(timer)timer.style.display="none";
    state.recordingStartTime=null;
    if(_recordingInterval){clearInterval(_recordingInterval);_recordingInterval=null;}
  }
}
function handleRecordingResult(p){
  state.recordingActions=p.actions||[];
  const form=document.getElementById("saveWorkflowForm");
  const info=document.getElementById("recordingInfo");
  if(form)form.style.display="block";
  if(info)info.textContent="Captured "+state.recordingActions.length+" actions. Give this workflow a name to save it.";
}
function saveWorkflow(){
  const name=(document.getElementById("wfName")||{}).value||"";
  const desc=(document.getElementById("wfDescription")||{}).value||"";
  const tagsStr=(document.getElementById("wfTags")||{}).value||"";
  if(!name.trim()){alert("Please enter a workflow name.");return;}
  if(!state.recordingActions||state.recordingActions.length===0){alert("No recorded actions to save.");return;}
  const tags=tagsStr.split(",").map(t=>t.trim()).filter(Boolean);
  if(state.ws&&state.ws.readyState===1){
    state.ws.send(JSON.stringify({type:"save_workflow",payload:{name:name.trim(),description:desc,actions:state.recordingActions,tags:tags}}));
  }
  discardRecording();
}
function discardRecording(){
  state.recordingActions=null;
  const form=document.getElementById("saveWorkflowForm");
  if(form)form.style.display="none";
  if(document.getElementById("wfName"))document.getElementById("wfName").value="";
  if(document.getElementById("wfDescription"))document.getElementById("wfDescription").value="";
  if(document.getElementById("wfTags"))document.getElementById("wfTags").value="";
}
function renderWorkflows(){
  const container=document.getElementById("workflowList");
  if(!container)return;
  const wfs=state.workflows||[];
  if(wfs.length===0){
    container.innerHTML='<div style="text-align:center;padding:40px;color:var(--muted);font-size:13px;">No workflows saved yet. Click Record to create one.</div>';
    return;
  }
  let html="";
  for(const wf of wfs){
    const stepCount=(wf.actions||[]).length;
    const tags=(wf.tags||[]).map(t=>'<span style="background:var(--bg);padding:2px 6px;border-radius:4px;font-size:10px;color:var(--muted);">'+t+'</span>').join(" ");
    const replayed=wf.replay_count>0?' <span style="font-size:11px;color:var(--muted);">Replayed '+wf.replay_count+'x</span>':"";
    const created=wf.created_at?new Date(wf.created_at).toLocaleString():"";
    html+='<div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:10px;">';
    html+='<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">';
    html+='<div><span style="font-weight:600;font-size:14px;">'+_esc(wf.name)+'</span>'+replayed+'</div>';
    html+='<div style="display:flex;gap:6px;">';
    html+='<button class="btn" onclick="replayWorkflow(\\\''+wf.id+'\\\')" style="font-size:11px;padding:4px 10px;">Replay</button>';
    html+='<button class="btn" onclick="deleteWorkflow(\\\''+wf.id+'\\\')" style="font-size:11px;padding:4px 10px;background:#2d3748;border:1px solid var(--border);">Delete</button>';
    html+='</div></div>';
    if(wf.description)html+='<p style="font-size:12px;color:var(--muted);margin-bottom:6px;">'+_esc(wf.description)+'</p>';
    html+='<div style="display:flex;gap:12px;align-items:center;font-size:11px;color:var(--muted);">';
    html+='<span>'+stepCount+' steps</span>';
    if(wf.target_app)html+='<span>App: '+_esc(wf.target_app)+'</span>';
    html+='<span>'+created+'</span>';
    if(tags)html+='<span>'+tags+'</span>';
    html+='</div></div>';
  }
  container.innerHTML=html;
}
function replayWorkflow(id){
  if(state.ws&&state.ws.readyState===1){
    state.ws.send(JSON.stringify({type:"replay_workflow",payload:{id:id}}));
    switchView("chat");
  }
}
async function deleteWorkflow(id){
  if(!confirm("Delete this workflow?"))return;
  try{
    const r=await fetch("/api/workflows/"+id,{method:"DELETE"});
    if(r.ok){
      state.workflows=state.workflows.filter(w=>w.id!==id);
      renderWorkflows();updateTabBadges();
    }
  }catch(e){console.error("Delete workflow error:",e);}
}
function _esc(s){if(!s)return"";return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
// ── Onboarding ──
function checkOnboarding(){
  if(localStorage.getItem("onboarding_dismissed")==="true"){
    const card=document.getElementById("onboardingCard");if(card)card.style.display="none";return;
  }
  const status={keys:false,soul:false,task:false,browser:false};
  if(window.__PRELOAD__&&window.__PRELOAD__.config&&window.__PRELOAD__.config.keys){
    const k=window.__PRELOAD__.config.keys;
    status.keys=!!(k.anthropic_configured||k.openai_configured||k.openrouter_configured);
  }
  // Starter tier activation also counts as keys configured
  if(!status.keys&&_licenseStatus&&_licenseStatus.status==="activated"){status.keys=true;}
  status.soul=localStorage.getItem("onboarding_soul_customized")==="true"||(_soulOriginal&&_soulOriginal.length>10);
  status.task=state.tasks.length>0;
  status.browser=state.tasks.some(t=>t.engine==="browser_use");
  // Update item 1 text based on license tier
  const keysTextEl=document.getElementById("onboard-keys-text");
  if(keysTextEl){
    if(_licenseStatus&&(_licenseStatus.status==="activated"||_licenseStatus.tier==="starter")){
      keysTextEl.textContent=status.keys?"API access configured via activation":"Activate your license to get API credits";
    }else{
      keysTextEl.textContent="Configure an API key (Anthropic, OpenAI, or OpenRouter)";
    }
  }
  ["keys","soul","task","browser"].forEach(k=>{
    const el=document.getElementById("onboard-"+k);
    if(el){if(status[k])el.classList.add("done");else el.classList.remove("done");}
  });
  const done=Object.values(status).filter(v=>v).length;
  const fill=document.getElementById("onboardFill");
  const text=document.getElementById("onboardText");
  if(fill)fill.style.width=(done/4*100)+"%";
  if(text)text.textContent=done+" / 4";
  if(done===4){
    setTimeout(()=>{
      const card=document.getElementById("onboardingCard");
      if(card){card.style.opacity="0";card.style.transform="translateY(-10px)";
        setTimeout(()=>{card.style.display="none";localStorage.setItem("onboarding_dismissed","true");},300);}
    },2000);
  }else{
    const card=document.getElementById("onboardingCard");if(card)card.style.display="block";
  }
}
function onboardAction(action){
  const el=document.getElementById("onboard-"+action);
  if(el&&el.classList.contains("done"))return;
  if(action==="keys"){
    if(_licenseStatus&&_licenseStatus.status==="not_activated"&&_licenseStatus.tier==="starter"){
      showActivationModal();
    }else{
      const cc=document.getElementById("configContent");
      if(cc&&cc.classList.contains("collapsed"))toggleSection("config");
      toggleInlineKey("openrouter");
    }
  }else if(action==="soul"){switchView("soul");}
  else if(action==="task"){switchView("chat");document.getElementById("prompt").focus();}
  else if(action==="browser"){switchView("chat");document.getElementById("engine").value="browser_use";document.getElementById("prompt").focus();}
}
function dismissOnboarding(){
  const card=document.getElementById("onboardingCard");
  if(card){card.style.opacity="0";card.style.transform="translateY(-10px)";
    setTimeout(()=>{card.style.display="none";localStorage.setItem("onboarding_dismissed","true");},300);}
}
let _soulOriginal="";
async function loadSoulFile(name){
  _currentSoulFile=name;
  document.querySelectorAll(".soul-tab").forEach(b=>b.classList.toggle("active",b.dataset.file===name));
  const editor=document.getElementById("soulEditor");
  editor.value="Loading...";
  try{
    const r=await api("GET","/api/personality/"+name);
    editor.value=r.content;_soulOriginal=r.content;
    const badge=document.getElementById("soulBadge");if(badge)badge.style.display="none";
    editor.oninput=()=>{
      const badge=document.getElementById("soulBadge");
      if(badge)badge.style.display=editor.value!==_soulOriginal?"block":"none";
    };
  }catch(e){editor.value="Error loading file: "+e.message;}
}
async function saveSoulFile(){
  if(!_currentSoulFile)return;
  const content=document.getElementById("soulEditor").value;
  const st=document.getElementById("soulSaveStatus");
  st.textContent="Saving...";st.style.color="var(--muted)";
  try{
    await api("PUT","/api/personality/"+_currentSoulFile,{content});
    _soulOriginal=content;
    st.textContent="Saved!";st.style.color="var(--ok)";
    const badge=document.getElementById("soulBadge");if(badge)badge.style.display="none";
    if(_currentSoulFile==="SOUL.md")localStorage.setItem("onboarding_soul_customized","true");
    setTimeout(()=>st.textContent="",2000);
  }catch(e){st.textContent="Error: "+e.message;st.style.color="var(--err)";}
}

// ── Memory View ──
async function loadMemory(){
  try{
    const m=await api("GET","/api/memory");
    const durEl=document.getElementById("durableMemory");
    const dailyEl=document.getElementById("dailyLogs");
    durEl.value=m.durable||"";
    let html="";
    for(const[date,content]of Object.entries(m.daily_logs||{})){
      html+='<div style="margin-bottom:8px"><div style="font-size:11px;font-weight:600;color:var(--accent);margin-bottom:4px">'+date+'</div>'
        +'<pre style="font-size:11px;color:var(--muted);white-space:pre-wrap;margin:0;max-height:120px;overflow-y:auto">'+esc(content)+'</pre></div>';
    }
    dailyEl.innerHTML=html||'<p style="color:var(--muted);font-size:11px">No daily logs yet</p>';
  }catch(e){console.error(e);}
}
async function saveDurableMemory(){
  const content=document.getElementById("durableMemory").value;
  const st=document.getElementById("memorySaveStatus");
  st.textContent="Saving...";
  try{
    await api("PUT","/api/personality/MEMORY.md",{content});
    st.textContent="Saved!";st.style.color="var(--ok)";
    setTimeout(()=>st.textContent="",2000);
  }catch(e){st.textContent="Error";st.style.color="var(--err)";}
}
async function addQuickMemory(){
  const text=document.getElementById("quickMemoryInput").value.trim();
  if(!text)return;
  try{
    await api("POST","/api/memory",{text,daily:true});
    document.getElementById("quickMemoryInput").value="";
    loadMemory();
  }catch(e){alert("Error: "+e.message);}
}
async function searchMemory(){
  const q=document.getElementById("memorySearchInput").value.trim();
  if(!q)return;
  const el=document.getElementById("memorySearchResults");
  try{
    const results=await api("GET","/api/memory/search?q="+encodeURIComponent(q));
    if(!results.length){el.innerHTML='<p style="color:var(--muted);font-size:11px">No results</p>';return;}
    el.innerHTML=results.map(r=>'<div style="font-size:11px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.03)"><span style="color:var(--accent)">'+esc(r.source)+':'+r.line+'</span> '+esc(r.text)+'</div>').join("");
  }catch(e){el.innerHTML='<p style="color:var(--err);font-size:11px">Search failed: '+esc(e.message)+'</p>';}
}

// ── Schedule View ──
async function loadScheduleView(){
  try{
    const s=await api("GET","/api/schedules");
    state.schedules=s;
    renderScheduleView();
  }catch(e){console.error(e);}
}
function renderScheduleView(){
  const c=document.getElementById("scheduleViewList");
  if(!c)return;
  if(!state.schedules.length){c.innerHTML='<div style="text-align:center;padding:40px;color:var(--muted)"><p style="font-size:16px;margin-bottom:8px">No scheduled tasks yet</p><p style="font-size:12px">Create recurring tasks that run automatically on a schedule.</p></div>';return;}
  c.innerHTML=state.schedules.map(s=>{
    const typeIcon=s.schedule_type==='once'?'⏱':'🔄';
    const typeLabel=s.schedule_type==='once'?'One-shot':s.schedule_type==='interval'?'Every '+s.schedule_value:'Cron: '+s.schedule_value;
    const nextRun=s.next_run?new Date(s.next_run).toLocaleString():'—';
    const lastRun=s.last_run?new Date(s.last_run).toLocaleString():'Never';
    return '<div class="card" style="margin-bottom:8px">'
      +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
      +'<div><span style="font-size:14px;font-weight:600">'+typeIcon+' '+esc(s.name)+'</span></div>'
      +'<div style="display:flex;gap:6px;align-items:center">'
      +'<button onclick="toggleSchedule(\\''+s.id+'\\','+!s.enabled+')" class="btn" style="font-size:11px;padding:4px 10px;'+(s.enabled?'background:var(--ok)':'background:var(--muted)')+'">'+(s.enabled?'Enabled':'Disabled')+'</button>'
      +'<button onclick="deleteSchedule(\\''+s.id+'\\')" class="btn" style="font-size:11px;padding:4px 10px;background:rgba(239,68,68,0.15);color:var(--err)">Delete</button>'
      +'</div></div>'
      +'<div style="font-size:12px;color:var(--text);margin-bottom:4px">'+esc(s.prompt)+'</div>'
      +'<div style="display:flex;gap:16px;font-size:11px;color:var(--muted)">'
      +'<span>'+typeLabel+'</span><span>Runs: '+s.run_count+'</span><span>Next: '+nextRun+'</span><span>Last: '+lastRun+'</span>'
      +'</div>'
      +'</div>';
  }).join("");
}

// ── Task History ──
let _expandedHistoryRow=null;
function filterHistory(){renderHistory();}
function renderHistory(){
  const tbody=document.getElementById("historyTableBody");
  if(!tbody)return;
  const fStatus=(document.getElementById("historyFilterStatus")||{}).value||"";
  const fEngine=(document.getElementById("historyFilterEngine")||{}).value||"";
  const fSearch=((document.getElementById("historySearch")||{}).value||"").toLowerCase();
  let tasks=[...state.tasks].sort((a,b)=>new Date(b.created_at)-new Date(a.created_at));
  if(fStatus)tasks=tasks.filter(t=>t.status===fStatus);
  if(fEngine)tasks=tasks.filter(t=>t.engine===fEngine);
  if(fSearch)tasks=tasks.filter(t=>t.prompt.toLowerCase().includes(fSearch)||(t.result&&t.result.summary&&t.result.summary.toLowerCase().includes(fSearch)));
  if(!tasks.length){tbody.innerHTML='<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted)">No tasks match filters</td></tr>';return;}
  _expandedHistoryRow=null;
  tbody.innerHTML=tasks.map(t=>{
    const time=new Date(t.created_at).toLocaleString([],{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});
    const prompt=esc(t.prompt.length>60?t.prompt.substring(0,60)+"...":t.prompt);
    const cost=t.result&&t.result.estimated_cost_usd?"$"+t.result.estimated_cost_usd.toFixed(4):"\\u2014";
    const dur=t.result&&t.result.total_duration_ms?(t.result.total_duration_ms>=60000?(t.result.total_duration_ms/60000).toFixed(1)+"m":(t.result.total_duration_ms/1000).toFixed(1)+"s"):"\\u2014";
    return '<tr onclick="toggleHistoryRow(\\''+t.id+'\\')" id="hrow-'+t.id+'">'
      +'<td>'+time+'</td>'
      +'<td>'+prompt+'</td>'
      +'<td>'+esc(t.engine)+'</td>'
      +'<td><span class="history-badge '+t.status+'">'+t.status+'</span></td>'
      +'<td style="text-align:right">'+cost+'</td>'
      +'<td style="text-align:right">'+dur+'</td>'
      +'</tr>';
  }).join("");
}
function toggleHistoryRow(taskId){
  const row=document.getElementById("hrow-"+taskId);if(!row)return;
  // Collapse if already expanded
  if(_expandedHistoryRow===taskId){
    const next=row.nextElementSibling;
    if(next&&next.classList.contains("history-expanded"))next.remove();
    row.style.background="";_expandedHistoryRow=null;return;
  }
  // Collapse previous
  if(_expandedHistoryRow){
    const prev=document.getElementById("hrow-"+_expandedHistoryRow);
    if(prev){const next=prev.nextElementSibling;if(next&&next.classList.contains("history-expanded"))next.remove();prev.style.background="";}
  }
  const t=state.tasks.find(x=>x.id===taskId);if(!t)return;
  let html='<div class="history-detail">';
  if(t.result&&t.result.summary)html+='<div class="history-result">'+renderMarkdown(t.result.summary)+'</div>';
  if(t.error)html+='<div class="msg-error" style="margin-bottom:12px">'+esc(t.error)+'</div>';
  html+='<div style="display:flex;gap:8px">';
  if(t.status==="complete"&&t.result){
    html+='<button class="btn" onclick="event.stopPropagation();copyResult(\\''+taskId+'\\',this)" style="font-size:11px;padding:6px 12px">Copy</button>';
    if(t.result.total_steps>0)html+='<button class="btn" onclick="event.stopPropagation();showReplay(\\''+taskId+'\\')" style="font-size:11px;padding:6px 12px;background:#2d3748;border:1px solid var(--border)">Replay Steps</button>';
  }
  html+='</div></div>';
  const tr=document.createElement("tr");tr.className="history-expanded";
  tr.innerHTML='<td colspan="6" style="padding:0">'+html+'</td>';
  row.insertAdjacentElement("afterend",tr);
  row.style.background="rgba(99,102,241,0.08)";
  _expandedHistoryRow=taskId;
}

document.addEventListener("DOMContentLoaded",()=>{
  const prompt = document.getElementById("prompt");
  prompt.onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();submit();}};
  prompt.oninput=e=>{prompt.style.height="auto";prompt.style.height=prompt.scrollHeight+"px";};
  document.getElementById("taskForm").onsubmit=e=>{e.preventDefault();submit();};
  
  if(localStorage.getItem('sidebar_left')==='true') toggleSidebar('left');
  ['engines','config','activity','liveview','schedules','templates'].forEach(id=>{
    const c=document.getElementById(id+'Content');
    const card=document.getElementById('card-'+id);
    if(c&&card&&localStorage.getItem('section_'+id)==='1'){c.classList.add('collapsed');card.querySelector('.chevron')?.classList.add('collapsed');}
  });
  // Use server-preloaded data for instant render (no fetch needed)
  if(window.__PRELOAD__){
    const p=window.__PRELOAD__;
    if(p.engines&&p.engines.length){state.engines=p.engines;renderEngines();}
    if(p.tasks&&p.tasks.length){state.tasks=p.tasks;settleAll(p.tasks);render();}
    if(p.schedules){state.schedules=p.schedules;renderSchedules();updateTabBadges();}
    if(p.templates){state.templates=p.templates;renderTemplates();}
    if(p.workflows){state.workflows=p.workflows;renderWorkflows();updateTabBadges();}
    if(p.config&&p.config.keys){
      try{
        const c=p.config;
        renderConfigSummary(c);
        if(c.remote&&c.remote.configured)state.bridgeActive=true;
        updateSystemHealth();
      }catch(e){console.warn("preload config render error:",e);}
    }
    console.log("[ClawBridge] Preloaded",p.engines?.length||0,"engines,",p.tasks?.length||0,"tasks");
  }
  refreshConfig();
  connect();
  showLastSession();
  checkOnboarding();
  // HTTP fallback — load engine/task data if WebSocket is slow or blocked
  loadInitialData();
  // Poll browser status every 10s (pause when tab hidden)
  let _browserPollId=setInterval(checkBrowserStatus,10000);
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){clearInterval(_browserPollId);_browserPollId=null;}
    else if(!_browserPollId){checkBrowserStatus();_browserPollId=setInterval(checkBrowserStatus,10000);}
  });
});
async function loadInitialData(){
  // Wait 1s for WS to populate — if still loading, fetch via HTTP
  await new Promise(r=>setTimeout(r,1200));
  try{
    if(!state.engines.length){
      const engines=await api("GET","/api/engines");
      if(engines&&engines.length){state.engines=engines;renderEngines();}
    }
    if(!state.tasks.length){
      const tasks=await api("GET","/api/tasks");
      if(tasks&&tasks.length){state.tasks=tasks;settleAll(tasks);render();}
    }
    if(!state.schedules.length){
      const scheds=await api("GET","/api/schedules");
      if(scheds){state.schedules=scheds;renderSchedules();}
    }
    if(!state.templates.length){
      const tmpls=await api("GET","/api/templates");
      if(tmpls){state.templates=tmpls;renderTemplates();}
    }
  }catch(e){console.warn("loadInitialData fallback error:",e);}
}

// License / Activation System
let _licenseStatus = null;
let _topupUrl = '';

async function checkLicenseStatus() {
  try {
    const data = await api("GET", "/api/license/status");
    _licenseStatus = data;
    _topupUrl = data.topup_url || 'https://clawbridge.ai/account';
    window._topupUrl = _topupUrl;
    updateLicenseBadge(data);
    updateCreditWidget(data);
    // Show activation modal if not activated and no keys
    if (data.status === 'not_activated') {
      showActivationModal();
    }
  } catch (e) {
    console.warn("Failed to check license status:", e);
  }
}

function updateLicenseBadge(data) {
  const badge = document.getElementById('licenseBadge');
  if (!badge) return;
  badge.style.display = 'inline';
  if (data.status === 'activated' || data.tier === 'starter') {
    badge.textContent = 'PRO';
    badge.className = 'license-badge pro';
  } else if (data.status === 'byok' || data.tier === 'byok') {
    badge.textContent = 'BYOK';
    badge.className = 'license-badge byok';
  } else if (data.status === 'not_activated') {
    badge.textContent = 'FREE';
    badge.className = 'license-badge free';
    badge.onclick = showActivationModal;
    badge.title = 'Click to activate';
  } else {
    badge.style.display = 'none';
  }
}

function updateCreditWidget(data) {
  const widget = document.getElementById('creditBalanceWidget');
  if (!widget) return;
  // Only show for activated starter tier
  if (data.status !== 'activated' || data.tier === 'byok') {
    widget.style.display = 'none';
    return;
  }
  widget.style.display = 'block';
  const remaining = data.credit_remaining_usd || 0;
  const limit = data.credit_limit_usd || 5;
  const pct = limit > 0 ? Math.min(100, (remaining / limit) * 100) : 0;
  document.getElementById('creditAmount').textContent = '$' + remaining.toFixed(2);
  document.getElementById('creditLimit').textContent = '$' + limit.toFixed(2);
  document.getElementById('creditBar').style.width = pct + '%';
  // Change bar color based on remaining
  const bar = document.getElementById('creditBar');
  if (pct < 20) bar.style.background = '#ef4444';
  else if (pct < 50) bar.style.background = '#f59e0b';
  else bar.style.background = '#6366f1';
}

function showActivationModal() {
  document.getElementById('activationModal').style.display = 'flex';
  document.getElementById('activationOptions').style.display = 'block';
  document.getElementById('activationCodeForm').style.display = 'none';
}

function closeActivationModal() {
  document.getElementById('activationModal').style.display = 'none';
}

function showActivationCodeInput() {
  document.getElementById('activationOptions').style.display = 'none';
  document.getElementById('activationCodeForm').style.display = 'block';
  document.getElementById('activationCodeInput').focus();
}

function hideActivationCodeInput() {
  document.getElementById('activationOptions').style.display = 'block';
  document.getElementById('activationCodeForm').style.display = 'none';
  document.getElementById('activationStatus').textContent = '';
}

async function activateCode() {
  const code = document.getElementById('activationCodeInput').value.trim();
  if (!code) {
    document.getElementById('activationStatus').innerHTML = '<span style="color:var(--err)">Please enter an activation code</span>';
    return;
  }
  const btn = document.getElementById('activateBtn');
  const status = document.getElementById('activationStatus');
  btn.disabled = true;
  btn.textContent = 'Activating...';
  status.innerHTML = '<span style="color:var(--muted)">Connecting to activation server...</span>';
  try {
    const result = await api("POST", "/api/license/activate", { activation_code: code });
    status.innerHTML = '<span style="color:var(--ok)">' + esc(result.message || 'Activated successfully!') + '</span>';
    setTimeout(() => {
      closeActivationModal();
      checkLicenseStatus();
    }, 1500);
  } catch (e) {
    status.innerHTML = '<span style="color:var(--err)">' + esc(e.message || 'Activation failed') + '</span>';
    btn.disabled = false;
    btn.textContent = 'Activate';
  }
}

// Check license status on page load
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(checkLicenseStatus, 1000);
  // Refresh every 5 minutes
  setInterval(checkLicenseStatus, 300000);
});
"""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ClawBridge Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>
  <style>""" + css + """</style>
</head>
<body>
  <header class="header">
    <h1 class="logo">ClawBridge <span id="licenseBadge" class="license-badge" style="display:none"></span></h1>
    <div class="system-health" tabindex="0" title="System Health">
      <span id="healthDot" class="system-health-dot sh-err"></span>
      <span id="healthText">Connecting...</span>
      <div class="system-health-dropdown">
        <div class="health-row"><span class="health-label">WebSocket</span><span id="healthWS" class="health-value h-err">Connecting...</span></div>
        <div class="health-row"><span class="health-label">Remote Bridge</span><span id="healthBridge" class="health-value" style="color:var(--muted)">Offline</span></div>
        <div class="health-row"><span class="health-label">Active Engines</span><span id="healthEngines" class="health-value" style="color:var(--muted)">0</span></div>
        <div class="health-row"><span class="health-label">Machine ID</span><span id="healthMachineId" class="health-value" style="color:var(--accent);font-size:9px;font-family:monospace;word-break:break-all;max-width:120px;text-align:right"></span></div>
      </div>
    </div>
  </header>
  <div class="layout" id="mainLayout">
    <aside id="leftSidebar">
      <div style="display:flex;justify-content:flex-end;margin-bottom:8px;">
        <button class="toggle-btn" onclick="toggleSidebar('left')" title="Toggle Sidebar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="11 17 6 12 11 7"></polyline><polyline points="18 17 13 12 18 7"></polyline></svg>
        </button>
      </div>
      <div class="collapsed-icons">
        <div onclick="toggleSidebar('left')" title="Engines">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Config">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Activity">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Browser View">
          <svg id="monitorIconCollapsed" class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
        </div>
        <div onclick="toggleSidebar('left')" title="Templates">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
        </div>
        <div style="border-top:1px solid rgba(255,255,255,0.06);margin:4px 0"></div>
        <div onclick="switchView('chat')" title="Chat">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
        </div>
        <div onclick="switchView('soul')" title="Soul">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
        </div>
        <div onclick="switchView('memory')" title="Memory">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
        </div>
        <div onclick="switchView('schedules')" title="Schedules">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
        </div>
        <div onclick="switchView('history')" title="History">
          <svg class="sidebar-icon-large" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>
        </div>
      </div>
      <div class="sidebar-section-label">System</div>
      <div class="card expandable" id="card-engines">
        <h2 class="expandable-header" onclick="toggleSection('engines')">
          <span style="display:flex;align-items:center;gap:8px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path></svg>Engines</span>
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </h2>
        <div class="expandable-content" id="enginesContent"><div id="engineList"><p class="muted">Loading...</p></div></div>
      </div>
      <div class="card expandable" id="card-config">
        <h2 class="expandable-header" onclick="toggleSection('config')">
          <span style="display:flex;align-items:center;gap:8px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>Config</span>
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </h2>
        <div class="expandable-content" id="configContent">
          <div id="configSummary"><p class="muted">Loading...</p></div>
          <div id="creditBalanceWidget" style="display:none;margin-top:16px;padding:12px;background:rgba(99,102,241,0.08);border-radius:8px;border:1px solid rgba(99,102,241,0.2)">
            <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Credit Balance</div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
              <span id="creditAmount" style="font-size:18px;font-weight:600;color:#6366f1">$0.00</span>
              <span style="color:var(--muted);font-size:12px">/</span>
              <span id="creditLimit" style="font-size:14px;color:var(--muted)">$0.00</span>
            </div>
            <div style="background:rgba(255,255,255,0.1);border-radius:4px;height:6px;overflow:hidden;margin-bottom:8px">
              <div id="creditBar" style="height:100%;background:#6366f1;transition:width 0.3s;width:0%"></div>
            </div>
            <button class="btn" onclick="window.open(window._topupUrl||'https://clawbridge.ai/account','_blank')" style="width:100%;font-size:11px;background:#6366f1">Buy More Credits</button>
          </div>
          <div style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.06)">
            <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Automation Mode</div>
            <div id="automationModePanel" style="margin-bottom:12px">
              <div style="display:flex;gap:4px;margin-bottom:8px">
                <button id="modeSupervised" class="btn mode-btn" onclick="setAutomationMode('supervised')" style="flex:1;min-width:0;font-size:10px;padding:8px 4px;overflow:hidden;box-sizing:border-box">
                  <div style="font-weight:600;white-space:nowrap">Supervised</div>
                  <div style="font-size:8px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Asks first</div>
                </button>
                <button id="modeAutonomous" class="btn mode-btn" onclick="setAutomationMode('autonomous')" style="flex:1;min-width:0;font-size:10px;padding:8px 4px;overflow:hidden;box-sizing:border-box">
                  <div style="font-weight:600;white-space:nowrap">Autonomous</div>
                  <div style="font-size:8px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">No pauses</div>
                </button>
              </div>
              <div id="automationModeHint" style="font-size:10px;color:var(--muted);line-height:1.4;padding:6px 8px;background:rgba(99,102,241,0.08);border-radius:4px">
                <strong>Supervised:</strong> Pauses before high-risk actions (purchases, form submissions, sensitive sites). Recommended for learning the system.
              </div>
            </div>
          </div>
          <div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.06)">
            <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Browser Session</div>
            <div id="browserSessionStatus" style="font-size:12px;margin-bottom:8px;padding:8px;background:rgba(255,255,255,0.03);border-radius:6px">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
                <span id="chromeStatusDot" style="width:8px;height:8px;border-radius:50%;background:var(--muted);flex-shrink:0"></span>
                <span id="chromeStatusText" style="font-size:12px">Not connected</span>
              </div>
              <div id="chromeModeText" style="font-size:10px;color:var(--muted)"></div>
            </div>
            <button class="btn" id="launchChromeBtn" style="width:100%;font-size:12px;margin-bottom:6px" onclick="launchChrome()">Launch Chrome Session</button>
            <button class="btn" id="stopChromeBtn" style="width:100%;font-size:12px;margin-bottom:6px;background:rgba(239,68,68,0.15);color:var(--err);display:none" onclick="stopChrome()">Stop Chrome Session</button>
            <div style="font-size:10px;color:var(--muted);line-height:1.4" title="Opens a dedicated Chrome profile at %LOCALAPPDATA%\\ClawBridge\\ChromeProfile. Sign into your accounts once — logins persist between sessions.">Persistent Chrome profile with saved logins</div>
            <div id="chromeExeInfo" style="font-size:10px;color:var(--muted);margin-top:6px"></div>
          </div>
        </div>
      </div>
      <div class="sidebar-section-label">Live</div>
      <div class="card expandable" id="card-activity">
        <h2 class="expandable-header" onclick="toggleSection('activity')">
          <span style="display:flex;align-items:center;gap:8px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>Activity</span>
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </h2>
        <div class="expandable-content" id="activityContent">
          <div id="activityFeed" class="activity-feed" style="overflow-y:auto;max-height:150px;"><p class="muted">Waiting for activity...</p></div>
        </div>
      </div>
      <div class="card expandable" id="card-liveview">
        <h2 class="expandable-header" onclick="toggleSection('liveview')">
          <span style="display:flex;align-items:center;gap:8px;"><svg id="monitorIcon" class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>Browser</span>
          <span style="display:flex;align-items:center;gap:6px;">
            <span id="liveStatus" style="font-size:9px;color:var(--muted)">Idle</span>
            <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
          </span>
        </h2>
        <div class="expandable-content collapsed" id="liveviewContent">
          <div class="live-view-img-wrap">
            <img id="liveImage" src="" alt="Live Browser Feed">
            <div id="livePlaceholder" style="display:flex;flex-direction:column;align-items:center;padding:24px 16px;gap:8px">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.3"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
              <div style="font-size:11px;color:var(--muted);text-align:center">No active session</div>
              <div id="lastSessionTime" style="font-size:9px;color:rgba(160,174,192,0.4)"></div>
            </div>
          </div>
        </div>
      </div>
      <div class="sidebar-section-label">Content</div>
      <div class="card expandable" id="card-templates">
        <h2 class="expandable-header" onclick="toggleSection('templates')">
          <span style="display:flex;align-items:center;gap:8px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>Templates</span>
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </h2>
        <div class="expandable-content collapsed" id="templatesContent">
          <div id="templateList"><p style="color:var(--muted);font-size:11px">No templates yet</p></div>
          <button class="btn" style="width:100%;font-size:11px;margin-top:8px;background:#2d3748;border:1px solid var(--border)" onclick="showNewTemplateForm()">+ New Template</button>
          <div id="newTemplateForm" style="display:none;margin-top:8px">
            <input id="tmplName" placeholder="Template name" style="margin-bottom:6px;font-size:12px">
            <textarea id="tmplPrompt" placeholder="Task prompt..." style="margin-bottom:6px;font-size:12px;min-height:50px"></textarea>
            <select id="tmplEngine" style="margin-bottom:6px;font-size:12px;width:100%!important"><option value="auto">Auto</option><option value="browser_use">browser-use</option><option value="computer_use">computer-use</option><option value="openclaw">OpenClaw</option></select>
            <button class="btn" style="width:100%;font-size:11px" onclick="createTemplate()">Save Template</button>
          </div>
        </div>
      </div>
      <div class="sidebar-section-label">Views</div>
      <div class="sidebar-nav-item active" onclick="switchView('chat')" id="nav-chat">
        <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
        <span>Chat</span>
      </div>
      <div class="sidebar-nav-item" onclick="switchView('soul')" id="nav-soul">
        <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
        <span>Soul</span>
        <span id="soulBadge" class="nav-badge" style="display:none"></span>
      </div>
      <div class="sidebar-nav-item" onclick="switchView('memory')" id="nav-memory">
        <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
        <span>Memory</span>
        <span id="memoryBadge" class="nav-badge" style="display:none"></span>
      </div>
      <div class="sidebar-nav-item" onclick="switchView('schedules')" id="nav-schedules">
        <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
        <span>Schedules</span>
        <span id="schedulesBadge" class="nav-badge" style="display:none">0</span>
      </div>
      <div class="sidebar-nav-item" onclick="switchView('history')" id="nav-history">
        <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>
        <span>History</span>
      </div>
      <div class="sidebar-nav-item" onclick="switchView('workflows')" id="nav-workflows">
        <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
        <span>Workflows</span>
        <span id="workflowsBadge" class="nav-badge" style="display:none">0</span>
      </div>
    </aside>
    <main>
      <div class="chat-header">
        <div style="display:flex;align-items:center;gap:12px;">
          <span style="font-size:14px;font-weight:600;color:var(--text);display:flex;align-items:center;gap:6px">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
            Chat
          </span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          <span id="taskCount" style="font-size:12px;color:var(--muted);cursor:pointer;padding:4px 8px;border-radius:6px;transition:all 0.15s;" onclick="switchView('history')" onmouseenter="this.style.background='rgba(99,102,241,0.1)';this.style.color='var(--accent)'" onmouseleave="this.style.background='transparent';this.style.color='var(--muted)'" title="View task history">0 tasks</span>
          <button id="clearChatBtn" onclick="clearChat()" title="Clear chat" style="background:none;border:1px solid var(--border);border-radius:6px;padding:4px 8px;cursor:pointer;color:var(--muted);display:flex;align-items:center;gap:4px;font-size:11px;transition:all 0.15s;" onmouseenter="this.style.color='var(--err)';this.style.borderColor='var(--err)'" onmouseleave="this.style.color='var(--muted)';this.style.borderColor='var(--border)'">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
            Clear
          </button>
        </div>
      </div>
      <!-- Chat View (default) -->
      <div id="chatView" style="display:flex;flex-direction:column;flex:1;overflow:hidden;">
        <div id="onboardingCard" class="onboarding-card" style="display:none;flex-shrink:0;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <div style="font-size:15px;font-weight:600;display:flex;align-items:center;gap:8px;">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
              Getting Started
            </div>
            <button onclick="dismissOnboarding()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:20px;padding:4px 8px;border-radius:6px;" title="Dismiss">&times;</button>
          </div>
          <div id="onboard-keys" class="onboarding-item" onclick="onboardAction('keys')"><div class="onboarding-check">&#10003;</div><div id="onboard-keys-text" style="font-size:13px">Set up API access</div></div>
          <div id="onboard-soul" class="onboarding-item" onclick="onboardAction('soul')"><div class="onboarding-check">&#10003;</div><div style="font-size:13px">Set up your agent identity and personality</div></div>
          <div id="onboard-task" class="onboarding-item" onclick="onboardAction('task')"><div class="onboarding-check">&#10003;</div><div style="font-size:13px">Run your first task</div></div>
          <div id="onboard-browser" class="onboarding-item" onclick="onboardAction('browser')"><div class="onboarding-check">&#10003;</div><div style="font-size:13px">Try the browser engine with your logins</div></div>
          <div style="display:flex;align-items:center;gap:10px;margin-top:12px;font-size:11px;color:var(--muted)">
            <div class="onboarding-progress-bar"><div id="onboardFill" class="onboarding-progress-fill" style="width:0%"></div></div>
            <span id="onboardText">0 / 4</span>
          </div>
        </div>
        <div id="taskList" class="task-list">
          <p style="color:var(--muted);text-align:center;padding:40px">Send a message to start.</p>
        </div>
        <div class="input-area">
          <form id="taskForm" class="input-container">
            <div style="display:flex;align-items:center;gap:4px;flex-shrink:0;">
              <select id="engine">
                <option value="auto">Auto</option>
                <option value="browser_use">browser-use</option>
                <option value="computer_use">computer-use</option>
                <option value="openclaw">OpenClaw</option>
              </select>
            </div>
            <textarea id="prompt" placeholder="Send a message..." rows="1" title="Enter to send, Shift+Enter for new line"></textarea>
            <button type="submit" class="btn" id="submitBtn" title="Send message (Enter)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              Send
            </button>
          </form>
          <div style="font-size:10px;color:rgba(160,174,192,0.5);text-align:center;margin-top:6px;letter-spacing:0.3px;">Enter to send &middot; Shift+Enter for new line</div>
        </div>
      </div>
      <!-- Soul Editor View -->
      <div id="soulView" style="display:none;flex-direction:column;flex:1;overflow:hidden;padding:20px;">
        <div style="max-width:800px;margin:0 auto;width:100%;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
            <div>
              <h3 style="font-size:16px;font-weight:600;margin-bottom:4px">Programmable Soul</h3>
              <p style="font-size:12px;color:var(--muted)">Define who your agent is — personality, identity, and user context. Injected into every engine prompt.</p>
            </div>
          </div>
          <div style="display:flex;gap:8px;margin-bottom:12px;">
            <button class="soul-tab active" data-file="SOUL.md" onclick="loadSoulFile('SOUL.md')" style="background:rgba(99,102,241,0.15);color:var(--accent);border:none;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">SOUL.md</button>
            <button class="soul-tab" data-file="IDENTITY.md" onclick="loadSoulFile('IDENTITY.md')" style="background:rgba(255,255,255,0.05);color:var(--muted);border:none;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">IDENTITY.md</button>
            <button class="soul-tab" data-file="USER.md" onclick="loadSoulFile('USER.md')" style="background:rgba(255,255,255,0.05);color:var(--muted);border:none;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">USER.md</button>
          </div>
          <textarea id="soulEditor" style="width:100%;min-height:400px;font-family:monospace;font-size:13px;line-height:1.6;padding:16px;border-radius:12px;resize:vertical;" placeholder="Loading..."></textarea>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
            <span id="soulSaveStatus" style="font-size:12px;color:var(--muted)"></span>
            <button class="btn" onclick="saveSoulFile()" style="font-size:13px;">Save Changes</button>
          </div>
        </div>
      </div>
      <!-- Memory View -->
      <div id="memoryView" style="display:none;flex-direction:column;flex:1;overflow-y:auto;padding:20px;">
        <div style="max-width:800px;margin:0 auto;width:100%;">
          <div style="margin-bottom:16px;">
            <h3 style="font-size:16px;font-weight:600;margin-bottom:4px">Agent Memory</h3>
            <p style="font-size:12px;color:var(--muted)">Durable memory persists forever. Daily logs capture transient notes and are auto-loaded for context.</p>
          </div>
          <div style="display:flex;gap:8px;margin-bottom:16px;">
            <input id="quickMemoryInput" placeholder="Quick note — appends to today's log..." style="flex:1;font-size:12px">
            <button class="btn" onclick="addQuickMemory()" style="font-size:12px;white-space:nowrap">+ Add Note</button>
          </div>
          <div style="display:flex;gap:8px;margin-bottom:16px;">
            <input id="memorySearchInput" placeholder="Search memory..." style="flex:1;font-size:12px" onkeydown="if(event.key==='Enter')searchMemory()">
            <button class="btn" onclick="searchMemory()" style="font-size:12px;background:#2d3748;border:1px solid var(--border)">Search</button>
          </div>
          <div id="memorySearchResults" style="margin-bottom:16px"></div>
          <div class="card" style="margin-bottom:16px">
            <h2 style="font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;margin-bottom:8px">Durable Memory (MEMORY.md)</h2>
            <textarea id="durableMemory" style="width:100%;min-height:200px;font-family:monospace;font-size:12px;line-height:1.5;resize:vertical" placeholder="Loading..."></textarea>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">
              <span id="memorySaveStatus" style="font-size:11px;color:var(--muted)"></span>
              <button class="btn" onclick="saveDurableMemory()" style="font-size:12px">Save Memory</button>
            </div>
          </div>
          <div class="card">
            <h2 style="font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;margin-bottom:8px">Daily Logs (Recent)</h2>
            <div id="dailyLogs" style="max-height:300px;overflow-y:auto"><p style="color:var(--muted);font-size:11px">Loading...</p></div>
          </div>
        </div>
      </div>
      <!-- Schedule View -->
      <div id="scheduleView" style="display:none;flex-direction:column;flex:1;overflow-y:auto;padding:20px;">
        <div style="max-width:800px;margin:0 auto;width:100%;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <div>
              <h3 style="font-size:16px;font-weight:600;margin-bottom:4px">Scheduled Tasks</h3>
              <p style="font-size:12px;color:var(--muted)">Create recurring tasks that run automatically. Supports one-shot, interval, and cron expressions.</p>
            </div>
            <button class="btn" onclick="showNewScheduleForm()" style="font-size:13px">+ New Schedule</button>
          </div>
          <div id="newScheduleForm" style="display:none;margin-bottom:16px" class="card">
            <h2 style="font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;margin-bottom:12px">Create Schedule</h2>
            <input id="schedName" placeholder="Schedule name (e.g. Check inbox)" style="margin-bottom:8px;font-size:13px">
            <textarea id="schedPrompt" placeholder="Task prompt..." style="margin-bottom:8px;font-size:13px;min-height:60px"></textarea>
            <div style="display:flex;gap:8px;margin-bottom:8px;">
              <select id="schedEngine" style="font-size:12px;width:auto!important;flex:1"><option value="auto">Auto</option><option value="browser_use">browser-use</option><option value="computer_use">computer-use</option><option value="openclaw">OpenClaw</option></select>
              <select id="schedType" style="font-size:12px;width:auto!important;flex:1"><option value="interval">Interval</option><option value="cron">Cron</option><option value="once">One-shot</option></select>
            </div>
            <input id="schedValue" placeholder="e.g. 30m, 2h, 1d (interval) or 0 */2 * * * (cron) or 2026-02-15T10:00:00 (once)" style="margin-bottom:8px;font-size:12px">
            <div style="font-size:10px;color:var(--muted);margin-bottom:12px;line-height:1.4">
              <strong>Interval:</strong> 30m, 2h, 1d, 300s &nbsp;|&nbsp;
              <strong>Cron:</strong> minute hour day month weekday (e.g. 0 9 * * 1-5 = 9am weekdays) &nbsp;|&nbsp;
              <strong>Once:</strong> ISO datetime
            </div>
            <div style="display:flex;gap:8px;">
              <button class="btn" onclick="createSchedule()" style="flex:1;font-size:13px">Create</button>
              <button class="btn" onclick="showNewScheduleForm()" style="flex:0;font-size:13px;background:#2d3748;border:1px solid var(--border)">Cancel</button>
            </div>
          </div>
          <div id="scheduleViewList"></div>
        </div>
      </div>
      <!-- History View -->
      <div id="historyView" style="display:none;flex-direction:column;flex:1;overflow-y:auto;padding:20px;">
        <div style="max-width:1200px;margin:0 auto;width:100%;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <div>
              <h3 style="font-size:16px;font-weight:600;margin-bottom:4px">Task History</h3>
              <p style="font-size:12px;color:var(--muted)">Browse, search, and replay all tasks</p>
            </div>
            <button class="btn" onclick="switchView('chat')" style="font-size:13px;background:#2d3748;border:1px solid var(--border)">Back to Chat</button>
          </div>
          <div class="history-filters">
            <span style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px">Filter:</span>
            <select id="historyFilterStatus" onchange="filterHistory()" style="font-size:12px;width:auto!important;">
              <option value="">All statuses</option>
              <option value="complete">Complete</option>
              <option value="error">Error</option>
              <option value="running">Running</option>
              <option value="pending">Pending</option>
            </select>
            <select id="historyFilterEngine" onchange="filterHistory()" style="font-size:12px;width:auto!important;">
              <option value="">All engines</option>
              <option value="browser_use">browser-use</option>
              <option value="computer_use">computer-use</option>
              <option value="openclaw">OpenClaw</option>
            </select>
            <input id="historySearch" placeholder="Search prompts or results..." oninput="filterHistory()" style="flex:1;min-width:200px;max-width:300px;font-size:13px;padding:8px 12px;">
          </div>
          <div style="overflow-x:auto;">
            <table class="history-table">
              <thead><tr>
                <th style="width:140px">Time</th>
                <th>Prompt</th>
                <th style="width:100px">Engine</th>
                <th style="width:90px">Status</th>
                <th style="width:80px;text-align:right">Cost</th>
                <th style="width:90px;text-align:right">Duration</th>
              </tr></thead>
              <tbody id="historyTableBody">
                <tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted)">No tasks yet</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <!-- Workflows View -->
      <div id="workflowsView" style="display:none;flex-direction:column;flex:1;overflow-y:auto;padding:20px;">
        <div style="max-width:1200px;margin:0 auto;width:100%;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <div>
              <h3 style="font-size:16px;font-weight:600;margin-bottom:4px">Workflows</h3>
              <p style="font-size:12px;color:var(--muted)">Record, save, and replay desktop workflows</p>
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
              <span id="recordingTimer" style="display:none;font-size:12px;color:#ef4444;font-weight:600;font-variant-numeric:tabular-nums;">00:00</span>
              <button id="recordBtn" class="btn" onclick="toggleRecording()" style="font-size:13px;background:#2d3748;border:1px solid var(--border)">
                <span id="recordBtnIcon" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;margin-right:6px;vertical-align:middle;"></span>
                <span id="recordBtnText">Record</span>
              </button>
              <button class="btn" onclick="switchView('chat')" style="font-size:13px;background:#2d3748;border:1px solid var(--border)">Back to Chat</button>
            </div>
          </div>
          <!-- Save workflow form (hidden until recording stops) -->
          <div id="saveWorkflowForm" style="display:none;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:16px;">
            <h4 style="font-size:13px;font-weight:600;margin-bottom:8px;">Save Recorded Workflow</h4>
            <p id="recordingInfo" style="font-size:12px;color:var(--muted);margin-bottom:10px;"></p>
            <input id="wfName" placeholder="Workflow name" style="margin-bottom:6px;font-size:12px;width:100%;box-sizing:border-box;">
            <input id="wfDescription" placeholder="Description (optional)" style="margin-bottom:6px;font-size:12px;width:100%;box-sizing:border-box;">
            <input id="wfTags" placeholder="Tags (comma-separated, optional)" style="margin-bottom:8px;font-size:12px;width:100%;box-sizing:border-box;">
            <div style="display:flex;gap:8px;">
              <button class="btn" onclick="saveWorkflow()" style="font-size:12px;flex:1;">Save Workflow</button>
              <button class="btn" onclick="discardRecording()" style="font-size:12px;background:#2d3748;border:1px solid var(--border);">Discard</button>
            </div>
          </div>
          <!-- Workflow list -->
          <div id="workflowList">
            <div style="text-align:center;padding:40px;color:var(--muted);font-size:13px;">No workflows saved yet. Click Record to create one.</div>
          </div>
        </div>
      </div>
    </main>
  </div>
  <!-- Activation Modal -->
  <div id="activationModal" class="modal-overlay" style="display:none">
    <div class="modal-content" style="max-width:460px;text-align:center">
      <h2 style="font-size:20px;margin-bottom:8px">Welcome to ClawBridge</h2>
      <p style="color:var(--muted);margin-bottom:24px;font-size:13px">Choose how to get started</p>
      <div id="activationOptions">
        <button class="btn activation-option" onclick="showActivationCodeInput()" style="width:100%;margin-bottom:12px;padding:14px;text-align:left;background:#2d3748;border:1px solid var(--border);box-sizing:border-box;overflow:hidden">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">I have an activation code</div>
        </button>
        <button class="btn activation-option" onclick="closeActivationModal()" style="width:100%;margin-bottom:12px;padding:14px;text-align:left;background:#2d3748;border:1px solid var(--border);box-sizing:border-box;overflow:hidden">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Continue without code</div>
        </button>
        <button class="btn activation-option" onclick="window.open('https://clawbridge.ai/pricing','_blank')" style="width:100%;padding:14px;text-align:left;background:linear-gradient(135deg,#6366f1,#8b5cf6);border:none;box-sizing:border-box;overflow:hidden">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Buy ClawBridge</div>
        </button>
      </div>
      <div id="activationCodeForm" style="display:none">
        <div style="margin-bottom:16px">
          <input type="text" id="activationCodeInput" placeholder="CB-XXXX-XXXX-XXXX" style="text-align:center;font-size:18px;letter-spacing:2px;text-transform:uppercase;padding:14px" maxlength="19">
        </div>
        <div id="activationStatus" style="font-size:12px;margin-bottom:12px"></div>
        <div style="display:flex;gap:8px">
          <button class="btn" onclick="hideActivationCodeInput()" style="flex:1;background:#2d3748;border:1px solid var(--border)">Back</button>
          <button class="btn" onclick="activateCode()" style="flex:2;background:#6366f1" id="activateBtn">Activate</button>
        </div>
      </div>
    </div>
  </div>
  <script>""" + js + """</script>
</body>
</html>"""
    return html

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(title="ClawBridge", version="0.1.0")

    # ── Dashboard Authentication Middleware ──────────────────────────
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    class AuthMiddleware(BaseHTTPMiddleware):
        """Simple token-based auth. Disabled when DASHBOARD_TOKEN is empty."""
        async def dispatch(self, request: Request, call_next):
            token = get_settings().dashboard_token
            if not token:
                return await call_next(request)  # No token set → open access
            # Allow health check without auth
            if request.url.path == "/health":
                return await call_next(request)
            # Check query param, header, or cookie
            req_token = (
                request.query_params.get("token", "")
                or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                or request.cookies.get("clawbridge_token", "")
            )
            if hmac.compare_digest(req_token.encode(), token.encode()):
                return await call_next(request)
            # For dashboard root, show login form instead of 401
            if request.url.path == "/" and request.method == "GET":
                return HTMLResponse(_login_page_html(request.url.path), status_code=200)
            return JSONResponse({"error": "Unauthorized. Set token via ?token= query param or Authorization header."}, status_code=401)

    app.add_middleware(AuthMiddleware)

    def _login_page_html(redirect_to: str = "/") -> str:
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>ClawBridge Login</title>
<style>body{{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#0a0a0f;color:#e4e4e7;font-family:system-ui}}
.card{{background:#18181b;padding:40px;border-radius:16px;border:1px solid rgba(255,255,255,0.06);max-width:360px;width:100%}}
h2{{margin:0 0 8px;font-size:20px}}p{{color:#71717a;font-size:13px;margin:0 0 24px}}
input{{width:100%;padding:10px 14px;background:#09090b;border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:#e4e4e7;font-size:14px;margin-bottom:16px;box-sizing:border-box}}
button{{width:100%;padding:10px;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer}}
button:hover{{background:#4f46e5}}</style></head>
<body><div class="card"><h2>ClawBridge</h2><p>Enter your dashboard token to continue</p>
<form onsubmit="event.preventDefault();const t=document.getElementById('tok').value;document.cookie='clawbridge_token='+t+';path=/;max-age=86400;SameSite=Strict';window.location.href='/?token='+encodeURIComponent(t)">
<input id="tok" type="password" placeholder="Dashboard token" autofocus>
<button type="submit">Unlock Dashboard</button></form></div></body></html>"""

    @app.on_event("startup")
    async def startup():
        logging.basicConfig(level=getattr(logging, get_settings().log_level.upper(), logging.INFO))
        await get_manager().init_engines()
        get_manager()._broadcast = _broadcast
        # Link audit logger to websocket broadcast
        get_audit()._on_log = lambda ev: asyncio.create_task(_broadcast({"type": "audit_event", "payload": ev.model_dump(mode="json")}))
        asyncio.create_task(get_manager().remote_bridge_loop())
        # Start schedule manager loop
        asyncio.create_task(get_schedule_manager().run_loop(get_manager().submit))

    connections: list[WebSocket] = []

    async def _broadcast(msg: dict) -> None:
        dead: list[WebSocket] = []
        for ws in connections[:]:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                connections.remove(ws)
            except ValueError:
                pass  # already removed by another broadcast

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        import json as _json
        from html import escape as _esc
        # Pre-load data server-side so the dashboard renders immediately
        # (avoids dependency on fetch/WebSocket working in browser)
        try:
            engines = await get_manager().engine_infos()
        except Exception:
            engines = []
        try:
            tasks = [t.model_dump(mode="json") for t in get_manager().list_tasks()]
        except Exception:
            tasks = []
        try:
            s = get_settings()
            config = {
                "keys": {"anthropic_configured": s.has_anthropic_key(), "openai_configured": s.has_openai_key(), "openrouter_configured": s.has_openrouter_key(), "default_model": s.default_model},
                "policy": {"mode": s.policy_mode, "max_concurrent_tasks": s.max_concurrent_tasks},
                "browser": {"mode": s.browser_mode, "cdp_url": s.browser_cdp_url, "user_data_dir": s.browser_user_data_dir, "chrome_exe": _find_chrome_exe() or "not found"},
                "machine_id": get_machine_id(),
                "remote": {"url": s.remote_bridge_url, "configured": bool(s.remote_bridge_url)}
            }
        except Exception:
            config = {}
        try:
            schedules = [s.model_dump() for s in get_schedule_manager().list_all()]
            templates = [t.model_dump() for t in get_template_manager().list_all()]
        except Exception:
            schedules, templates = [], []
        try:
            workflows = [w.model_dump(mode="json") for w in get_workflow_manager().list_all()]
        except Exception:
            workflows = []
        preload_data = {"engines": engines, "tasks": tasks, "config": config, "schedules": schedules, "templates": templates, "workflows": workflows}
        preload = '<script>window.__PRELOAD__=' + _json.dumps(preload_data, default=str) + ';</script>'
        html = _dashboard_html()
        html = html.replace("</head>", preload + "\n</head>")

        # --- Server-side render: replace "Loading..." placeholders with actual HTML ---
        # Engines
        if engines:
            engine_html_parts = []
            for e in engines:
                name = e.get("display_name") or e.get("name", "?")
                status = e.get("status", "unknown")
                if status == "available":
                    sc = "color:var(--ok)"
                elif status == "no_api_key":
                    sc = "color:#f59e0b"
                elif status == "error":
                    sc = "color:var(--err)"
                else:
                    sc = "color:var(--muted)"
                hint = ""
                if e.get("error_hint"):
                    hint = f'<div style="font-size:10px;color:var(--muted);margin-top:2px">{_esc(e["error_hint"])}</div>'
                engine_html_parts.append(
                    f'<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03)">'
                    f'<div style="display:flex;justify-content:space-between">'
                    f'<span>{_esc(name)}</span><span style="font-weight:600;{sc}">{_esc(status)}</span>'
                    f'</div>{hint}</div>'
                )
            engine_html = "".join(engine_html_parts)
            html = html.replace(
                '<div id="engineList"><p class="muted">Loading...</p></div>',
                f'<div id="engineList">{engine_html}</div>'
            )

        # Config
        if config and config.get("keys"):
            k = config["keys"]
            mid = _esc(str(config.get("machine_id", "")))
            def _ssr_provider_row(name, pkey, is_configured):
                chip_cls = "config-chip configured" if is_configured else "config-chip not-set clickable-chip"
                chip_text = "Configured" if is_configured else "Click to set"
                return (
                    f'<div class="config-provider-row">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;cursor:pointer" onclick="toggleInlineKey(\'{pkey}\')">'
                    f'<span style="color:var(--muted)">{_esc(name)}</span>'
                    f'<span class="{chip_cls}">{chip_text}</span></div>'
                    f'<div id="inline-key-{pkey}" style="display:none;padding:4px 0 8px">'
                    f'<div style="display:flex;gap:6px">'
                    f'<input type="password" id="key-input-{pkey}" placeholder="Paste {_esc(name)} API key..." style="flex:1;font-size:12px;padding:6px 10px" onkeydown="if(event.key===\'Enter\')saveInlineKey(\'{pkey}\')">'
                    f'<button class="btn" style="font-size:11px;padding:6px 12px;white-space:nowrap" onclick="saveInlineKey(\'{pkey}\')">Save</button>'
                    f'</div>'
                    f'<div id="key-status-{pkey}" style="font-size:10px;margin-top:4px"></div></div></div>'
                )
            primary = "None"
            if k.get("openrouter_configured"): primary = "OpenRouter"
            elif k.get("anthropic_configured"): primary = "Anthropic"
            elif k.get("openai_configured"): primary = "OpenAI"
            config_html = (
                f'<div class="config-provider-primary">Active: {_esc(primary)}</div>'
                + _ssr_provider_row("Anthropic", "anthropic", k.get("anthropic_configured"))
                + _ssr_provider_row("OpenAI", "openai", k.get("openai_configured"))
                + _ssr_provider_row("OpenRouter", "openrouter", k.get("openrouter_configured"))
            )
            html = html.replace(
                '<div id="configSummary"><p class="muted">Loading...</p></div>',
                f'<div id="configSummary">{config_html}</div>'
            )
            # Inject machine ID into health dropdown
            if mid:
                html = html.replace(
                    '<span id="healthMachineId"',
                    f'<span id="healthMachineId" title="{mid}"'
                )

        return html

    @app.post("/api/tasks")
    async def create_task(body: dict):
        prompt = body.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Missing required field: prompt")
        if len(prompt) > 50000:
            raise HTTPException(status_code=400, detail="Prompt too long (max 50,000 chars)")
        engine_str = body.get("engine", "auto")
        try:
            engine = EngineName(engine_str)
        except ValueError:
            valid = ", ".join(e.value for e in EngineName)
            raise HTTPException(status_code=400, detail=f"Invalid engine '{engine_str}'. Valid: {valid}")
        task = Task(prompt=prompt, engine=engine)
        return (await get_manager().submit(task)).model_dump(mode="json")

    @app.get("/api/tasks")
    async def list_tasks():
        return [t.model_dump(mode="json") for t in get_manager().list_tasks()]

    @app.delete("/api/tasks")
    async def clear_tasks():
        count = await get_manager().clear_tasks()
        await _broadcast({"type": "tasks_cleared", "payload": {}})
        return {"cleared": count}

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        t = get_manager().get(task_id)
        if not t:
            raise HTTPException(404, "Task not found")
        return t.model_dump(mode="json")

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, body: dict):
        action = body.get("action")
        if action == "cancel":
            t = await get_manager().cancel(task_id)
        elif action == "pause":
            t = await get_manager().pause(task_id)
        else:
            raise HTTPException(400, "Unknown action")
        if not t:
            raise HTTPException(404, "Task not found")
        return t.model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/steps")
    async def get_task_steps(task_id: str):
        """Retrieve step-level trace data for task replay."""
        t = get_manager().get(task_id)
        if not t:
            raise HTTPException(404, "Task not found")
        steps = get_steps_for_task(task_id)
        return {"task_id": task_id, "steps": steps, "total_steps": len(steps)}

    @app.get("/api/tasks/{task_id}/audit")
    async def get_task_audit(task_id: str):
        """Retrieve audit events for a specific task."""
        events = get_audit().recent(limit=100, task_id=task_id)
        return [e.model_dump(mode="json") for e in events]

    @app.get("/api/engines")
    async def list_engines():
        return await get_manager().engine_infos()

    @app.post("/api/engines/openclaw/install")
    async def install_openclaw():
        npm = shutil.which("npm")
        if not npm:
            raise HTTPException(400, "Node.js/npm not found. Install Node.js first: https://nodejs.org")
        await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "installing", "message": "Running npm install -g openclaw@latest ..."}})
        try:
            proc = await asyncio.create_subprocess_shell(
                f'"{npm}" install -g openclaw@latest',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                err_msg = (stderr or stdout or b"").decode(errors="replace").strip()
                await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "error", "message": err_msg}})
                raise HTTPException(500, f"npm install failed: {err_msg}")
        except HTTPException:
            raise
        except asyncio.TimeoutError:
            await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "error", "message": "Install timed out after 120s"}})
            raise HTTPException(500, "Install timed out")
        except Exception as e:
            msg = str(e)
            await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "error", "message": msg}})
            raise HTTPException(500, f"Install error: {msg}")
        # Re-initialize the engine
        mgr = get_manager()
        e = OpenClawEngine()
        await e.initialize()
        mgr._engines[EngineName.OPENCLAW] = e
        await _broadcast({"type": "engine_status", "payload": await mgr.engine_infos()})
        await _broadcast({"type": "install_progress", "payload": {"engine": "openclaw", "status": "done", "message": "OpenClaw installed successfully"}})
        return {"status": "ok", "engine_status": e._status.value}

    @app.get("/api/config")
    async def get_config():
        s = get_settings()
        return {
            "version": __version__,
            "keys": {"anthropic_configured": s.has_anthropic_key(), "openai_configured": s.has_openai_key(), "openrouter_configured": s.has_openrouter_key(), "default_model": s.default_model},
            "policy": {"mode": s.policy_mode, "max_concurrent_tasks": s.max_concurrent_tasks},
            "automation": {"mode": s.automation_mode},
            "browser": {"mode": s.browser_mode, "cdp_url": s.browser_cdp_url, "user_data_dir": s.browser_user_data_dir, "chrome_exe": _find_chrome_exe() or "not found"},
            "machine_id": get_machine_id(),
            "remote": {
                "url": s.remote_bridge_url,
                "configured": bool(s.remote_bridge_url)
            }
        }

    @app.post("/api/config/keys")
    async def save_key(body: dict):
        provider = body.get("provider", "")
        key = body.get("key", "").strip()
        env_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
        env_var = env_map.get(provider)
        if not env_var:
            raise HTTPException(400, f"Unknown provider: {provider}")
        if not key:
            raise HTTPException(400, "Key cannot be empty")
        # Update .env file
        env_path = Path(".env")
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(env_var + "=") or line.strip().startswith(env_var + " ="):
                lines[i] = f"{env_var}={key}"
                found = True
                break
        if not found:
            lines.append(f"{env_var}={key}")
        env_path.write_text("\n".join(lines) + "\n")
        # Update in-memory settings and env
        os.environ[env_var] = key
        setattr(Settings, env_var.lower().replace("api_key", "api_key"), key)
        # Map to Settings attribute names
        attr_map = {"anthropic": "anthropic_api_key", "openai": "openai_api_key", "openrouter": "openrouter_api_key"}
        setattr(Settings, attr_map[provider], key)
        # Re-initialize engines so browser-use picks up the new key
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok", "provider": provider}

    @app.post("/api/config/browser")
    async def save_browser_config(body: dict):
        mode = body.get("mode", "default")
        if mode not in ("default", "cdp", "user_data_dir"):
            raise HTTPException(400, f"Invalid browser mode: {mode}")
        cdp_url = body.get("cdp_url", "").strip()
        user_data_dir = body.get("user_data_dir", "").strip()
        # Persist to .env
        env_path = Path(".env")
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        env_updates = {"BROWSER_MODE": mode, "BROWSER_CDP_URL": cdp_url, "BROWSER_USER_DATA_DIR": user_data_dir}
        for env_var, val in env_updates.items():
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(env_var + "=") or line.strip().startswith(env_var + " ="):
                    lines[i] = f"{env_var}={val}"
                    found = True
                    break
            if not found:
                lines.append(f"{env_var}={val}")
        env_path.write_text("\n".join(lines) + "\n")
        # Update in-memory
        Settings.browser_mode = mode
        Settings.browser_cdp_url = cdp_url or "http://localhost:9222"
        Settings.browser_user_data_dir = user_data_dir
        os.environ["BROWSER_MODE"] = mode
        os.environ["BROWSER_CDP_URL"] = cdp_url or "http://localhost:9222"
        os.environ["BROWSER_USER_DATA_DIR"] = user_data_dir
        # Re-initialize engines
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok", "mode": mode}

    @app.post("/api/config/automation")
    async def save_automation_mode(body: dict):
        """Set automation mode: supervised (asks approval) or autonomous (runs freely)."""
        mode = body.get("mode", "supervised")
        if mode not in ("supervised", "autonomous"):
            raise HTTPException(400, f"Invalid automation mode: {mode}. Use 'supervised' or 'autonomous'.")
        # Persist to .env
        env_path = Path(".env")
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith("AUTOMATION_MODE=") or line.strip().startswith("AUTOMATION_MODE ="):
                lines[i] = f"AUTOMATION_MODE={mode}"
                found = True
                break
        if not found:
            lines.append(f"AUTOMATION_MODE={mode}")
        env_path.write_text("\n".join(lines) + "\n")
        # Update in-memory
        Settings.automation_mode = mode
        os.environ["AUTOMATION_MODE"] = mode
        await _broadcast({"type": "config_update", "payload": {"automation_mode": mode}})
        return {"status": "ok", "mode": mode}

    # ── License / Activation Endpoints ───────────────────────────────────

    @app.post("/api/license/activate")
    async def api_activate_license(body: dict):
        """Activate ClawBridge with an activation code."""
        code = body.get("activation_code", "").strip()
        if not code:
            raise HTTPException(400, "Missing activation_code")
        success, message = activate_license(code)
        if not success:
            raise HTTPException(400, message)
        # Re-initialize engines with new API key
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        # Broadcast license update
        info = get_license_status()
        await _broadcast({
            "type": "license_update",
            "payload": {
                "status": info.status.value,
                "tier": info.tier,
                "credit_limit_usd": info.credit_limit_usd,
                "credit_remaining_usd": info.credit_remaining_usd,
            }
        })
        return {"status": "ok", "message": message}

    @app.get("/api/license/status")
    async def api_license_status():
        """Get current license status and credit balance."""
        info = get_license_status()
        return {
            "status": info.status.value,
            "tier": info.tier,
            "credit_limit_usd": info.credit_limit_usd,
            "credit_used_usd": info.credit_used_usd,
            "credit_remaining_usd": info.credit_remaining_usd,
            "topup_url": info.topup_url,
            "error": info.error,
        }

    # ── Chrome Launcher ──────────────────────────────────────────────────
    _chrome_proc: subprocess.Popen | None = None
    if sys.platform == "darwin":
        _CLAWBRIDGE_PROFILE = os.path.expanduser("~/Library/Application Support/ClawBridge/ChromeProfile")
    elif sys.platform == "win32":
        _CLAWBRIDGE_PROFILE = os.path.expandvars(r"%LOCALAPPDATA%\ClawBridge\ChromeProfile")
    else:
        _CLAWBRIDGE_PROFILE = os.path.expanduser("~/.local/share/ClawBridge/ChromeProfile")

    @app.post("/api/browser/launch")
    async def launch_chrome(body: dict = {}):
        nonlocal _chrome_proc
        port = int(body.get("port", 9222))
        chrome_exe = _find_chrome_exe()
        if not chrome_exe:
            raise HTTPException(400, "Chrome not found on this system")
        # Kill our previously launched Chrome if still running
        if _chrome_proc and _chrome_proc.poll() is None:
            _chrome_proc.terminate()
            try:
                _chrome_proc.wait(timeout=5)
            except Exception:
                pass
        # Kill any existing Chrome so the new instance gets the debug port
        chrome_name = os.path.basename(chrome_exe).lower()
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/IM", chrome_name], capture_output=True, timeout=10)
            else:
                subprocess.run(["pkill", "-f", chrome_name], capture_output=True, timeout=10)
            await asyncio.sleep(2)
        except Exception as e:
            logging.warning("Failed to kill existing Chrome: %s", e)
        # Chrome requires a NON-default user-data-dir for --remote-debugging-port.
        # Use a dedicated ClawBridge profile — user signs in once, sessions persist.
        debug_udd = _CLAWBRIDGE_PROFILE
        os.makedirs(debug_udd, exist_ok=True)
        cmd = [
            chrome_exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={debug_udd}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1300,950",
        ]
        logging.info("Launching Chrome: %s", " ".join(cmd))
        _chrome_proc = subprocess.Popen(cmd)
        # Auto-set CDP mode so tasks use this Chrome
        Settings.browser_mode = "cdp"
        Settings.browser_cdp_url = f"http://localhost:{port}"
        os.environ["BROWSER_MODE"] = "cdp"
        os.environ["BROWSER_CDP_URL"] = f"http://localhost:{port}"
        # Wait for CDP to become available
        cdp_ok = False
        import httpx
        for _ in range(15):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    r = await client.get(f"http://localhost:{port}/json/version")
                    if r.status_code == 200:
                        cdp_ok = True
                        break
            except Exception:
                continue
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok", "pid": _chrome_proc.pid, "port": port, "cdp_url": f"http://localhost:{port}", "cdp_ready": cdp_ok}

    @app.get("/api/browser/status")
    async def browser_status():
        nonlocal _chrome_proc
        running = _chrome_proc is not None and _chrome_proc.poll() is None
        # Also try to ping the CDP endpoint
        cdp_reachable = False
        if Settings.browser_mode == "cdp":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=2) as client:
                    r = await client.get(f"{Settings.browser_cdp_url}/json/version")
                    cdp_reachable = r.status_code == 200
            except Exception:
                pass
        return {"launched": running, "pid": _chrome_proc.pid if running else None, "cdp_reachable": cdp_reachable, "mode": Settings.browser_mode}

    @app.post("/api/browser/stop")
    async def stop_chrome():
        nonlocal _chrome_proc
        if _chrome_proc and _chrome_proc.poll() is None:
            _chrome_proc.terminate()
            _chrome_proc.wait(timeout=5)
            _chrome_proc = None
        # Revert to default mode
        Settings.browser_mode = "default"
        os.environ["BROWSER_MODE"] = "default"
        await get_manager().init_engines()
        await _broadcast({"type": "engine_status", "payload": await get_manager().engine_infos()})
        return {"status": "ok"}

    @app.get("/api/config/audit")
    async def get_audit_events(limit: int = 50, task_id: str | None = None):
        return [e.model_dump(mode="json") for e in get_audit().recent(limit=limit, task_id=task_id)]

    # ── Personality / Soul Endpoints ────────────────────────────────────────
    @app.get("/api/personality")
    async def list_personality_files():
        return get_personality().list_files()

    @app.get("/api/personality/context")
    async def get_personality_context():
        return {"context": get_personality().get_system_context()}

    @app.get("/api/personality/{filename}")
    async def get_personality_file(filename: str):
        if filename not in PERSONALITY_FILES and filename != "MEMORY.md":
            raise HTTPException(404, f"Unknown personality file: {filename}")
        content = get_personality().get_file(filename)
        return {"name": filename, "content": content}

    @app.put("/api/personality/{filename}")
    async def save_personality_file(filename: str, body: dict):
        if filename not in PERSONALITY_FILES and filename != "MEMORY.md":
            raise HTTPException(400, f"Unknown personality file: {filename}")
        content = body.get("content", "")
        get_personality().save_file(filename, content)
        get_personality().append_memory(f"Updated {filename}", daily=True)
        return {"status": "ok", "name": filename}

    # ── Memory Endpoints ────────────────────────────────────────────────────
    @app.get("/api/memory")
    async def get_memory():
        return get_personality().get_memory()

    @app.post("/api/memory")
    async def add_memory(body: dict):
        text = body.get("text", "").strip()
        daily = body.get("daily", True)
        if not text:
            raise HTTPException(400, "text is required")
        get_personality().append_memory(text, daily=daily)
        return {"status": "ok"}

    @app.get("/api/memory/search")
    async def search_memory(q: str = ""):
        if not q.strip():
            return []
        return get_personality().search_memory(q)

    # ── Schedule Endpoints ──────────────────────────────────────────────────
    @app.get("/api/schedules")
    async def list_schedules():
        return [s.model_dump() for s in get_schedule_manager().list_all()]

    @app.post("/api/schedules")
    async def create_schedule(body: dict):
        name = body.get("name", "").strip()
        prompt = body.get("prompt", "").strip()
        engine = body.get("engine", "auto")
        schedule_type = body.get("schedule_type", "interval")
        schedule_value = body.get("schedule_value", "")
        if not name or not prompt:
            raise HTTPException(400, "name and prompt are required")
        if schedule_type not in ("once", "interval", "cron"):
            raise HTTPException(400, f"Invalid schedule_type: {schedule_type}")
        sched = get_schedule_manager().create(name, prompt, engine, schedule_type, schedule_value)
        get_personality().append_memory(f"Created schedule '{name}' ({schedule_type}: {schedule_value})", daily=True)
        await _broadcast({"type": "schedule_update", "payload": [s.model_dump() for s in get_schedule_manager().list_all()]})
        return sched.model_dump()

    @app.patch("/api/schedules/{sched_id}")
    async def update_schedule(sched_id: str, body: dict):
        sched = get_schedule_manager().update(sched_id, body)
        if not sched:
            raise HTTPException(404, "Schedule not found")
        await _broadcast({"type": "schedule_update", "payload": [s.model_dump() for s in get_schedule_manager().list_all()]})
        return sched.model_dump()

    @app.delete("/api/schedules/{sched_id}")
    async def delete_schedule(sched_id: str):
        if not get_schedule_manager().delete(sched_id):
            raise HTTPException(404, "Schedule not found")
        await _broadcast({"type": "schedule_update", "payload": [s.model_dump() for s in get_schedule_manager().list_all()]})
        return {"status": "ok"}

    # ── Template Endpoints ──────────────────────────────────────────────────
    @app.get("/api/templates")
    async def list_templates():
        return [t.model_dump() for t in get_template_manager().list_all()]

    @app.post("/api/templates")
    async def create_template(body: dict):
        name = body.get("name", "").strip()
        prompt = body.get("prompt", "").strip()
        engine = body.get("engine", "auto")
        if not name or not prompt:
            raise HTTPException(400, "name and prompt are required")
        tmpl = get_template_manager().create(name, prompt, engine)
        return tmpl.model_dump()

    @app.delete("/api/templates/{tmpl_id}")
    async def delete_template(tmpl_id: str):
        if not get_template_manager().delete(tmpl_id):
            raise HTTPException(404, "Template not found")
        return {"status": "ok"}

    @app.post("/api/templates/{tmpl_id}/use")
    async def use_template(tmpl_id: str):
        tmpl = get_template_manager().use(tmpl_id)
        if not tmpl:
            raise HTTPException(404, "Template not found")
        # Create and submit a task from the template
        task = Task(prompt=tmpl.prompt, engine=EngineName(tmpl.engine) if tmpl.engine != "auto" else EngineName.AUTO)
        result = await get_manager().submit(task)
        return {"template": tmpl.model_dump(), "task": result.model_dump(mode="json")}

    # ── Workflow Endpoints ─────────────────────────────────────────────────
    @app.get("/api/workflows")
    async def list_workflows():
        return [w.model_dump(mode="json") for w in get_workflow_manager().list_all()]

    @app.get("/api/workflows/{wf_id}")
    async def get_workflow(wf_id: str):
        wf = get_workflow_manager().get(wf_id)
        if not wf:
            raise HTTPException(404, "Workflow not found")
        return wf.model_dump(mode="json")

    @app.post("/api/workflows")
    async def create_workflow(body: dict):
        name = body.get("name", "").strip()
        actions = body.get("actions", [])
        if not name or not actions:
            raise HTTPException(400, "name and actions are required")
        description = body.get("description", "")
        target_app = body.get("target_app", "")
        # Auto-detect target app from window titles if not specified
        if not target_app:
            from collections import Counter as _Ctr
            browser_kw = ("brave", "chrome", "firefox", "edge", "safari", "opera", "clawbridge dashboard")
            titles = [a.get("window_title", "") for a in actions if a.get("window_title")]
            titles = [t for t in titles if not any(bk in t.lower() for bk in browser_kw)]
            if titles:
                target_app = _Ctr(titles).most_common(1)[0][0]
        tags = body.get("tags", [])
        wf = get_workflow_manager().create(name, description, actions, target_app, tags)
        await _broadcast({"type": "workflow_update", "payload": [w.model_dump(mode="json") for w in get_workflow_manager().list_all()]})
        return wf.model_dump(mode="json")

    @app.delete("/api/workflows/{wf_id}")
    async def delete_workflow(wf_id: str):
        if not get_workflow_manager().delete(wf_id):
            raise HTTPException(404, "Workflow not found")
        await _broadcast({"type": "workflow_update", "payload": [w.model_dump(mode="json") for w in get_workflow_manager().list_all()]})
        return {"status": "ok"}

    @app.post("/api/workflows/{wf_id}/replay")
    async def replay_workflow(wf_id: str):
        wf = get_workflow_manager().get(wf_id)
        if not wf:
            raise HTTPException(404, "Workflow not found")
        task = Task(prompt=f"replay: {wf.name}", engine=EngineName.COMPUTER_USE)
        result = await get_manager().submit(task)
        return {"workflow": wf.model_dump(mode="json"), "task": result.model_dump(mode="json")}

    @app.post("/api/recording/start")
    async def start_recording():
        mgr = get_manager()
        engine = mgr._engines.get(EngineName.COMPUTER_USE)
        if not engine:
            raise HTTPException(400, "computer-use engine not available")
        started = engine.start_recording()
        if not started:
            raise HTTPException(409, "Already recording")
        await _broadcast({"type": "recording_status", "payload": {"active": True}})
        return {"status": "recording"}

    @app.post("/api/recording/stop")
    async def stop_recording():
        mgr = get_manager()
        engine = mgr._engines.get(EngineName.COMPUTER_USE)
        if not engine:
            raise HTTPException(400, "computer-use engine not available")
        actions = await engine.stop_recording()
        await _broadcast({"type": "recording_status", "payload": {"active": False}})
        await _broadcast({"type": "recording_result", "payload": {"actions": actions, "count": len(actions)}})
        return {"status": "stopped", "actions": actions, "count": len(actions)}

    # ── Webhook Endpoint ────────────────────────────────────────────────────
    @app.post("/api/webhook/{webhook_id}")
    async def webhook_trigger(webhook_id: str, body: dict = {}):
        """External trigger — POST a prompt to run a task.
        The webhook_id can be a template ID (runs that template) or 'run' (runs body.prompt).
        """
        # Check if webhook_id is a template
        tmpl = get_template_manager().get(webhook_id)
        if tmpl:
            tmpl.use_count += 1
            get_template_manager()._save_template(tmpl)
            task = Task(prompt=tmpl.prompt, engine=EngineName(tmpl.engine) if tmpl.engine != "auto" else EngineName.AUTO)
        elif webhook_id == "run":
            prompt = body.get("prompt", "").strip()
            if not prompt:
                raise HTTPException(400, "prompt is required")
            engine = body.get("engine", "auto")
            task = Task(prompt=prompt, engine=EngineName(engine) if engine != "auto" else EngineName.AUTO)
        else:
            raise HTTPException(404, f"Unknown webhook ID: {webhook_id}. Use a template ID or 'run'.")
        result = await get_manager().submit(task)
        get_personality().append_memory(f"Webhook triggered: {task.prompt[:60]}...", daily=True)
        return {"status": "submitted", "task": result.model_dump(mode="json")}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        connections.append(websocket)
        try:
            await websocket.send_json({"type": "engine_status", "payload": await get_manager().engine_infos()})
            await websocket.send_json({"type": "task_list", "payload": [t.model_dump(mode="json") for t in get_manager().list_tasks()]})
            await websocket.send_json({"type": "schedule_update", "payload": [s.model_dump() for s in get_schedule_manager().list_all()]})
            await websocket.send_json({"type": "template_update", "payload": [t.model_dump() for t in get_template_manager().list_all()]})
            await websocket.send_json({"type": "workflow_update", "payload": [w.model_dump(mode="json") for w in get_workflow_manager().list_all()]})
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif data.get("type") == "approval_response":
                    # Handle approval response from dashboard
                    payload = data.get("payload", {})
                    request_id = payload.get("request_id")
                    approved = payload.get("approved", False)
                    if request_id:
                        handled = get_approval_manager().respond(request_id, approved)
                        await websocket.send_json({
                            "type": "approval_ack",
                            "payload": {"request_id": request_id, "handled": handled}
                        })
                elif data.get("type") == "recording_start":
                    engine = get_manager()._engines.get(EngineName.COMPUTER_USE)
                    if engine:
                        started = engine.start_recording()
                        await _broadcast({"type": "recording_status", "payload": {"active": started}})
                elif data.get("type") == "recording_stop":
                    engine = get_manager()._engines.get(EngineName.COMPUTER_USE)
                    if engine:
                        actions = await engine.stop_recording()
                        await _broadcast({"type": "recording_status", "payload": {"active": False}})
                        await websocket.send_json({"type": "recording_result", "payload": {"actions": actions, "count": len(actions)}})
                elif data.get("type") == "save_workflow":
                    payload = data.get("payload", {})
                    name = payload.get("name", "").strip()
                    actions = payload.get("actions", [])
                    if name and actions:
                        # Auto-detect target app from window titles if not specified
                        target_app = payload.get("target_app", "")
                        if not target_app:
                            from collections import Counter
                            browser_kw = ("brave", "chrome", "firefox", "edge", "safari", "opera", "clawbridge dashboard")
                            titles = [a.get("window_title", "") for a in actions if a.get("window_title")]
                            titles = [t for t in titles if not any(bk in t.lower() for bk in browser_kw)]
                            if titles:
                                target_app = Counter(titles).most_common(1)[0][0]
                        wf = get_workflow_manager().create(
                            name=name,
                            description=payload.get("description", ""),
                            actions=actions,
                            target_app=target_app,
                            tags=payload.get("tags", []),
                        )
                        await _broadcast({"type": "workflow_update", "payload": [w.model_dump(mode="json") for w in get_workflow_manager().list_all()]})
                        await websocket.send_json({"type": "workflow_saved", "payload": wf.model_dump(mode="json")})
                elif data.get("type") == "replay_workflow":
                    wf_id = data.get("payload", {}).get("id", "")
                    wf = get_workflow_manager().get(wf_id)
                    if wf:
                        task = Task(prompt=f"replay: {wf.name}", engine=EngineName.COMPUTER_USE)
                        result = await get_manager().submit(task)
                        await websocket.send_json({"type": "replay_started", "payload": {"task_id": result.id, "workflow": wf.name}})
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in connections:
                connections.remove(websocket)

    return app

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _create_tray_icon(url: str):
    """Create a system tray icon with menu. Returns the icon object or None."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    # Generate a simple icon (purple square with "CB" text)
    icon_path = Path(__file__).parent / "clawbridge.ico"
    if icon_path.exists():
        try:
            image = Image.open(str(icon_path))
        except Exception:
            image = None
    else:
        image = None

    if image is None:
        # Generate a simple colored icon programmatically
        image = Image.new("RGBA", (64, 64), (99, 102, 241, 255))  # accent purple
        draw = ImageDraw.Draw(image)
        # Draw a simple "C" shape
        draw.ellipse([8, 8, 56, 56], outline=(255, 255, 255, 255), width=6)
        draw.rectangle([32, 8, 56, 56], fill=(99, 102, 241, 255))  # cut right side for "C"

    def on_open(icon, item):
        webbrowser.open(url)

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"ClawBridge v{__version__}", None, enabled=False),
        pystray.MenuItem(f"Running on {url}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("ClawBridge", image, "ClawBridge", menu)
    return icon


def main() -> None:
    global _loading_server
    import time as _time

    s = get_settings()
    print()
    print(f"  ClawBridge v{__version__}")
    print("  Dashboard: http://%s:%s" % (s.host, s.port))
    print()
    if not s.has_any_key():
        print("  [!] Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in .env")
    url = "http://%s:%s" % (s.host, s.port)

    _startup_status.update({"stage": "Initializing application...", "progress": 80})

    # 1. System tray icon in background thread
    tray_icon = _create_tray_icon(url)
    if tray_icon:
        threading.Thread(target=tray_icon.run, daemon=True).start()
        print("  System tray icon active")

    # 2. Create the app
    _startup_status.update({
        "stage": "Initializing application...",
        "detail": "Setting up engines",
        "progress": 85,
    })
    print("  Initializing app...")
    app = create_app()

    # 3. Signal ready — loading page JS will see 100% and start polling /health
    _startup_status.update({"stage": "Starting dashboard...", "detail": "", "progress": 100})
    _time.sleep(0.5)  # Let loading page detect 100% and prepare for transition

    # 4. Shut down early loading server so uvicorn can bind the port
    if _loading_server is not None:
        _loading_server.shutdown()
        _loading_server.server_close()
        _loading_server = None
        _time.sleep(0.5)  # Port release

    # 5. Start the real server — loading page's /health poll will detect this
    print()
    uvicorn.run(app, host=s.host, port=s.port, log_level=s.log_level.lower())

if __name__ == "__main__":
    main()
