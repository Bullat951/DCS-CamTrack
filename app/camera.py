"""BRIO capture on its own thread, with exposure / focus / white balance / gain locked.

Auto exposure and autofocus hunting are a main jitter source for webcam head tracking: the image
brightness and sharpness change under the landmark model every few frames. DirectShow is used
because it exposes those controls (MSMF often ignores them). Only the newest frame is kept, so a
slow model never builds a queue (= latency).
"""
from __future__ import annotations

import threading
import time

import cv2


class Camera:
    def __init__(self, index: int = 0, width: int = 1280, height: int = 720, fps: int = 60,
                 exposure: float = -7.0, gain: float = 0.0, focus: float = 0.0, wb: float = 4500.0,
                 lock: bool = True, name: str = ""):
        self.cfg = dict(index=index, width=width, height=height, fps=fps, exposure=exposure,
                        gain=gain, focus=focus, wb=wb, lock=lock, name=name)
        self.cap = None
        self._frame = None
        self._t = 0.0
        self._n = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.info = {}
        self.backend = ""
        self.attempts: list[str] = []      # what was tried at the last open (debug log / error message)

    def open(self) -> bool:
        c = self.cfg
        self.attempts = []
        if c["fps"] > 60:
            return self._open_msmf()
        if self._open_dshow():
            return True
        # DirectShow refused the device (some cameras / drivers): Media Foundation can still stream it,
        # only without the exposure / focus lock
        return self._open_msmf(controls=False)

    def _open_dshow(self) -> bool:
        c = self.cfg
        cap = cv2.VideoCapture(c["index"], cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.attempts.append("DirectShow index %d: not opened" % c["index"])
            cap.release()
            return False
        # order matters on DirectShow: size + fps first, THEN the format - the other way round the
        # BRIO falls back to uncompressed YUY2, which USB carries at only ~10 fps at 720p (measured)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        cap.set(cv2.CAP_PROP_FPS, c["fps"])
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap, self.backend = cap, "dshow"
        self.attempts.append("DirectShow index %d: opened" % c["index"])
        self.apply_controls()
        self.info = {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps_reported": cap.get(cv2.CAP_PROP_FPS),
            "format": int(cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace"),
        }
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="camera")
        self._thread.start()
        return True

    def _open_msmf(self, controls: bool = True) -> bool:
        """90 fps: only Media Foundation offers the BRIO's 1280x720 @ 90 mode (DirectShow stays at 60), but
        it ignores exposure settings - so they are set through WinRT first; the camera keeps them."""
        c = self.cfg
        res = None
        if controls:
            from wincontrols import apply_controls
            res = apply_controls(name_hint=c.get("name") or "", exposure=c["exposure"], focus=c["focus"], wb=c["wb"],
                                 auto=not c["lock"])
        cap = cv2.VideoCapture(c["index"], cv2.CAP_MSMF, [cv2.CAP_PROP_FRAME_WIDTH, c["width"],
                                                          cv2.CAP_PROP_FRAME_HEIGHT, c["height"],
                                                          cv2.CAP_PROP_FPS, c["fps"]])
        if not cap.isOpened():
            cap.release()
            self.attempts.append("Media Foundation index %d (%dx%d @ %d): not opened" % (
                c["index"], c["width"], c["height"], c["fps"]))
            return False
        self.cap, self.backend = cap, "msmf"
        self.attempts.append("Media Foundation index %d: opened" % c["index"])
        self.info = {"width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                     "fps_reported": cap.get(cv2.CAP_PROP_FPS), "format": "MSMF", "controls": res}
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="camera")
        self._thread.start()
        return True

    def apply_controls(self):
        c, cap = self.cfg, self.cap
        if cap is None:
            return
        if self.backend == "msmf":
            return   # MSMF ignores these (at 90 fps set() reopens the camera with them applied through WinRT)
        if c["lock"]:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)   # DirectShow: 0.25 = manual
            cap.set(cv2.CAP_PROP_EXPOSURE, c["exposure"])  # log2 seconds: -7 = 1/128 s (fits 60 fps)
            cap.set(cv2.CAP_PROP_GAIN, c["gain"])
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            cap.set(cv2.CAP_PROP_FOCUS, c["focus"])
            cap.set(cv2.CAP_PROP_AUTO_WB, 0)
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, c["wb"])
        else:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            cap.set(cv2.CAP_PROP_AUTO_WB, 1)

    def set(self, **kw):
        """Change settings; call on the MAIN thread - a camera open on a worker thread can hang
        (DirectShow / COM apartment). Mode changes (fps) and 90 fps controls reopen the camera."""
        mode_keys = ("index", "width", "height", "fps", "name")
        reopen = (any(k in kw and kw[k] != self.cfg.get(k) for k in mode_keys)
                  or (self.cfg["fps"] > 60 or kw.get("fps", 0) > 60) or self.cap is None)
        self.cfg.update(kw)
        if reopen:
            self.close()
            return self.open()
        self.apply_controls()
        return True

    def _run(self):
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            t = time.perf_counter()
            if not ok:
                time.sleep(0.005)
                continue
            with self._lock:
                self._frame, self._t, self._n = frame, t, self._n + 1

    def latest(self):
        """(frame, capture time, frame number) - the same frame twice means no new one yet."""
        with self._lock:
            return self._frame, self._t, self._n

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.backend = ""
        with self._lock:
            self._frame = None
