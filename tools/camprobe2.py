"""Second probe: property order on DirectShow, and MSMF with manual exposure."""
from __future__ import annotations

import time

import cv2

F = lambda c: cv2.VideoWriter_fourcc(*c)


def run(cap, label, secs=3.0):
    for _ in range(10):
        cap.read()
    n, t0, worst, prev = 0, time.perf_counter(), 0.0, None
    while time.perf_counter() - t0 < secs:
        ok, _ = cap.read()
        if ok:
            t = time.perf_counter()
            n += 1
            if prev:
                worst = max(worst, t - prev)
            prev = t
    got = int(cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace")
    print(f"{label:52} {n / (time.perf_counter() - t0):5.1f} fps  got '{got}' "
          f"{int(cap.get(3))}x{int(cap.get(4))} exp {cap.get(cv2.CAP_PROP_EXPOSURE)} worst {worst * 1000:.0f} ms", flush=True)
    cap.release()


# DirectShow, format via the open() params (applied before the graph is built)
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW, [cv2.CAP_PROP_FOURCC, F("MJPG"), cv2.CAP_PROP_FRAME_WIDTH, 1280,
                                          cv2.CAP_PROP_FRAME_HEIGHT, 720, cv2.CAP_PROP_FPS, 60])
run(cap, "DSHOW open-params MJPG 1280x720@60")

# DirectShow, size first then fourcc
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 60); cap.set(cv2.CAP_PROP_FOURCC, F("MJPG"))
run(cap, "DSHOW size->fps->fourcc")

# DirectShow, fourcc + size + manual short exposure
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW, [cv2.CAP_PROP_FOURCC, F("MJPG"), cv2.CAP_PROP_FRAME_WIDTH, 1280,
                                          cv2.CAP_PROP_FRAME_HEIGHT, 720, cv2.CAP_PROP_FPS, 60])
cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25); cap.set(cv2.CAP_PROP_EXPOSURE, -7)
run(cap, "DSHOW open-params + exposure -7")

for exp in (-6, -7):
    cap = cv2.VideoCapture(0, cv2.CAP_MSMF, [cv2.CAP_PROP_FRAME_WIDTH, 1280, cv2.CAP_PROP_FRAME_HEIGHT, 720,
                                             cv2.CAP_PROP_FPS, 60])
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25); cap.set(cv2.CAP_PROP_EXPOSURE, exp)
    run(cap, f"MSMF open-params + exposure {exp}")
