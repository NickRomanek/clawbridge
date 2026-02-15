"""Low-level input recording using pynput (thread-based).

Captures mouse clicks/scrolls and keyboard events, coalescing rapid keystrokes
into single "type" events. Each event is tagged with the current foreground
window title at capture time.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, List

logger = logging.getLogger(__name__)

# Delay (seconds) before coalescing buffered keystrokes into a "type" event
_KEY_COALESCE_DELAY = 0.3


def _get_fg_window_title() -> str:
    """Get the foreground window title via ctypes (fast, no imports cached)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        buf = ctypes.create_unicode_buffer(512)
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            user32.GetWindowTextW(hwnd, buf, 512)
            return buf.value
    except Exception:
        pass
    return ""


class InputRecorder:
    """Records mouse and keyboard input via pynput listeners.

    Usage:
        recorder = InputRecorder()
        recorder.start()
        # ... user performs actions ...
        events = recorder.stop()  # returns list[dict]
    """

    def __init__(self):
        self._events: List[dict] = []
        self._mouse_listener = None
        self._keyboard_listener = None
        self._recording = False
        self._lock = threading.Lock()
        self._key_buffer: List[str] = []
        self._key_buffer_start: float = 0.0
        self._start_time: float = 0.0

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

        logger.info("InputRecorder stopped, captured %d events", len(self._events))
        return list(self._events)

    def _elapsed(self) -> float:
        return time.time() - self._start_time

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        if not pressed or not self._recording:
            return
        # Flush any pending keystrokes before recording a click
        self._flush_key_buffer()
        window_title = _get_fg_window_title()
        with self._lock:
            self._events.append({
                "type": "click",
                "timestamp": self._elapsed(),
                "x": x,
                "y": y,
                "button": str(button).split(".")[-1],  # "left", "right", "middle"
                "window_title": window_title,
            })

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

    def _on_key_press(self, key: Any) -> None:
        if not self._recording:
            return
        try:
            # Get the character or key name
            if hasattr(key, "char") and key.char:
                char = key.char
            else:
                char = str(key).replace("Key.", "")
                # Special keys that break text coalescing
                if char in ("enter", "return", "tab", "escape", "backspace", "delete",
                            "ctrl_l", "ctrl_r", "alt_l", "alt_r", "shift", "shift_r",
                            "cmd", "cmd_r", "caps_lock"):
                    self._flush_key_buffer()
                    window_title = _get_fg_window_title()
                    with self._lock:
                        self._events.append({
                            "type": "key",
                            "timestamp": self._elapsed(),
                            "key": char,
                            "window_title": window_title,
                        })
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
