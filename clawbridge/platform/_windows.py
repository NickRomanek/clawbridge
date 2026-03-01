"""Windows platform backend — ctypes Win32 API + pywinauto UIA.

Extracted from clawbridge.py and clawbridge/recorder/capture.py.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

from clawbridge.platform._base import PlatformBase

logger = logging.getLogger(__name__)

# ── Blocked key combos (Windows) ─────────────────────────────────────────

_BLOCKED_KEY_COMBOS_WIN32 = frozenset({
    "r+win",              # Run dialog -> arbitrary commands
    "win+x",              # Power user menu -> terminal access
    "alt+ctrl+delete",    # Security screen
    "alt+ctrl+del",       # Security screen (short form)
    "ctrl+esc+shift",     # Task Manager
    "l+win",              # Lock workstation
    "pause+win",          # System properties
    "alt+f4",             # Close window (can close critical apps)
})


class WindowsPlatform(PlatformBase):
    """Windows implementation using ctypes Win32 API and pywinauto UIA."""

    # ── Window management ────────────────────────────────────────────────

    def get_foreground_window_title(self) -> str:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            return buf.value
        except Exception:
            return ""

    def get_foreground_window_rect(self) -> Optional[tuple[int, int, int, int]]:
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            rect = ctypes.wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return None

    def get_window_title_at_point(self, x: int, y: int) -> str:
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            pt = ctypes.wintypes.POINT(x, y)
            hwnd = user32.WindowFromPoint(pt)
            if not hwnd:
                return ""
            GA_ROOT = 2
            root = user32.GetAncestor(hwnd, GA_ROOT)
            if root:
                hwnd = root
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            return buf.value
        except Exception:
            return ""

    def get_foreground_process_name(self) -> str:
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return ""
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if not handle:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(260)
                size = ctypes.wintypes.DWORD(260)
                kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
                full_path = buf.value
                if full_path:
                    return full_path.rsplit("\\", 1)[-1]
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            pass
        return ""

    def bring_app_to_foreground(self, app_keyword: str) -> bool:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kw_lower = app_keyword.lower()
            target_hwnd = [0]
            SW_RESTORE = 9

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def cb(hwnd, _):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.lower()
                    if kw_lower in title:
                        target_hwnd[0] = hwnd
                        return False
                return True

            user32.EnumWindows(cb, 0)
            if target_hwnd[0]:
                hwnd = target_hwnd[0]
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                import pyautogui as _pag
                _pag.press('alt')
                return True

            # Fallback: try by process name
            target_hwnd[0] = 0

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def cb_proc(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                try:
                    pid_val = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val))
                    h = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid_val.value)
                    if h:
                        name_buf = ctypes.create_unicode_buffer(260)
                        size = ctypes.c_ulong(260)
                        ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, name_buf, ctypes.byref(size))
                        ctypes.windll.kernel32.CloseHandle(h)
                        pname = name_buf.value.rsplit("\\", 1)[-1].lower()
                        if kw_lower in pname:
                            target_hwnd[0] = hwnd
                            return False
                except Exception:
                    pass
                return True

            user32.EnumWindows(cb_proc, 0)
            if target_hwnd[0]:
                hwnd = target_hwnd[0]
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                import pyautogui as _pag
                _pag.press('alt')
                return True

            # Browser-aware fallback: when keyword is "browser", find any
            # browser window by known process names (title/process substring
            # matching above fails because no title/process contains "browser")
            if kw_lower == "browser":
                _BROWSER_PROCS = frozenset((
                    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                    "opera.exe", "vivaldi.exe", "chromium.exe", "arc.exe",
                ))
                target_hwnd[0] = 0

                @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def cb_browser(hwnd, _):
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    try:
                        pid_val = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val))
                        h = ctypes.windll.kernel32.OpenProcess(
                            0x0400 | 0x0010, False, pid_val.value)
                        if h:
                            name_buf = ctypes.create_unicode_buffer(260)
                            size = ctypes.c_ulong(260)
                            ctypes.windll.kernel32.QueryFullProcessImageNameW(
                                h, 0, name_buf, ctypes.byref(size))
                            ctypes.windll.kernel32.CloseHandle(h)
                            pname = name_buf.value.rsplit("\\", 1)[-1].lower()
                            if pname in _BROWSER_PROCS:
                                # Skip tiny/invisible browser helper windows
                                length = user32.GetWindowTextLengthW(hwnd)
                                if length > 0:
                                    target_hwnd[0] = hwnd
                                    return False
                    except Exception:
                        pass
                    return True

                user32.EnumWindows(cb_browser, 0)
                if target_hwnd[0]:
                    hwnd = target_hwnd[0]
                    user32.ShowWindow(hwnd, SW_RESTORE)
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                    import pyautogui as _pag
                    _pag.press('alt')
                    return True
        except Exception as exc:
            logger.debug("bring_app_to_foreground failed: %s", exc)
        return False

    def focus_window_by_title(self, title: str) -> bool:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            title_lower = title.lower()
            target_hwnd = [0]
            SW_RESTORE = 9

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def cb(hwnd, _):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if title_lower in buf.value.lower():
                        target_hwnd[0] = hwnd
                        return False
                return True

            user32.EnumWindows(cb, 0)
            if target_hwnd[0]:
                hwnd = target_hwnd[0]
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                # Wait for input idle
                try:
                    kernel32 = ctypes.windll.kernel32
                    pid = ctypes.c_ulong(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    hProc = kernel32.OpenProcess(0x00100000, 0, pid.value)
                    if hProc:
                        user32.WaitForInputIdle(hProc, 2000)
                        kernel32.CloseHandle(hProc)
                except Exception:
                    pass
                return True
        except Exception as exc:
            logger.debug("focus_window_by_title failed: %s", exc)
        return False

    def verify_focus(self, app_keyword: str) -> tuple[bool, str]:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return (False, "")
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            actual_title = buf.value
            kw_lower = app_keyword.lower()

            if kw_lower in actual_title.lower():
                return (True, actual_title)

            # Check known browser title suffixes
            _BROWSER_TITLE_SUFFIXES = (
                "google chrome", "mozilla firefox", "microsoft edge",
                "brave", "opera", "vivaldi", "chromium", "arc",
            )
            if any(actual_title.lower().endswith(s) for s in _BROWSER_TITLE_SUFFIXES):
                if kw_lower in ("chrome", "firefox", "edge", "brave", "opera",
                                "vivaldi", "chromium", "arc", "browser"):
                    return (True, actual_title)

            # Fallback: check process name
            try:
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                h = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid.value)
                if h:
                    name_buf = ctypes.create_unicode_buffer(260)
                    size = ctypes.c_ulong(260)
                    ctypes.windll.kernel32.QueryFullProcessImageNameW(
                        h, 0, name_buf, ctypes.byref(size))
                    ctypes.windll.kernel32.CloseHandle(h)
                    pname = name_buf.value.rsplit("\\", 1)[-1].lower()
                    if kw_lower in pname:
                        return (True, actual_title)
            except Exception:
                pass

            return (False, actual_title)
        except Exception:
            return (False, "")

    def check_window_exists(self, title: str) -> bool:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            title_lower = title.lower()
            found = [False]

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def cb(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if title_lower in buf.value.lower():
                        found[0] = True
                        return False
                return True

            user32.EnumWindows(cb, 0)
            return found[0]
        except Exception:
            return False

    def enumerate_visible_windows(self) -> list[dict]:
        windows = []
        try:
            import ctypes
            user32 = ctypes.windll.user32

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def cb(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if title.strip():
                        pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        windows.append({
                            "title": title,
                            "pid": pid.value,
                        })
                return True

            user32.EnumWindows(cb, 0)
        except Exception as exc:
            logger.debug("enumerate_visible_windows failed: %s", exc)
        return windows

    # ── Accessibility ────────────────────────────────────────────────────

    def get_accessibility_tree(self, max_depth: int = 8, max_elements: int = 60) -> list[dict]:
        try:
            import ctypes
            from pywinauto import Desktop

            d = Desktop(backend="uia")
            user32 = ctypes.windll.user32
            fg_hwnd = user32.GetForegroundWindow()
            if not fg_hwnd:
                return []

            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(fg_hwnd, buf, 512)
            fg_title = buf.value

            target_win = None
            for w in d.windows():
                try:
                    if w.window_text() == fg_title:
                        target_win = w
                        break
                except Exception:
                    pass

            if not target_win:
                for w in d.windows():
                    try:
                        wt = w.window_text()
                        if wt and fg_title and fg_title[:20] in wt:
                            target_win = w
                            break
                    except Exception:
                        pass

            if not target_win:
                return []

            CLICKABLE_TYPES = frozenset({
                "Button", "Edit", "MenuItem", "ListItem", "TabItem",
                "ComboBox", "CheckBox", "RadioButton", "Hyperlink",
                "TreeItem", "DataItem", "Text", "Image",
            })

            tree = []
            for c in target_win.descendants(depth=max_depth):
                try:
                    ct = c.element_info.control_type
                    if ct not in CLICKABLE_TYPES:
                        continue
                    r = c.rectangle()
                    if r.width() < 10 or r.height() < 10:
                        continue
                    name = (c.window_text() or "").strip()[:80]
                    cx = (r.left + r.right) // 2
                    cy = (r.top + r.bottom) // 2
                    if cx <= 0 or cy <= 0:
                        continue
                    auto_id = ""
                    try:
                        auto_id = c.element_info.automation_id or ""
                    except Exception:
                        pass
                    parent_name = ""
                    try:
                        p = c.parent()
                        if p:
                            parent_name = (p.window_text() or "").strip()[:60]
                    except Exception:
                        pass
                    tree.append({
                        "control_type": ct, "name": name,
                        "automation_id": auto_id, "parent_name": parent_name,
                        "left": r.left, "top": r.top,
                        "right": r.right, "bottom": r.bottom,
                        "cx": cx, "cy": cy,
                    })
                    if len(tree) >= max_elements:
                        break
                except Exception:
                    pass

            return tree
        except Exception as exc:
            logger.debug("get_accessibility_tree failed: %s", exc)
            return []

    def get_element_at_point(self, x: int, y: int) -> dict:
        result = {
            "element_type": "", "element_name": "",
            "element_automation_id": "", "element_parent_name": "",
            "confidence": 0.0,
        }
        try:
            tree = self.get_accessibility_tree()
            if not tree:
                return result

            candidates = []
            for el in tree:
                if el["left"] <= x <= el["right"] and el["top"] <= y <= el["bottom"]:
                    area = (el["right"] - el["left"]) * (el["bottom"] - el["top"])
                    candidates.append((area, el))

            if not candidates:
                return result

            candidates.sort(key=lambda c: c[0])
            el = candidates[0][1]

            conf = 0.5
            if el.get("automation_id"):
                conf = 1.0
            elif el.get("name") and el.get("control_type"):
                conf = 0.8

            return {
                "element_type": el["control_type"],
                "element_name": el["name"],
                "element_automation_id": el.get("automation_id", ""),
                "element_parent_name": el.get("parent_name", ""),
                "confidence": conf,
            }
        except Exception as exc:
            logger.debug("get_element_at_point failed at (%d, %d): %s", x, y, exc)
            return result

    # ── System ───────────────────────────────────────────────────────────

    def set_dpi_aware(self) -> None:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    def get_blocked_key_combos(self) -> frozenset:
        return _BLOCKED_KEY_COMBOS_WIN32

    def launch_app_via_search(self, app_name: str) -> bool:
        try:
            import pyautogui
            pyautogui.hotkey('win', 's')
            import time
            time.sleep(0.5)
            pyautogui.typewrite(app_name, interval=0.05)
            time.sleep(0.3)
            pyautogui.press('enter')
            return True
        except Exception as exc:
            logger.debug("launch_app_via_search failed: %s", exc)
            return False
