#!/usr/bin/env python3
"""
ClawBridge macOS Build Script — Assembles a self-contained .app bundle.

Creates a macOS .app with embedded Python, all dependencies,
Playwright Chromium, and optional Node.js for OpenClaw.

Usage:
    python build_macos.py                  # Full build
    python build_macos.py --skip-nodejs    # Skip Node.js bundling
    python build_macos.py --skip-playwright # Skip Playwright Chromium download
    python build_macos.py --arch arm64     # Build for specific architecture (arm64 or x64)

Output:
    dist/ClawBridge.app/                   # Self-contained macOS app bundle

Requires macOS to run (uses framework Python and .app bundle structure).
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import tarfile
import tempfile
import platform
from pathlib import Path

if sys.platform != "darwin":
    print("ERROR: This build script must be run on macOS.")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────────────────────

VERSION = "0.5.1"

ROOT = Path(__file__).parent.resolve()
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "ClawBridge.app"
BUNDLE_DIR = APP_DIR / "Contents" / "Resources" / "bundle"

PYTHON_VERSION = "3.12.8"

# Detect architecture
MACHINE = platform.machine()  # arm64 or x86_64
if MACHINE == "arm64":
    NODE_ARCH = "arm64"
elif MACHINE == "x86_64":
    NODE_ARCH = "x64"
else:
    print(f"WARNING: Unknown architecture '{MACHINE}', defaulting to x64")
    NODE_ARCH = "x64"

NODE_VERSION = "22.14.0"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-darwin-{NODE_ARCH}.tar.gz"

# Files to include from project root
PROJECT_FILES = [
    "clawbridge.py",
    "clawbridge_mcp.py",
    ".env.example",
    "LICENSE.txt",
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


def extract_tar_gz(tar_path: Path, dest: Path, strip_top: int = 0):
    """Extract a .tar.gz file. strip_top=1 removes the top-level folder."""
    with tarfile.open(tar_path, "r:gz") as tf:
        if strip_top:
            members = tf.getmembers()
            prefix = members[0].name.split("/")[0] + "/"
            for m in members:
                if m.name.startswith(prefix) and len(m.name) > len(prefix):
                    m.name = m.name[len(prefix):]
                    if m.issym() or m.islnk():
                        if m.linkname.startswith(prefix):
                            m.linkname = m.linkname[len(prefix):]
                    tf.extract(m, str(dest))
        else:
            tf.extractall(str(dest))


# ── Build Steps ─────────────────────────────────────────────────────────────

def step_clean():
    banner("Cleaning previous build")
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
        print(f"    Removed old ClawBridge.app/")
    # Create the full .app structure upfront
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DIR / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    (APP_DIR / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    print("    Created ClawBridge.app/ structure")


def step_python_venv():
    banner("Creating Python virtual environment")

    # Use the system Python (from Homebrew, pyenv, or python.org installer)
    # to create a venv inside the bundle
    venv_dir = BUNDLE_DIR / "python"
    print(f"    Creating venv with {sys.executable}...")
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True, capture_output=True
    )

    python_exe = venv_dir / "bin" / "python"
    pip_exe = venv_dir / "bin" / "pip"

    # Upgrade pip
    print("    Upgrading pip...")
    subprocess.run(
        [str(pip_exe), "install", "--upgrade", "pip", "setuptools"],
        check=True, capture_output=True
    )

    # Install all dependencies
    print("    Installing ClawBridge dependencies (this takes a minute)...")
    req_file = ROOT / "requirements.txt"

    pip_env = os.environ.copy()
    pip_env["PYTHONNOUSERSITE"] = "1"

    result = subprocess.run(
        [str(pip_exe), "install", "-r", str(req_file)],
        capture_output=True, text=True, env=pip_env
    )
    if result.returncode != 0:
        print(f"    [!] pip install failed:\n{result.stderr[:2000]}")
        sys.exit(1)

    # Count installed packages
    site_pkgs = venv_dir / "lib"
    # Find the python3.xx directory inside lib
    py_dirs = list(site_pkgs.glob("python3.*"))
    if py_dirs:
        sp = py_dirs[0] / "site-packages"
        pkg_count = len([d for d in sp.iterdir() if d.is_dir() and not d.name.startswith("_")])
        print(f"    Installed {pkg_count} packages")

    return python_exe


def step_playwright(python_exe: Path):
    banner("Installing Playwright Chromium")
    browsers_dir = BUNDLE_DIR / "playwright_browsers"
    browsers_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
    env["PYTHONNOUSERSITE"] = "1"

    print("    Downloading Chromium (this takes a minute)...")
    result = subprocess.run(
        [str(python_exe), "-m", "playwright", "install", "chromium"],
        env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"    [!] Playwright install failed:\n{result.stderr[:2000]}")
        sys.exit(1)

    total = sum(f.stat().st_size for f in browsers_dir.rglob("*") if f.is_file())
    print(f"    Chromium installed ({total // (1024*1024)} MB)")


def step_nodejs():
    banner(f"Bundling Node.js (for OpenClaw engine, {NODE_ARCH})")
    cache_dir = ROOT / ".build_cache"
    cache_dir.mkdir(exist_ok=True)

    tar_path = cache_dir / f"node-v{NODE_VERSION}-darwin-{NODE_ARCH}.tar.gz"
    download(NODE_URL, tar_path, f"Node.js {NODE_VERSION} ({NODE_ARCH})")

    node_dir = BUNDLE_DIR / "nodejs"
    node_dir.mkdir(exist_ok=True)
    extract_tar_gz(tar_path, node_dir, strip_top=1)

    # Verify
    node_exe = node_dir / "bin" / "node"
    if node_exe.exists():
        print(f"    Node.js bundled ({node_exe.stat().st_size // (1024*1024)} MB)")
    else:
        print("    [!] node not found after extraction!")
        sys.exit(1)

    # Remove bloat
    for name in ["CHANGELOG.md", "README.md", "BUILDING.md"]:
        f = node_dir / name
        if f.exists():
            f.unlink()

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

    # Copy clawbridge/ package (platform abstraction, recorder, perception)
    pkg_src = ROOT / "clawbridge"
    pkg_dst = BUNDLE_DIR / "clawbridge"
    if pkg_src.is_dir():
        shutil.copytree(pkg_src, pkg_dst, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache",
        ))
        pkg_files = sum(1 for _ in pkg_dst.rglob("*.py"))
        print(f"    clawbridge/ ({pkg_files} Python files)")

    # Create default workspace structure
    ws = BUNDLE_DIR / "workspace"
    ws.mkdir(exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    (ws / "templates").mkdir(exist_ok=True)
    (ws / "schedules").mkdir(exist_ok=True)
    print("    workspace/ (with subdirs)")

    # Create logs directory
    (BUNDLE_DIR / "logs").mkdir(exist_ok=True)
    print("    logs/")


def step_app_metadata():
    banner("Writing .app metadata")

    contents = APP_DIR / "Contents"
    resources_dir = contents / "Resources"

    # Info.plist
    info_plist = contents / "Info.plist"
    info_plist.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>ClawBridge</string>
    <key>CFBundleDisplayName</key>
    <string>ClawBridge</string>
    <key>CFBundleIdentifier</key>
    <string>ai.clawbridge.app</string>
    <key>CFBundleVersion</key>
    <string>{VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>{VERSION}</string>
    <key>CFBundleExecutable</key>
    <string>ClawBridge</string>
    <key>CFBundleIconFile</key>
    <string>clawbridge</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
    <key>NSAppleEventsUsageDescription</key>
    <string>ClawBridge uses AppleScript to activate applications and automate desktop tasks.</string>
</dict>
</plist>
""")
    print("    Info.plist")

    # Copy icon if available
    for icon_name in ("clawbridge.icns",):
        src = ROOT / icon_name
        if src.exists():
            shutil.copy2(src, resources_dir / icon_name)
            print(f"    {icon_name} -> Resources/")

    # Launcher script — finds bundle dir relative to itself inside the .app
    launcher = contents / "MacOS" / "ClawBridge"
    launcher.write_text(
        '#!/usr/bin/env bash\n'
        'CONTENTS_DIR="$(cd "$(dirname "$0")/.." && pwd)"\n'
        'BUNDLE_DIR="$CONTENTS_DIR/Resources/bundle"\n'
        'export PLAYWRIGHT_BROWSERS_PATH="$BUNDLE_DIR/playwright_browsers"\n'
        'export PATH="$BUNDLE_DIR/nodejs/bin:$BUNDLE_DIR/python/bin:$PATH"\n'
        'export CLAWBRIDGE_OPEN_BROWSER=1\n'
        '# Redirect to log file in bundle\n'
        'exec "$BUNDLE_DIR/python/bin/python" "$BUNDLE_DIR/clawbridge.py" \\\n'
        '  > "$BUNDLE_DIR/logs/app_stdout.log" 2> "$BUNDLE_DIR/logs/app_stderr.log"\n'
    )
    launcher.chmod(0o755)
    print("    MacOS/ClawBridge (launcher)")


def step_summary():
    banner("Build complete!")

    total = sum(f.stat().st_size for f in APP_DIR.rglob("*") if f.is_file())
    total_mb = total / (1024 * 1024)

    print(f"    Output:  {APP_DIR}")
    print(f"    Size:    {total_mb:.0f} MB")
    print(f"    Arch:    {NODE_ARCH}")
    print()
    print("    Bundle contents (Resources/bundle/):")
    for item in sorted(BUNDLE_DIR.iterdir()):
        if item.is_dir():
            dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            print(f"      {item.name + '/':30s} {dir_size // (1024*1024):>5d} MB")
        else:
            print(f"      {item.name:30s} {item.stat().st_size // 1024:>5d} KB")
    print()
    print("    Next steps:")
    print("      1. Test:  open dist/ClawBridge.app")
    print("      2. Pack:  pip install dmgbuild && dmgbuild -s dmg_settings.py 'ClawBridge' dist/ClawBridge.dmg")
    print("      3. Ship:  Distribute the .dmg")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build ClawBridge macOS .app bundle")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--skip-nodejs", action="store_true", help="Skip Node.js bundling")
    parser.add_argument("--skip-playwright", action="store_true", help="Skip Playwright Chromium")
    parser.add_argument("--arch", choices=["arm64", "x64"], default=None,
                        help="Target architecture (default: auto-detect)")
    args = parser.parse_args()

    if args.version:
        print(f"ClawBridge macOS Build System v{VERSION}")
        sys.exit(0)

    if args.arch:
        global NODE_ARCH, NODE_URL
        NODE_ARCH = args.arch
        NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-darwin-{NODE_ARCH}.tar.gz"

    print()
    print("  ==========================================")
    print("       ClawBridge Build System")
    print("       macOS .app Bundle")
    print(f"       Architecture: {NODE_ARCH}")
    print("  ==========================================")

    step_clean()
    python_exe = step_python_venv()

    if not args.skip_playwright:
        step_playwright(python_exe)
    else:
        print("\n  [skip] Playwright Chromium (--skip-playwright)")

    if not args.skip_nodejs:
        step_nodejs()
    else:
        print("\n  [skip] Node.js (--skip-nodejs)")

    step_project_files()
    step_app_metadata()
    step_summary()


if __name__ == "__main__":
    main()
