"""Perception modules for ClawBridge — screenshot and accessibility utilities."""

from clawbridge.perception.screenshot import (
    take_screenshot,
    take_window_crop,
    get_foreground_window_rect,
    screenshots_similar,
)
from clawbridge.perception.accessibility import (
    ElementSnapshot,
    get_accessibility_tree,
    get_element_at_point,
    find_matching_element,
)

__all__ = [
    "take_screenshot",
    "take_window_crop",
    "get_foreground_window_rect",
    "screenshots_similar",
    "ElementSnapshot",
    "get_accessibility_tree",
    "get_element_at_point",
    "find_matching_element",
]
