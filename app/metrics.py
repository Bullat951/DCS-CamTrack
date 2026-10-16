"""Measurements: frame rate, pipeline latency, and a 'hold still' jitter test (RMS per axis)."""
from __future__ import annotations

import math
import time
from collections import deque


class Rate:
    """Events per second over the last `window` seconds; tick(t, count) for several at once."""

    def __init__(self, window: float = 2.0):
        self.ts = deque()     # (time, count)
        self.window = window

    def tick(self, t: float | None = None, count: int = 1) -> None:
        t = time.perf_counter() if t is None else t
        self.ts.append((t, count))
        while self.ts and t - self.ts[0][0] > self.window:
            self.ts.popleft()

    @property
    def hz(self) -> float:
        if len(self.ts) < 2:
            return 0.0
        span = self.ts[-1][0] - self.ts[0][0]
        if span <= 0:
            return 0.0
        return sum(c for _, c in list(self.ts)[1:]) / span


class Mean:
    def __init__(self, n: int = 120):
        self.v = deque(maxlen=n)

    def add(self, x: float) -> None:
        self.v.append(x)

    @property
    def value(self) -> float:
        return sum(self.v) / len(self.v) if self.v else 0.0


def rms_about_mean(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


class StillTest:
    """Collect poses for `seconds`; report RMS (raw and filtered) per axis."""

    def __init__(self, seconds: float = 10.0):
        self.seconds = seconds
        self.start = None
        self.raw: list[dict] = []
        self.flt: list[dict] = []
        self.result: dict | None = None

    def begin(self, t: float):
        self.start, self.raw, self.flt, self.result = t, [], [], None

    @property
    def running(self) -> bool:
        return self.start is not None

    def add(self, t: float, raw: dict, flt: dict):
        if self.start is None:
            return
        self.raw.append(raw)
        self.flt.append(flt)
        if t - self.start >= self.seconds:
            axes = ("yaw", "pitch", "roll", "x", "y", "z")
            self.result = {
                "samples": len(self.raw),
                "raw": {a: rms_about_mean([p[a] for p in self.raw]) for a in axes},
                "filtered": {a: rms_about_mean([p[a] for p in self.flt]) for a in axes},
            }
            self.start = None
