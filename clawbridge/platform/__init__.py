"""Platform abstraction layer — auto-selects the correct backend.

Usage:
    from clawbridge.platform import platform as _plat
    title = _plat.get_foreground_window_title()
"""

from __future__ import annotations

import sys

from clawbridge.platform._base import PlatformBase

if sys.platform == "win32":
    from clawbridge.platform._windows import WindowsPlatform
    platform: PlatformBase = WindowsPlatform()
elif sys.platform == "darwin":
    from clawbridge.platform._macos import MacOSPlatform
    platform: PlatformBase = MacOSPlatform()
else:
    from clawbridge.platform._linux import LinuxPlatform
    platform: PlatformBase = LinuxPlatform()

__all__ = ["platform", "PlatformBase"]
