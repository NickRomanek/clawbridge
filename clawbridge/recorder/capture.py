"""Low-level input recording using pynput (thread-based).

Captures mouse clicks/scrolls and keyboard events, coalescing rapid keystrokes
into single "type" events. Each event is tagged with the current foreground
window title at capture time.

Click events are enriched inline with:
- Accessibility metadata (element_name, element_type, automation_id, parent_name)
- Screenshot capture (720p JPEG, base64)
Both are captured at click time while the correct window is in focus.
"""

from __future__ import annotations

import base64
import io
import logging
import threading
import time
from typing import Any, List

logger = logging.getLogger(__name__)

# Platform abstraction — auto-selects Windows/macOS/Linux backend
from clawbridge.platform import platform as _plat

# Delay (seconds) before coalescing buffered keystrokes into a "type" event
_KEY_COALESCE_DELAY = 0.3

# A11y tree cache — avoids re-enumeration on rapid clicks (0.5s TTL)
_a11y_cache: list = []
_a11y_cache_time: float = 0.0
_A11Y_CACHE_TTL = 0.5
_a11y_lock = threading.Lock()


def _get_fg_window_title() -> str:
    """Get the foreground window title via platform abstraction."""
    return _plat.get_foreground_window_title()


def _get_window_title_at(x: int, y: int) -> str:
    """Get the title of the window at screen coordinates (x, y).

    Uses platform-specific hit-test (WindowFromPoint on Windows,
    CGWindowListCopyWindowInfo on macOS) then walks up to the root
    window. More reliable than get_foreground_window_title() for
    clicks that dismiss their target.
    """
    return _plat.get_window_title_at_point(x, y)


def _get_fg_process_name() -> str:
    """Get the process name (e.g. 'Telegram.exe' / 'Telegram') of the foreground window."""
    return _plat.get_foreground_process_name()


# Last-known non-dashboard foreground title — fallback when the clicked
# window has already closed by the time we read it.
_last_app_title: str = ""
_DASHBOARD_TITLE_MARKERS = ("clawbridge dashboard", "clawbridge login",
                            "localhost:8765", "127.0.0.1:8765")


def _get_fg_window_rect() -> tuple[int, int, int, int] | None:
    """Get the foreground window's bounding rect as (left, top, right, bottom).

    Used to compute window-relative click coordinates so replays work
    even when the target window has been moved to a different position.
    """
    return _plat.get_foreground_window_rect()


def _get_a11y_element_at(x: int, y: int) -> dict:
    """Synchronous a11y lookup at click coordinates. Called from pynput thread.
    Returns dict with element_type, element_name, element_automation_id,
    element_parent_name, confidence. All empty strings on failure."""
    global _a11y_cache, _a11y_cache_time
    result = {"element_type": "", "element_name": "", "element_automation_id": "",
              "element_parent_name": "", "confidence": 0.0}
    try:
        now = time.monotonic()
        tree = None

        with _a11y_lock:
            if _a11y_cache and (now - _a11y_cache_time) < _A11Y_CACHE_TTL:
                tree = _a11y_cache

        if tree is None:
            try:
                tree = _plat.get_accessibility_tree(max_depth=8, max_elements=80)
                with _a11y_lock:
                    _a11y_cache = tree
                    _a11y_cache_time = time.monotonic()
            except Exception as exc:
                logger.debug("A11y tree enumeration failed during click: %s", exc)
                return result

        if not tree:
            return result

        # Find element at (x, y) — smallest bounding rect wins
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
        logger.debug("A11y enrichment failed at (%d, %d): %s", x, y, exc)
        return result


def _capture_screenshot_sync(max_dim: int = 720) -> str:
    """Synchronous screenshot capture. Called from pynput thread.
    Returns base64-encoded JPEG or empty string."""
    try:
        import mss as mss_mod
        from PIL import Image
        with mss_mod.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            w, h = img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        logger.debug("Screenshot capture failed: %s", exc)
        return ""


class InputRecorder:
    """Records mouse and keyboard input via pynput listeners.

    Usage:
        recorder = InputRecorder(capture_screenshots=True)
        recorder.start()
        # ... user performs actions ...
        events = recorder.stop()  # returns list[dict]
    """

    def __init__(self, capture_screenshots: bool = True, on_action=None):
        self._events: List[dict] = []
        self._mouse_listener = None
        self._keyboard_listener = None
        self._recording = False
        self._lock = threading.Lock()
        self._key_buffer: List[str] = []
        self._key_buffer_start: float = 0.0
        self._start_time: float = 0.0
        self._capture_screenshots = capture_screenshots
        self._on_action = on_action  # callback(dict) for live action feed
        self._action_count = 0
        # Key repeat dedup: track last modifier key and timestamp to suppress
        # Windows key-repeat events (~33ms apart) when user holds a modifier.
        self._last_modifier_key: str = ""
        self._last_modifier_time: float = 0.0

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        """Start recording mouse and keyboard input."""
        if self._recording:
            return

        from pynput import mouse, keyboard

        self._events = []
        self._key_buffer = []
        self._key_buffer_start = 0.0
        self._recording = True
        self._start_time = time.time()

        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()
        logger.info("InputRecorder started")

    def stop(self) -> List[dict]:
        """Stop recording and return captured events."""
        if not self._recording:
            return []

        self._recording = False

        # Flush remaining key buffer
        self._flush_key_buffer()

        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None

        # Wait briefly for background a11y enrichment threads to finish.
        # Click events are already recorded; this just gives enrichment
        # a chance to populate element_name/screenshot fields.
        _deadline = time.time() + 1.5
        for t in threading.enumerate():
            if t.name == "a11y-enrich" and t.is_alive():
                remaining = _deadline - time.time()
                if remaining > 0:
                    t.join(timeout=remaining)

        # Strip the final click event if it occurred very close to stop time.
        # This is the stop-record button click itself — it's ALWAYS the last
        # event and happens within ~200ms of stop() being called.  Even if
        # the dashboard window-title filter catches it downstream, this is a
        # reliable belt-and-suspenders defense because it doesn't depend on
        # window title matching.
        _stop_ts = self._elapsed()
        if (self._events
                and self._events[-1].get("type") == "click"
                and (_stop_ts - self._events[-1].get("timestamp", 0)) < 0.5):
            _removed = self._events.pop()
            logger.info("InputRecorder: stripped trailing click (%.3fs before stop, title='%s')",
                        _stop_ts - _removed.get("timestamp", 0),
                        (_removed.get("window_title", "") or "")[:60])

        logger.info("InputRecorder stopped, captured %d events", len(self._events))
        return list(self._events)

    def _elapsed(self) -> float:
        return time.time() - self._start_time

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        if not pressed or not self._recording:
            return
        # Flush any pending keystrokes before recording a click
        self._flush_key_buffer()
        # Use WindowFromPoint first — more reliable for clicks that
        # close/dismiss their target window (e.g. "Don't Save" in Notepad),
        # because GetForegroundWindow may already reflect the next window.
        global _last_app_title
        window_title = _get_window_title_at(x, y)
        if not window_title:
            window_title = _get_fg_window_title()
        process_name = _get_fg_process_name()
        # Track whether this click is on the dashboard UI.
        # IMPORTANT: Do NOT remap dashboard clicks to _last_app_title.
        # The old behavior masked dashboard clicks with the previous app's
        # title, causing them to evade the dashboard filter in
        # stop_recording() and get saved+replayed in workflows.
        # Instead, keep the dashboard window_title intact so downstream
        # filters can properly strip these events.
        wt_lower = window_title.lower()
        _is_dashboard_click = any(m in wt_lower for m in _DASHBOARD_TITLE_MARKERS)
        if not _is_dashboard_click and window_title:
            _last_app_title = window_title

        # Capture window rect for window-relative coordinates (survives window moves)
        window_rect = _get_fg_window_rect()
        if window_rect is not None:
            win_x = x - window_rect[0]
            win_y = y - window_rect[1]
        else:
            win_x = win_y = None

        # Record click event IMMEDIATELY so subsequent clicks aren't lost
        # while a11y enrichment blocks.  A11y + screenshot run in a background
        # thread and update the event in-place via its index.
        with self._lock:
            event = {
                "type": "click",
                "timestamp": self._elapsed(),
                "x": x,
                "y": y,
                "button": str(button).split(".")[-1],  # "left", "right", "middle"
                "window_title": window_title,
                "element_type": "",
                "element_name": "",
                "element_automation_id": "",
                "element_parent_name": "",
                "confidence": 0.0,
                "process_name": process_name,
                "screenshot_b64": "",
            }
            if win_x is not None:
                event["window_x"] = win_x
                event["window_y"] = win_y
            self._events.append(event)
            event_idx = len(self._events) - 1
            self._action_count += 1
            action_count = self._action_count

        # Fire live action callback immediately (outside lock)
        if self._on_action:
            try:
                self._on_action({
                    "action_type": "click",
                    "window_title": window_title,
                    "element_name": "",
                    "count": action_count,
                })
            except Exception:
                pass

        # Enrich with a11y + screenshot in background thread so the pynput
        # listener thread is free to capture the next click immediately.
        capture_ss = self._capture_screenshots
        def _enrich():
            a11y = _get_a11y_element_at(x, y)
            screenshot_b64 = ""
            if capture_ss:
                screenshot_b64 = _capture_screenshot_sync()
            with self._lock:
                if event_idx < len(self._events):
                    ev = self._events[event_idx]
                    ev["element_type"] = a11y.get("element_type", "")
                    ev["element_name"] = a11y.get("element_name", "")
                    ev["element_automation_id"] = a11y.get("element_automation_id", "")
                    ev["element_parent_name"] = a11y.get("element_parent_name", "")
                    ev["confidence"] = a11y.get("confidence", 0.0)
                    ev["screenshot_b64"] = screenshot_b64

        threading.Thread(target=_enrich, daemon=True, name="a11y-enrich").start()

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self._recording:
            return
        self._flush_key_buffer()
        window_title = _get_fg_window_title()
        with self._lock:
            self._events.append({
                "type": "scroll",
                "timestamp": self._elapsed(),
                "x": x,
                "y": y,
                "scroll_dx": dx,
                "scroll_dy": dy,
                "window_title": window_title,
            })

    # Map special key names to their printable characters for text coalescing.
    # Without this, e.g. Key.space records as the literal string "space" in the
    # coalesce buffer, producing "spaceu" instead of " u".
    _PRINTABLE_KEY_MAP: dict[str, str] = {
        "space": " ",
    }

    def _on_key_press(self, key: Any) -> None:
        if not self._recording:
            return
        try:
            # Get the character or key name
            if hasattr(key, "char") and key.char:
                char = key.char
            else:
                char = str(key).replace("Key.", "")
                # Special keys that break text coalescing — recorded as "key" events
                if char in ("enter", "return", "tab", "escape", "backspace", "delete",
                            "ctrl_l", "ctrl_r", "alt_l", "alt_r", "shift", "shift_r",
                            "cmd", "cmd_r", "caps_lock"):
                    # Suppress key-repeat for modifier keys. When a user holds
                    # Shift/Ctrl/Alt/Win, Windows fires repeats every ~33ms.
                    # We only want the first press, not 20-30 duplicates.
                    _MODIFIERS = ("ctrl_l", "ctrl_r", "alt_l", "alt_r",
                                  "shift", "shift_r", "cmd", "cmd_r")
                    now = time.time()
                    if char in _MODIFIERS:
                        if (char == self._last_modifier_key
                                and (now - self._last_modifier_time) < 0.15):
                            return  # suppress key repeat
                        self._last_modifier_key = char
                        self._last_modifier_time = now
                    else:
                        self._last_modifier_key = ""
                    self._flush_key_buffer()
                    window_title = _get_fg_window_title()
                    with self._lock:
                        self._events.append({
                            "type": "key",
                            "timestamp": self._elapsed(),
                            "key": char,
                            "window_title": window_title,
                        })
                        self._action_count += 1
                    if self._on_action:
                        try:
                            self._on_action({
                                "action_type": "key",
                                "window_title": window_title,
                                "element_name": char,
                                "count": self._action_count,
                            })
                        except Exception:
                            pass
                    return
                # Convert printable special keys (e.g. space) to actual characters
                char = self._PRINTABLE_KEY_MAP.get(char, None)
                if char is None:
                    # Unknown special key — record as "key" event, don't coalesce
                    self._flush_key_buffer()
                    window_title = _get_fg_window_title()
                    key_name = str(key).replace("Key.", "")
                    with self._lock:
                        self._events.append({
                            "type": "key",
                            "timestamp": self._elapsed(),
                            "key": key_name,
                            "window_title": window_title,
                        })
                        self._action_count += 1
                    if self._on_action:
                        try:
                            self._on_action({
                                "action_type": "key",
                                "window_title": window_title,
                                "element_name": key_name,
                                "count": self._action_count,
                            })
                        except Exception:
                            pass
                    return

            # Coalesce printable characters
            now = time.time()
            with self._lock:
                if self._key_buffer and (now - self._key_buffer_start) > _KEY_COALESCE_DELAY:
                    self._flush_key_buffer_locked()
                if not self._key_buffer:
                    self._key_buffer_start = now
                self._key_buffer.append(char)
        except Exception:
            pass

    def _on_key_release(self, key: Any) -> None:
        pass  # We only track key presses

    def _flush_key_buffer(self) -> None:
        with self._lock:
            self._flush_key_buffer_locked()

    def _flush_key_buffer_locked(self) -> None:
        if self._key_buffer:
            text = "".join(self._key_buffer)
            window_title = _get_fg_window_title()
            self._events.append({
                "type": "type",
                "timestamp": self._elapsed(),
                "text": text,
                "window_title": window_title,
            })
            self._key_buffer = []
            self._action_count += 1
            # Fire live action callback for typed text
            if self._on_action:
                try:
                    self._on_action({
                        "action_type": "type",
                        "window_title": window_title,
                        "element_name": "",
                        "count": self._action_count,
                    })
                except Exception:
                    pass
