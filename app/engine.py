"""Tracking engine on its own thread: camera -> pose (MediaPipe matrix or personal rigid model) -> filter ->
prediction -> opentrack UDP. The UI only reads `snapshot()` and calls the command methods."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

import curves as curvemod
from camera import Camera
from dcsout import DcsOutput
from filters import OutputPump, PoseFilter, Predictor, StillGate
from metrics import Mean, Rate, StillTest
from output import OpentrackUdp
from posemath import AXIS_SIGN, orthonormalize, relative_pose
from rigid import RigidPose, build_model, points, refine_model
from tracker import FaceTracker

from appdirs import data_dir, migrate_dev_data
from devices import camera_index

migrate_dev_data()
DATA = data_dir()
SETTINGS = DATA / "settings.json"
PERSONAL = DATA / "personal_face.npz"
RESULTS = DATA / "test_results.txt"
AXES = ("x", "y", "z", "yaw", "pitch", "roll")
DEFAULTS = {
    "camera": {"index": 0, "name": "", "width": 1280, "height": 720, "fps": 60, "exposure": -7.0, "gain": 0.0,
               "focus": 0.0, "wb": 4500.0, "lock": True},
    "dcs_folder": "",               # Saved Games\DCS* folder for the hook ("" = the first one found)
    "filter": {"enabled": True, "rot": [0.6, 0.03], "pos": [0.8, 0.05]},
    "predict_ms": 20.0,
    "source": "mediapipe",          # "mediapipe" | "rigid"
    "sign": dict(AXIS_SIGN),
    "udp": {"host": "127.0.0.1", "port": 4242},
    "hold_lost_s": 1.0,
    "start_minimized": False,
    "output": "dcs",                # "dcs" (HeadTracker hook, no TrackIR) | "opentrack" (UDP)
    "curves": {},                   # per-axis overrides of curves.DEFAULTS
    "bind": {"centre": "", "pause": ""},
    "still_gate": {"deg": 0.2, "cm": 0.1},   # view-level hysteresis against amplified tremble
}


def load_settings() -> dict:
    s = json.loads(json.dumps(DEFAULTS))
    try:
        user = json.loads(SETTINGS.read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k].update(v)
            else:
                s[k] = v
    except (OSError, ValueError):
        pass
    return s


def save_settings(s: dict) -> None:
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


def pose_matrix(rot: np.ndarray, m_mp: np.ndarray) -> np.ndarray:
    """4x4 with the given rotation and MediaPipe's translation (cm)."""
    out = np.eye(4)
    out[:3, :3] = rot
    out[:3, 3] = m_mp[:3, 3]
    return out


class Engine(threading.Thread):
    CALIB_S = 20.0

    def __init__(self, settings: dict):
        super().__init__(daemon=True, name="engine")
        self.s = settings
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snap: dict = {"status": "STARTING"}
        self._cmd: list = []
        self.rigid = RigidPose.load(PERSONAL)
        self.error = ""
        # Open the camera HERE, on the creating (main) thread: a DirectShow open on a worker thread
        # hangs forever (COM apartment) - found with a stack dump. Reading frames on a thread is fine.
        cam_cfg = dict(settings["camera"])
        cam_cfg["index"] = camera_index(cam_cfg.get("name", ""), int(cam_cfg.get("index", 0)))
        self.cam = Camera(**cam_cfg)
        self.cam_ok = self.cam.open()
        print("engine: camera %s (index %s) open=%s info=%s, output=%s" % (
            cam_cfg.get("name") or "-", cam_cfg["index"], self.cam_ok, self.cam.info, settings.get("output")), flush=True)
        self._cam_lock = threading.Lock()
        self.paused = False
        self.dcs = DcsOutput()

    # ---------------------------------------------------------------- commands (UI thread)
    def command(self, name: str, *args):
        with self._lock:
            self._cmd.append((name, args))

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snap)

    def set_camera(self, **kw) -> bool:
        """MAIN thread only (camera opens can hang on a worker thread). The loop pauses meanwhile."""
        with self._cam_lock:
            if "name" in kw:          # another camera: its DirectShow index by name
                kw["index"] = camera_index(kw["name"], int(self.s["camera"].get("index", 0)))
            self.cam_ok = self.cam.set(**kw)
            self.s["camera"].update(kw)
            return self.cam_ok

    def stop(self):
        self._stop.set()

    # ---------------------------------------------------------------- loop
    def run(self):
        s = self.s
        cam = self.cam
        if not self.cam_ok:
            self.error = "Camera not available - is another tracker (opentrack NeuralNet?) using it?"
            with self._lock:
                self._snap = {"status": "NO CAMERA", "error": self.error}
            return
        tracker = FaceTracker()
        flt = PoseFilter(rot=tuple(s["filter"]["rot"]), pos=tuple(s["filter"]["pos"]))
        pred = Predictor(lead_ms=s["predict_ms"])
        gate = StillGate(s["still_gate"]["deg"], s["still_gate"]["cm"])
        # 240 Hz to DCS: smooth between camera frames (curves read live so the editor applies at once)
        pump = OutputPump(lambda view, active: self.dcs.send(
            curvemod.normalize(view, curvemod.merged(s.get("curves"))), active))
        pump.start()
        view_hist: list = []          # view after curves + gate, for the still test's view jitter
        udp = OpentrackUdp(s["udp"]["host"], s["udp"]["port"])
        rate, cam_rate, lat, proc = Rate(), Rate(), Mean(), Mean()
        still = StillTest(10.0)
        test_label = ""
        centre, centre_src = None, None
        last_n, last_out, last_seen = -1, {a: 0.0 for a in AXES}, 0.0
        raw = {a: 0.0 for a in AXES}
        history: list = []
        calib = None                       # {"t0", "clouds", "mps", "w", "h"}
        result = ""
        try:
            while not self._stop.is_set():
                with self._lock:
                    cmds, self._cmd = self._cmd, []
                with self._cam_lock:
                    frame, t_cap, n = cam.latest()
                for name, args in cmds:
                    if name == "centre":
                        centre = None
                    elif name == "test":
                        test_label = args[0]
                        still.begin(t_cap or time.perf_counter())
                    elif name == "calibrate":
                        calib = {"t0": time.perf_counter(), "clouds": [], "mps": [], "next": 0.0}
                    elif name == "filter":
                        flt.set(rot=tuple(s["filter"]["rot"]), pos=tuple(s["filter"]["pos"]))
                    elif name == "predict":
                        pred.lead_ms = s["predict_ms"]
                    elif name == "gate":
                        gate.thr_deg, gate.thr_cm = s["still_gate"]["deg"], s["still_gate"]["cm"]
                    elif name == "source":
                        centre = None
                        if self.rigid:
                            self.rigid.reset()
                    elif name == "pause":
                        self.paused = not self.paused if not args else bool(args[0])
                if frame is None or n == last_n:
                    time.sleep(0.001)
                    continue
                if last_n >= 0 and n > last_n:
                    cam_rate.tick(t_cap, n - last_n)
                if last_n < 0:
                    print("engine: first camera frame %s" % (frame.shape,), flush=True)
                last_n = n
                h, w = frame.shape[:2]
                t0 = time.perf_counter()
                m, lms = tracker.process(frame, t_cap)
                fit_px = None
                now = time.perf_counter()
                if m is not None:
                    # calibration: collect the rigid points + MediaPipe's rotation, 10 a second
                    if calib is not None:
                        if now >= calib["next"]:
                            calib["next"] = now + 0.1
                            calib["clouds"].append(points(lms, w, h))
                            calib["mps"].append(orthonormalize(m[:3, :3]))
                        if now - calib["t0"] >= self.CALIB_S:
                            result = self._finish_calibration(calib, w, h)
                            calib = None
                    rot = None
                    use_rigid = s["source"] == "rigid" and self.rigid is not None
                    if use_rigid:
                        rot, fit_px = self.rigid.rotation(points(lms, w, h), w, h)
                    mm = pose_matrix(rot, m) if rot is not None else m
                    src = "rigid" if rot is not None else "mediapipe"
                    if centre is None or centre_src != src:
                        centre, centre_src = mm.copy(), src
                        flt.reset()
                    raw = relative_pose(mm, centre, s["sign"])
                    out = pred(flt(raw, t_cap, s["filter"]["enabled"]), flt.vel)
                    status, last_seen, last_out = "TRACKING", now, out
                else:
                    status = "HOLD" if now - last_seen < s["hold_lost_s"] else "LOST"
                    out = last_out
                    if status == "LOST":
                        flt.reset()
                        if self.rigid:
                            self.rigid.reset()
                proc.add((time.perf_counter() - t0) * 1000)
                curves = curvemod.merged(s.get("curves"))
                view = gate(curvemod.shaped_pose(out, curves))     # what DCS gets, in deg / cm
                if s.get("output") == "opentrack":
                    if not self.paused:          # paused: opentrack keeps the last pose (it has no mouse hand-over)
                        udp.send(out)
                else:
                    # paused -> 'inactive' packets: the hook stops driving the view, DCS's mouse look takes over
                    pump.set(view, time.perf_counter(), active=not self.paused and status != "LOST")
                if still.running:
                    view_hist.append(view)
                rate.tick()
                lat.add((time.perf_counter() - t_cap) * 1000)
                if m is not None:
                    still.add(t_cap, raw, out)
                if still.result:
                    from metrics import rms_about_mean
                    r = still.result["filtered"]
                    rr = still.result["raw"]
                    vj = {a: rms_about_mean([v[a] for v in view_hist]) for a in ("yaw", "pitch", "roll")} if view_hist else {}
                    view_hist = []
                    result = ("%s: head yaw %.3f pitch %.3f roll %.3f deg, x %.3f y %.3f z %.3f cm (raw yaw %.3f pitch %.3f)"
                              " | VIEW in DCS yaw %.3f pitch %.3f roll %.3f deg - %s"
                              % (test_label, r["yaw"], r["pitch"], r["roll"], r["x"], r["y"], r["z"], rr["yaw"], rr["pitch"],
                                 vj.get("yaw", 0), vj.get("pitch", 0), vj.get("roll", 0), s["source"]))
                    with open(RESULTS, "a", encoding="utf-8") as fh:
                        fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + result + "\n")
                    still.result = None
                history.append((now, out["yaw"], out["pitch"], out["roll"]))
                while history and now - history[0][0] > 6.0:
                    history.pop(0)
                with self._lock:
                    self._snap = {
                        "status": status, "frame": frame, "lms": lms, "pose": out, "raw": raw,
                        "cam_hz": cam_rate.hz, "track_hz": rate.hz, "model_ms": proc.value, "latency_ms": lat.value,
                        "fit_px": fit_px, "testing": still.running, "test_label": test_label, "result": result,
                        "calibrating": None if calib is None else (time.perf_counter() - calib["t0"]) / self.CALIB_S,
                        "has_rigid": self.rigid is not None, "history": list(history), "camera": cam.info,
                        "paused": self.paused, "view": view,
                        "dcs": dict(self.dcs.status, connected=self.dcs.connected()),
                    }
        finally:
            cam.close()
            tracker.close()
            udp.close()
            pump.stop()
            self.dcs.close()

    def _finish_calibration(self, calib: dict, w: int, h: int) -> str:
        clouds, mps = calib["clouds"], calib["mps"]
        if len(clouds) < 60:
            return "calibration: too few face frames (%d) - keep your face in view" % len(clouds)
        yaws = [abs(np.degrees(np.arctan2(r[0, 2], r[2, 2]))) for r in mps]
        if max(yaws) < 20:
            return "calibration: turn your head more (max yaw %.0f deg, need 20+)" % max(yaws)
        model = refine_model(build_model(clouds), clouds, w, h)
        rp = RigidPose(model)
        pairs = []
        resid = []
        for c, mp_r in zip(clouds, mps):
            rp.reset()
            r, res = rp.raw_rotation(c, w, h)
            if r is not None:
                pairs.append((r, mp_r))
                resid.append(res)
        rp.fit_alignment(pairs)
        rp.reset()
        rp.save(PERSONAL)
        self.rigid = rp
        return "calibration done: %d views, max yaw %.0f deg, fit %.2f px - pose source 'personal' available" % (
            len(pairs), max(yaws), float(np.median(resid)))
