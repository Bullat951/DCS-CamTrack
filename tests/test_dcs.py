"""Curves, DCS packet + status channel, hotkey binding parsing."""
from __future__ import annotations

import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import curves  # noqa: E402
import dcsout  # noqa: E402
import hotkeys  # noqa: E402


class CurveTest(unittest.TestCase):
    def test_monotone_cubic_through_points_no_overshoot(self):
        pts = [[10, 20], [30, 140]]                         # the user's opentrack yaw curve
        self.assertAlmostEqual(curves.evaluate(pts, 10), 20)
        self.assertAlmostEqual(curves.evaluate(pts, 30), 140)
        self.assertEqual(curves.evaluate(pts, 0), 0)
        self.assertEqual(curves.evaluate(pts, 50), 140)     # flat after the last point
        ys = [curves.evaluate(pts, x / 10) for x in range(0, 401)]
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])))   # monotone
        self.assertLessEqual(max(ys), 140 + 1e-9)                      # no overshoot

    def test_separate_curve_per_direction(self):
        c = curves.merged({"pitch": {"mirror": False, "points_pos": [[30, 60]], "points_neg": [[30, 90]],
                                     "deadzone": 0.0}})["pitch"]
        self.assertAlmostEqual(curves.shape(30, c), 60)
        self.assertAlmostEqual(curves.shape(-30, c), -90)   # looking down gets its own curve

    def test_soft_deadzone_has_no_kink_at_the_centre(self):
        c = curves.merged({"yaw": {"points_pos": [[10, 20], [30, 140]], "mirror": True, "deadzone": 1.0}})["yaw"]
        self.assertLess(abs(curves.shape(0.2, c)), 0.02)            # calm in the centre
        h = 0.01                                                     # slope rises smoothly, never jumps
        slopes = [(curves.shape(x + h, c) - curves.shape(x, c)) / h for x in [i * 0.05 for i in range(0, 80)]]
        jumps = [abs(b - a) for a, b in zip(slopes, slopes[1:])]
        self.assertLess(max(jumps), 0.15)
        self.assertAlmostEqual(curves.shape(20, c), curves.evaluate(c["points_pos"], 19.0), delta=0.05)  # = hard dz far out
        self.assertAlmostEqual(curves.shape(-3, c), -curves.shape(3, c))                                   # symmetric

    def test_to_dcs_normalised_and_inverted(self):
        cv = curves.merged({"yaw": {"points_pos": [[90, 90]], "mirror": True, "deadzone": 0, "full_scale": 180, "invert": True}})
        vals = curves.to_dcs({"yaw": 90, "pitch": 0, "roll": 0, "x": 0, "y": 0, "z": 0}, cv)
        self.assertEqual(len(vals), 6)
        self.assertAlmostEqual(vals[0], -0.5)
        self.assertTrue(all(-1 <= v <= 1 for v in vals))

    def test_old_gain_settings_convert_without_jump(self):
        old = {"gain_pos": 2.0, "gain_neg": 2.5, "deadzone": 0.3, "expo": 0.3, "full_scale": 90.0}
        new = curves.merged({"pitch": dict(old)})["pitch"]
        self.assertFalse(new["mirror"])
        for head in (5.0, 15.0, 30.0):                      # same output as the old formula (within the sampling)
            a = head - 0.3
            x = min(a * 2.0 / 90, 1)
            expect = 90 * ((1 - 0.3) * x + 0.3 * x ** 3)
            self.assertAlmostEqual(curves.shape(head, new), expect, delta=1.5)

    def test_unknown_keys_ignored(self):
        m = curves.merged({"yaw": {"bogus": 1}})
        self.assertNotIn("bogus", m["yaw"])

    def test_import_opentrack_qt_points(self):
        import tempfile, os
        ini = ('[spline-yaw]\npoints=@Variant(\\0\\0\\0\\x7f\\0\\0\\0\\xfQList<QPointF>\\0\\0\\0\\0\\x2@$\\0\\0\\0\\0\\0\\0'
               '@4\\0\\0\\0\\0\\0\\0@>\\0\\0\\0\\0\\0\\0@a\\x80\\0\\0\\0\\0\\0)\n\n[spline-pitch-alt]\n'
               'points=@Variant(\\0\\0\\0\\x7f\\0\\0\\0\\xfQList<QPointF>\\0\\0\\0\\0\\x1@1\\0\\0\\0\\0\\0\\0@R\\xc0\\0\\0\\0\\0\\0)\n')
        p = os.path.join(tempfile.mkdtemp(), "t.ini")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(ini)
        d = curves.import_opentrack(p)
        self.assertEqual(d["yaw"]["points_pos"], [[10.0, 20.0], [30.0, 140.0]])
        self.assertEqual(d["pitch"]["points_neg"], [[17.0, 75.0]])
        self.assertFalse(d["pitch"]["mirror"])


class DcsOutTest(unittest.TestCase):
    def test_packet_format_matches_the_hook(self):
        p = dcsout.pack(7, True, [0.1, -0.2, 0, 0.5, -1, 1]).decode()
        self.assertTrue(p.startswith("HTK1 7 1 "))
        self.assertEqual(len(p.split()), 9)

    def test_status_channel(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))             # a free port (the real app may hold 4246)
        port = probe.getsockname()[1]
        probe.close()
        out = dcsout.DcsOutput(status_port=port)
        try:
            time.sleep(0.2)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(b"HTKS 1.0.0 CH-47Fbl1 1 42", ("127.0.0.1", port))
            s.close()
            deadline = time.time() + 2
            while time.time() < deadline and not out.connected():
                time.sleep(0.05)
            self.assertTrue(out.connected())
            self.assertEqual(out.status["unit"], "CH-47Fbl1")
            self.assertTrue(out.status["applying"])
        finally:
            out.close()

    def test_hook_source_exists(self):
        self.assertTrue(dcsout.HOOK_SRC.is_file())


class HotkeyTest(unittest.TestCase):
    def test_parse_and_describe(self):
        self.assertEqual(hotkeys.parse("key:120:ctrl:shift"), ("key", 120, [0x11, 0x10]))
        self.assertEqual(hotkeys.parse("joy:2:14"), ("joy", 2, 14))
        self.assertIsNone(hotkeys.parse(""))
        self.assertEqual(hotkeys.describe("key:120:ctrl"), "Ctrl+F9")
        self.assertEqual(hotkeys.describe("joy:0:5"), "Joystick 1 button 5")
        self.assertEqual(hotkeys.describe(""), "(not set)")


if __name__ == "__main__":
    unittest.main()
