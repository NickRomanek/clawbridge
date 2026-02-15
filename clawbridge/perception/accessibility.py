"""Enhanced UIA accessibility wrapper for ClawBridge perception layer.

Built on the same pywinauto UIA pattern as ComputerUseEngine._get_ui_elements(),
but enriched with automation_id, parent tracking, and element matching for replay.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import List, Tuple

logger = logging.getLogger(__name__)

CLICKABLE_TYPES = frozenset({
    "Button", "Edit", "MenuItem", "ListItem", "TabItem",
    "ComboBox", "CheckBox", "RadioButton", "Hyperlink",
    "TreeItem", "DataItem", "Text", "Image",
})


@dataclass
class ElementSnapshot:
    """Snapshot of a single UI element from the accessibility tree."""
    control_type: str = ""
    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    bounding_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    center_x: int = 0
    center_y: int = 0
    is_password: bool = False
    parent_name: str = ""

    def to_dict(self) -> dict:
        return {
            "control_type": self.control_type,
            "name": self.name,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "bounding_rect": list(self.bounding_rect),
            "center_x": self.center_x,
            "center_y": self.center_y,
            "is_password": self.is_password,
            "parent_name": self.parent_name,
        }


async def get_accessibility_tree(max_depth: int = 8, max_elements: int = 60) -> List[ElementSnapshot]:
    """Enumerate interactive UI elements from the foreground window.

    Enhanced version of ComputerUseEngine._get_ui_elements() with:
    - automation_id tracking
    - parent_name tracking
    - class_name tracking
    - password field detection
    """
    loop = asyncio.get_running_loop()

    def _enumerate() -> List[ElementSnapshot]:
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

            # Find matching pywinauto window
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

            elements: List[ElementSnapshot] = []
            for c in target_win.descendants(depth=max_depth):
                try:
                    ct = c.element_info.control_type
                    if ct not in CLICKABLE_TYPES:
                        continue
                    r = c.rectangle()
                    if r.width() < 10 or r.height() < 10:
                        continue
                    name = (c.window_text() or "").strip()[:80]
                    if not name and ct not in ("Edit", "Image"):
                        continue

                    cx = (r.left + r.right) // 2
                    cy = (r.top + r.bottom) // 2
                    if cx <= 0 or cy <= 0:
                        continue

                    # Get automation_id and class_name
                    auto_id = ""
                    cls_name = ""
                    try:
                        auto_id = c.element_info.automation_id or ""
                    except Exception:
                        pass
                    try:
                        cls_name = c.element_info.class_name or ""
                    except Exception:
                        pass

                    # Get parent name
                    parent_name = ""
                    try:
                        p = c.parent()
                        if p:
                            parent_name = (p.window_text() or "").strip()[:60]
                    except Exception:
                        pass

                    # Detect password fields
                    is_pwd = False
                    if ct == "Edit":
                        try:
                            is_pwd = "password" in (auto_id + cls_name + name).lower()
                        except Exception:
                            pass

                    elements.append(ElementSnapshot(
                        control_type=ct,
                        name=name,
                        automation_id=auto_id,
                        class_name=cls_name,
                        bounding_rect=(r.left, r.top, r.right, r.bottom),
                        center_x=cx,
                        center_y=cy,
                        is_password=is_pwd,
                        parent_name=parent_name,
                    ))

                    if len(elements) >= max_elements:
                        break
                except Exception:
                    pass
            return elements
        except Exception as exc:
            logger.debug("Accessibility tree enumeration failed: %s", exc)
            return []

    try:
        return await loop.run_in_executor(None, _enumerate)
    except Exception:
        return []


def get_element_at_point(x: int, y: int, tree: List[ElementSnapshot]) -> ElementSnapshot | None:
    """Find the element whose bounding rect contains (x, y). Returns nearest if multiple."""
    candidates = []
    for el in tree:
        left, top, right, bottom = el.bounding_rect
        if left <= x <= right and top <= y <= bottom:
            # Prefer smaller elements (more specific)
            area = (right - left) * (bottom - top)
            candidates.append((area, el))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])  # smallest area first
    return candidates[0][1]


def find_matching_element(
    target: ElementSnapshot,
    candidates: List[ElementSnapshot],
    threshold: float = 0.7,
) -> Tuple[ElementSnapshot | None, float]:
    """Multi-strategy element matcher for replay.

    Matching strategies (in priority order):
    1. automation_id exact match → confidence 1.0
    2. name + control_type + parent_name → 0.95
    3. name + control_type → 0.85
    4. control_type + bounding_rect proximity → 0.6

    Returns (matched_element, confidence) or (None, 0.0) if below threshold.
    """
    best_match: ElementSnapshot | None = None
    best_confidence = 0.0

    for el in candidates:
        conf = 0.0

        # Strategy 1: automation_id exact match
        if target.automation_id and el.automation_id and target.automation_id == el.automation_id:
            conf = 1.0

        # Strategy 2: name + control_type + parent_name
        elif (target.name and el.name and target.name == el.name
              and target.control_type == el.control_type
              and target.parent_name and el.parent_name
              and target.parent_name == el.parent_name):
            conf = 0.95

        # Strategy 3: name + control_type
        elif (target.name and el.name and target.name == el.name
              and target.control_type == el.control_type):
            conf = 0.85

        # Strategy 4: control_type + bounding_rect proximity
        elif target.control_type == el.control_type:
            dist = math.sqrt(
                (target.center_x - el.center_x) ** 2
                + (target.center_y - el.center_y) ** 2
            )
            if dist < 100:
                conf = max(0.6, 0.8 - dist / 500.0)

        if conf > best_confidence:
            best_confidence = conf
            best_match = el

    if best_confidence >= threshold:
        return best_match, best_confidence
    return None, 0.0
