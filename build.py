#!/usr/bin/env python3
"""
ClawBridge Build Script — Assembles a portable Windows distribution.

Creates a self-contained folder with embedded Python, all dependencies,
Playwright Chromium, and optional Node.js for OpenClaw.

Usage:
    python build.py                  # Full build
    python build.py --skip-nodejs    # Skip Node.js bundling
    python build.py --skip-playwright # Skip Playwright Chromium download

Output:
    dist/ClawBridge/                 # Portable folder (ready to ZIP or wrap in Inno Setup)

The folder is 100% self-contained. User just runs ClawBridge.bat.
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
import tarfile
import tempfile
import json
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

VERSION = "0.5.3"

ROOT = Path(__file__).parent.resolve()
DIST_DIR = ROOT / "dist"
BUNDLE_DIR = DIST_DIR / "ClawBridge"

PYTHON_VERSION = "3.12.8"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"

NODE_VERSION = "22.14.0"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip"

# Files to include from project root
PROJECT_FILES = [
    "clawbridge.py",
    "clawbridge_mcp.py",
    ".env.example",
    "LICENSE.txt",
    "clawbridge.ico",
    "requirements.txt",
    "loading.html",
]

# ── Helpers ─────────────────────────────────────────────────────────────────

def banner(msg: str):
    print()
    print(f"  {'-' * 50}")
    print(f"  {msg}")
    print(f"  {'-' * 50}")

def download(url: str, dest: Path, label: str = ""):
    if dest.exists():
        print(f"    [cached] {dest.name}")
        return
    print(f"    Downloading {label or url}...")
    urllib.request.urlretrieve(url, str(dest))
    print(f"    -> {dest.name} ({dest.stat().st_size // (1024*1024)} MB)")

def extract_zip(zip_path: Path, dest: Path, strip_top: int = 0):
    """Extract a ZIP file. strip_top=1 removes the top-level folder."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        if strip_top:
            members = zf.namelist()
            prefix = members[0].split("/")[0] + "/"
            for m in members:
                if m.startswith(prefix) and len(m) > len(prefix):
                    target = dest / m[len(prefix):]
                    if m.endswith("/"):
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(m) as src, open(target, "wb") as dst:
                            dst.write(src.read())
        else:
            zf.extractall(str(dest))


# ── Build Steps ─────────────────────────────────────────────────────────────

def step_clean():
    banner("Cleaning previous build")
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)
        print("    Removed old dist/ClawBridge/")
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    print("    Created dist/ClawBridge/")


def step_python_embedded():
    banner("Embedding Python runtime")
    cache_dir = ROOT / ".build_cache"
    cache_dir.mkdir(exist_ok=True)

    zip_path = cache_dir / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    download(PYTHON_EMBED_URL, zip_path, f"Python {PYTHON_VERSION} embeddable")

    py_dir = BUNDLE_DIR / "python"
    py_dir.mkdir(exist_ok=True)
    extract_zip(zip_path, py_dir)

    # Enable pip: modify python312._pth to uncomment import site
    pth_files = list(py_dir.glob("python*._pth"))
    if pth_files:
        pth = pth_files[0]
        content = pth.read_text()
        # Uncomment "import site" and add Lib\site-packages
        lines = content.splitlines()
        new_lines = []
        for line in lines:
            if line.strip() == "#import site":
                new_lines.append("import site")
            else:
                new_lines.append(line)
        if "Lib\\site-packages" not in content:
            new_lines.append("Lib\\site-packages")
        # Add app root (parent of python/) so `from clawbridge.recorder...` works
        if ".." not in new_lines:
            new_lines.append("..")
        pth.write_text("\n".join(new_lines))
        print(f"    Patched {pth.name} to enable pip/site-packages + app root")

    # Install pip into embedded Python
    print("    Installing pip into embedded Python...")
    get_pip = cache_dir / "get-pip.py"
    if not get_pip.exists():
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", str(get_pip))
    python_exe = py_dir / "python.exe"
    subprocess.run(
        [str(python_exe), str(get_pip), "--no-warn-script-location"],
        check=True, capture_output=True
    )
    print("    pip installed")

    # Upgrade setuptools + pip to avoid build failures on user machines
    # (embedded Python ships with minimal/broken setuptools)
    print("    Upgrading setuptools and pip...")
    subprocess.run(
        [str(python_exe), "-m", "pip", "install", "--upgrade",
         "setuptools", "pip", "--no-warn-script-location", "--disable-pip-version-check"],
        check=True, capture_output=True
    )
    print("    setuptools and pip upgraded")

    # Install all dependencies
    # Use --ignore-installed to force install into embedded Python even if
    # packages exist in user's global site-packages
    print("    Installing ClawBridge dependencies (this takes a minute)...")
    req_file = ROOT / "requirements.txt"

    # Set environment to isolate from user site-packages
    pip_env = os.environ.copy()
    pip_env["PYTHONNOUSERSITE"] = "1"  # Disable user site-packages

    result = subprocess.run(
        [str(python_exe), "-m", "pip", "install", "-r", str(req_file),
         "--no-warn-script-location", "--disable-pip-version-check",
         "--ignore-installed"],
        capture_output=True, text=True, env=pip_env
    )
    if result.returncode != 0:
        print(f"    [!] pip install failed:\n{result.stderr[:2000]}")
        sys.exit(1)

    # Count installed packages
    site_pkgs = py_dir / "Lib" / "site-packages"
    pkg_count = len([d for d in site_pkgs.iterdir() if d.is_dir() and not d.name.startswith("_")])
    print(f"    Installed {pkg_count} packages into embedded Python")

    return python_exe


def step_playwright(python_exe: Path):
    banner("Installing Playwright Chromium")
    browsers_dir = BUNDLE_DIR / "playwright_browsers"
    browsers_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
    env["PYTHONNOUSERSITE"] = "1"  # Use only embedded Python packages

    print("    Downloading Chromium (this takes a minute)...")
    result = subprocess.run(
        [str(python_exe), "-m", "playwright", "install", "chromium"],
        env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"    [!] Playwright install failed:\n{result.stderr[:2000]}")
        sys.exit(1)

    # Calculate Chromium size
    total = sum(f.stat().st_size for f in browsers_dir.rglob("*") if f.is_file())
    print(f"    Chromium installed ({total // (1024*1024)} MB)")


def step_nodejs():
    banner("Bundling Node.js (for OpenClaw engine)")
    cache_dir = ROOT / ".build_cache"
    cache_dir.mkdir(exist_ok=True)

    zip_path = cache_dir / f"node-v{NODE_VERSION}-win-x64.zip"
    download(NODE_URL, zip_path, f"Node.js {NODE_VERSION}")

    node_dir = BUNDLE_DIR / "nodejs"
    node_dir.mkdir(exist_ok=True)
    extract_zip(zip_path, node_dir, strip_top=1)

    # Verify
    node_exe = node_dir / "node.exe"
    if node_exe.exists():
        print(f"    Node.js bundled ({node_exe.stat().st_size // (1024*1024)} MB)")
    else:
        print("    [!] node.exe not found after extraction!")
        sys.exit(1)

    # Remove bloat from Node.js distribution
    for name in ["CHANGELOG.md", "README.md", "BUILDING.md"]:
        f = node_dir / name
        if f.exists():
            f.unlink()

    # NOTE: We do NOT pre-install OpenClaw here (~1.1 GB of node_modules).
    # The dashboard has an "Install OpenClaw" button that installs on demand.
    print("    OpenClaw will be installed on first use via dashboard")


def step_project_files():
    banner("Copying project files")
    for fname in PROJECT_FILES:
        src = ROOT / fname
        if src.exists():
            shutil.copy2(src, BUNDLE_DIR / fname)
            print(f"    {fname}")
        else:
            print(f"    [skip] {fname} (not found)")

    # Copy clawbridge package (recorder, etc.)
    pkg_src = ROOT / "clawbridge"
    pkg_dst = BUNDLE_DIR / "clawbridge"
    if pkg_src.exists():
        shutil.copytree(pkg_src, pkg_dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        print("    clawbridge/ (package)")
    else:
        print("    [skip] clawbridge/ (not found)")

    # Create default workspace structure
    ws = BUNDLE_DIR / "workspace"
    ws.mkdir(exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    (ws / "templates").mkdir(exist_ok=True)
    (ws / "schedules").mkdir(exist_ok=True)
    (ws / "workflows").mkdir(exist_ok=True)
    print("    workspace/ (with subdirs)")

    # Copy default personality files if they exist
    ws_src = ROOT / "workspace"
    for md_name in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"):
        md_src = ws_src / md_name
        if md_src.exists():
            shutil.copy2(md_src, ws / md_name)
            print(f"    workspace/{md_name}")

    # Create logs directory
    (BUNDLE_DIR / "logs").mkdir(exist_ok=True)
    print("    logs/")


def step_launcher_scripts():
    banner("Creating launcher scripts")

    # run.bat — console mode (shows logs)
    run_bat = BUNDLE_DIR / "run.bat"
    run_bat.write_text(
        '@echo off\r\n'
        'title ClawBridge\r\n'
        'cd /d "%~dp0"\r\n'
        'set PLAYWRIGHT_BROWSERS_PATH=%~dp0playwright_browsers\r\n'
        'set PATH=%~dp0nodejs;%~dp0python\\Scripts;%PATH%\r\n'
        '"%~dp0python\\python.exe" clawbridge.py\r\n'
        'if errorlevel 1 (\r\n'
        '    echo.\r\n'
        '    echo ClawBridge exited with an error. Check logs/ for details.\r\n'
        '    pause\r\n'
        ')\r\n',
        encoding="utf-8"
    )
    print("    run.bat (console mode)")

    # ClawBridge.bat — windowless mode (Python opens browser after loading server starts)
    cb_bat = BUNDLE_DIR / "ClawBridge.bat"
    cb_bat.write_text(
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        'set PLAYWRIGHT_BROWSERS_PATH=%~dp0playwright_browsers\r\n'
        'set PATH=%~dp0nodejs;%~dp0python\\Scripts;%PATH%\r\n'
        'set CLAWBRIDGE_OPEN_BROWSER=1\r\n'
        '"%~dp0python\\pythonw.exe" "%~dp0clawbridge.py"\r\n',
        encoding="utf-8"
    )
    print("    ClawBridge.bat (windowless/tray mode + auto-open browser)")

    # update.bat — re-install deps (for manual updates)
    update_bat = BUNDLE_DIR / "update.bat"
    update_bat.write_text(
        '@echo off\r\n'
        'title ClawBridge Update\r\n'
        'cd /d "%~dp0"\r\n'
        'echo Updating ClawBridge dependencies...\r\n'
        '"%~dp0python\\python.exe" -m pip install -r requirements.txt '
        '--no-warn-script-location --disable-pip-version-check\r\n'
        'echo.\r\n'
        'echo Updating Playwright Chromium...\r\n'
        'set PLAYWRIGHT_BROWSERS_PATH=%~dp0playwright_browsers\r\n'
        '"%~dp0python\\python.exe" -m playwright install chromium\r\n'
        'echo.\r\n'
        'echo Done! You can close this window.\r\n'
        'pause\r\n',
        encoding="utf-8"
    )
    print("    update.bat (dependency updater)")

    # install_openclaw.bat — used by Inno Setup post-install task
    oc_bat = BUNDLE_DIR / "install_openclaw.bat"
    oc_bat.write_text(
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        'set PATH=%~dp0nodejs;%PATH%\r\n'
        '"%~dp0nodejs\\npm.cmd" install -g openclaw@latest\r\n',
        encoding="utf-8"
    )
    print("    install_openclaw.bat (OpenClaw installer)")


def step_summary():
    banner("Build complete!")

    # Calculate total size
    total = sum(f.stat().st_size for f in BUNDLE_DIR.rglob("*") if f.is_file())
    total_mb = total / (1024 * 1024)

    print(f"    Output:  {BUNDLE_DIR}")
    print(f"    Size:    {total_mb:.0f} MB")
    print()
    print("    Contents:")
    for item in sorted(BUNDLE_DIR.iterdir()):
        if item.is_dir():
            dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            print(f"      {item.name + '/':30s} {dir_size // (1024*1024):>5d} MB")
        else:
            print(f"      {item.name:30s} {item.stat().st_size // 1024:>5d} KB")
    print()
    print("    Next steps:")
    print("      1. Test:  cd dist\\ClawBridge && run.bat")
    print("      2. Pack:  python build.py --inno  (creates Setup.exe)")
    print("      3. Ship:  ZIP the folder or distribute the installer")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build ClawBridge portable distribution")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--skip-nodejs", action="store_true", help="Skip Node.js bundling")
    parser.add_argument("--skip-playwright", action="store_true", help="Skip Playwright Chromium")
    parser.add_argument("--inno", action="store_true", help="Run Inno Setup after building")
    args = parser.parse_args()

    if args.version:
        print(f"ClawBridge Build System v{VERSION}")
        sys.exit(0)

    print()
    print("  ==========================================")
    print("       ClawBridge Build System")
    print("       Portable Windows Distribution")
    print("  ==========================================")

    step_clean()
    python_exe = step_python_embedded()

    if not args.skip_playwright:
        step_playwright(python_exe)
    else:
        print("\n  [skip] Playwright Chromium (--skip-playwright)")

    if not args.skip_nodejs:
        step_nodejs()
    else:
        print("\n  [skip] Node.js (--skip-nodejs)")

    step_project_files()
    step_launcher_scripts()
    step_summary()

    if args.inno:
        banner("Running Inno Setup Compiler")
        iss_file = ROOT / "installer.iss"
        if not iss_file.exists():
            print("    [!] installer.iss not found!")
            sys.exit(1)
        iscc = shutil.which("ISCC") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if not Path(iscc).exists():
            print(f"    [!] Inno Setup compiler not found at: {iscc}")
            print("    Install from: https://jrsoftware.org/isdl.php")
            sys.exit(1)
        subprocess.run([iscc, str(iss_file)], check=True)
        print("    Installer built!")


if __name__ == "__main__":
    main()
