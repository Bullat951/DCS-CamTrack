"""One-Euro filter (Casiez et al. 2012): heavy smoothing while still, little lag while moving.

The cutoff rises with the signal's speed: cutoff = min_cutoff + beta * |speed|.
Small min_cutoff -> calmer when still; larger beta -> less lag when turning.
"""
from __future__ import annotations

import math
import threading


def _alpha(cutoff_hz: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.05, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = None
        self.dx = 0.0
        self.t = None

    def reset(self):
        self.x, self.dx, self.t = None, 0.0, None

    def __call__(self, value: float, t: float) -> float:
        if self.x is None or self.t is None or t <= self.t:
            self.x, self.t, self.dx = value, t, 0.0
            return value
        dt = t - self.t
        self.t = t
        dx = (value - self.x) / dt
        a_d = _alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        a = _alpha(cutoff, dt)
        self.x = a * value + (1 - a) * self.x
        return self.x


class PoseFilter:
    """Six One-Euro filters: rotation (deg) and translation (cm) tuned separately.
    Also keeps the velocity of the filtered pose (for prediction), low-passed at `vel_hz`."""

    AXES = ("x", "y", "z", "yaw", "pitch", "roll")

    def __init__(self, rot=(0.6, 0.03), pos=(0.8, 0.05), vel_hz: float = 6.0):
        self.f = {a: OneEuro(*(pos if a in ("x", "y", "z") else rot)) for a in self.AXES}
        self.vel_hz = vel_hz
        self.vel = {a: 0.0 for a in self.AXES}
        self._prev: dict | None = None
        self._t = None

    def _track_velocity(self, out: dict, t: float) -> None:
        if self._prev is not None and self._t is not None and t > self._t:
            dt = t - self._t
            a = _alpha(self.vel_hz, dt)
            for k in self.AXES:
                self.vel[k] = a * (out[k] - self._prev[k]) / dt + (1 - a) * self.vel[k]
        self._prev, self._t = dict(out), t

    def set(self, rot=None, pos=None):
        for a, flt in self.f.items():
            mc, b = (pos if a in ("x", "y", "z") else rot) or (flt.min_cutoff, flt.beta)
            flt.min_cutoff, flt.beta = mc, b

    def reset(self):
        for flt in self.f.values():
            flt.reset()
        self.vel = {a: 0.0 for a in self.AXES}
        self._prev = self._t = None

    def __call__(self, pose: dict, t: float, enabled: bool = True) -> dict:
        out = {a: self.f[a](pose[a], t) for a in self.AXES} if enabled else dict(pose)
        self._track_velocity(out, t)
        return out


class StillGate:
    """Hysteresis per axis on the VIEW (after the curves' gain): the output only moves when the input is
    more than `thr` away, and then only by the excess - so a still head's amplified micro-tremble never
    reaches DCS, while real movement passes with no delay (at most `thr` behind, never lagging in time)."""

    def __init__(self, thr_deg: float = 0.2, thr_cm: float = 0.1):
        self.thr_deg, self.thr_cm = thr_deg, thr_cm
        self.y: dict | None = None

    def reset(self):
        self.y = None

    def __call__(self, view: dict) -> dict:
        if self.y is None:
            self.y = dict(view)
            return dict(view)
        for a, v in view.items():
            thr = self.thr_cm if a in ("x", "y", "z") else self.thr_deg
            d = v - self.y[a]
            if d > thr:
                self.y[a] = v - thr
            elif d < -thr:
                self.y[a] = v + thr
        return dict(self.y)


class OutputPump(threading.Thread):
    """Sends the view at `hz` (240) instead of the camera's 60: between camera frames it continues along
    the view's own velocity (at most 1.5 frames ahead - no waiting, so no added delay) and a very short
    smoothing (tau_ms) removes the kinks where a new frame arrives. DCS then gets a fresh, smooth value
    every one of its frames instead of a 60 Hz staircase (the remaining 'choppy')."""

    def __init__(self, send, hz: float = 240.0, tau_ms: float = 6.0):
        super().__init__(daemon=True, name="output-pump")
        self.send, self.dt, self.tau = send, 1.0 / hz, tau_ms / 1000.0
        self._lock = threading.Lock()
        self._sample = None          # (view dict, time, velocity dict, frame interval)
        self._active = False
        self._stop = threading.Event()
        self._y: dict | None = None

    def set(self, view: dict, t: float, active: bool):
        with self._lock:
            prev = self._sample
            vel, interval = {a: 0.0 for a in view}, 1 / 60
            if prev is not None and t > prev[1]:
                interval = min(max(t - prev[1], 1 / 240), 0.1)
                for a, v in view.items():
                    raw = (v - prev[0][a]) / interval
                    vel[a] = 0.5 * raw + 0.5 * prev[2][a]
            self._sample, self._active = (dict(view), t, vel, interval), active

    def run(self):
        import time as _t
        nxt = _t.perf_counter()
        while not self._stop.is_set():
            nxt += self.dt
            with self._lock:
                smp, active = self._sample, self._active
            if smp is not None:
                view, t, vel, interval = smp
                ahead = min(max(_t.perf_counter() - t, 0.0), 1.5 * interval)
                target = {a: view[a] + vel[a] * ahead for a in view}
                if self._y is None or not active:
                    self._y = target
                else:
                    k = 1.0 - math.exp(-self.dt / self.tau) if self.tau > 0 else 1.0
                    self._y = {a: self._y[a] + k * (target[a] - self._y[a]) for a in target}
                try:
                    self.send(dict(self._y), active)
                except Exception:
                    pass
            delay = nxt - _t.perf_counter()
            if delay > 0:
                _t.sleep(delay)
            else:
                nxt = _t.perf_counter()

    def stop(self):
        self._stop.set()


class Predictor:
    """Projects the pose ahead by `lead_ms` along its velocity, to cancel the pipeline's delay.

    Only while really moving: below `thr` (deg/s, cm/s) nothing is added, between thr and 2*thr it
    ramps in - so a still head (velocity = noise) never gets extra jitter. The lead is clamped."""

    def __init__(self, lead_ms: float = 25.0, thr_deg: float = 8.0, thr_cm: float = 4.0,
                 max_deg: float = 6.0, max_cm: float = 2.0):
        self.lead_ms, self.thr_deg, self.thr_cm, self.max_deg, self.max_cm = lead_ms, thr_deg, thr_cm, max_deg, max_cm

    def __call__(self, pose: dict, vel: dict) -> dict:
        if self.lead_ms <= 0:
            return pose
        out = dict(pose)
        lead = self.lead_ms / 1000.0
        for a in PoseFilter.AXES:
            lin = a in ("x", "y", "z")
            thr, cap = (self.thr_cm, self.max_cm) if lin else (self.thr_deg, self.max_deg)
            v = vel.get(a, 0.0)
            ramp = min(1.0, max(0.0, (abs(v) - thr) / thr))
            out[a] = pose[a] + max(-cap, min(cap, v * lead * ramp))
        return out
