"""
dmgbuild settings for ClawBridge macOS installer.

Usage:
    pip install dmgbuild
    dmgbuild -s dmg_settings.py "ClawBridge" dist/ClawBridge.dmg

Docs: https://dmgbuild.readthedocs.io/
"""

import os
from pathlib import Path

try:
    ROOT = Path(__file__).parent.resolve()
except NameError:
    # dmgbuild loads this file via exec() where __file__ is not defined
    ROOT = Path.cwd()

# ── Volume Settings ─────────────────────────────────────────────────────────

# Volume name shown in Finder title bar when mounted
volume_name = "ClawBridge"

# Disk image format: UDBZ = bzip2 compressed (good balance of size and speed)
format = "UDBZ"

# Volume size — None means auto-calculate from contents
size = None

# ── Files to Include ────────────────────────────────────────────────────────

# Only the self-contained .app bundle (everything is inside it)
files = [
    str(ROOT / "dist" / "ClawBridge.app"),
]

# Symlink to /Applications for drag-and-drop install
symlinks = {
    "Applications": "/Applications",
}

# ── Window Appearance ───────────────────────────────────────────────────────

# Window position and size when the DMG is opened
window_rect = ((200, 120), (540, 380))

# Icon size in the DMG window
icon_size = 128

# Icon positions — classic 2-item layout: app on left, Applications on right
icon_locations = {
    "ClawBridge.app": (140, 160),
    "Applications": (400, 160),
}

# Background color (no background image by default — keeps it simple)
background_color = "#1a1a2e"

# Text size for icon labels
text_size = 14

# ── Volume Icon ─────────────────────────────────────────────────────────────

# Use the app icon for the volume icon too
icon_file = str(ROOT / "clawbridge.icns") if (ROOT / "clawbridge.icns").exists() else None

# ── Code Signing (optional) ────────────────────────────────────────────────

# Set these environment variables for CI signing:
#   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
#   NOTARIZE_APPLE_ID="your@email.com"
#   NOTARIZE_TEAM_ID="TEAMID"
#   NOTARIZE_PASSWORD="app-specific-password"

# dmgbuild doesn't handle code signing itself — that's done in the
# GitHub Actions workflow before dmgbuild runs.
