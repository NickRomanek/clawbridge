"""Abstract base class defining platform-agnostic window/accessibility operations.

All platform backends (_windows.py, _macos.py, _linux.py) implement this interface.
The monolith and recorder import the auto-selected backend via __init__.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class PlatformBase(ABC):
    """Platform abstraction interface for window management and accessibility."""

    # ── Window management ────────────────────────────────────────────────

    @abstractmethod
    def get_foreground_window_title(self) -> str:
        """Return the title of the currently focused window, or '' on failure."""

    @abstractmethod
    def get_foreground_window_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Return (left, top, right, bottom) of the foreground window, or None."""

    @abstractmethod
    def get_window_title_at_point(self, x: int, y: int) -> str:
        """Return the title of the window at screen coordinates (x, y).

        Uses the deepest hit-test then walks up to the root/top-level window.
        More reliable than get_foreground_window_title() for clicks that
        dismiss their target (e.g. 'Don't Save' button in Notepad).
        """

    @abstractmethod
    def get_foreground_process_name(self) -> str:
        """Return the process name (e.g. 'chrome.exe') of the foreground window."""

    @abstractmethod
    def bring_app_to_foreground(self, app_keyword: str) -> bool:
        """Activate the first window whose title or process matches *app_keyword*.

        Returns True if a matching window was found and activated.
        """

    @abstractmethod
    def focus_window_by_title(self, title: str) -> bool:
        """Focus the window whose title best matches *title*.

        Returns True on success.
        """

    @abstractmethod
    def verify_focus(self, app_keyword: str) -> tuple[bool, str]:
        """Check if the foreground window matches *app_keyword*.

        Returns (matched, actual_title).
        """

    @abstractmethod
    def check_window_exists(self, title: str) -> bool:
        """Return True if any visible window's title contains *title* (case-insensitive)."""

    @abstractmethod
    def enumerate_visible_windows(self) -> list[dict]:
        """Return a list of dicts describing visible windows.

        Each dict has at minimum: {'title': str, 'pid': int}.
        Implementations may add extra keys (e.g. 'process_name', 'bounds').
        """

    # ── Accessibility ────────────────────────────────────────────────────

    @abstractmethod
    def get_accessibility_tree(self, max_depth: int = 8, max_elements: int = 60) -> list[dict]:
        """Enumerate interactive UI elements from the foreground window.

        Returns list of dicts with keys:
            control_type, name, automation_id, parent_name,
            left, top, right, bottom, cx, cy
        """

    @abstractmethod
    def get_element_at_point(self, x: int, y: int) -> dict:
        """Return accessibility info for the UI element at (x, y).

        Returns dict with keys:
            element_type, element_name, element_automation_id,
            element_parent_name, confidence (float 0-1)
        """

    # ── System ───────────────────────────────────────────────────────────

    @abstractmethod
    def set_dpi_aware(self) -> None:
        """Enable DPI awareness so pixel coordinates match logical resolution."""

    @abstractmethod
    def get_blocked_key_combos(self) -> frozenset:
        """Return the set of dangerous key combos to block on this platform.

        Each combo is a string of '+'-separated sorted lowercase key names.
        """

    @abstractmethod
    def launch_app_via_search(self, app_name: str) -> bool:
        """Launch an application using the platform's search/launch mechanism.

        Windows: Win+S search, macOS: open -a, Linux: no-op.
        Returns True if launch was attempted.
        """
