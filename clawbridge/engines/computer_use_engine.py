"""Computer-use engine adapter for ClawBridge.

Provides full desktop control (mouse, keyboard, screenshots) via Anthropic's
computer-use tool API.  Works with ANTHROPIC_API_KEY directly or via
OPENROUTER_API_KEY as a proxy.

Requires: anthropic, pyautogui, Pillow, mss
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from clawbridge.config import get_settings
from clawbridge.engines.base import EngineBase, EngineError
from clawbridge.shared.schemas import (
    EngineName,
    EngineStatus,
    StepResult,
    Task,
    TaskResult,
    TaskStatus,
    TaskStep,
    TokenUsage,
)

logger = logging.getLogger(__name__)


# Keywords in a task prompt that suggest desktop (not browser) work.
DESKTOP_KEYWORDS = [
    # OS elements
    "desktop", "taskbar", "start menu", "system tray", "notification",
    "folder", "file manager", "explorer", "finder", "dock", "spotlight",
    "system preferences", "settings", "control panel",
    # Office / productivity
    "app", "application", "notepad", "excel", "word", "powerpoint",
    "libreoffice", "calc", "writer", "outlook", "onenote",
    # Terminal
    "terminal", "command prompt", "powershell", "cmd", "wsl", "bash",
    # Messaging / communication
    "telegram", "discord", "slack", "whatsapp", "signal", "skype",
    "teams", "zoom", "webex", "google meet",
    # Browsers (when referenced as desktop apps)
    "chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari",
    # Media
    "spotify", "vlc", "media player", "foobar", "winamp", "itunes",
    # Dev tools
    "vscode", "vs code", "visual studio", "intellij", "pycharm",
    "sublime", "atom", "cursor",
    # Gaming / misc
    "steam", "epic games", "obs", "obs studio",
    # Knowledge / notes
    "notion", "obsidian", "evernote", "todoist", "trello",
    # Window actions
    "drag", "window", "minimize", "maximize", "close window",
    "screenshot", "snipping tool", "paint",
]


# ── System prompt template ─────────────────────────────────────────────
# Uses {scaled_width} and {scaled_height} placeholders, filled at runtime.
SYSTEM_PROMPT_TEMPLATE = """\
You are a desktop automation agent controlling a Windows PC.
The screen is {scaled_width}x{scaled_height} pixels.

================================================================
MANDATORY REASONING PROTOCOL
================================================================
Before choosing ANY action, you MUST write your reasoning in this format:

[OBSERVE] What I see on screen right now (list visible windows, apps, UI elements)
[GOAL] The specific sub-goal I need to accomplish next
[PLAN] Which decision path I will follow (reference the trees below)
[ACTION] The exact action I will take and why

Do NOT skip this reasoning. It makes your actions more accurate.

================================================================
DECISION TREE 1: FINDING OR SWITCHING TO AN APP
================================================================
For ANY app you need to interact with, follow this EXACT order.
STOP at the first level that succeeds.

LEVEL 1 — IS THE APP ALREADY VISIBLE ON SCREEN?
  Scan the entire screenshot for the app window. Visual fingerprints:

  Telegram:
    - Blue header bar with app name
    - Chat list on the left side
    - Message input at BOTTOM with placeholder "Write a message..."
    - If you see "Write a message..." anywhere, Telegram is open

  Discord:
    - Dark gray/purple UI
    - Channel sidebar on the left
    - Message box at bottom with "Message #channel" placeholder

  Slack:
    - Purple/white UI with channel sidebar
    - Message composer at bottom of conversation

  WhatsApp:
    - Green header bar
    - Chat list or conversation view

  Browser (Chrome / Edge / Firefox):
    - Tab bar at the very top
    - Address bar just below tabs
    - Webpage content area

  VS Code / Cursor:
    - Dark sidebar with file tree on left
    - Editor tabs across the top
    - Integrated terminal at the bottom

  File Explorer:
    - Navigation breadcrumb at top
    - Folder tree on left pane
    - File/folder list on right pane

  Spotify:
    - Dark UI with green accent color
    - Playlist sidebar on left
    - Playback controls at bottom

  -> If the app is VISIBLE: interact with it directly.
     DO NOT search for it, re-open it, or navigate to it.

LEVEL 2 — IS IT ON THE TASKBAR?
  Look at the BOTTOM of the screen. The Windows taskbar shows:
  - Pinned app icons (always visible)
  - Running app icons (have a thin line/underline beneath them)
  -> If ON TASKBAR: single-click the icon to bring app to foreground.
     Then WAIT for the next screenshot to confirm it appeared.

LEVEL 3 — USE WINDOWS SEARCH (LAST RESORT ONLY)
  -> Click the search icon on the taskbar or press the Windows key.
  -> Type the app name, wait for results, click the matching result.
  -> Only use this if the app is NOT visible AND NOT on the taskbar.

================================================================
DECISION TREE 2: MESSAGING APPS (Telegram, Discord, Slack, etc.)
================================================================
Once the messaging app is in the foreground:

Step 1: Is the correct conversation/chat already open?
  HOW TO CHECK: Read the FOREGROUND WINDOW line in the SYSTEM INFO section.
  The window title typically contains the chat/channel name.
  Examples:
    - "Agent intelligence – (351553)" means Telegram has "Agent intelligence" open
    - "$BOOTS Community – (351556)" means a DIFFERENT chat is open
    - "#general - Discord" means Discord has the #general channel open
  -> If the correct chat IS open in the window title: skip to Step 3
  -> If a DIFFERENT chat is open or you're unsure: go to Step 2

Step 2: Navigate to the correct conversation using SEARCH
  IMPORTANT: Do NOT try to click on chat items in the sidebar list.
  Sidebar items are small and tightly packed — clicking them is unreliable.
  ALWAYS use the app's search bar instead:

  For Telegram:
    1. Click the search bar at the top of Telegram (or press Escape first
       to clear any current state, then click the search field)
    2. Type the chat/group name
    3. Wait for search results to appear
    4. Click the FIRST matching result
    5. Wait for the conversation to load and verify via SYSTEM INFO

  For Discord:
    1. Press Ctrl+K to open Quick Switcher
    2. Type the channel name
    3. Click the matching result

  For Slack:
    1. Press Ctrl+K to open Quick Switcher
    2. Type the channel/person name
    3. Click the matching result

Step 3: Type and send the message
  - Click the message input field at the BOTTOM of the conversation
    (look for placeholder text like "Write a message...", "Type a message...",
     "Message #channel", etc.)
  - Type the message text
  - Press Enter to send (unless the task says NOT to send)

================================================================
DECISION TREE 3: BROWSER TASKS
================================================================
Step 1: Is a browser already open?
  -> If YES: click the address bar (or press Ctrl+L), type the URL, press Enter
  -> If NO: follow Decision Tree 1 to open a browser first

Step 2: Do NOT close or rearrange existing tabs unless the task requires it.

================================================================
HOW TO USE SYSTEM INFO
================================================================
Each tool result includes SYSTEM INFO from Windows accessibility APIs.
This is MORE RELIABLE than trying to read text from the screenshot.

- FOREGROUND WINDOW: Tells you the title of the currently focused window.
  Use this to determine WHICH app and WHICH chat/document is active.
- VISIBLE WINDOWS: Lists all open windows. Use this to determine what's available.
- RUNNING APPS: Lists running processes. Use this to know what's installed/running.

ALWAYS check SYSTEM INFO before deciding your next action.

================================================================
ANTI-PATTERNS — NEVER DO THESE
================================================================
- PREFER using search over clicking dense sidebar items, but if the ZOOMED
  VIEW clearly shows the target and you can locate it in the FULL SCREEN
  image, a direct click is acceptable
- NEVER search for an app that is already visible on screen
- NEVER re-open an app that is already in the foreground
- NEVER type text without first clicking the target input field
- NEVER use the Start menu / search if the app icon is on the taskbar
- NEVER close, minimize, or move windows you don't need to touch
- NEVER take more than 3 actions to reach an input field already visible on screen
- NEVER repeat the same failed action — try a different approach
- NEVER request a "screenshot" action — you already receive a fresh screenshot
  after every action automatically

================================================================
CORE RULES
================================================================
1. ONE action per turn. Examine the result screenshot before the next action.
2. Aim for the CENTER of clickable elements (buttons, fields, icons).
3. Be efficient — take the FEWEST actions possible to complete the task.
4. If an action didn't work (screenshot looks the same), try a DIFFERENT approach.
5. When the task is complete, respond with a text summary (no tool call).
6. TRUST the SYSTEM INFO text data over what you think you see in screenshots.

================================================================
DUAL IMAGE PROTOCOL
================================================================
Each turn you may receive TWO images:
1. FULL SCREEN — shows the entire desktop at {scaled_width}x{scaled_height}.
   ALL your coordinate-based actions (clicks, drags, etc.) MUST use
   coordinates from THIS image.
2. ZOOMED VIEW — a higher-resolution crop of the foreground window.
   Use this ONLY for reading text, verifying UI elements, and understanding
   details that are hard to see in the full screen image.
   Do NOT estimate coordinates from the zoomed view.

If only one image is present, it is always the full screen image.
"""


def looks_like_desktop_task(prompt: str) -> bool:
    """Heuristic: does the prompt sound like it needs desktop control?"""
    lower = prompt.lower()
    return any(kw in lower for kw in DESKTOP_KEYWORDS)


class ComputerUseEngine(EngineBase):
    """Agent engine for full desktop control via Anthropic's computer-use tool."""

    def __init__(self) -> None:
        self._status: EngineStatus = EngineStatus.STOPPED
        self._client: Any = None  # anthropic.Anthropic instance
        self._model: str = ""
        self._is_openrouter: bool = False
        self._screen_width: int = 0
        self._screen_height: int = 0
        self._scaled_width: int = 0
        self._scaled_height: int = 0
        self.on_screenshot: Callable[[str], Any] | None = None

    # ── EngineBase properties ─────────────────────────────────────────────

    @property
    def name(self) -> EngineName:
        return EngineName.COMPUTER_USE

    @property
    def display_name(self) -> str:
        return "computer-use"

    @property
    def description(self) -> str:
        return (
            "Full desktop control via mouse, keyboard, and screenshots. "
            "Powered by Anthropic computer-use."
        )

    def _capabilities(self) -> list[str]:
        return ["mouse", "keyboard", "screenshot", "desktop_control", "type", "click"]

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Import deps, detect screen, create Anthropic client."""
        self._status = EngineStatus.STARTING
        settings = get_settings()

        # 1. Check required packages
        try:
            import anthropic  # noqa: F401
            import pyautogui  # noqa: F401
            import mss  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError as exc:
            self._status = EngineStatus.NOT_INSTALLED
            logger.warning(
                "computer-use dependencies not installed (%s). "
                "Install with: pip install anthropic pyautogui Pillow mss",
                exc,
            )
            return

        # 2. Detect screen resolution & ensure DPI-aware pixel coords
        try:
            import ctypes as _ct
            _ct.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

        try:
            self._screen_width, self._screen_height = pyautogui.size()
            logger.info(
                "Screen detected: %dx%d", self._screen_width, self._screen_height
            )
        except Exception as exc:
            self._status = EngineStatus.ERROR
            logger.error(
                "Cannot detect screen (headless environment?): %s", exc
            )
            return

        # 3. Compute scaled dimensions for API screenshots
        max_w = settings.computer_use_max_screen_width
        max_h = settings.computer_use_max_screen_height
        scale = min(max_w / self._screen_width, max_h / self._screen_height, 1.0)
        self._scaled_width = int(self._screen_width * scale)
        self._scaled_height = int(self._screen_height * scale)

        # 4. Create Anthropic client (direct or via OpenRouter)
        try:
            self._model = settings.computer_use_model
            if settings.has_anthropic_key:
                self._client = anthropic.Anthropic(
                    api_key=settings.anthropic_api_key,
                )
            elif settings.has_openrouter_key:
                # OpenRouter's "Anthropic Skin" -- base_url must be /api (not /api/v1)
                self._client = anthropic.Anthropic(
                    api_key=settings.openrouter_api_key,
                    base_url="https://openrouter.ai/api",
                )
                self._is_openrouter = True
                # OpenRouter uses its own model naming convention
                if "/" not in self._model:
                    self._model = f"anthropic/{self._model}"
            else:
                self._status = EngineStatus.ERROR
                logger.warning(
                    "computer-use requires ANTHROPIC_API_KEY or OPENROUTER_API_KEY"
                )
                return

            self._status = EngineStatus.AVAILABLE
            logger.info(
                "computer-use engine initialized (model=%s, scaled=%dx%d)",
                self._model,
                self._scaled_width,
                self._scaled_height,
            )

        except Exception as exc:
            self._status = EngineStatus.ERROR
            logger.error("computer-use initialization failed: %s", exc, exc_info=True)

    async def stop(self) -> None:
        self._client = None
        self._status = EngineStatus.STOPPED
        logger.info("computer-use engine stopped")

    async def get_status(self) -> EngineStatus:
        return self._status

    # ── Screenshot helpers ────────────────────────────────────────────────

    async def _take_screenshot(self) -> str:
        """Capture the primary monitor, scale, return base64 PNG."""
        import mss as mss_mod
        from PIL import Image

        loop = asyncio.get_event_loop()

        def _capture() -> str:
            with mss_mod.mss() as sct:
                monitor = sct.monitors[1]  # primary
                raw = sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                # Scale down for the API
                if (
                    img.width > self._scaled_width
                    or img.height > self._scaled_height
                ):
                    img = img.resize(
                        (self._scaled_width, self._scaled_height),
                        Image.LANCZOS,
                    )

                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("utf-8")

        return await loop.run_in_executor(None, _capture)

    def _broadcast_screenshot(self, b64: str) -> None:
        """Push a screenshot to the dashboard live view."""
        if self.on_screenshot:
            try:
                self.on_screenshot(b64)
            except Exception as exc:
                logger.debug("Screenshot broadcast failed: %s", exc)

    # ── Foreground window rect & crop ─────────────────────────────────

    async def _get_foreground_window_rect(self) -> tuple[int, int, int, int] | None:
        """Get the foreground window bounding box in raw screen pixels.

        Returns (left, top, right, bottom) or None if detection fails
        or the crop would be redundant (e.g. window is nearly fullscreen).
        """
        loop = asyncio.get_event_loop()

        def _get() -> tuple[int, int, int, int] | None:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            try:
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    return None
                rect = RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return None
                left = max(0, rect.left)
                top = max(0, rect.top)
                right = min(self._screen_width, rect.right)
                bottom = min(self._screen_height, rect.bottom)
                w, h = right - left, bottom - top
                if w <= 0 or h <= 0:
                    return None
                # Skip if nearly fullscreen (crop ≈ full screenshot)
                if w >= self._screen_width * 0.95 and h >= self._screen_height * 0.95:
                    return None
                # Skip tiny windows (tooltips, popups)
                if w < 200 or h < 150:
                    return None
                return (left, top, right, bottom)
            except Exception:
                return None

        try:
            return await loop.run_in_executor(None, _get)
        except Exception:
            return None

    async def _take_window_crop(
        self, rect: tuple[int, int, int, int], max_dim: int = 1280
    ) -> str | None:
        """Capture the foreground window region at higher resolution.

        Args:
            rect: (left, top, right, bottom) in raw screen pixels.
            max_dim: Cap for the longest dimension of the crop.

        Returns base64-encoded PNG, or None on failure.
        """
        import mss as mss_mod
        from PIL import Image

        left, top, right, bottom = rect
        loop = asyncio.get_event_loop()

        def _capture() -> str | None:
            try:
                with mss_mod.mss() as sct:
                    monitor = {
                        "left": left,
                        "top": top,
                        "width": right - left,
                        "height": bottom - top,
                    }
                    raw = sct.grab(monitor)
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                    # Scale down only if larger than max_dim
                    w, h = img.size
                    if max(w, h) > max_dim:
                        scale = max_dim / max(w, h)
                        img = img.resize(
                            (int(w * scale), int(h * scale)),
                            Image.LANCZOS,
                        )

                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    return base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception as exc:
                logger.debug("Window crop failed: %s", exc)
                return None

        try:
            return await loop.run_in_executor(None, _capture)
        except Exception:
            return None

    # ── Screen description (Windows accessibility) ─────────────────────

    async def _describe_screen(self) -> str:
        """Use Windows accessibility APIs to describe visible windows and
        key UI elements as plain text.  This supplements the screenshot so
        the model doesn't have to rely solely on vision to know what's open.
        """
        loop = asyncio.get_event_loop()

        def _gather() -> str:
            import subprocess as _sp

            lines: list[str] = []

            # 1. List visible (non-minimized) windows via PowerShell
            try:
                ps = (
                    "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} "
                    "| Select-Object ProcessName, MainWindowTitle "
                    "| Format-Table -AutoSize -HideTableHeaders"
                )
                out = _sp.check_output(
                    ["powershell", "-NoProfile", "-Command", ps],
                    timeout=3,
                    text=True,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
                windows = [
                    w.strip() for w in out.strip().splitlines() if w.strip()
                ]
                if windows:
                    lines.append("VISIBLE WINDOWS:")
                    for w in windows[:15]:
                        lines.append(f"  - {w}")
            except Exception:
                pass

            # 2. Identify the foreground window
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if buf.value:
                    lines.append(f"\nFOREGROUND WINDOW: {buf.value}")
            except Exception:
                pass

            # 3. Check if common apps are running
            try:
                ps2 = (
                    "Get-Process -Name Telegram,Discord,Slack,Spotify,"
                    "chrome,msedge,firefox,Code,Telegram.Desktop "
                    "-ErrorAction SilentlyContinue "
                    "| Select-Object ProcessName -Unique "
                    "| Format-Table -HideTableHeaders"
                )
                out2 = _sp.check_output(
                    ["powershell", "-NoProfile", "-Command", ps2],
                    timeout=3,
                    text=True,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
                apps = [a.strip() for a in out2.strip().splitlines() if a.strip()]
                if apps:
                    lines.append(f"\nRUNNING APPS: {', '.join(apps)}")
            except Exception:
                pass

            return "\n".join(lines) if lines else ""

        try:
            return await loop.run_in_executor(None, _gather)
        except Exception:
            return ""

    # ── Screenshot comparison ────────────────────────────────────────────

    @staticmethod
    def _screenshots_similar(b64_a: str, b64_b: str, threshold: int = 5) -> bool:
        """Compare two base64 PNG screenshots using average perceptual hash.

        Returns True if the images are nearly identical (hamming distance
        between their 64-bit average hashes is <= *threshold*).
        """
        from PIL import Image

        def _avg_hash(b64: str) -> int:
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            img = img.resize((8, 8), Image.LANCZOS).convert("L")
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            return sum(1 << i for i, p in enumerate(pixels) if p >= avg)

        hash_a = _avg_hash(b64_a)
        hash_b = _avg_hash(b64_b)
        distance = bin(hash_a ^ hash_b).count("1")
        return distance <= threshold

    # ── Action execution ──────────────────────────────────────────────────

    async def _execute_action(self, tool_input: dict) -> str:
        """Translate a Claude computer-use tool_input into a pyautogui call.

        Returns a short human-readable status string.
        """
        import pyautogui

        loop = asyncio.get_event_loop()
        action = tool_input.get("action", "")

        # Coordinate scaling: Claude uses scaled coords, pyautogui needs real ones
        def _scale_coord(coord: list[int]) -> tuple[int, int]:
            x, y = coord
            sx = int(x * self._screen_width / self._scaled_width)
            sy = int(y * self._screen_height / self._scaled_height)
            # Clamp to screen bounds
            sx = max(0, min(sx, self._screen_width - 1))
            sy = max(0, min(sy, self._screen_height - 1))
            return sx, sy

        if action == "screenshot":
            return "screenshot_taken"

        elif action == "mouse_move":
            rx, ry = _scale_coord(tool_input["coordinate"])
            await loop.run_in_executor(
                None, lambda: pyautogui.moveTo(rx, ry, duration=0.3)
            )
            return f"mouse_moved_to_{rx}_{ry}"

        elif action == "left_click":
            rx, ry = _scale_coord(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.click(rx, ry))
            return f"clicked_{rx}_{ry}"

        elif action == "right_click":
            rx, ry = _scale_coord(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.rightClick(rx, ry))
            return f"right_clicked_{rx}_{ry}"

        elif action == "double_click":
            rx, ry = _scale_coord(tool_input["coordinate"])
            await loop.run_in_executor(None, lambda: pyautogui.doubleClick(rx, ry))
            return f"double_clicked_{rx}_{ry}"

        elif action == "middle_click":
            rx, ry = _scale_coord(tool_input["coordinate"])
            await loop.run_in_executor(
                None, lambda: pyautogui.middleClick(rx, ry)
            )
            return f"middle_clicked_{rx}_{ry}"

        elif action == "left_click_drag":
            start = _scale_coord(tool_input["start_coordinate"])
            end = _scale_coord(tool_input["coordinate"])

            def _drag():
                pyautogui.moveTo(start[0], start[1])
                pyautogui.drag(
                    end[0] - start[0], end[1] - start[1], duration=0.5
                )

            await loop.run_in_executor(None, _drag)
            return f"dragged_{start}_to_{end}"

        elif action == "type":
            text = tool_input.get("text", "")

            def _type_text():
                # pyautogui.write() only handles ASCII; for Unicode use
                # the clipboard-paste fallback.
                if text.isascii():
                    pyautogui.write(text, interval=0.02)
                else:
                    import pyperclip

                    pyperclip.copy(text)
                    pyautogui.hotkey("ctrl", "v")

            await loop.run_in_executor(None, _type_text)
            return f"typed_{len(text)}_chars"

        elif action == "key":
            key_combo = tool_input.get("text", "")

            def _press():
                keys = [k.strip() for k in key_combo.split("+")]
                if len(keys) > 1:
                    pyautogui.hotkey(*keys)
                else:
                    pyautogui.press(keys[0])

            await loop.run_in_executor(None, _press)
            return f"pressed_{key_combo}"

        elif action == "cursor_position":
            pos = pyautogui.position()
            return f"cursor_at_{pos.x}_{pos.y}"

        elif action == "scroll":
            rx, ry = _scale_coord(tool_input.get("coordinate", [self._scaled_width // 2, self._scaled_height // 2]))
            clicks = tool_input.get("amount", 3)

            def _scroll():
                pyautogui.scroll(clicks, x=rx, y=ry)

            await loop.run_in_executor(None, _scroll)
            return f"scrolled_{clicks}_at_{rx}_{ry}"

        else:
            logger.warning("Unknown computer-use action: %s", action)
            return f"unknown_action_{action}"

    # ── Task execution ────────────────────────────────────────────────────

    async def run_task(self, task: Task) -> Task:
        """Run a full task using the Anthropic computer-use tool loop."""
        if self._status != EngineStatus.AVAILABLE:
            raise EngineError(
                EngineName.COMPUTER_USE,
                f"Engine not available (status: {self._status.value})",
            )

        self._status = EngineStatus.RUNNING
        start_time = time.monotonic()
        settings = get_settings()
        max_steps = min(settings.max_actions_per_task, 50)
        action_delay = settings.computer_use_action_delay_ms / 1000.0

        try:
            # Initial screenshot + accessibility description
            initial_screenshot = await self._take_screenshot()
            self._broadcast_screenshot(initial_screenshot)
            screen_desc = await self._describe_screen()
            if screen_desc:
                logger.info("Screen description:\n%s", screen_desc)

            # Native Anthropic computer-use tool (direct API only)
            native_tool = [
                {
                    "type": "computer_20241022",
                    "name": "computer",
                    "display_width_px": self._scaled_width,
                    "display_height_px": self._scaled_height,
                    "display_number": 1,
                }
            ]
            # Standard function tool for OpenRouter compatibility
            func_tool = [
                {
                    "name": "computer",
                    "description": (
                        f"Control the computer screen ({self._scaled_width}x"
                        f"{self._scaled_height}). Returns a screenshot after "
                        "the action."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "screenshot", "mouse_move", "left_click",
                                    "right_click", "double_click", "middle_click",
                                    "left_click_drag", "type", "key",
                                    "cursor_position", "scroll",
                                ],
                                "description": "The action to perform",
                            },
                            "coordinate": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "[x, y] pixel coordinates for mouse actions",
                            },
                            "start_coordinate": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "[x, y] start coordinates for drag",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text to type, or key combo like 'ctrl+c'",
                            },
                            "amount": {
                                "type": "integer",
                                "description": "Scroll amount (positive=up, negative=down)",
                            },
                        },
                        "required": ["action"],
                    },
                }
            ]
            tools = native_tool if not self._is_openrouter else func_tool

            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                scaled_width=self._scaled_width,
                scaled_height=self._scaled_height,
            )

            # Build the initial user message with task + screenshot + context
            context_text = ""
            if screen_desc:
                context_text += (
                    f"SYSTEM INFO (from Windows accessibility APIs):\n"
                    f"{screen_desc}\n\n"
                    "Use this info to understand what is ALREADY open. "
                    "If the target app is listed in VISIBLE WINDOWS or "
                    "FOREGROUND WINDOW, it is already on screen — interact "
                    "with it directly in the screenshot."
                )
            context_text += "\n\nComplete the task."

            # Attempt to capture a zoomed crop of the foreground window
            fg_rect = await self._get_foreground_window_rect()
            initial_crop = None
            if fg_rect:
                initial_crop = await self._take_window_crop(fg_rect)
                if initial_crop:
                    logger.info(
                        "Initial crop: window at (%d,%d)-(%d,%d)",
                        *fg_rect,
                    )

            content_blocks: list[dict[str, Any]] = [
                {"type": "text", "text": task.prompt},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": initial_screenshot,
                    },
                },
            ]

            if initial_crop:
                content_blocks.append({
                    "type": "text",
                    "text": (
                        "Above: FULL SCREEN overview. Below: ZOOMED VIEW of "
                        "the foreground window for reading text clearly. "
                        "IMPORTANT: All coordinate values in your actions "
                        "MUST refer to the FULL SCREEN image above. Do NOT "
                        "use coordinates from the zoomed view."
                    ),
                })
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": initial_crop,
                    },
                })

            content_blocks.append({"type": "text", "text": context_text})
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": content_blocks}
            ]

            step_count = 0
            total_input_tokens = 0
            total_output_tokens = 0
            final_text = ""
            prev_screenshot = initial_screenshot  # for stale detection

            while step_count < max_steps:
                # Call Anthropic API with computer-use beta
                api_kwargs = dict(
                    model=self._model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=tools,
                    messages=messages,
                )
                if not self._is_openrouter:
                    api_kwargs["betas"] = ["computer-use-2024-10-22"]
                response = self._client.messages.create(**api_kwargs)

                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                # Separate tool-use blocks from text blocks
                tool_use_blocks = [
                    b for b in response.content if b.type == "tool_use"
                ]
                text_blocks = [
                    b.text for b in response.content if b.type == "text"
                ]

                if text_blocks:
                    final_text = "\n".join(text_blocks)
                    # Log the model's reasoning so users can see the thought
                    # process in the console / log file.
                    for tb in text_blocks:
                        logger.info(
                            "computer-use reasoning (step %d): %s",
                            step_count + 1,
                            tb[:500],
                        )

                # If no tool calls, the model is done
                if not tool_use_blocks:
                    break

                # Execute each tool call and collect results
                tool_results: list[dict[str, Any]] = []
                for tool_block in tool_use_blocks:
                    action_name = tool_block.input.get("action", "")
                    is_screenshot_only = action_name == "screenshot"

                    # Screenshot requests don't count as real steps
                    if not is_screenshot_only:
                        step_count += 1

                    logger.info(
                        "computer-use step %d/%d: %s%s",
                        step_count,
                        max_steps,
                        action_name or "?",
                        " (free)" if is_screenshot_only else "",
                    )

                    # Execute the action (screenshot is a no-op)
                    if not is_screenshot_only:
                        await self._execute_action(tool_block.input)
                        # Wait for UI to settle after real actions
                        await asyncio.sleep(action_delay)

                    screenshot_b64 = await self._take_screenshot()
                    self._broadcast_screenshot(screenshot_b64)
                    step_desc = await self._describe_screen()

                    # Build tool_result content with optional hints
                    result_content: list[dict[str, Any]] = []

                    # Step budget + screen info
                    hint = f"[Step {step_count} of {max_steps}]"
                    if step_desc:
                        hint += f"\n\nCURRENT SYSTEM STATE:\n{step_desc}"
                    result_content.append({
                        "type": "text",
                        "text": hint,
                    })

                    # Stale screenshot detection — only for real actions
                    if (
                        not is_screenshot_only
                        and prev_screenshot
                        and self._screenshots_similar(
                            prev_screenshot, screenshot_b64
                        )
                    ):
                        result_content.append({
                            "type": "text",
                            "text": (
                                "WARNING: The screenshot appears unchanged after "
                                "your last action. The action may have had no "
                                "effect. Consider trying a different approach."
                            ),
                        })
                        logger.warning(
                            "Stale screenshot detected at step %d", step_count
                        )

                    result_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    })

                    # Foreground window crop for text readability
                    fg_rect = await self._get_foreground_window_rect()
                    if fg_rect:
                        crop_b64 = await self._take_window_crop(fg_rect)
                        if crop_b64:
                            result_content.append({
                                "type": "text",
                                "text": (
                                    "Above: FULL SCREEN. Below: ZOOMED "
                                    "foreground window. Use FULL SCREEN "
                                    "coordinates for all actions."
                                ),
                            })
                            result_content.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": crop_b64,
                                },
                            })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result_content,
                    })

                    prev_screenshot = screenshot_b64

                # Append conversation turns
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            else:
                # Exhausted max_steps
                if not final_text:
                    final_text = (
                        f"Reached maximum step limit ({max_steps}). "
                        "Task may be incomplete."
                    )

            duration_ms = int((time.monotonic() - start_time) * 1000)

            task.result = TaskResult(
                summary=(final_text or "Task completed.")[:5000],
                total_steps=step_count,
                total_duration_ms=duration_ms,
                engine_used=EngineName.COMPUTER_USE,
                tokens_used=TokenUsage(
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                ),
            )
            task.status = TaskStatus.COMPLETE
            task.updated_at = datetime.now(tz=timezone.utc)
            logger.info(
                "Task %s completed via computer-use in %dms (%d steps)",
                task.id,
                duration_ms,
                step_count,
            )

        except Exception as exc:
            task.status = TaskStatus.ERROR
            task.error = str(exc)
            task.updated_at = datetime.now(tz=timezone.utc)
            logger.error("Task %s failed via computer-use: %s", task.id, exc)

        finally:
            self._status = EngineStatus.AVAILABLE

        return task

    async def execute_step(self, task: Task, step: TaskStep) -> StepResult:
        """Execute a single step by wrapping it as a micro-task."""
        micro_task = Task(
            prompt=f"{step.action}: {step.target}",
            engine=EngineName.COMPUTER_USE,
        )
        result_task = await self.run_task(micro_task)
        return StepResult(
            summary=(
                result_task.result.summary if result_task.result else "Step completed"
            ),
            duration_ms=(
                result_task.result.total_duration_ms if result_task.result else 0
            ),
        )
