"""Process raw recorded events into enriched RecordedAction objects.

Events arrive pre-enriched from InputRecorder (a11y data and screenshots
captured at click time). This processor normalizes them into the
RecordedAction schema and optionally queries ScreenPipe for OCR text.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def _query_screenpipe(timestamp: float) -> dict:
    """Query ScreenPipe API for OCR text near the given timestamp.
    Returns {"ocr_text": "..."} or empty dict.
    ScreenPipe runs on localhost:3030 and provides continuous OCR."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as client:
            from datetime import datetime, timezone
            ts = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
            resp = await client.get(
                "http://localhost:3030/search",
                params={"content_type": "ocr", "limit": 1, "start_time": ts}
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", [])
                if items:
                    ocr_text = items[0].get("content", {}).get("text", "")
                    return {"ocr_text": ocr_text}
    except Exception:
        pass
    return {}


_screenpipe_checked: bool = False
_screenpipe_available: bool = False

async def _check_screenpipe_available() -> bool:
    """Check if ScreenPipe is running on localhost:3030. Cached after first check."""
    global _screenpipe_checked, _screenpipe_available
    if _screenpipe_checked:
        return _screenpipe_available
    _screenpipe_checked = True
    try:
        import httpx
        async with httpx.AsyncClient(timeout=0.3) as client:
            resp = await client.get("http://localhost:3030/health")
            _screenpipe_available = resp.status_code == 200
    except Exception:
        _screenpipe_available = False
    return _screenpipe_available


async def process_recording(raw_events: List[dict],
                            capture_screenshots: bool = True,
                            use_screenpipe: bool = True) -> List[dict]:
    """Convert raw pynput events into RecordedAction-compatible dicts.

    Events from InputRecorder already contain:
    - window_title (captured at event time)
    - element_type, element_name, element_automation_id, element_parent_name,
      confidence (captured at click time via inline a11y)
    - screenshot_b64 (captured at click time)

    This processor normalizes the schema and optionally adds ScreenPipe OCR.

    Returns list of dicts matching RecordedAction schema fields.
    """
    actions: List[dict] = []

    # Check ScreenPipe availability once at start
    screenpipe_available = False
    if use_screenpipe:
        screenpipe_available = await _check_screenpipe_available()
        if screenpipe_available:
            logger.info("ScreenPipe detected — using for OCR enrichment")

    for event in raw_events:
        etype = event.get("type", "")
        window_title = event.get("window_title", "")

        action: dict = {
            "timestamp": event.get("timestamp", 0.0),
            "action_type": etype,
            "x": event.get("x", 0),
            "y": event.get("y", 0),
            "button": event.get("button", ""),
            "text": event.get("text", ""),
            "key": event.get("key", ""),
            "scroll_amount": event.get("scroll_dy", 0),
            # Pass through a11y data captured at click time
            "element_type": event.get("element_type", ""),
            "element_name": event.get("element_name", ""),
            "element_automation_id": event.get("element_automation_id", ""),
            "element_parent_name": event.get("element_parent_name", ""),
            "window_title": window_title,
            # Pass through screenshot captured at click time
            "screenshot_b64": event.get("screenshot_b64", ""),
            "ocr_text": "",
            "confidence": event.get("confidence", 0.0),
        }

        # Pass through window-relative coordinates (for moved-window replay)
        if "window_x" in event and "window_y" in event:
            action["window_x"] = event["window_x"]
            action["window_y"] = event["window_y"]

        # ScreenPipe OCR enrichment for clicks
        if etype == "click" and screenpipe_available:
            sp_data = await _query_screenpipe(event.get("timestamp", 0.0))
            if sp_data.get("ocr_text"):
                action["ocr_text"] = sp_data["ocr_text"][:500]  # Cap to prevent unbounded storage/injection

        actions.append(action)

    enriched_clicks = sum(1 for a in actions if a.get("confidence", 0) > 0)
    screenshot_count = sum(1 for a in actions if a.get("screenshot_b64"))
    logger.info("Processed %d raw events into %d actions (%d enriched clicks, %d screenshots)",
                len(raw_events), len(actions), enriched_clicks, screenshot_count)
    return actions
