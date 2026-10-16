"""Head rotation from RIGID face landmarks fitted to the user's own face shape.

MediaPipe's own transform fits a generic face. Here: a personal 3D shape of ~35 landmarks that do
not move with expressions (nose bridge, eye corners, forehead, cheekbones, temples - no mouth, jaw
or brows, which move when talking on SRS), learned by generalized Procrustes from a short
calibration, then fitted to each frame with Umeyama (rotation + scale + translation).

Landmarks are in MediaPipe's image frame: x right, y down (pixels), z away from the camera (same
scale as x) - the OpenCV camera frame. Off-centre faces look slightly rotated under this scaled
orthographic view; the ray to the face centre corrects that (perspective correction).
"""
from __future__ import annotations

import math

import numpy as np

RIGID = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1,            # forehead centre line, nose bridge
         33, 133, 362, 263, 130, 359, 243, 463,              # eye corners
         116, 345, 123, 352, 117, 346, 50, 280,              # cheekbones
         234, 454, 127, 356, 162, 389, 54, 284, 103, 332]    # temples / upper face sides

CV_TO_MP = np.diag([1.0, -1.0, -1.0])   # OpenCV camera frame -> MediaPipe's (y up, z toward camera)


def points(lms, w: int, h: int, idx=RIGID) -> np.ndarray:
    return np.array([[lms[i].x * w, lms[i].y * h, lms[i].z * w] for i in idx], dtype=np.float64)


def _normalize(p: np.ndarray) -> np.ndarray:
    c = p - p.mean(axis=0)
    return c / np.linalg.norm(c)


def kabsch(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Rotation R minimising |R src_i - dst_i| (both centred), no reflection."""
    h = src.T @ dst
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    return vt.T @ np.diag([1.0, 1.0, d]) @ u.T


def umeyama(src: np.ndarray, dst: np.ndarray):
    """dst ~ s R src + t  ->  (s, R, t)."""
    ms, md = src.mean(axis=0), dst.mean(axis=0)
    a, b = src - ms, dst - md
    r = kabsch(a, b)
    s = float(np.sum(b * (a @ r.T)) / np.sum(a * a))
    return s, r, md - s * (r @ ms)


def build_model(clouds: list[np.ndarray], iters: int = 10) -> np.ndarray:
    """Generalized Procrustes: the mean rigid shape (centred, unit size) of many views."""
    shapes = [_normalize(c) for c in clouds]
    ref = shapes[0]
    for _ in range(iters):
        aligned = [(kabsch(s, ref) @ s.T).T for s in shapes]
        new = _normalize(np.mean(aligned, axis=0))
        if np.linalg.norm(new - ref) < 1e-9:
            ref = new
            break
        ref = new
    return ref


def refine_model(model: np.ndarray, views: list[np.ndarray], w: int, h: int, iters: int = 8,
                 face_cm: float = 15.0) -> np.ndarray:
    """Bundle-adjust the shape against the calibration views (true perspective).

    The GPA mean bakes in each view's perspective distortion (near points look larger): on synthetic
    data that left ~4 px of residual and up to 7 deg of cross-axis error. Alternate: pose of every view by
    solvePnP, then each point re-triangulated (linear least squares) from all views; repeat."""
    import cv2
    f = focal_px(h)
    k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)
    shape = model * face_cm
    for _ in range(iters):
        projs = []
        for v in views:
            s, r0, _ = umeyama(shape / face_cm, v)
            c = v[:, :2].mean(axis=0)
            dist = f * face_cm / max(s, 1e-6)
            rvec0, _ = cv2.Rodrigues(r0)
            t0 = np.array([[(c[0] - w / 2) * dist / f], [(c[1] - h / 2) * dist / f], [dist]])
            ok, rvec, tvec = cv2.solvePnP(shape, v[:, :2].astype(np.float64), k, None, rvec0, t0,
                                          useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
            if ok and tvec[2, 0] > 0:
                r, _ = cv2.Rodrigues(rvec)
                projs.append((k @ np.hstack([r, tvec]), v))
        if len(projs) < 3:
            break
        new = np.empty_like(shape)
        for j in range(shape.shape[0]):
            rows = []
            for p, v in projs:
                x, y = v[j, 0], v[j, 1]
                rows.append(x * p[2] - p[0])
                rows.append(y * p[2] - p[1])
            a = np.array(rows)
            _, _, vt = np.linalg.svd(a)
            X = vt[-1]
            new[j] = X[:3] / X[3]
        new -= new.mean(axis=0)
        shape = new / np.linalg.norm(new) * face_cm * np.linalg.norm(model)
    out = shape - shape.mean(axis=0)
    return out / np.linalg.norm(out)


def ray_rotation(cx: float, cy: float, w: int, h: int, f: float) -> np.ndarray:
    """Rotation turning the optical axis (0,0,1) onto the ray through pixel (cx, cy) (camera frame)."""
    d = np.array([(cx - w / 2) / f, (cy - h / 2) / f, 1.0])
    d /= np.linalg.norm(d)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(z, d)
    s, c = np.linalg.norm(v), float(z @ d)
    if s < 1e-12:
        return np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]) / s
    ang = math.atan2(s, c)
    return np.eye(3) + math.sin(ang) * k + (1 - math.cos(ang)) * (k @ k)


def focal_px(h: int, vfov_deg: float = 63.0) -> float:
    """MediaPipe's own camera model (vertical FOV 63 deg) - same intrinsics as its matrix."""
    return (h / 2) / math.tan(math.radians(vfov_deg) / 2)


class RigidPose:
    """Rotation by a true perspective fit (solvePnP) of the personal rigid shape to the 2D landmarks.

    (An orthographic Umeyama fit with a ray correction was tried first: 1.2 deg short at 25 deg yaw and
    15 deg wrong for a face 20 cm off-centre on synthetic perspective data - solvePnP is exact.)"""

    FACE_CM = 15.0   # the shape's size; any value gives the same rotation, only distance scales

    def __init__(self, model: np.ndarray, align: np.ndarray | None = None):
        self.model = model
        # model frame -> head frame (MediaPipe's canonical face axes): the learned shape sits in an
        # arbitrary frame; without this, angles came out on mixed axes (synthetic: 25 deg yaw read
        # as 24 yaw + 4 pitch - 4.5 roll)
        self.align = np.eye(3) if align is None else align
        self._rvec = None
        self._tvec = None

    def raw_rotation(self, pts, w, h, f=None):
        """Model -> camera rotation (MediaPipe frame) without the head alignment."""
        a, self.align = self.align, np.eye(3)
        try:
            return self.rotation(pts, w, h, f)
        finally:
            self.align = a

    def fit_alignment(self, pairs: list[tuple[np.ndarray, np.ndarray]]) -> None:
        """pairs of (raw rigid rotation, MediaPipe head rotation) for the same frames, both model->camera:
        align = mean over frames of raw^T @ mp (chordal mean by SVD)."""
        s = sum(r.T @ m for r, m in pairs)
        u, _, vt = np.linalg.svd(s)
        a = u @ vt
        if np.linalg.det(a) < 0:
            u[:, -1] *= -1
            a = u @ vt
        self.align = a

    @classmethod
    def load(cls, path) -> "RigidPose | None":
        try:
            d = np.load(path)
            return cls(d["model"], d["align"] if "align" in d else None)
        except (OSError, KeyError, ValueError):
            return None

    def save(self, path) -> None:
        np.savez(path, model=self.model, align=self.align)

    def rotation(self, pts: np.ndarray, w: int, h: int, f: float | None = None) -> tuple[np.ndarray, float]:
        """(3x3 head rotation in MediaPipe's frame, RMS reprojection error in px)."""
        import cv2
        f = f or focal_px(h)
        k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)
        obj = self.model * self.FACE_CM
        img = pts[:, :2].astype(np.float64)
        if self._rvec is None:
            # first guess from the orthographic fit, at a plausible distance
            s, r0, _ = umeyama(self.model, pts)
            rvec0, _ = cv2.Rodrigues(r0)
            c = pts[:, :2].mean(axis=0)
            dist = f * self.FACE_CM / max(s, 1e-6)
            self._rvec, self._tvec = rvec0, np.array([[(c[0] - w / 2) * dist / f], [(c[1] - h / 2) * dist / f], [dist]])
        ok, rvec, tvec = cv2.solvePnP(obj, img, k, None, self._rvec.copy(), self._tvec.copy(),
                                      useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok or tvec[2, 0] <= 0:
            self._rvec = None
            return None, float("inf")
        self._rvec, self._tvec = rvec, tvec
        proj, _ = cv2.projectPoints(obj, rvec, tvec, k, None)
        resid = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img) ** 2, axis=1))))
        r, _ = cv2.Rodrigues(rvec)
        return CV_TO_MP @ r @ CV_TO_MP @ self.align, resid

    def reset(self):
        self._rvec = self._tvec = None
