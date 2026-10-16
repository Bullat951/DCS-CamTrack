"""Personal rigid model on synthetic faces projected in TRUE perspective (like a real camera)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from posemath import euler_yxz, rot_yxz  # noqa: E402
from rigid import CV_TO_MP, RIGID, RigidPose, build_model, focal_px, refine_model, umeyama  # noqa: E402

W, H = 1280, 720
F = focal_px(H)
rng = np.random.default_rng(3)
# a face-like rigid point set in cm, camera frame (x right, y down, z away), centred on the head
FACE = rng.normal(0, 1, (len(RIGID), 3)) * np.array([6.0, 7.0, 3.0])


class Lm:
    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


def project(r_cv: np.ndarray, centre_cm: np.ndarray, noise_px: float = 0.0) -> np.ndarray:
    """Perspective projection -> landmark-like points (px, px, depth in x-pixel scale)."""
    p = (r_cv @ FACE.T).T + centre_cm
    x = F * p[:, 0] / p[:, 2] + W / 2
    y = F * p[:, 1] / p[:, 2] + H / 2
    z = F * (p[:, 2] - centre_cm[2]) / centre_cm[2]
    out = np.stack([x, y, z], axis=1)
    return out + rng.normal(0, noise_px, out.shape) if noise_px else out


def mp_angles(r_mp: np.ndarray) -> tuple[float, float, float]:
    return euler_yxz(r_mp)


class RigidTest(unittest.TestCase):
    def setUp(self):
        truth = [rot_yxz(y, p, 0) for y in (-30, -10, 0, 15, 35) for p in (-15, 0, 12)]
        views = [project(CV_TO_MP @ t @ CV_TO_MP, np.array([0, 0, 60.0]), 0.7) for t in truth]
        self.rp = RigidPose(refine_model(build_model(views), views, W, H))
        # calibration also gives MediaPipe's head rotation per view (here: the truth, in MediaPipe's frame)
        pairs = []
        for v, t in zip(views, truth):
            self.rp.reset()
            pairs.append((self.rp.raw_rotation(v, W, H)[0], t))
        self.rp.fit_alignment(pairs)
        self.rp.reset()
        self.centre = self.rp.rotation(project(np.eye(3), np.array([0, 0, 60.0])), W, H)[0]

    def rel(self, r_true_mp, centre_cm, noise=0.0):
        r_cv = CV_TO_MP @ r_true_mp @ CV_TO_MP
        self.rp.reset()
        r, _ = self.rp.rotation(project(r_cv, centre_cm, noise), W, H)
        return mp_angles(self.centre.T @ r)

    def test_recovers_rotation_on_axis(self):
        for yaw, pitch, roll in [(25, 0, 0), (0, -15, 0), (0, 0, 10), (40, 12, -6), (-55, 8, 4)]:
            got = self.rel(rot_yxz(yaw, pitch, roll), np.array([0, 0, 60.0]))
            for g, e in zip(got, (yaw, pitch, roll)):
                self.assertAlmostEqual(g, e, delta=1.0)

    def test_perspective_correction_off_centre(self):
        # head NOT rotated, but 20 cm to the side and 10 cm up: must read ~0 deg, not the ray angle (~18 deg)
        got = self.rel(np.eye(3), np.array([20.0, -10.0, 60.0]))
        for g in got:
            self.assertLess(abs(g), 1.0)

    def test_noise_robust(self):
        got = self.rel(rot_yxz(20, 5, 0), np.array([0, 0, 60.0]), noise=0.5)
        self.assertAlmostEqual(got[0], 20, delta=1.5)

    def test_umeyama_exact(self):
        r = rot_yxz(30, -10, 5)
        dst = 2.5 * (r @ FACE.T).T + np.array([1, 2, 3])
        s, rr, t = umeyama(FACE, dst)
        self.assertAlmostEqual(s, 2.5, places=6)
        self.assertTrue(np.allclose(rr, r, atol=1e-9))

    def test_save_load(self):
        import tempfile, os
        p = os.path.join(tempfile.mkdtemp(), "m.npz")
        self.rp.save(p)
        self.assertTrue(np.allclose(RigidPose.load(p).model, self.rp.model))


if __name__ == "__main__":
    unittest.main()
