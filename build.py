"""ClawBridge build script -- creates a distributable binary using PyInstaller.

Usage:
    python build.py

Output:
    dist/clawbridge.exe  (Windows)
    dist/clawbridge      (Mac/Linux)

The binary bundles the Python runtime, all dependencies, and the web dashboard
into a single executable. Your friend runs it and opens localhost:8765.
"""

import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build_temp"


def build():
    print("=" * 50)
    print("  ClawBridge Build")
    print("=" * 50)
    print()

    # Ensure PyInstaller is available
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("  [!] PyInstaller not installed. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Build command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "clawbridge",
        "--onefile",
        "--console",  # Keep console for logging output
        "--workpath", str(BUILD_DIR),
        "--distpath", str(DIST_DIR),
        # Include LICENSE
        "--add-data", f"{ROOT / 'LICENSE.txt'}{os.pathsep}.",
        # Hidden imports that PyInstaller may miss
        "--hidden-import", "clawbridge.server.routes.tasks",
        "--hidden-import", "clawbridge.server.routes.engines",
        "--hidden-import", "clawbridge.server.routes.config_routes",
        "--hidden-import", "clawbridge.server.routes.ws",
        "--hidden-import", "clawbridge.engines.browser_use_engine",
        "--hidden-import", "clawbridge.engines.openclaw_engine",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        # Entry point
        str(ROOT / "clawbridge.py"),
    ]

    print(f"  Building binary...")
    print(f"  Output: {DIST_DIR}")
    print()

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print()
        print("=" * 50)
        print("  Build successful!")
        print(f"  Binary: {DIST_DIR / 'clawbridge'}")
        print()
        print("  To distribute:")
        print(f"    1. Copy {DIST_DIR / 'clawbridge'} + .env.example to your friend")
        print("    2. They rename .env.example -> .env and add their API key")
        print("    3. They run the binary and open localhost:8765")
        print("=" * 50)
    else:
        print()
        print("  [!] Build failed. Check output above for errors.")
        sys.exit(1)


if __name__ == "__main__":
    build()
