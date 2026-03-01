"""Tests for the platform abstraction layer (clawbridge.platform).

Uses mocking so tests run on any OS without requiring actual platform APIs.
"""

from __future__ import annotations

import sys
from unittest.mock import patch, MagicMock

import pytest


class TestPlatformBase:
    """Test that PlatformBase defines all 14 required methods."""

    def test_abstract_methods(self):
        from clawbridge.platform._base import PlatformBase
        # All abstract methods should be listed
        expected = {
            "get_foreground_window_title",
            "get_foreground_window_rect",
            "get_window_title_at_point",
            "get_foreground_process_name",
            "bring_app_to_foreground",
            "focus_window_by_title",
            "verify_focus",
            "check_window_exists",
            "enumerate_visible_windows",
            "get_accessibility_tree",
            "get_element_at_point",
            "set_dpi_aware",
            "get_blocked_key_combos",
            "launch_app_via_search",
        }
        actual = set(PlatformBase.__abstractmethods__)
        assert actual == expected, f"Missing: {expected - actual}, Extra: {actual - expected}"


class TestLinuxPlatform:
    """Test that the Linux stub returns safe defaults."""

    def test_all_methods_return_defaults(self):
        from clawbridge.platform._linux import LinuxPlatform
        plat = LinuxPlatform()

        assert plat.get_foreground_window_title() == ""
        assert plat.get_foreground_window_rect() is None
        assert plat.get_window_title_at_point(100, 100) == ""
        assert plat.get_foreground_process_name() == ""
        assert plat.bring_app_to_foreground("test") is False
        assert plat.focus_window_by_title("test") is False
        assert plat.verify_focus("test") == (True, "")  # Assume focused
        assert plat.check_window_exists("test") is False
        assert plat.enumerate_visible_windows() == []
        assert plat.get_accessibility_tree() == []
        elem = plat.get_element_at_point(0, 0)
        assert elem["element_type"] == ""
        assert elem["confidence"] == 0.0
        plat.set_dpi_aware()  # no-op
        assert plat.get_blocked_key_combos() == frozenset()
        assert plat.launch_app_via_search("test") is False


class TestWindowsPlatform:
    """Test Windows platform methods with mocked ctypes."""

    def test_blocked_key_combos(self):
        from clawbridge.platform._windows import _BLOCKED_KEY_COMBOS_WIN32
        # Verify known dangerous combos are blocked
        assert "r+win" in _BLOCKED_KEY_COMBOS_WIN32
        assert "alt+ctrl+delete" in _BLOCKED_KEY_COMBOS_WIN32
        assert "alt+f4" in _BLOCKED_KEY_COMBOS_WIN32
        assert "l+win" in _BLOCKED_KEY_COMBOS_WIN32
        # Verify non-dangerous combos are not blocked
        assert "ctrl+c" not in _BLOCKED_KEY_COMBOS_WIN32
        assert "ctrl+v" not in _BLOCKED_KEY_COMBOS_WIN32

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_get_foreground_window_title_returns_string(self):
        from clawbridge.platform._windows import WindowsPlatform
        plat = WindowsPlatform()
        result = plat.get_foreground_window_title()
        assert isinstance(result, str)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_get_foreground_window_rect_returns_tuple_or_none(self):
        from clawbridge.platform._windows import WindowsPlatform
        plat = WindowsPlatform()
        result = plat.get_foreground_window_rect()
        assert result is None or (isinstance(result, tuple) and len(result) == 4)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_enumerate_visible_windows_returns_list(self):
        from clawbridge.platform._windows import WindowsPlatform
        plat = WindowsPlatform()
        result = plat.enumerate_visible_windows()
        assert isinstance(result, list)
        if result:
            assert "title" in result[0]
            assert "pid" in result[0]

    def test_get_element_at_point_returns_dict(self):
        from clawbridge.platform._windows import WindowsPlatform
        plat = WindowsPlatform()
        # Even if it fails (not on Windows), should return valid dict
        result = plat.get_element_at_point(0, 0)
        assert isinstance(result, dict)
        assert "element_type" in result
        assert "confidence" in result


class TestMacOSPlatform:
    """Test macOS platform with mocked PyObjC."""

    def test_blocked_key_combos(self):
        from clawbridge.platform._macos import _BLOCKED_KEY_COMBOS_MACOS
        # Verify macOS-specific dangerous combos are blocked
        assert "cmd+q" in _BLOCKED_KEY_COMBOS_MACOS
        assert "cmd+ctrl+q" in _BLOCKED_KEY_COMBOS_MACOS
        assert "cmd+q+shift" in _BLOCKED_KEY_COMBOS_MACOS
        # Verify non-dangerous combos are not blocked
        assert "cmd+c" not in _BLOCKED_KEY_COMBOS_MACOS
        assert "cmd+v" not in _BLOCKED_KEY_COMBOS_MACOS

    def test_set_dpi_aware_is_noop(self):
        from clawbridge.platform._macos import MacOSPlatform
        plat = MacOSPlatform()
        plat.set_dpi_aware()  # Should not raise

    def test_sanitize_applescript_string(self):
        from clawbridge.platform._macos import _sanitize_applescript_string
        assert _sanitize_applescript_string('hello "world"') == "hello world"
        assert _sanitize_applescript_string("it\\'s") == "its"
        assert _sanitize_applescript_string("safe_name") == "safe_name"

    def test_ax_role_map(self):
        from clawbridge.platform._macos import _AX_ROLE_MAP
        # Key macOS AX roles should map to Windows UIA control types
        assert _AX_ROLE_MAP["AXButton"] == "Button"
        assert _AX_ROLE_MAP["AXTextField"] == "Edit"
        assert _AX_ROLE_MAP["AXCheckBox"] == "CheckBox"
        assert _AX_ROLE_MAP["AXLink"] == "Hyperlink"


class TestPlatformAutoSelect:
    """Test that __init__.py auto-selects the correct backend."""

    def test_platform_is_instance_of_base(self):
        from clawbridge.platform import platform, PlatformBase
        assert isinstance(platform, PlatformBase)

    def test_correct_backend_selected(self):
        from clawbridge.platform import platform
        if sys.platform == "win32":
            from clawbridge.platform._windows import WindowsPlatform
            assert isinstance(platform, WindowsPlatform)
        elif sys.platform == "darwin":
            from clawbridge.platform._macos import MacOSPlatform
            assert isinstance(platform, MacOSPlatform)
        else:
            from clawbridge.platform._linux import LinuxPlatform
            assert isinstance(platform, LinuxPlatform)

    def test_blocked_combos_not_empty_on_win_or_mac(self):
        from clawbridge.platform import platform
        combos = platform.get_blocked_key_combos()
        if sys.platform in ("win32", "darwin"):
            assert len(combos) > 0
