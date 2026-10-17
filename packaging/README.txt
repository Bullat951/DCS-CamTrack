Head Tracker - webcam head tracking for DCS World (no TrackIR, no opentrack, no drivers)
=======================================================================================

WORK IN PROGRESS - this is not a final version; filters and defaults are still being developed.
Written with the help of Claude, an AI assistant by Anthropic.

What you need: Windows 10 / 11 (64-bit), a webcam, DCS World. Nothing to install.

1. Unzip this folder anywhere and double-click "Head Tracker.exe".
2. Setup tab: pick your camera and a mode (start with 1280x720 @ 60 fps; if the live
   "camera .. fps" under the preview is lower, take 30 fps). Pick your Saved Games\DCS folder
   and click "Install / update DCS hook" (DCS must be closed).
3. Keep opentrack / TrackIR software CLOSED when you start DCS.
4. In the cockpit: look straight ahead and press Centre. Tracking tab -> "Calibrate my face"
   once (20 s, turn slowly, include looking down) for the personal model (optional).
5. DCS output tab: bind "Pause = mouse look" and "Centre" to a key or HOTAS button that DCS
   itself does not use. Pause hands the view to DCS's own mouse look; press again to resume.
6. Response curves: per axis, drag the points (double-click adds, right-click deletes). Untick
   "Same curve both directions" to give looking down its own curve. "Import from opentrack"
   copies your opentrack curves.

Your settings live in %APPDATA%\HeadTracker (a new version in a new folder keeps them).
Problems: Setup tab -> tick "Write a debug log", restart Head Tracker, reproduce the problem, close it,
then "Open log folder" and send the newest debug-*.log. Crashes: %APPDATA%\HeadTracker\ui.log

To remove: delete this folder, %APPDATA%\HeadTracker and Saved Games\DCS\Scripts\Hooks\HeadTracker-hook.lua.
