# Phase 4: UI Enhancements & Browser Integration

This phase focuses on improving the dashboard usability with collapsible sidebars and providing a live visual "Bridge" to the browser directly in the UI.

## Proposed Changes

### [Component] Browser Engine
#### [MODIFY] [browser_use_engine.py](file:///d:/AWorkSpace/clawbridge/clawbridge/engines/browser_use_engine.py)
- **Viewport Config**: Explicitly set the browser viewport and window size in `Agent` settings to ensure it doesn't default to something oversized.
- **Screenshot Hooks**: Add a hook to the `Agent` to broadcast the current screenshot via the `TaskManager` whenever a new step is executed.

### [Component] UI
#### [MODIFY] [clawbridge.py](file:///d:/AWorkSpace/clawbridge/clawbridge.py) (inside `_dashboard_html`)
- **Collapsible Rails**: Add CSS and JS to allow the left (Config) and right (Activity) columns to be toggled.
- **Live View Panel**: Implement a "Live View" panel in the center area that displays the latest screenshot received from the active engine.
- **Responsive Layout**: Adjust the layout to handle the dynamic width of the center column when sidebars are collapsed.

## Implementation Details

### Collapsible Logic
Using CSS classes `.collapsed` and small toggle buttons (arrows/icons) at the top of each sidebar.

### Browser Mirroring
The engine will send `{"type": "live_view", "payload": {"image": "base64..."}}` messages. The frontend will display this on a `<canvas>` or `<img>` element with `object-fit: contain`.

## Verification Plan

### Manual Verification
- Verify that sidebars collapse/expand smoothly.
- Run a task and verify that the "Live View" mirrors the browser's actions.
- Verify the browser window size is more reasonable and consistent.
