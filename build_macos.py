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

VERSION = "0.5.7"

ROOT = Path(__file__).parent.resolve()
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "ClawBridge.app"
BUNDLE_DIR = APP_DIR / "Contents" / "Resources" / "bundle"

PYTHON_VERSION = "3.12.9"
PBS_RELEASE = "20250317"  # python-build-standalone release tag

# Detect architecture
MACHINE = platform.machine()  # arm64 or x86_64
if MACHINE == "arm64":
    NODE_ARCH = "arm64"
    PBS_ARCH = "aarch64"
elif MACHINE == "x86_64":
    NODE_ARCH = "x64"
    PBS_ARCH = "x86_64"
else:
    print(f"WARNING: Unknown architecture '{MACHINE}', defaulting to x64")
    NODE_ARCH = "x64"
    PBS_ARCH = "x86_64"

PBS_URL = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}/"
    f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-{PBS_ARCH}-apple-darwin-install_only_stripped.tar.gz"
)

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


def step_python():
    banner("Installing standalone Python")

    cache_dir = ROOT / ".build_cache"
    cache_dir.mkdir(exist_ok=True)
    tar_name = f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-{PBS_ARCH}-apple-darwin-install_only_stripped.tar.gz"
    tar_path = cache_dir / tar_name

    # Download python-build-standalone (fully relocatable, no framework dependency)
    download(PBS_URL, tar_path, f"Python {PYTHON_VERSION} ({PBS_ARCH})")

    # Extract — the tarball contains a `python/` directory at the root
    python_dir = BUNDLE_DIR / "python"
    print("    Extracting...")
    extract_tar_gz(tar_path, BUNDLE_DIR, strip_top=0)
    # python-build-standalone extracts to install/ — rename to python/
    extracted = BUNDLE_DIR / "python"
    if not extracted.exists():
        # Some builds extract to "install/" instead
        alt = BUNDLE_DIR / "install"
        if alt.exists():
            alt.rename(extracted)
        else:
            print("    [!] Unexpected archive structure, listing contents:")
            for item in BUNDLE_DIR.iterdir():
                print(f"        {item.name}")
            sys.exit(1)

    python_exe = python_dir / "bin" / "python3"
    if not python_exe.exists():
        python_exe = python_dir / "bin" / f"python{'.'.join(PYTHON_VERSION.split('.')[:2])}"
    if not python_exe.exists():
        print(f"    [!] Python binary not found in {python_dir / 'bin'}")
        sys.exit(1)

    py_size = sum(f.stat().st_size for f in python_dir.rglob("*") if f.is_file())
    print(f"    Python {PYTHON_VERSION} standalone ({py_size // (1024*1024)} MB)")

    # Install pip (standalone Python may not include it)
    pip_exe = python_dir / "bin" / "pip3"
    if not pip_exe.exists():
        print("    Installing pip...")
        subprocess.run(
            [str(python_exe), "-m", "ensurepip", "--upgrade"],
            check=True, capture_output=True
        )
        pip_exe = python_dir / "bin" / "pip3"

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
    py_ver = ".".join(PYTHON_VERSION.split(".")[:2])
    sp = python_dir / "lib" / f"python{py_ver}" / "site-packages"
    if sp.exists():
        pkg_count = len([d for d in sp.iterdir() if d.is_dir() and not d.name.startswith("_")])
        print(f"    Installed {pkg_count} packages")

    # Remove unnecessary files to save space
    for name in ("test", "tests", "idlelib", "tkinter", "turtledemo"):
        d = python_dir / "lib" / f"python{py_ver}" / name
        if d.exists():
            shutil.rmtree(d)
    # Remove __pycache__ dirs
    for pc in python_dir.rglob("__pycache__"):
        if pc.is_dir():
            shutil.rmtree(pc)

    return python_exe


def step_codesign_python():
    """Ad-hoc re-sign all Python binaries and extensions.

    python-build-standalone is already relocatable, but macOS may reject
    binaries without valid code signatures. Ad-hoc signing fixes this.
    """
    banner("Code-signing Python binaries")

    resigned = 0
    python_dir = BUNDLE_DIR / "python"

    # Sign all Mach-O binaries, .so, and .dylib files
    for pattern in ("bin/*", "lib/**/*.so", "lib/**/*.dylib"):
        for f in python_dir.glob(pattern):
            if f.is_symlink() or not f.is_file():
                continue
            subprocess.run(
                ["codesign", "--force", "--sign", "-", str(f)],
                capture_output=True
            )
            resigned += 1

    print(f"    Re-signed {resigned} files (ad-hoc)")


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


def step_icon(python_exe: Path):
    banner("Generating .icns icon")

    # Look for source PNG (prefer assets/logo.png, fall back to transparentlogo.png)
    logo_src = None
    for candidate in ("assets/logo.png", "transparentlogo.png", "clawbridge.png"):
        p = ROOT / candidate
        if p.exists():
            logo_src = p
            break

    if logo_src is None:
        print("    [skip] No source logo found (assets/logo.png, transparentlogo.png)")
        return

    print(f"    Source: {logo_src.name}")

    # Pre-process: trim transparent padding and center on 1024x1024 canvas
    # Uses Pillow from the venv (already installed via requirements.txt)
    trimmed = DIST_DIR / "_icon_trimmed.png"
    trim_script = (
        "from PIL import Image\n"
        f"img = Image.open(r'{logo_src}')\n"
        "bbox = img.getbbox()\n"
        "if bbox:\n"
        "    cropped = img.crop(bbox)\n"
        "    w, h = cropped.size\n"
        "    # Fit into 1024x1024 with minimal padding (~2.5% each side)\n"
        "    target = 1024\n"
        "    content_size = int(target * 0.95)\n"
        "    scale = content_size / max(w, h)\n"
        "    new_w, new_h = int(w * scale), int(h * scale)\n"
        "    resized = cropped.resize((new_w, new_h), Image.LANCZOS)\n"
        "    canvas = Image.new('RGBA', (target, target), (0, 0, 0, 0))\n"
        "    x = (target - new_w) // 2\n"
        "    y = (target - new_h) // 2\n"
        "    canvas.paste(resized, (x, y))\n"
        "    canvas.save(r'" + str(trimmed) + "')\n"
        "    print(f'Trimmed: {w}x{h} -> {new_w}x{new_h} centered on {target}x{target}')\n"
    )
    result = subprocess.run(
        [str(python_exe), "-c", trim_script],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not trimmed.exists():
        print(f"    [warn] Trim failed ({result.stderr[:200]}), using original")
        trimmed = logo_src
    else:
        print(f"    {result.stdout.strip()}")

    # Create iconset directory with required sizes
    iconset = DIST_DIR / "ClawBridge.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    # macOS .icns requires these exact sizes
    sizes = [16, 32, 64, 128, 256, 512]
    for size in sizes:
        # Standard resolution
        out = iconset / f"icon_{size}x{size}.png"
        subprocess.run(
            ["sips", "-z", str(size), str(size), str(trimmed), "--out", str(out)],
            check=True, capture_output=True
        )
        # Retina (@2x) — the next size up labeled as @2x of current
        out2x = iconset / f"icon_{size}x{size}@2x.png"
        retina_size = size * 2
        subprocess.run(
            ["sips", "-z", str(retina_size), str(retina_size), str(trimmed), "--out", str(out2x)],
            check=True, capture_output=True
        )

    # Convert iconset to .icns
    icns_path = APP_DIR / "Contents" / "Resources" / "clawbridge.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
        check=True, capture_output=True
    )

    # Cleanup
    shutil.rmtree(iconset)
    if trimmed != logo_src and trimmed.exists():
        trimmed.unlink()
    print(f"    Generated clawbridge.icns ({icns_path.stat().st_size // 1024} KB)")


def step_app_metadata():
    banner("Writing .app metadata")

    contents = APP_DIR / "Contents"
    resources_dir = contents / "Resources"

    # Info.plist
    # LSArchitecturePriority prevents Finder from launching bash under Rosetta
    # which corrupts platform.processor() and breaks rubicon-objc's ARM64 guard
    plist_arch = "arm64" if NODE_ARCH == "arm64" else "x86_64"
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
    <key>LSArchitecturePriority</key>
    <array>
        <string>{plist_arch}</string>
    </array>
    <key>NSAppleEventsUsageDescription</key>
    <string>ClawBridge uses AppleScript to activate applications and automate desktop tasks.</string>
</dict>
</plist>
""")
    print("    Info.plist")

    # Launcher script — finds bundle dir relative to itself inside the .app
    # Handles: quarantine stripping, dylib loading, error dialogs
    launcher = contents / "MacOS" / "ClawBridge"
    launcher.write_text(
        '#!/usr/bin/env bash\n'
        'CONTENTS_DIR="$(cd "$(dirname "$0")/.." && pwd)"\n'
        'BUNDLE_DIR="$CONTENTS_DIR/Resources/bundle"\n'
        'LOG_DIR="$BUNDLE_DIR/logs"\n'
        'mkdir -p "$LOG_DIR"\n'
        '\n'
        '# Strip quarantine attributes — needed for unsigned apps downloaded from internet.\n'
        '# Try without sudo first; if that fails (permissions), prompt via osascript.\n'
        'if xattr -r -l "$CONTENTS_DIR" 2>/dev/null | grep -q "com.apple.quarantine"; then\n'
        '  xattr -cr "$CONTENTS_DIR" 2>/dev/null || \\\n'
        '    osascript -e "do shell script \\"xattr -cr \'$CONTENTS_DIR\'\\" with administrator privileges" 2>/dev/null || true\n'
        'fi\n'
        '\n'
        'export PLAYWRIGHT_BROWSERS_PATH="$BUNDLE_DIR/playwright_browsers"\n'
        'export PATH="$BUNDLE_DIR/nodejs/bin:$BUNDLE_DIR/python/bin:$PATH"\n'
        'export CLAWBRIDGE_OPEN_BROWSER=1\n'
        '\n'
        '# Python standalone — set PYTHONHOME so it finds stdlib + site-packages\n'
        'export PYTHONHOME="$BUNDLE_DIR/python"\n'
        '\n'
        '# macOS .app bundles start with cwd / (read-only). Set workspace path\n'
        '# inside the bundle and cd to $HOME so relative paths work.\n'
        'export CLAWBRIDGE_WORKSPACE="${CLAWBRIDGE_WORKSPACE:-$BUNDLE_DIR/workspace}"\n'
        'cd "$HOME"\n'
        '\n'
        '# Check that the bundle exists\n'
        'if [ ! -f "$BUNDLE_DIR/clawbridge.py" ]; then\n'
        '  osascript -e \'display dialog "ClawBridge failed to start.\\n\\n'
        'The application bundle is missing or corrupted.\\n'
        'Try re-downloading from clawbridge.ai/download" '
        'with title "ClawBridge" buttons {"OK"} default button "OK" with icon stop\'\n'
        '  exit 1\n'
        'fi\n'
        '\n'
        '# Kill any stale ClawBridge process still holding port 8765\n'
        'lsof -ti:8765 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true\n'
        'sleep 0.5\n'
        '\n'
        '# Run ClawBridge, capture exit code\n'
        '"$BUNDLE_DIR/python/bin/python3" "$BUNDLE_DIR/clawbridge.py" \\\n'
        '  > "$LOG_DIR/app_stdout.log" 2> "$LOG_DIR/app_stderr.log"\n'
        'EXIT_CODE=$?\n'
        '\n'
        '# Show error dialog if it crashed\n'
        'if [ $EXIT_CODE -ne 0 ]; then\n'
        '  ERR_TAIL=$(tail -5 "$LOG_DIR/app_stderr.log" 2>/dev/null || echo "No error log")\n'
        '  osascript -e "display dialog \\"ClawBridge exited with an error (code $EXIT_CODE).\\n\\n$ERR_TAIL\\n\\nFull log: $LOG_DIR/app_stderr.log\\" '
        'with title \\"ClawBridge\\" buttons {\\"Open Log\\", \\"OK\\"} default button \\"OK\\" with icon stop" \\\n'
        '    -e "set btn to button returned of result" \\\n'
        '    -e "if btn is \\"Open Log\\" then" \\\n'
        '    -e "  do shell script \\"open \\\\\\"$LOG_DIR/app_stderr.log\\\\\\"\\"" \\\n'
        '    -e "end if"\n'
        'fi\n'
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
        global NODE_ARCH, NODE_URL, PBS_ARCH, PBS_URL
        NODE_ARCH = args.arch
        NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-darwin-{NODE_ARCH}.tar.gz"
        # Also update Python standalone arch
        PBS_ARCH = "aarch64" if args.arch == "arm64" else "x86_64"
        PBS_URL = (
            f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}/"
            f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-{PBS_ARCH}-apple-darwin-install_only_stripped.tar.gz"
        )

    print()
    print("  ==========================================")
    print("       ClawBridge Build System")
    print("       macOS .app Bundle")
    print(f"       Architecture: {NODE_ARCH}")
    print("  ==========================================")

    step_clean()
    python_exe = step_python()

    if not args.skip_playwright:
        step_playwright(python_exe)
    else:
        print("\n  [skip] Playwright Chromium (--skip-playwright)")

    if not args.skip_nodejs:
        step_nodejs()
    else:
        print("\n  [skip] Node.js (--skip-nodejs)")

    step_project_files()
    step_icon(python_exe)
    step_app_metadata()
    step_codesign_python()

    step_summary()


if __name__ == "__main__":
    main()
