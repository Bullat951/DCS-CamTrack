"""Set the BRIO's exposure / focus / white balance through WinRT's VideoDeviceController.

Media Foundation (the only Windows path that gives the BRIO's 1280x720 @ 90 fps mode to OpenCV) ignores
OpenCV's exposure setting, but the camera KEEPS its controls after a program closes. So: open the device
exclusively here, set the controls, close - then stream through Media Foundation. Runs on its own thread
(a WinRT call on the main thread first breaks a later DirectShow / MF open there - COM apartment).
"""
from __future__ import annotations

import asyncio
import threading


async def _apply(name_hint: str, exposure: float | None, focus: float | None, wb: float | None, auto: bool) -> dict:
    from winrt.windows.media.capture import (MediaCapture, MediaCaptureInitializationSettings,
                                             MediaCaptureMemoryPreference, MediaCaptureSharingMode,
                                             StreamingCaptureMode)
    from winrt.windows.media.capture.frames import MediaFrameSourceGroup
    group = next((g for g in await MediaFrameSourceGroup.find_all_async() if name_hint.lower() in g.display_name.lower()), None)
    if group is None:
        return {"error": f"no camera named like '{name_hint}'"}
    cap = MediaCapture()
    st = MediaCaptureInitializationSettings()
    st.source_group = group
    st.sharing_mode = MediaCaptureSharingMode.EXCLUSIVE_CONTROL
    st.memory_preference = MediaCaptureMemoryPreference.CPU
    st.streaming_capture_mode = StreamingCaptureMode.VIDEO
    await cap.initialize_with_settings_async(st)
    v = cap.video_device_controller
    out = {}
    try:
        if auto:
            out["exposure"] = v.exposure.try_set_auto(True)
            out["focus"] = v.focus.try_set_auto(True)
            out["wb"] = v.white_balance.try_set_auto(True)
        else:
            if exposure is not None:
                out["exposure"] = v.exposure.try_set_auto(False) and v.exposure.try_set_value(float(exposure))
            if focus is not None:
                out["focus"] = v.focus.try_set_auto(False) and v.focus.try_set_value(float(focus))
            if wb is not None:
                out["wb"] = v.white_balance.try_set_auto(False) and v.white_balance.try_set_value(float(wb))
        out["exposure_now"] = v.exposure.try_get_value()[1]
    finally:
        cap.close()
    return out


def apply_controls(name_hint: str = "BRIO", exposure: float | None = -8.0, focus: float | None = 0.0,
                   wb: float | None = 4500.0, auto: bool = False, timeout: float = 10.0) -> dict:
    res: dict = {}

    def run():
        try:
            res.update(asyncio.run(_apply(name_hint, exposure, focus, wb, auto)))
        except Exception as e:  # camera busy (another app streaming) etc.
            res["error"] = str(e)
    t = threading.Thread(target=run, daemon=True, name="wincontrols")
    t.start()
    t.join(timeout)
    if t.is_alive():
        res["error"] = "timeout"
    return res
