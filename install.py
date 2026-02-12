#!/usr/bin/env python3
"""
ClawBridge Installer & Setup Wizard
====================================
Cross-platform interactive installer. Downloads dependencies,
walks through configuration, and gets ClawBridge running locally.

Usage:
  python install.py          # Full interactive install
  python install.py --skip-deps   # Skip dependency installation
  python install.py --headless    # Non-interactive with defaults
"""

import os
import sys
import subprocess
import shutil
import json
import time
import platform
import textwrap
from pathlib import Path

# ─── Constants ───
MIN_PYTHON = (3, 10)
SCRIPT_DIR = Path(__file__).parent.resolve()
VENV_DIR = SCRIPT_DIR / ".venv"
WORKSPACE_DIR = SCRIPT_DIR / "workspace"
ENV_FILE = SCRIPT_DIR / ".env"
ENV_EXAMPLE = SCRIPT_DIR / ".env.example"
IS_WINDOWS = platform.system() == "Windows"

# ─── Colors ───
class C:
    """ANSI colors (disabled on Windows without VT support)."""
    _enabled = True
    @classmethod
    def _init(cls):
        if IS_WINDOWS:
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                cls._enabled = False
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    WHITE = "\033[97m"

C._init()

def c(color, text):
    if not C._enabled:
        return text
    return f"{color}{text}{C.RESET}"

def banner():
    art = r"""
   _____ _                 ____       _     _
  / ____| |               |  _ \     (_)   | |
 | |    | | __ ___      __| |_) |_ __ _  __| | __ _  ___
 | |    | |/ _` \ \ /\ / /|  _ <| '__| |/ _` |/ _` |/ _ \
 | |____| | (_| |\ V  V / | |_) | |  | | (_| | (_| |  __/
  \_____|_|\__,_| \_/\_/  |____/|_|  |_|\__,_|\__, |\___|
                                                __/ |
                                               |___/
    """
    print(c(C.CYAN, art))
    print(c(C.BOLD + C.WHITE, "  Interactive Setup Wizard"))
    print(c(C.DIM, "  Your local AI automation hub\n"))

def hr():
    print(c(C.DIM, "  " + "─" * 56))

def ok(msg):
    print(f"  {c(C.GREEN, '✓')} {msg}")

def warn(msg):
    print(f"  {c(C.YELLOW, '!')} {msg}")

def err(msg):
    print(f"  {c(C.RED, '✗')} {msg}")

def info(msg):
    print(f"  {c(C.CYAN, '→')} {msg}")

def step(num, title):
    print()
    print(f"  {c(C.MAGENTA + C.BOLD, f'Step {num}.')} {c(C.BOLD, title)}")
    hr()

def ask(prompt, default=None, secret=False, validate=None):
    """Prompt user for input with optional default and validation."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            if secret:
                import getpass
                val = getpass.getpass(f"  {prompt}{suffix}: ").strip()
            else:
                val = input(f"  {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if not val and default is not None:
            val = default
        if validate and not validate(val):
            continue
        return val

def ask_choice(prompt, choices, default=0):
    """Show numbered choices and return selected value."""
    print(f"  {prompt}")
    for i, (label, value) in enumerate(choices):
        marker = c(C.GREEN, "→") if i == default else " "
        print(f"    {marker} {i + 1}) {label}")
    while True:
        try:
            raw = input(f"  Choice [1-{len(choices)}, default={default + 1}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if not raw:
            return choices[default][1]
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx][1]
        except ValueError:
            pass
        print(f"  {c(C.RED, 'Invalid choice. Try again.')}")

def ask_yn(prompt, default=True):
    """Yes/no prompt."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"  {prompt} {suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    if not raw:
        return default
    return raw in ("y", "yes")

def run(cmd, desc=None, capture=False, check=True):
    """Run a subprocess command."""
    if desc:
        info(desc)
    try:
        result = subprocess.run(
            cmd, shell=isinstance(cmd, str),
            capture_output=capture, text=True,
            check=check, cwd=str(SCRIPT_DIR)
        )
        return result
    except subprocess.CalledProcessError as e:
        if capture:
            return e
        raise

def check_command(cmd):
    """Check if a command exists."""
    return shutil.which(cmd) is not None

# ─── Prerequisite Checks ───

def check_python():
    """Verify Python version."""
    v = sys.version_info
    if v >= MIN_PYTHON:
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    else:
        err(f"Python {v.major}.{v.minor} found — need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
        info("Download: https://www.python.org/downloads/")
        return False

def check_node():
    """Check for Node.js (optional, for OpenClaw)."""
    if not check_command("node"):
        warn("Node.js not found (OpenClaw engine won't be available)")
        info("Install Node 22+: https://nodejs.org/")
        return False
    result = run(["node", "--version"], capture=True, check=False)
    if result.returncode == 0:
        ver = result.stdout.strip()
        ok(f"Node.js {ver}")
        return True
    return False

def check_git():
    """Check for Git."""
    if check_command("git"):
        result = run(["git", "--version"], capture=True, check=False)
        if result.returncode == 0:
            ok(f"Git {result.stdout.strip().replace('git version ', '')}")
            return True
    warn("Git not found (optional, for updates)")
    return False

# ─── Installation Steps ───

def create_venv():
    """Create Python virtual environment."""
    if VENV_DIR.exists():
        ok("Virtual environment already exists")
        return True
    info("Creating virtual environment...")
    result = run([sys.executable, "-m", "venv", str(VENV_DIR)], capture=True, check=False)
    if result.returncode == 0:
        ok("Virtual environment created")
        return True
    else:
        err("Failed to create venv")
        if hasattr(result, 'stderr'):
            print(f"    {result.stderr}")
        return False

def get_pip():
    """Get the pip executable from venv."""
    if IS_WINDOWS:
        return str(VENV_DIR / "Scripts" / "pip.exe")
    return str(VENV_DIR / "bin" / "pip")

def get_python():
    """Get the python executable from venv."""
    if IS_WINDOWS:
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")

def install_deps():
    """Install Python dependencies."""
    pip = get_pip()
    info("Upgrading pip...")
    run([pip, "install", "--upgrade", "pip", "-q"], capture=True, check=False)

    info("Installing dependencies (this may take a few minutes)...")
    result = run([pip, "install", "-r", str(SCRIPT_DIR / "requirements.txt")], check=False)
    if result.returncode == 0:
        ok("Python dependencies installed")
        return True
    else:
        err("Some dependencies failed to install")
        return False

def install_playwright():
    """Install Playwright Chromium browser."""
    py = get_python()
    info("Installing Chromium browser for browser-use engine...")
    result = run([py, "-m", "playwright", "install", "chromium"], check=False)
    if result.returncode == 0:
        ok("Chromium installed")
        return True
    else:
        warn("Playwright chromium install failed — browser-use may not work")
        return False

def install_openclaw():
    """Install OpenClaw globally via npm."""
    info("Installing OpenClaw...")
    result = run(["npm", "install", "-g", "openclaw@latest"], capture=True, check=False)
    if result.returncode == 0:
        ok("OpenClaw installed")
        return True
    else:
        warn("OpenClaw install failed — you can install manually later")
        return False

# ─── Configuration Wizard ───

def wizard():
    """Interactive configuration wizard. Returns dict of env values."""
    config = {}

    step(3, "Configure Your API Keys")
    print()
    info("ClawBridge is BYOK (Bring Your Own Key) — your keys stay local.")
    info("You need at least ONE API key to get started.")
    print()

    # API Keys
    providers = [
        ("Anthropic", "ANTHROPIC_API_KEY", "sk-ant-", "Best for computer-use engine"),
        ("OpenAI", "OPENAI_API_KEY", "sk-", "Best for browser-use engine"),
        ("OpenRouter", "OPENROUTER_API_KEY", "sk-or-", "Access 100+ models with one key"),
    ]

    keys_set = []
    for name, env_key, prefix, desc in providers:
        print(f"  {c(C.BOLD, name)} — {c(C.DIM, desc)}")
        key = ask(f"  {name} API key (Enter to skip)", default="", secret=True)
        if key:
            config[env_key] = key
            keys_set.append(name)
            ok(f"{name} key configured")
        else:
            config[env_key] = ""
        print()

    if not keys_set:
        warn("No API keys provided — you can add them later in the dashboard or .env file")

    # Default Model
    step(4, "Choose Default Model")
    print()
    model_choices = [
        ("GPT-4o (OpenAI — fast, reliable)", "openai/gpt-4o"),
        ("GPT-4o Mini (OpenAI — fast & cheap)", "openai/gpt-4o-mini"),
        ("Claude Sonnet 4 (Anthropic — best for tool use)", "anthropic/claude-sonnet-4-20250514"),
        ("Claude Sonnet 4 via OpenRouter", "anthropic/claude-sonnet-4-20250514"),
    ]

    # Smart default based on which key was provided
    default_model_idx = 0
    if "Anthropic" in keys_set and "OpenAI" not in keys_set:
        default_model_idx = 2

    config["DEFAULT_MODEL"] = ask_choice("Which model should be the default?", model_choices, default=default_model_idx)

    # Engines
    step(5, "Select Engines")
    print()
    info("Engines determine HOW ClawBridge automates tasks:")
    print(f"    {c(C.CYAN, 'browser-use')}  — Headless browser automation (web tasks)")
    print(f"    {c(C.CYAN, 'computer-use')} — Desktop control (clicks, types, screenshots)")
    print(f"    {c(C.CYAN, 'openclaw')}     — Agent-based scripting (requires Node.js)")
    print()

    engines = []
    if ask_yn("Enable browser-use engine?", default=True):
        engines.append("browser_use")
    if ask_yn("Enable computer-use engine?", default=True):
        engines.append("computer_use")
    if check_command("node") and ask_yn("Enable OpenClaw engine?", default=False):
        engines.append("openclaw")

    config["ENABLED_ENGINES"] = ",".join(engines) if engines else "browser_use"

    # Server settings
    step(6, "Server Settings")
    print()
    config["CLAWBRIDGE_HOST"] = ask("Host", default="127.0.0.1")
    config["CLAWBRIDGE_PORT"] = ask("Port", default="8765")

    # Browser mode
    browser_choices = [
        ("Fresh browser each time (no saved logins)", "default"),
        ("Persistent profile (saves logins & cookies)", "user_data_dir"),
        ("Connect to existing Chrome (advanced)", "cdp"),
    ]
    config["BROWSER_MODE"] = ask_choice("Browser mode:", browser_choices, default=0)

    # Policy
    step(7, "Safety Policy")
    print()
    policy_choices = [
        ("Guarded — auto-run safe reads, prompt for risky actions (recommended)", "guarded"),
        ("Strict — prompt for everything except reads", "strict"),
        ("Permissive — auto-run everything (local trust mode)", "permissive"),
    ]
    config["POLICY_MODE"] = ask_choice("Action policy:", policy_choices, default=0)

    # Computer-use model
    if "computer_use" in engines:
        config["COMPUTER_USE_MODEL"] = "anthropic/claude-sonnet-4-20250514"

    return config

def write_env(config):
    """Write .env file from wizard config."""
    # Read template
    if ENV_EXAMPLE.exists():
        template = ENV_EXAMPLE.read_text()
    else:
        template = ""

    # Build .env content
    lines = []
    lines.append("# ClawBridge Configuration")
    lines.append(f"# Generated by setup wizard on {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # Map of all possible keys with defaults from .env.example
    defaults = {}
    if template:
        for line in template.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                defaults[key.strip()] = val.strip()

    # Merge wizard config with defaults
    merged = {**defaults, **config}

    # Write categorized
    categories = {
        "API Keys": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"],
        "Model": ["DEFAULT_MODEL", "COMPUTER_USE_MODEL"],
        "Server": ["CLAWBRIDGE_HOST", "CLAWBRIDGE_PORT"],
        "Engines": ["ENABLED_ENGINES", "OPENCLAW_PATH"],
        "Browser": ["BROWSER_HEADLESS", "BROWSER_MODE", "BROWSER_CDP_URL", "BROWSER_USER_DATA_DIR"],
        "Computer-Use": ["COMPUTER_USE_MAX_SCREEN_WIDTH", "COMPUTER_USE_MAX_SCREEN_HEIGHT", "COMPUTER_USE_ACTION_DELAY_MS"],
        "Policy": ["POLICY_MODE", "MAX_CONCURRENT_TASKS", "MAX_ACTIONS_PER_TASK"],
        "Logging": ["LOG_RETENTION_HOURS", "LOG_LEVEL"],
        "Remote Bridge": ["REMOTE_BRIDGE_URL", "REMOTE_AUTH_TOKEN"],
    }

    written_keys = set()
    for cat_name, keys in categories.items():
        lines.append(f"# ----- {cat_name} -----")
        for key in keys:
            val = merged.get(key, "")
            lines.append(f"{key}={val}")
            written_keys.add(key)
        lines.append("")

    # Write any remaining keys not in categories
    remaining = {k: v for k, v in merged.items() if k not in written_keys}
    if remaining:
        lines.append("# ----- Other -----")
        for k, v in remaining.items():
            lines.append(f"{k}={v}")

    env_content = "\n".join(lines) + "\n"

    # Backup existing .env
    if ENV_FILE.exists():
        backup = ENV_FILE.with_suffix(".env.backup")
        shutil.copy2(ENV_FILE, backup)
        info(f"Existing .env backed up to {backup.name}")

    ENV_FILE.write_text(env_content)
    ok(".env file created")

def create_workspace():
    """Create workspace directories and default files."""
    dirs = [
        WORKSPACE_DIR,
        WORKSPACE_DIR / "memory",
        WORKSPACE_DIR / "templates",
        WORKSPACE_DIR / "schedules",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Default personality files
    defaults = {
        "SOUL.md": textwrap.dedent("""\
            # Soul

            You are ClawBridge, a local AI automation assistant.

            ## Core Truths
            - You run locally on the user's machine — their data never leaves their control
            - You are BYOK (Bring Your Own Key) — the user's API keys are theirs
            - You automate browser and desktop tasks with care and precision
            - You ask before taking risky or irreversible actions

            ## Boundaries
            - Never share API keys or sensitive data
            - Stop and ask if unsure about a destructive action
            - Respect rate limits and be cost-conscious

            ## Vibe
            - Efficient but not cold
            - Technical but not jargon-heavy
            - Helpful without being pushy
            """),
        "IDENTITY.md": textwrap.dedent("""\
            # Identity

            Name: ClawBridge
            Role: Local AI Automation Hub
            Version: 0.1.0

            ## Capabilities
            - Browser automation (web research, form filling, data extraction)
            - Desktop automation (app control, file management, screenshots)
            - Scheduled tasks (cron jobs, recurring automation)
            - Memory (persistent context across sessions)

            ## Style
            - Respond concisely
            - Show your work when running multi-step tasks
            - Use markdown for structured output
            """),
        "USER.md": textwrap.dedent("""\
            # User

            ## Preferences
            - (Add your preferences here)

            ## Projects
            - (Add your active projects here)

            ## Notes
            - (Add any context you want the AI to remember)
            """),
        "MEMORY.md": "# Memory\n\nDurable long-term knowledge. Edit freely — this persists across sessions.\n",
    }

    for filename, content in defaults.items():
        filepath = WORKSPACE_DIR / filename
        if not filepath.exists():
            filepath.write_text(content)

    ok("Workspace initialized")

def create_start_scripts():
    """Create convenient start scripts."""
    # Windows batch file
    if IS_WINDOWS:
        bat = SCRIPT_DIR / "start.bat"
        if not bat.exists():
            bat.write_text(textwrap.dedent("""\
                @echo off
                echo Starting ClawBridge...
                call .venv\\Scripts\\activate.bat
                python clawbridge.py
                pause
                """))
            ok("Created start.bat")

        # PowerShell start script
        ps1 = SCRIPT_DIR / "start.ps1"
        if not ps1.exists():
            ps1.write_text(textwrap.dedent("""\
                # ClawBridge Launcher
                Write-Host "Starting ClawBridge..." -ForegroundColor Cyan
                & .venv\\Scripts\\Activate.ps1
                python clawbridge.py
                """))
            ok("Created start.ps1")
    else:
        # Unix start script
        sh = SCRIPT_DIR / "start.sh"
        if not sh.exists():
            sh.write_text(textwrap.dedent("""\
                #!/usr/bin/env bash
                echo "Starting ClawBridge..."
                source .venv/bin/activate
                python clawbridge.py
                """))
            sh.chmod(0o755)
            ok("Created start.sh")

# ─── Main Install Flow ───

def main():
    skip_deps = "--skip-deps" in sys.argv
    headless = "--headless" in sys.argv

    banner()

    # Step 1: Check prerequisites
    step(1, "Checking Prerequisites")
    print()

    if not check_python():
        err("Cannot continue without Python 3.10+")
        sys.exit(1)

    has_node = check_node()
    check_git()
    print()

    # Step 2: Install dependencies
    if not skip_deps:
        step(2, "Installing Dependencies")
        print()

        if not create_venv():
            err("Cannot continue without virtual environment")
            sys.exit(1)

        if not install_deps():
            if not ask_yn("Continue despite install errors?", default=False):
                sys.exit(1)

        # Playwright
        if ask_yn("Install Chromium for browser-use engine?", default=True) if not headless else True:
            install_playwright()

        # OpenClaw
        if has_node:
            if ask_yn("Install OpenClaw (agent engine)?", default=False) if not headless else False:
                install_openclaw()
    else:
        ok("Skipping dependency installation (--skip-deps)")

    # Step 3-7: Configuration wizard
    if not headless:
        config = wizard()
    else:
        # Headless defaults
        config = {
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", ""),
            "DEFAULT_MODEL": "openai/gpt-4o",
            "ENABLED_ENGINES": "browser_use,computer_use",
            "CLAWBRIDGE_HOST": "127.0.0.1",
            "CLAWBRIDGE_PORT": "8765",
            "BROWSER_MODE": "default",
            "POLICY_MODE": "guarded",
        }

    # Write config
    print()
    step(8 if not headless else 3, "Finalizing Setup")
    print()
    write_env(config)
    create_workspace()
    create_start_scripts()

    # Create logs directory
    (SCRIPT_DIR / "logs").mkdir(exist_ok=True)
    ok("Logs directory ready")

    # Summary
    print()
    hr()
    print()
    print(f"  {c(C.GREEN + C.BOLD, '✓ ClawBridge is ready!')}")
    print()

    host = config.get("CLAWBRIDGE_HOST", "127.0.0.1")
    port = config.get("CLAWBRIDGE_PORT", "8765")

    if IS_WINDOWS:
        print(f"  {c(C.BOLD, 'To start:')}")
        print(f"    {c(C.CYAN, '.\\\\start.bat')}  or  {c(C.CYAN, '.\\\\start.ps1')}")
        print()
        print(f"  {c(C.BOLD, 'Or manually:')}")
        print(f"    {c(C.DIM, '.venv\\\\Scripts\\\\activate')}")
        print(f"    {c(C.DIM, 'python clawbridge.py')}")
    else:
        print(f"  {c(C.BOLD, 'To start:')}")
        print(f"    {c(C.CYAN, './start.sh')}")
        print()
        print(f"  {c(C.BOLD, 'Or manually:')}")
        print(f"    {c(C.DIM, 'source .venv/bin/activate')}")
        print(f"    {c(C.DIM, 'python clawbridge.py')}")

    print()
    print(f"  {c(C.BOLD, 'Dashboard:')} {c(C.CYAN, f'http://{host}:{port}')}")
    print()

    engines = config.get("ENABLED_ENGINES", "browser_use").split(",")
    keys = [k for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"] if config.get(k)]
    print(f"  {c(C.DIM, 'Engines:')}  {', '.join(engines)}")
    print(f"  {c(C.DIM, 'API Keys:')} {len(keys)} configured")
    print(f"  {c(C.DIM, 'Policy:')}   {config.get('POLICY_MODE', 'guarded')}")
    print()

    if not keys:
        warn("No API keys configured — add them in the dashboard or .env file")
        print()

    # Offer to start now
    if not headless:
        if ask_yn("Start ClawBridge now?", default=True):
            print()
            info(f"Starting ClawBridge on http://{host}:{port} ...")
            info("Press Ctrl+C to stop")
            print()
            py = get_python()
            try:
                os.execv(py, [py, str(SCRIPT_DIR / "clawbridge.py")])
            except Exception:
                subprocess.run([py, str(SCRIPT_DIR / "clawbridge.py")])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {c(C.YELLOW, 'Setup cancelled.')}\n")
        sys.exit(1)
