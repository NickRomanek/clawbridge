"""Screenshot utilities extracted from ComputerUseEngine for reuse by recorder/replay."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Tuple

from clawbridge.platform import platform as _plat

logger = logging.getLogger(__name__)


async def take_screenshot(scaled_w: int, scaled_h: int, screen_w: int, screen_h: int) -> str:
    """Capture full screen, scale to target dimensions, return base64 PNG."""
    loop = asyncio.get_running_loop()

    def _capture() -> str:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = sct.grab(monitor)
            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            if pil_img.size != (scaled_w, scaled_h):
                pil_img = pil_img.resize((scaled_w, scaled_h), Image.LANCZOS)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

    return await loop.run_in_executor(None, _capture)


async def take_window_crop(rect: Tuple[int, int, int, int], max_dim: int = 1280) -> str | None:
    """Capture a crop of the screen at *rect* (left, top, right, bottom), return base64 PNG."""
    loop = asyncio.get_running_loop()

    def _capture() -> str | None:
        import mss
        from PIL import Image

        left, top, right, bottom = rect
        w, h = right - left, bottom - top
        if w < 20 or h < 20:
            return None
        region = {"left": left, "top": top, "width": w, "height": h}
        with mss.mss() as sct:
            img = sct.grab(region)
            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            # Scale down if too large
            if max(pil_img.size) > max_dim:
                ratio = max_dim / max(pil_img.size)
                new_size = (int(pil_img.width * ratio), int(pil_img.height * ratio))
                pil_img = pil_img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

    try:
        return await loop.run_in_executor(None, _capture)
    except Exception:
        return None


async def get_foreground_window_rect(screen_w: int, screen_h: int) -> Tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) of the foreground window, or None."""
    loop = asyncio.get_running_loop()

    def _get_rect() -> Tuple[int, int, int, int] | None:
        raw = _plat.get_foreground_window_rect()
        if not raw:
            return None
        left = max(0, raw[0])
        top = max(0, raw[1])
        right = min(screen_w, raw[2])
        bottom = min(screen_h, raw[3])
        if right - left < 20 or bottom - top < 20:
            return None
        return (left, top, right, bottom)

    try:
        return await loop.run_in_executor(None, _get_rect)
    except Exception:
        return None


async def screenshots_similar(b64_a: str, b64_b: str, threshold: int = 5) -> bool:
    """Compare two base64-encoded screenshots. Returns True if average pixel diff < threshold."""
    loop = asyncio.get_running_loop()

    def _compare() -> bool:
        from PIL import Image
        import numpy as np

        img_a = Image.open(io.BytesIO(base64.b64decode(b64_a))).convert("RGB")
        img_b = Image.open(io.BytesIO(base64.b64decode(b64_b))).convert("RGB")
        # Resize to same small size for fast comparison
        size = (160, 90)
        img_a = img_a.resize(size, Image.LANCZOS)
        img_b = img_b.resize(size, Image.LANCZOS)
        arr_a = np.array(img_a, dtype=np.float32)
        arr_b = np.array(img_b, dtype=np.float32)
        diff = np.mean(np.abs(arr_a - arr_b))
        return diff < threshold

    try:
        return await loop.run_in_executor(None, _compare)
    except Exception:
        return False
