"""macOS platform backend — PyObjC (Quartz/Cocoa) + AppleScript + AXUIElement.

Requires macOS 11+ and the following permissions in System Settings > Privacy:
  - Accessibility (for AXUIElement API and app activation)
  - Screen Recording (for screenshots via mss)

Dependencies (darwin-only, in requirements.txt):
  pyobjc-framework-Cocoa>=10.0
  pyobjc-framework-Quartz>=10.0
  pyobjc-framework-ApplicationServices>=10.0
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

from clawbridge.platform._base import PlatformBase

logger = logging.getLogger(__name__)

# ── Blocked key combos (macOS) ───────────────────────────────────────────

_BLOCKED_KEY_COMBOS_MACOS = frozenset({
    "cmd+q",                  # Quit (dangerous in automation)
    "cmd+esc+option",         # Force Quit (sorted: cmd, esc, option)
    "cmd+ctrl+q",             # Lock Screen
    "cmd+q+shift",            # Log Out
    "cmd+option+power",       # Sleep (sorted: cmd, option, power)
    "cmd+ctrl+power",         # Force restart (sorted: cmd, ctrl, power)
})

# AX role -> UIA control_type mapping (for consistency with Windows)
_AX_ROLE_MAP = {
    "AXButton": "Button",
    "AXTextField": "Edit",
    "AXTextArea": "Edit",
    "AXSecureTextField": "Edit",
    "AXMenuItem": "MenuItem",
    "AXRow": "ListItem",
    "AXCell": "DataItem",
    "AXTabButton": "TabItem",
    "AXCheckBox": "CheckBox",
    "AXRadioButton": "RadioButton",
    "AXLink": "Hyperlink",
    "AXComboBox": "ComboBox",
    "AXPopUpButton": "ComboBox",
    "AXImage": "Image",
    "AXStaticText": "Text",
    "AXOutlineRow": "TreeItem",
}


def _check_accessibility_permission() -> bool:
    """Check if this process has Accessibility permission. Prompts user if not."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from CoreFoundation import CFDictionaryCreate, kCFBooleanTrue
        options = {b"AXTrustedCheckOptionPrompt": True}
        # Try the simpler approach first
        try:
            return AXIsProcessTrustedWithOptions(
                {"AXTrustedCheckOptionPrompt": True}
            )
        except Exception:
            # Fallback: just check without prompting
            from ApplicationServices import AXIsProcessTrusted
            return AXIsProcessTrusted()
    except ImportError:
        logger.debug("ApplicationServices not available -- not on macOS?")
        return False
    except Exception as exc:
        logger.debug("Accessibility permission check failed: %s", exc)
        return False


def _run_applescript(script: str, timeout: float = 5.0) -> str:
    """Run an AppleScript and return stdout. Empty string on failure."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _sanitize_applescript_string(s: str) -> str:
    """Strip characters dangerous in AppleScript string literals."""
    return s.replace("\\", "").replace('"', "").replace("'", "")


class MacOSPlatform(PlatformBase):
    """macOS implementation using PyObjC, Quartz, and AppleScript."""

    def __init__(self):
        self._accessibility_checked = False
        self._accessibility_granted = False

    def _ensure_accessibility(self) -> bool:
        """Lazy-check accessibility permission once."""
        if not self._accessibility_checked:
            self._accessibility_checked = True
            self._accessibility_granted = _check_accessibility_permission()
            if not self._accessibility_granted:
                logger.warning(
                    "Accessibility permission not granted. "
                    "Enable in System Settings > Privacy & Security > Accessibility."
                )
        return self._accessibility_granted

    # ── Window management ────────────────────────────────────────────────

    def get_foreground_window_title(self) -> str:
        try:
            from AppKit import NSWorkspace
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowOwnerPID,
                kCGWindowName,
                kCGWindowLayer,
            )
            frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not frontmost:
                return ""
            pid = frontmost.processIdentifier()

            windows = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            if not windows:
                return ""

            for win in windows:
                if win.get(kCGWindowOwnerPID) == pid and win.get(kCGWindowLayer, 99) == 0:
                    title = win.get(kCGWindowName, "")
                    if title:
                        return str(title)

            # Fallback: app name
            return str(frontmost.localizedName() or "")
        except ImportError:
            # PyObjC not installed, use AppleScript fallback
            return _run_applescript(
                'tell application "System Events" to get name of first process '
                'whose frontmost is true'
            )
        except Exception:
            return ""

    def get_foreground_window_rect(self) -> Optional[tuple[int, int, int, int]]:
        try:
            from AppKit import NSWorkspace
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowOwnerPID,
                kCGWindowBounds,
                kCGWindowLayer,
            )
            frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not frontmost:
                return None
            pid = frontmost.processIdentifier()

            windows = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            if not windows:
                return None

            for win in windows:
                if win.get(kCGWindowOwnerPID) == pid and win.get(kCGWindowLayer, 99) == 0:
                    bounds = win.get(kCGWindowBounds)
                    if bounds:
                        x = int(bounds.get("X", 0))
                        y = int(bounds.get("Y", 0))
                        w = int(bounds.get("Width", 0))
                        h = int(bounds.get("Height", 0))
                        if w > 20 and h > 20:
                            return (x, y, x + w, y + h)
            return None
        except ImportError:
            return None
        except Exception:
            return None

    def get_window_title_at_point(self, x: int, y: int) -> str:
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowBounds,
                kCGWindowName,
                kCGWindowLayer,
            )
            windows = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            if not windows:
                return ""

            # Windows are returned front-to-back
            for win in windows:
                if win.get(kCGWindowLayer, 99) != 0:
                    continue
                bounds = win.get(kCGWindowBounds)
                if not bounds:
                    continue
                wx = int(bounds.get("X", 0))
                wy = int(bounds.get("Y", 0))
                ww = int(bounds.get("Width", 0))
                wh = int(bounds.get("Height", 0))
                if wx <= x <= wx + ww and wy <= y <= wy + wh:
                    title = win.get(kCGWindowName, "")
                    if title:
                        return str(title)
            return ""
        except ImportError:
            return ""
        except Exception:
            return ""

    def get_foreground_process_name(self) -> str:
        try:
            from AppKit import NSWorkspace
            frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
            if frontmost:
                # bundleURL gives /Applications/App.app, we want "App"
                name = frontmost.localizedName()
                if name:
                    return str(name)
        except ImportError:
            return _run_applescript(
                'tell application "System Events" to get name of first process '
                'whose frontmost is true'
            )
        except Exception:
            pass
        return ""

    def bring_app_to_foreground(self, app_keyword: str) -> bool:
        try:
            from AppKit import NSWorkspace, NSRunningApplication
            workspace = NSWorkspace.sharedWorkspace()
            apps = workspace.runningApplications()
            kw_lower = app_keyword.lower()

            for app in apps:
                name = str(app.localizedName() or "").lower()
                bundle_id = str(app.bundleIdentifier() or "").lower()
                if kw_lower in name or kw_lower in bundle_id:
                    # NSApplicationActivateIgnoringOtherApps = 1 << 1
                    app.activateWithOptions_(1 << 1)
                    return True
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("bring_app_to_foreground (PyObjC) failed: %s", exc)

        # Fallback: AppleScript
        safe = _sanitize_applescript_string(app_keyword)
        if safe:
            result = _run_applescript(f'tell application "{safe}" to activate')
            return result is not None  # osascript returns '' on success
        return False

    def focus_window_by_title(self, title: str) -> bool:
        # Extract app name from title (e.g. "My Page - Google Chrome" -> "Google Chrome")
        app_name = title.split(" - ")[-1].strip() if " - " in title else title
        safe = _sanitize_applescript_string(app_name)
        if not safe:
            return False

        script = (
            f'tell application "System Events"\n'
            f'  set procs to every process whose name contains "{safe}"\n'
            f'  if (count of procs) > 0 then\n'
            f'    set frontmost of (item 1 of procs) to true\n'
            f'    return "ok"\n'
            f'  end if\n'
            f'end tell'
        )
        result = _run_applescript(script)
        return result == "ok"

    def verify_focus(self, app_keyword: str) -> tuple[bool, str]:
        try:
            from AppKit import NSWorkspace
            frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not frontmost:
                return (False, "")
            name = str(frontmost.localizedName() or "")
            kw_lower = app_keyword.lower()

            if kw_lower in name.lower():
                return (True, name)

            # Also check window title via Quartz
            title = self.get_foreground_window_title()
            if kw_lower in title.lower():
                return (True, title)

            return (False, title or name)
        except ImportError:
            # Fallback
            title = self.get_foreground_window_title()
            if app_keyword.lower() in title.lower():
                return (True, title)
            return (False, title)
        except Exception:
            return (False, "")

    def check_window_exists(self, title: str) -> bool:
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowName,
                kCGWindowLayer,
            )
            windows = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            if not windows:
                return False
            title_lower = title.lower()
            for win in windows:
                if win.get(kCGWindowLayer, 99) != 0:
                    continue
                wname = win.get(kCGWindowName, "")
                if wname and title_lower in str(wname).lower():
                    return True
            return False
        except ImportError:
            return False
        except Exception:
            return False

    def enumerate_visible_windows(self) -> list[dict]:
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowOwnerPID,
                kCGWindowName,
                kCGWindowOwnerName,
                kCGWindowBounds,
                kCGWindowLayer,
            )
            windows = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            if not windows:
                return []

            result = []
            for win in windows:
                if win.get(kCGWindowLayer, 99) != 0:
                    continue
                title = win.get(kCGWindowName, "")
                if not title:
                    continue
                entry = {
                    "title": str(title),
                    "pid": int(win.get(kCGWindowOwnerPID, 0)),
                    "process_name": str(win.get(kCGWindowOwnerName, "")),
                }
                bounds = win.get(kCGWindowBounds)
                if bounds:
                    entry["bounds"] = (
                        int(bounds.get("X", 0)),
                        int(bounds.get("Y", 0)),
                        int(bounds.get("X", 0)) + int(bounds.get("Width", 0)),
                        int(bounds.get("Y", 0)) + int(bounds.get("Height", 0)),
                    )
                result.append(entry)
            return result
        except ImportError:
            # Fallback: AppleScript
            out = _run_applescript(
                'tell application "System Events" to get name of every process '
                'whose visible is true'
            )
            if out:
                return [{"title": n.strip(), "pid": 0} for n in out.split(",") if n.strip()]
            return []
        except Exception:
            return []

    # ── Accessibility ────────────────────────────────────────────────────

    def get_accessibility_tree(self, max_depth: int = 8, max_elements: int = 60) -> list[dict]:
        if not self._ensure_accessibility():
            return []

        try:
            from AppKit import NSWorkspace
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowOwnerPID,
                kCGWindowLayer,
            )
            from ApplicationServices import (
                AXUIElementCreateApplication,
                AXUIElementCopyAttributeValue,
            )
            import CoreFoundation

            frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not frontmost:
                return []
            pid = frontmost.processIdentifier()
            app_element = AXUIElementCreateApplication(pid)

            tree = []
            self._walk_ax_tree(app_element, tree, 0, max_depth, max_elements)
            return tree
        except ImportError:
            logger.debug("PyObjC AX imports not available")
            return []
        except Exception as exc:
            logger.debug("get_accessibility_tree (macOS) failed: %s", exc)
            return []

    def _walk_ax_tree(self, element, tree: list, depth: int,
                      max_depth: int, max_elements: int) -> None:
        """Recursively walk the AXUIElement tree and collect interactive elements."""
        if depth > max_depth or len(tree) >= max_elements:
            return

        try:
            from ApplicationServices import AXUIElementCopyAttributeValue
            import CoreFoundation

            # Get role
            err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
            if err != 0 or not role:
                return
            role = str(role)

            # Map AX role to control type
            control_type = _AX_ROLE_MAP.get(role, "")

            if control_type:
                # Get name/title
                name = ""
                err, val = AXUIElementCopyAttributeValue(element, "AXTitle", None)
                if err == 0 and val:
                    name = str(val).strip()[:80]
                if not name:
                    err, val = AXUIElementCopyAttributeValue(element, "AXDescription", None)
                    if err == 0 and val:
                        name = str(val).strip()[:80]
                if not name:
                    err, val = AXUIElementCopyAttributeValue(element, "AXValue", None)
                    if err == 0 and val:
                        v = str(val).strip()[:80]
                        if len(v) < 50:  # Don't use long text content as name
                            name = v

                # Get position and size
                err, pos = AXUIElementCopyAttributeValue(element, "AXPosition", None)
                err2, size = AXUIElementCopyAttributeValue(element, "AXSize", None)
                if err == 0 and err2 == 0 and pos and size:
                    try:
                        from Quartz import CGPointMakeWithDictionaryRepresentation, CGSizeMakeWithDictionaryRepresentation
                        # pos and size are AXValue types; extract via CG
                        x = int(pos.x) if hasattr(pos, 'x') else 0
                        y = int(pos.y) if hasattr(pos, 'y') else 0
                        w = int(size.width) if hasattr(size, 'width') else 0
                        h = int(size.height) if hasattr(size, 'height') else 0
                    except Exception:
                        x = y = w = h = 0

                    if w >= 10 and h >= 10:
                        # Get identifier (similar to automation_id)
                        auto_id = ""
                        err, val = AXUIElementCopyAttributeValue(element, "AXIdentifier", None)
                        if err == 0 and val:
                            auto_id = str(val)

                        # Get parent name
                        parent_name = ""
                        err, parent = AXUIElementCopyAttributeValue(element, "AXParent", None)
                        if err == 0 and parent:
                            err2, ptitle = AXUIElementCopyAttributeValue(parent, "AXTitle", None)
                            if err2 == 0 and ptitle:
                                parent_name = str(ptitle).strip()[:60]

                        cx = x + w // 2
                        cy = y + h // 2
                        if cx > 0 and cy > 0:
                            tree.append({
                                "control_type": control_type,
                                "name": name,
                                "automation_id": auto_id,
                                "parent_name": parent_name,
                                "left": x, "top": y,
                                "right": x + w, "bottom": y + h,
                                "cx": cx, "cy": cy,
                            })

            # Recurse into children
            if len(tree) < max_elements:
                err, children = AXUIElementCopyAttributeValue(element, "AXChildren", None)
                if err == 0 and children:
                    for child in children:
                        if len(tree) >= max_elements:
                            break
                        self._walk_ax_tree(child, tree, depth + 1, max_depth, max_elements)
        except Exception:
            pass

    def get_element_at_point(self, x: int, y: int) -> dict:
        result = {
            "element_type": "", "element_name": "",
            "element_automation_id": "", "element_parent_name": "",
            "confidence": 0.0,
        }

        if not self._ensure_accessibility():
            return result

        try:
            from ApplicationServices import (
                AXUIElementCreateSystemWide,
                AXUIElementCopyElementAtPosition,
                AXUIElementCopyAttributeValue,
            )

            system_wide = AXUIElementCreateSystemWide()
            err, element = AXUIElementCopyElementAtPosition(system_wide, float(x), float(y), None)
            if err != 0 or not element:
                return result

            # Get role
            err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
            control_type = ""
            if err == 0 and role:
                control_type = _AX_ROLE_MAP.get(str(role), str(role))

            # Get name
            name = ""
            for attr in ("AXTitle", "AXDescription", "AXValue"):
                err, val = AXUIElementCopyAttributeValue(element, attr, None)
                if err == 0 and val:
                    name = str(val).strip()[:80]
                    if name:
                        break

            # Get identifier
            auto_id = ""
            err, val = AXUIElementCopyAttributeValue(element, "AXIdentifier", None)
            if err == 0 and val:
                auto_id = str(val)

            # Get parent name
            parent_name = ""
            err, parent = AXUIElementCopyAttributeValue(element, "AXParent", None)
            if err == 0 and parent:
                for attr in ("AXTitle", "AXDescription"):
                    err2, ptitle = AXUIElementCopyAttributeValue(parent, attr, None)
                    if err2 == 0 and ptitle:
                        parent_name = str(ptitle).strip()[:60]
                        if parent_name:
                            break

            conf = 0.5
            if auto_id:
                conf = 1.0
            elif name and control_type:
                conf = 0.8

            return {
                "element_type": control_type,
                "element_name": name,
                "element_automation_id": auto_id,
                "element_parent_name": parent_name,
                "confidence": conf,
            }
        except ImportError:
            return result
        except Exception as exc:
            logger.debug("get_element_at_point (macOS) failed at (%d, %d): %s", x, y, exc)
            return result

    # ── System ───────────────────────────────────────────────────────────

    def set_dpi_aware(self) -> None:
        # No-op on macOS — Retina is handled by the OS.
        # pyautogui reports logical (not physical) pixels automatically.
        pass

    def get_blocked_key_combos(self) -> frozenset:
        return _BLOCKED_KEY_COMBOS_MACOS

    def launch_app_via_search(self, app_name: str) -> bool:
        try:
            subprocess.Popen(
                ["open", "-a", app_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.debug("launch_app_via_search (macOS) failed: %s", exc)
            return False
