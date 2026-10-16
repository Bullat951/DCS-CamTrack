"""Measure what the camera really delivers per backend / format / exposure (no model, no window)."""
from __future__ import annotations

import sys
import time

import cv2

FOURCC = lambda c: cv2.VideoWriter_fourcc(*c)


def probe(backend, name, fourcc, w, h, fps, exposure=None, secs=3.0, index=0):
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        return f"{name:5} {fourcc} {w}x{h}@{fps} exp={exposure}: cannot open"
    cap.set(cv2.CAP_PROP_FOURCC, FOURCC(fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps)
    if exposure is not None:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
    for _ in range(10):
        cap.read()
    n, t0, dts, prev = 0, time.perf_counter(), [], None
    while time.perf_counter() - t0 < secs:
        ok, f = cap.read()
        if ok:
            n += 1
            t = time.perf_counter()
            if prev:
                dts.append(t - prev)
            prev = t
    el = time.perf_counter() - t0
    got = int(cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace")
    gw, gh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    exp_now = cap.get(cv2.CAP_PROP_EXPOSURE)
    cap.release()
    worst = max(dts) * 1000 if dts else 0
    return (f"{name:5} ask {fourcc} {w}x{h}@{fps} exp={exposure}: {n / el:5.1f} fps  "
            f"(got {got} {gw}x{gh}, exposure now {exp_now}, worst gap {worst:.0f} ms)")


if __name__ == "__main__":
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    for args in [
        (cv2.CAP_DSHOW, "DSHOW", "MJPG", 1280, 720, 60, None),
        (cv2.CAP_DSHOW, "DSHOW", "MJPG", 1280, 720, 60, -7),
        (cv2.CAP_DSHOW, "DSHOW", "MJPG", 1280, 720, 60, -8),
        (cv2.CAP_DSHOW, "DSHOW", "YUY2", 1280, 720, 60, None),
        (cv2.CAP_MSMF, "MSMF", "MJPG", 1280, 720, 60, None),
        (cv2.CAP_DSHOW, "DSHOW", "MJPG", 640, 480, 60, None),
    ]:
        print(probe(*args, index=idx), flush=True)
