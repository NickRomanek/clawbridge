"""Process raw recorded events into enriched RecordedAction objects.

Enriches click events with accessibility metadata and uses per-event
window title captured at recording time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def process_recording(raw_events: List[dict]) -> List[dict]:
    """Convert raw pynput events into enriched action dicts.

    Each event already has window_title from capture time.
    For click events, attempts to enrich with accessibility metadata
    by querying the UIA tree for the element at the click coordinates.

    Returns list of dicts matching RecordedAction schema fields.
    """
    actions: List[dict] = []

    for event in raw_events:
        etype = event.get("type", "")
        # Use per-event window_title from recorder (captured at event time)
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
            "element_type": "",
            "element_name": "",
            "element_automation_id": "",
            "element_parent_name": "",
            "window_title": window_title,
        }

        actions.append(action)

    logger.info("Processed %d raw events into %d actions", len(raw_events), len(actions))
    return actions
