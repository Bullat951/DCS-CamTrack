# DCS-CamTrack

> **Work in progress - this is not a final version.** It works well on the author's PC, but filters,
> defaults and setup are still being developed and may change. Feedback and test reports are welcome.

Webcam head tracking for **DCS World** - no TrackIR, no opentrack, no vJoy, no drivers.

A normal webcam, Google's MediaPipe face tracking at 60 fps, smart filtering, per-axis response
curves, and a tiny DCS hook that drives the cockpit view directly. Press one button and DCS's own
**mouse look** takes over; press it again and your head has the view back.

## Why this exists

With TrackIR-style head tracking (TrackIR, opentrack, ...) DCS switches into "TrackIR mode" for the
whole session, and **its mouse look stops working in the cockpit**. Pausing the tracker only freezes
the view - you still cannot use the mouse to look at the awkward places: low behind the seat, a panel
down by your knee, a switch behind your shoulder - spots your neck can't comfortably reach.

DCS-CamTrack was created to fix exactly that. It does not use the TrackIR interface at all, so DCS
never enters TrackIR mode: press **Pause** and DCS's own mouse look is back instantly, look wherever
you need, press Pause again and your head drives the view again.

## How it fits together

```
webcam ──60 fps──▶ MediaPipe face landmarks ──▶ head pose ──▶ filter + prediction ──▶ curves
                                                                                        │
DCS cockpit view ◀── Export.LoSetCommand(Absolute Camera axes) ◀── HeadTracker-hook.lua ◀┘  (UDP, 240 Hz)
```

## Features

- **Accurate and steady**: MediaPipe Face Landmarker (478 points) instead of a single-image
  regressor; One-Euro filter (calm when still, fast when moving), latency prediction, a still-gate
  against amplified tremble, and a 240 Hz output stage so DCS gets a smooth value every frame.
- **Straight into DCS**: the six *Absolute Camera* view axes are driven from a Lua GUI hook in your
  Saved Games - nothing in the DCS install is touched, so the integrity check stays happy.
- **Pause = mouse look**: while paused nothing is sent, and DCS's native mouse look works.
- **Response curves per axis**: drag points, separate curve for each direction (e.g. looking down),
  soft dead zone, live dot showing your head; **import your opentrack curves**.
- **Global buttons**: Pause and Centre on any keyboard key or HOTAS / joystick button, working while
  DCS has focus.
- **Personal face model** (optional): a 20 s calibration learns your face shape; pose from rigid
  landmarks only (no mouth / jaw - steadier while talking on SRS), solved in true perspective.
- **Portable**: unzip and run. Settings per user in `%APPDATA%\HeadTracker`.
- Optional output to **opentrack** (UDP 4242) if you prefer its pipeline.

## Requirements

Windows 10 / 11 (64-bit), a webcam (720p @ 60 fps recommended), DCS World. Nothing to install.

## Quick start

1. Download `HeadTracker-portable-<version>.zip` from **Releases**, unzip anywhere,
   double-click **`Head Tracker.exe`**.
2. **Setup** tab: pick your camera and mode (start with 1280x720 @ 60 fps - the real rate shows under
   the preview). Pick your `Saved Games\DCS` folder and click **Install / update DCS hook**
   (with DCS closed).
3. **Close opentrack / TrackIR software** before starting DCS (if DCS finds a TrackIR client at start
   it stays in TrackIR mode for the whole session).
4. Start DCS, get into a cockpit, look straight ahead and press **Centre**.
5. **DCS output** tab: bind **Pause = mouse look** and **Centre** to a key or HOTAS button DCS itself
   does not use. Shape the response with the curves; untick *Same curve both directions* for an axis
   that needs a different curve one way (looking down usually needs more).

If an axis moves the wrong way, tick **Invert in DCS** for it. *Full scale* is how many view degrees
(cm for x / y / z) equal the end of DCS's axis.

## Tips

- **Lighting**: a lit face, no strong light behind you. Lock exposure in the Tracking tab (default on)
  - automatic exposure / focus hunting is a big jitter source.
- **Camera position**: at or a little below eye level tracks looking down best.
- **Still test** (Tracking tab) measures jitter in your head pose and in the DCS view.
- **Problems**: turn on the **debug log** (Setup tab -> *Write a debug log*), restart Head Tracker,
  reproduce the problem, close Head Tracker and send the newest file from **Open log folder**
  (`%APPDATA%\HeadTracker\debug\debug-<date>-<time>.log`, the last 5 are kept). It has the PC, cameras,
  DCS folder / hook state and settings at start, every action (centre, pause, hotkeys, settings changes),
  tracking / DCS-link changes, errors, a health line every 5 s (fps, face found, timings, head and view
  values, packets to DCS) and the hook's lines from `dcs.log`. Crashes of the packaged exe also go to
  `%APPDATA%\HeadTracker\ui.log`.

## How it works (for the curious)

DCS has axis commands *Absolute Camera Horizontal / Vertical View, Roll Shift, Horizontal / Vertical /
Longitude Shift* (command ids 2010, 2011, 2047, 2049, 2051, 2053 - the same in every aircraft). The hook
receives `HTK1 <seq> <active> <6 values>` over UDP 127.0.0.1:4245 and applies the newest packet every
frame with `Export.LoSetCommand`; when nothing fresh arrives it sends nothing, which leaves the view to
DCS's mouse look. A 1 Hz status goes back on UDP 4246 for the app.

## Build from source

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-build.txt
.venv\Scripts\python -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Python 3.14. Run from source with `.venv\Scripts\python app\ui.py`. The hook test runs with DCS's own
Lua: `"<DCS>\bin\luae.exe" tests\dcs_hook_test.lua dcs\HeadTracker-hook.lua`. `tools\` has camera probes
(frame rate per backend / format).

## Status

Tested on one PC (Logitech BRIO, DCS 2.9.30, CH-47F / JF-17 / F/A-18C). Multiplayer, other cameras and
other PCs: reports welcome. 90 fps capture is experimental.

## Acknowledgements

This project was written with the help of **Claude**, an AI assistant by Anthropic - code, tests and
documentation were developed together with it, and tested by the author in DCS.

## License

MIT - see `LICENSE`. Third-party components and their licenses: `THIRD_PARTY_NOTICES.md`.
Not affiliated with Eagle Dynamics.
