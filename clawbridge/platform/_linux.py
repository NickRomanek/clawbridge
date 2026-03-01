"""Linux platform backend — stubs returning empty/False.

Linux desktop automation support is not yet implemented.
All methods degrade gracefully so the app still runs (browser-use
and OpenClaw engines work, computer-use falls back to vision).
"""

from __future__ import annotations

import logging
from typing import Optional

from clawbridge.platform._base import PlatformBase

logger = logging.getLogger(__name__)


class LinuxPlatform(PlatformBase):
    """Stub Linux implementation — all methods return empty/False."""

    def get_foreground_window_title(self) -> str:
        return ""

    def get_foreground_window_rect(self) -> Optional[tuple[int, int, int, int]]:
        return None

    def get_window_title_at_point(self, x: int, y: int) -> str:
        return ""

    def get_foreground_process_name(self) -> str:
        return ""

    def bring_app_to_foreground(self, app_keyword: str) -> bool:
        return False

    def focus_window_by_title(self, title: str) -> bool:
        return False

    def verify_focus(self, app_keyword: str) -> tuple[bool, str]:
        return (True, "")  # Assume focused to avoid blocking

    def check_window_exists(self, title: str) -> bool:
        return False

    def enumerate_visible_windows(self) -> list[dict]:
        return []

    def get_accessibility_tree(self, max_depth: int = 8, max_elements: int = 60) -> list[dict]:
        return []

    def get_element_at_point(self, x: int, y: int) -> dict:
        return {
            "element_type": "", "element_name": "",
            "element_automation_id": "", "element_parent_name": "",
            "confidence": 0.0,
        }

    def set_dpi_aware(self) -> None:
        pass

    def get_blocked_key_combos(self) -> frozenset:
        return frozenset()

    def launch_app_via_search(self, app_name: str) -> bool:
        return False
