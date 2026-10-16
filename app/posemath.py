"""Head pose from MediaPipe's facial transformation matrix, relative to a stored centre.

MediaPipe gives a 4x4 face -> camera transform (cm). We take the rotation relative to the centre
pose (R_c^T R), turn it into yaw / pitch / roll (Y-X-Z, degrees) and the translation difference
(camera axes, cm). Signs are mapped to opentrack's convention by AXIS_SIGN (checked in the app;
each axis can be inverted in the settings).
"""
from __future__ import annotations

import math

import numpy as np

# camera / MediaPipe -> opentrack: yaw left +, pitch up +, roll left +, x right +, y up +, z back +
AXIS_SIGN = {"x": 1.0, "y": 1.0, "z": 1.0, "yaw": 1.0, "pitch": 1.0, "roll": 1.0}


def euler_yxz(r: np.ndarray) -> tuple[float, float, float]:
    """R = Ry(yaw) Rx(pitch) Rz(roll) -> (yaw, pitch, roll) in degrees."""
    pitch = math.asin(max(-1.0, min(1.0, -r[1, 2])))
    if abs(r[1, 2]) < 0.9999:
        yaw = math.atan2(r[0, 2], r[2, 2])
        roll = math.atan2(r[1, 0], r[1, 1])
    else:  # gimbal lock (pitch +-90): roll folded into yaw
        yaw = math.atan2(-r[2, 0], r[0, 0])
        roll = 0.0
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)


def rot_yxz(yaw: float, pitch: float, roll: float) -> np.ndarray:
    y, p, r = map(math.radians, (yaw, pitch, roll))
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return ry @ rx @ rz


def orthonormalize(r: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(r)
    m = u @ vt
    if np.linalg.det(m) < 0:
        u[:, -1] *= -1
        m = u @ vt
    return m


def relative_pose(m: np.ndarray, centre: np.ndarray, sign: dict | None = None) -> dict:
    """Pose of 4x4 transform m relative to centre (4x4), in opentrack axes."""
    s = sign or AXIS_SIGN
    r = orthonormalize(m[:3, :3])
    rc = orthonormalize(centre[:3, :3])
    rel = rc.T @ r
    yaw, pitch, roll = euler_yxz(rel)
    d = m[:3, 3] - centre[:3, 3]
    return {"x": s["x"] * float(d[0]), "y": s["y"] * float(d[1]), "z": s["z"] * float(d[2]),
            "yaw": s["yaw"] * yaw, "pitch": s["pitch"] * pitch, "roll": s["roll"] * roll}
