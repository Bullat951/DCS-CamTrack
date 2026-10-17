"""Head Tracker window (tkinter): preview, live values + graph, calibration, tests, all settings.
Started by 'Head Tracker.exe'. The tracking runs in engine.Engine; this only shows and sends commands."""
from __future__ import annotations

import os as _os
import sys

# Packaged exe: no console, sys.stdout / stderr are None - log from the FIRST line on, so an import
# error in the bundle is written down instead of the program just vanishing.
if getattr(sys, "frozen", False) and not _os.environ.get("HEADTRACKER_LOG"):
    _d = _os.path.join(_os.environ.get("APPDATA", _os.path.expanduser("~")), "HeadTracker")
    _os.makedirs(_d, exist_ok=True)
    _os.environ["HEADTRACKER_LOG"] = _os.path.join(_d, "ui.log")
    sys.stdout = sys.stderr = open(_os.environ["HEADTRACKER_LOG"], "w", encoding="utf-8", buffering=1)
    import traceback as _tb
    sys.excepthook = lambda *a: _tb.print_exception(*a)

import ctypes
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json  # noqa: E402

from appdirs import data_dir, frozen  # noqa: E402
from curve_editor import CurveEditor  # noqa: E402
from devices import MODES, dcs_folders, list_cameras, mode_label  # noqa: E402

VERSION = "0.1.5"
from curves import AXES as CURVE_AXES, import_opentrack, merged  # noqa: E402
from dcsout import default_dcs_folder, hook_state, install_hook  # noqa: E402
from debuglog import dcs_log_lines, dlog, system_header  # noqa: E402
from engine import AXES, Engine, load_settings, save_settings  # noqa: E402
from hotkeys import Hotkeys, describe  # noqa: E402

OUTLINE = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
           152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10]
BG, PANEL, FG, MUTED, ACCENT, WARN, BAD = "#141414", "#1e1e1e", "#e8e8e8", "#8a8a8a", "#4cc38a", "#e0a030", "#e05050"
COL = {"yaw": "#4c9be8", "pitch": "#e8964c", "roll": "#b07ce8"}


def single_instance() -> bool:
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    single_instance.h = k32.CreateMutexW(None, False, "Local\\PersonalHeadTracker")
    return k32.GetLastError() != 183


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.s = load_settings()
        if self.s.get("debug_log"):
            try:
                dlog.start(system_header(VERSION, self.s))
                self._log_dcs("dcs.log at start")
            except OSError as e:
                print("debug log could not start: %r" % e)
        self.engine = Engine(self.s)
        self.engine.start()
        root.title("Head Tracker")
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=FG, fieldbackground=PANEL)
        style.configure("TButton", padding=4)
        style.configure("TCheckbutton", background=PANEL, foreground=FG)
        style.configure("TRadiobutton", background=PANEL, foreground=FG)
        style.configure("TLabelframe", background=PANEL, foreground=FG)
        style.configure("TLabelframe.Label", background=PANEL, foreground=MUTED)
        style.configure("Horizontal.TScale", background=PANEL)

        left = tk.Frame(root, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        tabs = ttk.Notebook(root)
        tabs.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        setup_tab = tk.Frame(tabs, bg=BG)
        right = tk.Frame(tabs, bg=BG)
        dcs_tab = tk.Frame(tabs, bg=BG)
        tabs.add(setup_tab, text="Setup")
        tabs.add(right, text="Tracking")
        tabs.add(dcs_tab, text="DCS output")
        self.build_dcs_tab(dcs_tab)
        self.build_setup_tab(setup_tab)
        tabs.select(right if self.s["camera"].get("name") else setup_tab)   # first run: Setup

        self.status = tk.Label(left, text="starting...", bg=BG, fg=MUTED, font=("Segoe UI", 12, "bold"), anchor="w")
        self.status.pack(fill="x")
        self.video = tk.Label(left, bg="#000")
        self.video.pack()
        self.values = tk.Label(left, text="", bg=BG, fg=FG, font=("Consolas", 11), anchor="w", justify="left")
        self.values.pack(fill="x", pady=(6, 0))
        self.metrics = tk.Label(left, text="", bg=BG, fg=MUTED, font=("Consolas", 10), anchor="w", justify="left")
        self.metrics.pack(fill="x")
        self.graph = tk.Canvas(left, width=640, height=150, bg=PANEL, highlightthickness=0)
        self.graph.pack(pady=(6, 0))
        self.result = tk.Label(left, text="", bg=BG, fg=ACCENT, font=("Segoe UI", 10), anchor="w", justify="left",
                               wraplength=640)
        self.result.pack(fill="x", pady=(6, 0))

        # ---- actions
        f = ttk.LabelFrame(right, text="Actions")
        f.pack(fill="x", pady=(0, 6))
        ttk.Button(f, text="Centre (look straight ahead)", command=lambda: self.engine.command("centre")).pack(fill="x", padx=6, pady=2)
        ttk.Button(f, text="Calibrate my face (20 s, turn slowly)", command=self.calibrate).pack(fill="x", padx=6, pady=2)
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Button(row, text="Still test (10 s)", command=lambda: self.engine.command("test", "still")).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="Talk test (10 s)", command=lambda: self.engine.command("test", "talk")).pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.calib_bar = ttk.Progressbar(f, maximum=1.0)
        self.calib_bar.pack(fill="x", padx=6, pady=(2, 6))

        # ---- pose source
        f = ttk.LabelFrame(right, text="Pose source")
        f.pack(fill="x", pady=(0, 6))
        self.source = tk.StringVar(value=self.s["source"])
        ttk.Radiobutton(f, text="MediaPipe (generic face)", value="mediapipe", variable=self.source, command=self.set_source).pack(anchor="w", padx=6)
        self.rb_rigid = ttk.Radiobutton(f, text="Personal rigid model (calibrate first)", value="rigid", variable=self.source, command=self.set_source)
        self.rb_rigid.pack(anchor="w", padx=6, pady=(0, 4))

        # ---- filter + prediction
        f = ttk.LabelFrame(right, text="Smoothing / prediction")
        f.pack(fill="x", pady=(0, 6))
        self.filt_on = tk.BooleanVar(value=self.s["filter"]["enabled"])
        ttk.Checkbutton(f, text="Filter on", variable=self.filt_on, command=self.set_filter).pack(anchor="w", padx=6)
        self.rot_mc = self.slider(f, "Rotation calm (lower = calmer when still)", 0.05, 3.0, self.s["filter"]["rot"][0], self.set_filter)
        self.rot_b = self.slider(f, "Rotation response (higher = less lag)", 0.0, 0.2, self.s["filter"]["rot"][1], self.set_filter)
        self.pos_mc = self.slider(f, "Position calm", 0.05, 3.0, self.s["filter"]["pos"][0], self.set_filter)
        self.pos_b = self.slider(f, "Position response", 0.0, 0.3, self.s["filter"]["pos"][1], self.set_filter)
        self.pred = self.slider(f, "Prediction (ms ahead, 0 = off)", 0, 60, self.s["predict_ms"], self.set_predict)
        self.gate_deg = self.slider(f, "Still gate - view tremble ignored below (deg, in DCS)", 0.0, 1.0,
                                    self.s["still_gate"]["deg"], self.set_gate)
        self.gate_cm = self.slider(f, "Still gate - position (cm)", 0.0, 0.5, self.s["still_gate"]["cm"], self.set_gate)

        f = ttk.LabelFrame(right, text="Final smoothing (240 Hz, before the curves)")
        f.pack(fill="x", pady=(0, 6))
        sm = self.s["smoothing"]
        self.sm_mode = tk.StringVar(value=sm.get("mode", "accela"))
        ttk.Radiobutton(f, text="Accela - opentrack's default filter (glides, no sticky gate)", value="accela",
                        variable=self.sm_mode, command=self.set_smoothing).pack(anchor="w", padx=6)
        ttk.Radiobutton(f, text="Extrapolate + still gate (the earlier way)", value="extrapolate",
                        variable=self.sm_mode, command=self.set_smoothing).pack(anchor="w", padx=6)
        self.sm_rot = self.slider(f, "Accela rotation smoothing (opentrack default 1.5)", 0.05, 2.5, sm["rot"], self.set_smoothing)
        self.sm_pos = self.slider(f, "Accela position smoothing (default 1.0)", 0.05, 1.5, sm["pos"], self.set_smoothing)
        self.sm_rdz = self.slider(f, "Accela rotation dead zone (deg, default 0.03)", 0.0, 0.2, sm["rot_dz"], self.set_smoothing)
        self.sm_pdz = self.slider(f, "Accela position dead zone (cm, default 0.1)", 0.0, 1.0, sm["pos_dz"], self.set_smoothing)

        # ---- camera
        f = ttk.LabelFrame(right, text="Camera")
        f.pack(fill="x", pady=(0, 6))
        row = tk.Frame(f, bg=PANEL)
        row.pack(anchor="w", padx=6)
        self.fps = tk.IntVar(value=int(self.s["camera"]["fps"]))
        ttk.Radiobutton(row, text="30 fps", value=30, variable=self.fps, command=self.set_camera).pack(side="left")
        ttk.Radiobutton(row, text="60 fps (stable)", value=60, variable=self.fps, command=self.set_camera).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(row, text="90 fps (experimental: 30-90, exposure -7 or shorter)", value=90, variable=self.fps,
                        command=self.set_camera).pack(side="left", padx=(8, 0))
        self.lock = tk.BooleanVar(value=self.s["camera"]["lock"])
        ttk.Checkbutton(f, text="Lock exposure / focus / white balance", variable=self.lock, command=self.set_camera).pack(anchor="w", padx=6)
        self.expo = self.slider(f, "Exposure (lower = darker, faster)", -11, -3, self.s["camera"]["exposure"], self.set_camera, step=1)
        self.gain = self.slider(f, "Gain (brightness, adds noise)", 0, 255, self.s["camera"]["gain"], self.set_camera, step=1)

        # ---- axes
        f = ttk.LabelFrame(right, text="Invert axis")
        f.pack(fill="x")
        row = tk.Frame(f, bg=PANEL)
        row.pack(padx=6, pady=4)
        self.inv = {}
        for i, a in enumerate(AXES):
            v = tk.BooleanVar(value=self.s["sign"][a] < 0)
            self.inv[a] = v
            ttk.Checkbutton(row, text=a, variable=v, command=self.set_sign).grid(row=i // 3, column=i % 3, sticky="w", padx=4)

        if self.s.get("start_minimized"):
            root.iconify()
        self.hotkeys = Hotkeys({"centre": lambda: self.hotkey("centre"),
                                "pause": lambda: self.hotkey("pause")}, self.s["bind"])
        dlog.event("hotkeys: %s" % self.s["bind"])
        self.hotkeys.start()
        self.tick()

    # ---------------------------------------------------------------- Setup tab
    def build_setup_tab(self, tab):
        f = ttk.LabelFrame(tab, text="Camera")
        f.pack(fill="x", pady=(0, 6))
        cams = list_cameras()
        cur = self.s["camera"].get("name") or (cams[0] if cams else "")
        self.cam_name = tk.StringVar(value=cur)
        ttk.Combobox(f, textvariable=self.cam_name, values=cams, state="readonly", width=42).pack(anchor="w", padx=6, pady=(4, 2))
        cm = self.s["camera"]
        self._modes = {mode_label(m): m for m in MODES}
        cur_mode = mode_label((cm["width"], cm["height"], cm["fps"]))
        if cur_mode not in self._modes:
            self._modes[cur_mode] = (cm["width"], cm["height"], cm["fps"])
        self.cam_mode = tk.StringVar(value=cur_mode)
        ttk.Combobox(f, textvariable=self.cam_mode, values=list(self._modes), state="readonly", width=42).pack(anchor="w", padx=6, pady=2)
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Button(row, text="Use this camera / mode", command=self.apply_camera_choice).pack(side="left")
        self.cam_info = tk.Label(row, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 9))
        self.cam_info.pack(side="left", padx=8)
        tk.Label(f, text="The real frame rate shows under the preview ('camera .. fps'). If it is lower than the mode,\n"
                         "the camera cannot do it in this light / mode - pick 30 fps or a smaller size.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8), justify="left").pack(anchor="w", padx=6, pady=(0, 6))

        f = ttk.LabelFrame(tab, text="DCS")
        f.pack(fill="x", pady=(0, 6))
        folders = [str(p) for p in dcs_folders()]
        cur = self.s.get("dcs_folder") or (folders[0] if folders else "")
        self.dcs_folder = tk.StringVar(value=cur)
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Combobox(row, textvariable=self.dcs_folder, values=folders, width=40).pack(side="left")
        ttk.Button(row, text="Browse...", command=self.browse_dcs).pack(side="left", padx=4)
        self.dcs_folder.trace_add("write", lambda *_: self.s.__setitem__("dcs_folder", self.dcs_folder.get()))
        self.s["dcs_folder"] = cur
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Button(row, text="Install / update DCS hook", command=self.install_hook).pack(side="left")
        self.hook_lbl2 = tk.Label(row, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 9))
        self.hook_lbl2.pack(side="left", padx=8)
        tk.Label(f, text="Saved Games\\DCS (or DCS.openbeta ...). The hook is a small Lua file there; DCS must be closed\n"
                         "to install it. Keep opentrack / TrackIR closed when you start DCS.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8), justify="left").pack(anchor="w", padx=6, pady=(0, 6))

        f = ttk.LabelFrame(tab, text="Debug log")
        f.pack(fill="x", pady=(0, 6))
        self.debug_var = tk.BooleanVar(value=bool(self.s.get("debug_log")))
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Checkbutton(row, text="Write a debug log (from the next start)", variable=self.debug_var,
                        command=self.set_debug).pack(side="left")
        ttk.Button(row, text="Open log folder", command=self.open_debug_folder).pack(side="right")
        self.debug_lbl = tk.Label(f, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 8), justify="left", anchor="w")
        self.debug_lbl.pack(fill="x", padx=6, pady=(0, 6))
        self.set_debug(initial=True)

        f = ttk.LabelFrame(tab, text="About")
        f.pack(fill="x")
        tk.Label(f, text="Head Tracker %s - settings in %s" % (VERSION, data_dir()), bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=6, pady=4)

    def set_debug(self, initial=False):
        if not initial:
            self.s["debug_log"] = bool(self.debug_var.get())
        on, want = dlog.enabled, bool(self.s.get("debug_log"))
        if on:
            txt = "Writing: %s%s" % (dlog.path, "\nOff from the next start." if not want else
                                     "\nSend this file for troubleshooting (after closing Head Tracker).")
        else:
            txt = ("Restart Head Tracker to start the log." if want else
                   "For troubleshooting: tick, restart, reproduce the problem, close, send the newest file.")
        self.debug_lbl.config(text=txt, fg=ACCENT if on else (WARN if want else MUTED))

    def open_debug_folder(self):
        d = data_dir() / "debug"
        d.mkdir(parents=True, exist_ok=True)
        _os.startfile(d)

    def hotkey(self, name):
        dlog.event("hotkey " + name)
        self.engine.command(name)

    def _log_dcs(self, title):
        if dlog.enabled:
            lines = dcs_log_lines(self.s.get("dcs_folder") or default_dcs_folder())
            dlog.event("%s: %d HEADTRACK line(s)%s" % (title, len(lines), "".join("\n    " + ln for ln in lines)))

    def apply_camera_choice(self):
        w, h, fps = self._modes[self.cam_mode.get()]
        self.status.config(text="opening camera...", fg=WARN)
        self.root.update_idletasks()
        ok = self.engine.set_camera(name=self.cam_name.get(), width=w, height=h, fps=fps)
        self.fps.set(fps)      # the Tracking tab's fps too - else its next change reopens at its old rate
        self.cam_info.config(text="ok" if ok else "could not open - try another mode", fg=ACCENT if ok else BAD)

    def browse_dcs(self):
        from tkinter import filedialog
        from devices import saved_games_root
        d = filedialog.askdirectory(title="Saved Games\\DCS folder", initialdir=str(saved_games_root()))
        if d:
            self.dcs_folder.set(d)

    # ---------------------------------------------------------------- DCS tab
    def build_dcs_tab(self, tab):
        f = ttk.LabelFrame(tab, text="Output")
        f.pack(fill="x", pady=(0, 6))
        self.output = tk.StringVar(value=self.s.get("output", "dcs"))
        ttk.Radiobutton(f, text="Straight to DCS (HeadTracker hook - no TrackIR, mouse look on pause)",
                        value="dcs", variable=self.output, command=self.set_output).pack(anchor="w", padx=6)
        ttk.Radiobutton(f, text="opentrack (UDP 4242)", value="opentrack", variable=self.output,
                        command=self.set_output).pack(anchor="w", padx=6)
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Button(row, text="Install / update DCS hook", command=self.install_hook).pack(side="left")
        self.hook_lbl = tk.Label(row, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 9))
        self.hook_lbl.pack(side="left", padx=8)
        self.dcs_lbl = tk.Label(f, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left")
        self.dcs_lbl.pack(fill="x", padx=6, pady=(0, 4))

        f = ttk.LabelFrame(tab, text="Buttons (work while DCS has focus)")
        f.pack(fill="x", pady=(0, 6))
        self.bind_lbl = {}
        for name, label in (("pause", "Pause = mouse look"), ("centre", "Centre")):
            row = tk.Frame(f, bg=PANEL)
            row.pack(fill="x", padx=6, pady=2)
            tk.Label(row, text=label, bg=PANEL, fg=FG, width=18, anchor="w").pack(side="left")
            lbl = tk.Label(row, text=describe(self.s["bind"].get(name, "")), bg=PANEL, fg=ACCENT, width=22, anchor="w")
            lbl.pack(side="left")
            self.bind_lbl[name] = lbl
            ttk.Button(row, text="Bind", command=lambda n=name: self.bind(n)).pack(side="left")
            ttk.Button(row, text="Clear", command=lambda n=name: self.set_bind(n, "")).pack(side="left", padx=(4, 0))
        self.pause_btn = ttk.Button(f, text="Pause now", command=lambda: self.engine.command("pause"))
        self.pause_btn.pack(fill="x", padx=6, pady=(2, 6))

        f = ttk.LabelFrame(tab, text="Response curves")
        f.pack(fill="x")
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=4)
        tk.Label(row, text="Axis", bg=PANEL, fg=MUTED).pack(side="left")
        self.curve_axis = tk.StringVar(value="pitch")
        cb = ttk.Combobox(row, textvariable=self.curve_axis, values=list(CURVE_AXES), state="readonly", width=8)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda _e: self.load_curve())
        self.curve_val = tk.Label(row, text="", bg=PANEL, fg=FG, font=("Consolas", 9))
        self.curve_val.pack(side="left", padx=6)
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6)
        self.cv_mirror = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Same curve both directions", variable=self.cv_mirror, command=self.set_mirror).pack(side="left")
        self.cv_side = tk.StringVar(value="pos")
        self.rb_pos = ttk.Radiobutton(row, text="edit +", value="pos", variable=self.cv_side, command=self.load_curve)
        self.rb_neg = ttk.Radiobutton(row, text="edit - (down / right)", value="neg", variable=self.cv_side, command=self.load_curve)
        self.rb_pos.pack(side="left", padx=(10, 0))
        self.rb_neg.pack(side="left", padx=(4, 0))
        self.editor = CurveEditor(f, self.set_points)
        self.editor.pack(padx=6, pady=4)
        tk.Label(f, text="drag points - double-click adds - right-click deletes - green ring = your head now",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=6)
        self.cv = {}
        for key, label, lo, hi in (("deadzone", "Dead zone (deg / cm)", 0.0, 5.0),
                                   ("full_scale", "Full scale = DCS axis end (deg / cm)", 5.0, 360.0)):
            self.cv[key] = self.slider(f, label, lo, hi, 0.0, self.set_curve)
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", padx=6, pady=(2, 6))
        self.cv_inv = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Invert in DCS", variable=self.cv_inv, command=self.set_curve).pack(side="left")
        ttk.Button(row, text="Import from opentrack", command=self.import_ot).pack(side="right")
        ttk.Button(row, text="Reset axis", command=self.reset_curve).pack(side="right", padx=4)
        self.load_curve()

    def _curve(self) -> dict:
        """The current axis' curve, materialised in the settings (so edits persist)."""
        a = self.curve_axis.get()
        cur = merged(self.s.get("curves"))[a]
        self.s.setdefault("curves", {})[a] = cur
        return cur

    def set_mirror(self):
        c = self._curve()
        c["mirror"] = bool(self.cv_mirror.get())
        if not c["mirror"]:
            c["points_neg"] = [list(p) for p in c.get("points_neg") or c["points_pos"]]
        self.load_curve()

    def set_points(self, points):
        c = self._curve()
        side = "points_neg" if (not c["mirror"] and self.cv_side.get() == "neg") else "points_pos"
        c[side] = [list(p) for p in points]

    def reset_curve(self):
        self.s.setdefault("curves", {}).pop(self.curve_axis.get(), None)
        self.load_curve()

    def import_ot(self):
        from tkinter import filedialog
        import os
        guess = os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "Documents", "opentrack-2.3", "default.ini")
        if not os.path.isfile(guess):
            guess = os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "opentrack-2.3", "default.ini")
        path = guess if os.path.isfile(guess) else filedialog.askopenfilename(title="opentrack profile (.ini)",
                                                                                 filetypes=[("opentrack profile", "*.ini")])
        if not path:
            return
        try:
            found = import_opentrack(path)
        except Exception as e:
            self.result.config(text="import failed: %s" % e, fg=BAD)
            return
        for a, d in found.items():
            cur = merged(self.s.get("curves"))[a]
            cur.update(d)
            if cur["mirror"]:
                cur["points_neg"] = [list(p) for p in cur["points_pos"]]
            # the DCS axis end must reach at least the curve's highest output
            cur["full_scale"] = max(cur["full_scale"], max(p[1] for p in cur["points_pos"] + cur["points_neg"]))
            self.s.setdefault("curves", {})[a] = cur
        self.result.config(text="imported opentrack curves for: %s (from %s)" % (", ".join(sorted(found)) or "none", path), fg=ACCENT)
        self.load_curve()

    def set_output(self):
        self.s["output"] = self.output.get()

    def install_hook(self):
        self.result.config(text=install_hook(self.s.get("dcs_folder") or None), fg=ACCENT)
        self._hook_check = 0

    def bind(self, name):
        self.bind_lbl[name].config(text="press a key or button...", fg=WARN)
        self.hotkeys.capture(lambda b: self.root.after(0, self.set_bind, name, b))

    def set_bind(self, name, binding):
        self.s["bind"][name] = binding
        self.hotkeys.set_binding(name, binding)
        self.bind_lbl[name].config(text=describe(binding), fg=ACCENT)

    def load_curve(self):
        a = self.curve_axis.get()
        c = merged(self.s.get("curves"))[a]
        self._loading = True
        for k, var in self.cv.items():
            var.set(c[k])
        self.cv_inv.set(bool(c["invert"]))
        self.cv_mirror.set(bool(c["mirror"]))
        self._loading = False
        for rb in (self.rb_pos, self.rb_neg):
            rb.state(["disabled"] if c["mirror"] else ["!disabled"])
        if c["mirror"]:
            self.cv_side.set("pos")
        pts = c["points_neg"] if (not c["mirror"] and self.cv_side.get() == "neg") else c["points_pos"]
        self.editor.set_curve(pts, c["full_scale"], "cm" if a in ("x", "y", "z") else "deg")

    def set_curve(self):
        if getattr(self, "_loading", False):
            return
        c = self._curve()
        for k, v in self.cv.items():
            c[k] = round(float(v.get()), 3)
        c["invert"] = bool(self.cv_inv.get())
        self.editor.full_scale = c["full_scale"]
        self.editor._ranges()
        self.editor.draw()

    def slider(self, parent, label, lo, hi, value, cb, step=None):
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=6)
        var = tk.DoubleVar(value=value)
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=6)
        val = tk.Label(row, text="", bg=PANEL, fg=FG, width=6, font=("Consolas", 9))
        val.pack(side="right")

        def changed(_=None):
            if step:
                var.set(round(var.get() / step) * step)
            cb()
        ttk.Scale(row, from_=lo, to=hi, variable=var, command=changed, length=230).pack(side="left", fill="x", expand=True)
        var.trace_add("write", lambda *_: val.config(text=f"{var.get():.3g}"))   # also when set from code
        val.config(text=f"{value:.3g}")
        return var

    # ---------------------------------------------------------------- settings -> engine
    def set_source(self):
        self.s["source"] = self.source.get()
        self.engine.command("source")

    def set_filter(self):
        self.s["filter"] = {"enabled": self.filt_on.get(), "rot": [self.rot_mc.get(), self.rot_b.get()],
                            "pos": [self.pos_mc.get(), self.pos_b.get()]}
        self.engine.command("filter")

    def set_predict(self):
        self.s["predict_ms"] = round(self.pred.get())
        self.engine.command("predict")

    def set_smoothing(self):
        self.s["smoothing"] = {"mode": self.sm_mode.get(), "rot": round(self.sm_rot.get(), 3),
                               "pos": round(self.sm_pos.get(), 3), "rot_dz": round(self.sm_rdz.get(), 3),
                               "pos_dz": round(self.sm_pdz.get(), 3)}
        self.engine.command("smoothing")

    def set_gate(self):
        self.s["still_gate"] = {"deg": round(self.gate_deg.get(), 3), "cm": round(self.gate_cm.get(), 3)}
        self.engine.command("gate")

    def set_camera(self):
        # applied 0.6 s after the last change: at 90 fps every change reopens the camera (~1 s)
        if getattr(self, "_cam_job", None):
            self.root.after_cancel(self._cam_job)
        self._cam_job = self.root.after(600, self._apply_camera)

    def _apply_camera(self):
        self._cam_job = None
        kw = dict(fps=int(self.fps.get()), lock=self.lock.get(), exposure=float(round(self.expo.get())),
                  gain=float(round(self.gain.get())))
        if kw == {k: self.s["camera"].get(k) for k in kw}:
            return
        self.status.config(text="reopening camera...", fg=WARN)
        self.root.update_idletasks()
        if not self.engine.set_camera(**kw):
            self.result.config(text="camera could not be reopened with these settings - try 60 fps", fg=BAD)

    def set_sign(self):
        for a, v in self.inv.items():
            self.s["sign"][a] = -1.0 if v.get() else 1.0

    def calibrate(self):
        self.engine.command("calibrate")

    # ---------------------------------------------------------------- refresh
    def tick(self):
        snap = self.engine.snapshot()
        st = snap.get("status", "")
        self.status.config(text=st + ("  -  " + snap["error"] if snap.get("error") else ""),
                           fg={"TRACKING": ACCENT, "HOLD": WARN}.get(st, BAD if st in ("LOST", "NO CAMERA") else MUTED))
        frame = snap.get("frame")
        if frame is not None:
            small = cv2.resize(frame, (640, 360))
            lms = snap.get("lms")
            if lms:
                pts = [(int(lms[i].x * 640), int(lms[i].y * 360)) for i in OUTLINE]
                for p, q in zip(pts, pts[1:]):
                    cv2.line(small, p, q, (120, 220, 80), 1, cv2.LINE_AA)
            img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
            self.video.configure(image=img)
            self.video.image = img
        p = snap.get("pose")
        if p:
            self.values.config(text="yaw %+7.2f   pitch %+7.2f   roll %+7.2f deg\nx   %+7.2f   y     %+7.2f   z    %+7.2f cm"
                               % (p["yaw"], p["pitch"], p["roll"], p["x"], p["y"], p["z"]))
            fit = snap.get("fit_px")
            self.metrics.config(text="camera %.0f fps   tracker %.0f Hz   model %.1f ms   capture->send %.1f ms%s"
                                % (snap["cam_hz"], snap["track_hz"], snap["model_ms"], snap["latency_ms"],
                                   ("   fit %.2f px" % fit) if fit is not None else ""))
        if snap.get("testing"):
            self.result.config(text="%s test running - %s..." % (snap["test_label"],
                               "hold still" if snap["test_label"] == "still" else "hold still and TALK"), fg=WARN)
        elif snap.get("result"):
            self.result.config(text=snap["result"], fg=ACCENT)
        cal = snap.get("calibrating")
        self.calib_bar["value"] = cal if cal is not None else 0
        if cal is not None:
            self.result.config(text="calibrating: turn your head slowly left/right and up/down (%.0f s left)"
                               % (Engine.CALIB_S * (1 - cal)), fg=WARN)
        self.rb_rigid.state(["!disabled"] if snap.get("has_rigid") else ["disabled"])
        # DCS tab
        if not hasattr(self, "_hook_check") or self._hook_check <= 0:
            self._hook_check = 60
            hs = hook_state(self.s.get("dcs_folder") or None)
            for lbl in (self.hook_lbl, self.hook_lbl2):
                lbl.config(text="hook: " + hs, fg=ACCENT if hs == "installed" else WARN)
            # autosave (a crash must not lose curves / bindings)
            js = json.dumps(self.s, sort_keys=True)
            if js != getattr(self, "_saved_js", None):
                if dlog.enabled and getattr(self, "_saved_js", None):
                    dlog.settings_changed(json.loads(self._saved_js), json.loads(js))
                try:
                    save_settings(self.s)
                    self._saved_js = js
                except OSError:
                    pass
        self._hook_check -= 1
        d = snap.get("dcs") or {}
        if self.s.get("output") == "opentrack":
            self.dcs_lbl.config(text="sending to opentrack on UDP 4242", fg=MUTED)
        elif d.get("connected"):
            self.dcs_lbl.config(text="DCS connected - %s - %s" % (d.get("unit") or "menu",
                                "head tracking ON" if d.get("applying") else "mouse look (paused / not tracking)"),
                                fg=ACCENT if d.get("applying") else WARN)
        else:
            self.dcs_lbl.config(text="DCS: no hook answering (DCS not running, or hook not installed yet)", fg=MUTED)
        paused = snap.get("paused")
        self.pause_btn.config(text="RESUME head tracking" if paused else "Pause now (mouse look)")
        if paused and st == "TRACKING":
            self.status.config(text="PAUSED - mouse look", fg=WARN)
        v = (snap.get("view") or {}).get(self.curve_axis.get())
        hv = (snap.get("pose") or {}).get(self.curve_axis.get())
        if v is not None and hv is not None:
            self.curve_val.config(text="head %+6.1f -> view %+6.1f" % (hv, v))
            c = merged(self.s.get("curves"))[self.curve_axis.get()]
            on_side = c["mirror"] or (hv < 0) == (self.cv_side.get() == "neg")
            self.editor.set_live(max(abs(hv) - c["deadzone"], 0.0) if on_side else None)
        self.draw_graph(snap.get("history") or [])
        self.root.after(33, self.tick)

    def draw_graph(self, hist):
        g = self.graph
        g.delete("all")
        W, H = 640, 150
        g.create_line(0, H / 2, W, H / 2, fill="#333")
        if len(hist) < 2:
            return
        t1 = hist[-1][0]
        span = max(max(abs(v) for h in hist for v in h[1:]), 5.0)
        for k, idx in (("yaw", 1), ("pitch", 2), ("roll", 3)):
            pts = []
            for h in hist:
                pts += [W - (t1 - h[0]) / 6.0 * W, H / 2 - h[idx] / span * (H / 2 - 6)]
            g.create_line(*pts, fill=COL[k], width=1.5)
            g.create_text(8 + 50 * (idx - 1), 10, text=k, fill=COL[k], anchor="w", font=("Segoe UI", 9))
        g.create_text(W - 6, 10, text="+-%.0f deg, 6 s" % span, fill=MUTED, anchor="e", font=("Segoe UI", 9))

    def close(self):
        save_settings(self.s)
        dlog.event("closing")
        self.hotkeys.stop()
        self.engine.stop()
        self.engine.join(timeout=2.0)
        self._log_dcs("dcs.log at close")
        dlog.close()
        self.root.destroy()


def main():
    import os
    import traceback
    log = os.environ.get("HEADTRACKER_LOG")
    if log and not frozen():  # pythonw via the dev launcher (the packaged exe redirected at the top already)
        sys.stdout = sys.stderr = open(log, "w", encoding="utf-8", buffering=1)
    if not single_instance():
        ctypes.windll.user32.MessageBoxW(None, "Head Tracker is already running.", "Head Tracker", 0x40)
        return
    try:
        root = tk.Tk()
        root.report_callback_exception = lambda *a: traceback.print_exception(*a)
        App(root)
        root.mainloop()
    except Exception:
        traceback.print_exc()
        ctypes.windll.user32.MessageBoxW(None, "Head Tracker could not start - details in\n%s" % (log or "the console"),
                                         "Head Tracker", 0x10)


if __name__ == "__main__":
    main()
