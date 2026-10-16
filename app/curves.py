"""Response curves per axis: head movement -> view movement, as editable points.

Each axis has a curve of points (head deg / cm -> view deg / cm) starting at (0, 0), interpolated with a
MONOTONE cubic (Fritsch-Carlson: smooth, never overshoots between points), flat after the last point.
`mirror` = the same curve for both directions; otherwise `points_neg` is used for the negative side
(looking down / right ...). A dead zone is taken off first. `full_scale` = how many view degrees (cm) equal
1.0 on DCS's absolute camera axis; `invert` flips the DCS direction.
Older settings with gain / expo are converted to points on load (sampled from the old formula).
"""
from __future__ import annotations

import math
import re
import struct

AXES = ("yaw", "pitch", "roll", "x", "y", "z")

DEFAULTS = {
    "yaw":   {"points_pos": [[72.0, 180.0]], "points_neg": [[72.0, 180.0]], "mirror": True,
              "deadzone": 0.3, "full_scale": 180.0, "invert": False},
    "pitch": {"points_pos": [[45.0, 90.0]], "points_neg": [[36.0, 90.0]], "mirror": False,
              "deadzone": 0.3, "full_scale": 90.0, "invert": False},
    "roll":  {"points_pos": [[90.0, 90.0]], "points_neg": [[90.0, 90.0]], "mirror": True,
              "deadzone": 0.5, "full_scale": 90.0, "invert": False},
    "x":     {"points_pos": [[20.0, 30.0]], "points_neg": [[20.0, 30.0]], "mirror": True,
              "deadzone": 0.2, "full_scale": 30.0, "invert": False},
    "y":     {"points_pos": [[20.0, 30.0]], "points_neg": [[20.0, 30.0]], "mirror": True,
              "deadzone": 0.2, "full_scale": 30.0, "invert": False},
    "z":     {"points_pos": [[20.0, 30.0]], "points_neg": [[20.0, 30.0]], "mirror": True,
              "deadzone": 0.2, "full_scale": 30.0, "invert": False},
}
KEYS = ("points_pos", "points_neg", "mirror", "deadzone", "full_scale", "invert")


# ---------------------------------------------------------------- monotone cubic
def _prep(points) -> tuple[list[float], list[float], list[float]]:
    pts = sorted((float(x), float(y)) for x, y in points if float(x) > 0)
    xs, ys = [0.0], [0.0]
    for x, y in pts:
        if x > xs[-1] + 1e-9:
            xs.append(x)
            ys.append(max(y, ys[-1]))          # keep it monotone
    n = len(xs)
    if n == 1:
        return xs, ys, [0.0]
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [d[0]] + [0.0] * (n - 2) + [d[-1]]
    for i in range(1, n - 1):
        m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2
    for i in range(n - 1):                     # Fritsch-Carlson limiter: no overshoot
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9:
            t = 3 / s ** 0.5
            m[i], m[i + 1] = t * a * d[i], t * b * d[i]
    return xs, ys, m


def evaluate(points, x: float) -> float:
    xs, ys, m = _prep(points)
    if x <= 0:
        return 0.0
    if x >= xs[-1]:
        return ys[-1]                          # flat after the last point (like opentrack)
    i = max(k for k in range(len(xs) - 1) if xs[k] <= x)
    h = xs[i + 1] - xs[i]
    t = (x - xs[i]) / h
    h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
    h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1]


# ---------------------------------------------------------------- shaping
def soft_deadzone(a: float, dz: float) -> float:
    """|head| minus a SOFT dead zone: a - dz * tanh(a / dz). Slope 0 at the centre rising smoothly to 1,
    the same as a hard dead zone further out. A hard one (slope 0, then the curve's full slope at once)
    was felt as a bump every time the head passed the centre."""
    if dz <= 0:
        return a
    return a - dz * math.tanh(a / dz)


def shape(v: float, c: dict) -> float:
    """Head value (deg / cm) -> view value (deg / cm) for one axis."""
    a = soft_deadzone(abs(v), c["deadzone"])
    if a <= 0:
        return 0.0
    pts = c["points_pos"] if (v > 0 or c["mirror"]) else c["points_neg"]
    y = evaluate(pts, a)
    return y if v > 0 else -y


def shaped_pose(pose: dict, curves: dict) -> dict:
    return {a: shape(pose[a], curves[a]) for a in AXES}


def normalize(view: dict, curves: dict) -> list[float]:
    """View values (deg / cm, after the curves) -> the six DCS axis values in -1..1 (yaw..z)."""
    out = []
    for a in AXES:
        c = curves[a]
        v = view[a] / max(c["full_scale"], 1e-6)
        if c["invert"]:
            v = -v
        out.append(max(-1.0, min(1.0, v)))
    return out


def to_dcs(pose: dict, curves: dict) -> list[float]:
    return normalize(shaped_pose(pose, curves), curves)


# ---------------------------------------------------------------- settings
def _from_gain(c: dict) -> dict:
    """Old gain / expo settings -> points, sampled from the old formula (so nothing jumps)."""
    fs = max(float(c.get("full_scale", 90.0)), 1e-6)
    e = min(max(float(c.get("expo", 0.0)), 0.0), 1.0)
    out = {}
    for side, key in (("points_pos", "gain_pos"), ("points_neg", "gain_neg")):
        g = max(float(c.get(key, 1.0)), 1e-6)
        end = fs / g                                   # head value that reaches the end
        out[side] = [[round(end * f, 3), round(fs * ((1 - e) * f + e * f ** 3), 3)] for f in (0.25, 0.5, 0.75, 1.0)]
    out["mirror"] = abs(float(c.get("gain_pos", 1)) - float(c.get("gain_neg", 1))) < 1e-9
    return out


def merged(user: dict | None) -> dict:
    out = {a: {k: (list(map(list, v)) if isinstance(v, list) else v) for k, v in DEFAULTS[a].items()} for a in AXES}
    for a, c in (user or {}).items():
        if a not in out or not isinstance(c, dict):
            continue
        if "gain_pos" in c and "points_pos" not in c:
            c = dict(c, **_from_gain(c))
        out[a].update({k: v for k, v in c.items() if k in KEYS})
    return out


# ---------------------------------------------------------------- opentrack import
def _qt_unescape(s: str) -> bytes:
    """QSettings' escaped byte string -> bytes ('\\0', '\\xHH...', other chars as-is)."""
    out, i = bytearray(), 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "0":
                out.append(0); i += 2; continue
            if nxt == "x":
                j = i + 2
                while j < len(s) and s[j] in "0123456789abcdefABCDEF":
                    j += 1
                out.append(int(s[i + 2:j], 16) & 0xFF); i = j; continue
            out.append(ord(nxt)); i += 2; continue
        out.append(ord(ch) & 0xFF); i += 1
    return bytes(out)


def _decode_points(value: str) -> list[list[float]]:
    m = re.search(r"@Variant\((.*)\)\s*$", value)
    if not m:
        return []
    b = _qt_unescape(m.group(1))
    k = b.find(b"QList<QPointF>\0")
    if k < 0:
        return []
    p = k + len(b"QList<QPointF>\0")
    n = struct.unpack(">I", b[p:p + 4])[0]
    p += 4
    pts = []
    for _ in range(n):
        x, y = struct.unpack(">dd", b[p:p + 16])
        p += 16
        pts.append([round(x, 3), round(y, 3)])
    return pts


OT_NAMES = {"yaw": "yaw", "pitch": "pitch", "roll": "roll", "X": "x", "Y": "y", "Z": "z"}


def import_opentrack(ini_path) -> dict:
    """{axis: {"points_pos": [...], "points_neg"?: [...], "mirror": bool}} from opentrack's [spline-*] sections."""
    with open(ini_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    found: dict = {}
    for sec, body in re.findall(r"^\[spline-([^\]]+)\]\s*\n(.*?)(?=^\[|\Z)", text, re.M | re.S):
        pm = re.search(r"^points=(.*)$", body, re.M)
        if not pm:
            continue
        pts = _decode_points(pm.group(1).strip())
        if not pts:
            continue
        alt = sec.endswith("-alt") or sec.endswith("_alt")
        name = OT_NAMES.get(sec[:-4] if alt else sec)
        if not name:
            continue
        d = found.setdefault(name, {"mirror": True})
        if alt:
            d["points_neg"] = pts
            d["mirror"] = False
        else:
            d["points_pos"] = pts
    return found
