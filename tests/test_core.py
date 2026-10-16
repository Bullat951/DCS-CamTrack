"""Core tests (no camera): filter, pose math, UDP packet, still test. Run: .venv\\Scripts\\python -m unittest discover -s tests"""
from __future__ import annotations

import math
import random
import struct
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from filters import OneEuro, PoseFilter  # noqa: E402
from metrics import StillTest, rms_about_mean  # noqa: E402
from output import pack  # noqa: E402
from posemath import euler_yxz, relative_pose, rot_yxz  # noqa: E402


def m4(yaw=0.0, pitch=0.0, roll=0.0, t=(0.0, 0.0, -50.0)):
    m = np.eye(4)
    m[:3, :3] = rot_yxz(yaw, pitch, roll)
    m[:3, 3] = t
    return m


class PoseMathTest(unittest.TestCase):
    def test_euler_round_trip(self):
        for yaw, pitch, roll in [(0, 0, 0), (30, 10, -5), (-80, -25, 15), (120, 40, 30), (-150, -60, -20)]:
            got = euler_yxz(rot_yxz(yaw, pitch, roll))
            for a, b in zip(got, (yaw, pitch, roll)):
                self.assertAlmostEqual(a, b, places=6)

    def test_relative_to_centre(self):
        centre = m4(yaw=10, pitch=-5, t=(1, 2, -50))
        head = np.eye(4)
        head[:3, :3] = centre[:3, :3] @ rot_yxz(25, 8, -3)
        head[:3, 3] = (3, 1, -45)
        p = relative_pose(head, centre)
        self.assertAlmostEqual(p["yaw"], 25, places=6)
        self.assertAlmostEqual(p["pitch"], 8, places=6)
        self.assertAlmostEqual(p["roll"], -3, places=6)
        self.assertAlmostEqual(p["x"], 2)
        self.assertAlmostEqual(p["z"], 5)

    def test_sign_inversion(self):
        p = relative_pose(m4(yaw=20), m4(), {"x": 1, "y": 1, "z": 1, "yaw": -1, "pitch": 1, "roll": 1})
        self.assertAlmostEqual(p["yaw"], -20, places=6)

    def test_noisy_matrix_is_orthonormalized(self):
        m = m4(yaw=15)
        m[:3, :3] *= 1.02   # scale noise as in a fitted transform
        self.assertAlmostEqual(relative_pose(m, m4())["yaw"], 15, places=4)


class FilterTest(unittest.TestCase):
    def test_reduces_jitter_when_still(self):
        random.seed(1)
        f = OneEuro(0.6, 0.03)
        raw, out = [], []
        for i in range(600):                     # 10 s at 60 fps, 0.3 deg noise
            v = random.gauss(0, 0.3)
            raw.append(v)
            out.append(f(v, i / 60))
        self.assertLess(rms_about_mean(out[60:]), 0.3 * rms_about_mean(raw[60:]))

    def test_follows_a_fast_turn(self):
        f = OneEuro(0.6, 0.03)
        t, out = 0.0, 0.0
        for i in range(120):                     # 90 deg/s turn for 1 s
            t = i / 60
            out = f(90 * t, t)
        self.assertGreater(out, 0.9 * 90 * t)    # little lag at speed

    def test_pose_filter_axes(self):
        pf = PoseFilter()
        p = pf({a: 1.0 for a in PoseFilter.AXES}, 0.0)
        self.assertEqual(set(p), set(PoseFilter.AXES))


class PredictorTest(unittest.TestCase):
    def run_pf(self, signal, lead_ms):
        from filters import Predictor
        pf, pr = PoseFilter(), Predictor(lead_ms=lead_ms)
        outs = []
        for i, v in enumerate(signal):
            t = i / 60
            o = pf({a: (v if a == "yaw" else 0.0) for a in PoseFilter.AXES}, t)
            outs.append(pr(o, pf.vel)["yaw"])
        return outs

    def test_still_head_gets_no_extra_jitter(self):
        random.seed(2)
        noise = [random.gauss(0, 0.3) for _ in range(600)]
        a, b = self.run_pf(noise, 0), self.run_pf(noise, 30)
        self.assertLessEqual(rms_about_mean(b[60:]), rms_about_mean(a[60:]) * 1.05)

    def test_turn_has_less_lag(self):
        turn = [min(60.0, 120.0 * i / 60) for i in range(90)]      # 120 deg/s for 0.5 s
        without, with_ = self.run_pf(turn, 0), self.run_pf(turn, 30)
        i = 25                                                      # mid-turn
        self.assertLess(abs(turn[i] - with_[i]), abs(turn[i] - without[i]))
        self.assertLess(max(with_), 60.0 + 6.0 + 1e-9)            # overshoot bounded by the cap


class StillGateTest(unittest.TestCase):
    def test_tremble_below_threshold_is_removed(self):
        from filters import StillGate
        random.seed(5)
        g = StillGate(0.2, 0.1)
        outs = [g({"yaw": random.uniform(-0.18, 0.18), "x": 0.0})["yaw"] for _ in range(600)]
        self.assertLess(max(outs) - min(outs), 0.2)          # amplified tremble gone (was +-0.18)
        self.assertLess(rms_about_mean(outs[60:]), 0.02)

    def test_real_movement_passes_without_time_lag(self):
        from filters import StillGate
        g = StillGate(0.2, 0.1)
        g({"yaw": 0.0})
        out = 0.0
        for i in range(1, 61):                             # 60 deg turn
            out = g({"yaw": float(i)})["yaw"]
            self.assertAlmostEqual(out, i - 0.2)           # follows every frame, only 0.2 deg behind
        self.assertAlmostEqual(out, 59.8)


class OutputPumpTest(unittest.TestCase):
    def test_upsamples_a_60hz_turn_smoothly(self):
        import time as _t
        from filters import OutputPump
        got = []
        pump = OutputPump(lambda v, a: got.append((_t.perf_counter(), v["yaw"])), hz=240, tau_ms=6)
        pump.start()
        try:
            t0 = _t.perf_counter()
            for i in range(30):                                 # 0.5 s at 60 Hz, 60 deg/s
                pump.set({"yaw": i * 1.0}, _t.perf_counter(), True)
                _t.sleep(1 / 60)
        finally:
            pump.stop()
            pump.join(1)
        dt = got[-1][0] - got[0][0]
        self.assertGreater(len(got) / dt, 180)                # ~240 sends a second, not 60
        steps = [b[1] - a[1] for a, b in zip(got[len(got) // 3:], got[len(got) // 3 + 1:])]
        self.assertLess(max(steps), 0.75)                     # no 60 Hz 1-degree staircase (240 Hz ~0.25 each)
        self.assertGreater(got[-1][1], 25)                    # keeps up with the turn


class OutputTest(unittest.TestCase):
    def test_opentrack_packet(self):
        b = pack({"x": 1, "y": 2, "z": 3, "yaw": 4, "pitch": 5, "roll": 6})
        self.assertEqual(len(b), 48)
        self.assertEqual(struct.unpack("<6d", b), (1, 2, 3, 4, 5, 6))


class RateTest(unittest.TestCase):
    def test_same_timestamp_does_not_divide_by_zero(self):
        from metrics import Rate
        r = Rate()
        r.tick(1.0, 1)
        r.tick(1.0, 2)          # skipped frames reported with the same capture time
        self.assertEqual(r.hz, 0.0)

    def test_counts_batched_frames(self):
        from metrics import Rate
        r = Rate()
        for i in range(31):     # 1 s, tracker keeps up with every 2nd camera frame
            r.tick(i / 30, 2)
        self.assertAlmostEqual(r.hz, 60.0, places=6)


class StillTestTest(unittest.TestCase):
    def test_reports_after_duration(self):
        st = StillTest(1.0)
        st.begin(0.0)
        for i in range(70):
            p = {a: math.sin(i) * 0.1 for a in ("yaw", "pitch", "roll", "x", "y", "z")}
            st.add(i / 60, p, p)
        self.assertIsNotNone(st.result)
        self.assertGreater(st.result["raw"]["yaw"], 0)
        self.assertFalse(st.running)


if __name__ == "__main__":
    unittest.main()
