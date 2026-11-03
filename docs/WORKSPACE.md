# Workspace and robot inspection

Field and Dashboard keep the robot list, central field and selected-robot inspector in separate panes. On desktop, drag the inner edge of either side pane to change its width. Drag the bottom edge of an inspector panel to change its height. Separators also accept arrow keys (Shift for larger steps); Home or a double-click restores the default size. Sizes are saved in this browser for each page. Narrow layouts retain the existing stacked Field layout or Dashboard drawers.

Diagnostics panels can be folded using the button in their heading. Drawings and network budget start folded. The selected robot's STOP and Resume remain visible; posture/recovery and Go to are under labeled disclosures. The joystick, speed scales and turn controls appear while Manual is on. Speed scales run from 0.1 to 1.0 of the robot's configured manual limits; the robot clamps normalized sticks to this range. Local ghosts show their preview controls without robot posture/navigation commands. Telemetry-only and read-only robots have no command controls; the gateway also rejects joystick requests to telemetry-only targets. Real Manual is cancelled when its telemetry becomes stale.

Select a robot and click its miniature to open the enlarged inspection view. Drag to orbit, use the wheel or pinch to zoom, and right-drag or use two fingers to pan. Double-click a robot part to set an orbit/zoom pivot on its surface, or choose **Pick pivot** and tap a point. An empty-space selection uses the plane through the current pivot. A cyan marker shows the pivot. **Reset view** frames the whole robot again. Close or Escape returns focus to the miniature and restores its whole-robot framing.

The miniature and expanded view share one canvas and renderer; telemetry continues posing the selected model. On WebGL/model-load failure the viewer shows a 2D preview and explains that 3D inspection is unavailable. Inspection and layout changes do not issue robot commands.

Offline regression:

```bash
python3 tools/test_workspace_browser.py /tmp/oraculum-workspace-check
python3 tools/test_manual_browser.py /tmp/oraculum-workspace-check
node tools/check_simulation.mjs
```

The browser checks serve static files on a temporary loopback port, supplies fixture telemetry, and intercepts API calls. They start no robot gateway, UDP sender or SSH connection. Screenshots and results go in the supplied directory. Physical control/camera acceptance is a separate hardware task.
