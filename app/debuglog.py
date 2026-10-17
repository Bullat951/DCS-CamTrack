"""Debug log for remote troubleshooting. Off by default; switched on in the Setup tab, it starts writing at the
NEXT program start (so the whole run is in it, from the camera open on). One file per start in
%APPDATA%\\HeadTracker\\debug, the last KEEP kept. In it: system / camera / DCS facts and the settings at
start, everything the program prints (tracebacks too), timestamped events, a health line every few seconds
and the settings changes as diffs. `dlog` does nothing until start() - callers need no checks."""
from __future__ import annotations

import json
import platform
import sys
import threading
import time
from pathlib import Path

from appdirs import data_dir, frozen

KEEP = 5
TRACKERS = ("opentrack.exe", "TrackIR5.exe", "TrackIR.exe", "FaceTrackNoIR.exe", "AITrack.exe")


def flatten(d, prefix: str = "") -> dict:
    """{'a': {'b': 1}} -> {'a.b': 1}; lists stay values."""
    out = {}
    for k, v in (d or {}).items():
        key = prefix + str(k)
        if isinstance(v, dict) and v:
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def settings_diff(old: dict, new: dict) -> list[str]:
    a, b = flatten(old), flatten(new)
    out = []
    for k in sorted(set(a) | set(b)):
        if a.get(k, "<none>") != b.get(k, "<none>"):
            out.append("%s: %s -> %s" % (k, json.dumps(a.get(k, "<none>")), json.dumps(b.get(k, "<none>"))))
    return out


def dcs_log_lines(dcs_folder, tag: str = "HEADTRACK", last: int = 40) -> list[str]:
    """The hook's own lines from the DCS log (the newest `last`)."""
    p = Path(dcs_folder) / "Logs" / "dcs.log" if dcs_folder else None
    if not p or not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if tag in ln][-last:]


class _Tee:
    """stdout / stderr copy into the log (the original stream may be None in the packaged exe)."""

    def __init__(self, orig, log: "DebugLog"):
        self.orig, self.log = orig, log

    def write(self, s):
        if self.orig is not None:
            try:
                self.orig.write(s)
            except (OSError, ValueError):
                pass
        self.log.raw(s)
        return len(s)

    def flush(self):
        if self.orig is not None:
            try:
                self.orig.flush()
            except (OSError, ValueError):
                pass


class DebugLog:
    def __init__(self):
        self.fh = None
        self.path: Path | None = None
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()
        self._bol = True                       # raw output at the beginning of a line

    @property
    def enabled(self) -> bool:
        return self.fh is not None

    def start(self, header: list[str], folder: Path | None = None, keep: int = KEEP, tee: bool = True) -> Path:
        folder = Path(folder) if folder else data_dir() / "debug"
        folder.mkdir(parents=True, exist_ok=True)
        old = sorted(folder.glob("debug-*.log"))
        for f in old[:max(0, len(old) - (keep - 1))]:
            try:
                f.unlink()
            except OSError:
                pass
        self.path = folder / time.strftime("debug-%Y%m%d-%H%M%S.log")
        self.fh = open(self.path, "a", encoding="utf-8", buffering=1)
        self._t0 = time.perf_counter()
        self.fh.write("=== Head Tracker debug log, started %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        for ln in header:
            self.fh.write("  " + ln + "\n")
        self.fh.write("=== events (time, seconds since start) ===\n")
        if tee:
            sys.stdout = _Tee(sys.stdout, self)
            sys.stderr = _Tee(sys.stderr, self)
        return self.path

    def _stamp(self) -> str:
        return "%s %8.3f " % (time.strftime("%H:%M:%S"), time.perf_counter() - self._t0)

    def event(self, msg: str) -> None:
        if self.fh is None:
            return
        with self._lock:
            try:
                if not self._bol:
                    self.fh.write("\n")
                    self._bol = True
                self.fh.write(self._stamp() + msg + "\n")
            except (OSError, ValueError):
                pass

    def raw(self, s: str) -> None:
        """Printed output: each line stamped and marked 'out|'."""
        if self.fh is None or not s:
            return
        with self._lock:
            try:
                for part in s.splitlines(keepends=True):
                    if self._bol:
                        self.fh.write(self._stamp() + "out| ")
                    self.fh.write(part)
                    self._bol = part.endswith("\n")
            except (OSError, ValueError):
                pass

    def settings_changed(self, old: dict, new: dict) -> None:
        for ln in settings_diff(old, new):
            self.event("setting " + ln)

    def close(self) -> None:
        with self._lock:
            if self.fh is not None:
                try:
                    self.fh.write(self._stamp() + "=== log closed ===\n")
                    self.fh.close()
                except (OSError, ValueError):
                    pass
            self.fh = None
        for name in ("stdout", "stderr"):
            s = getattr(sys, name)
            if isinstance(s, _Tee):
                setattr(sys, name, s.orig)


dlog = DebugLog()


def system_header(version: str, settings: dict) -> list[str]:
    """What the other PC looks like - each part guarded, a failing probe must not stop the program."""
    out = ["app %s, %s, python %s" % (version, "packaged exe" if frozen() else "from source", sys.version.split()[0]),
           "windows %s (%s)" % (platform.platform(), platform.machine()),
           "exe %s" % sys.executable, "data %s" % data_dir()]
    try:
        from devices import list_cameras
        cams = list_cameras()
        out.append("cameras (DirectShow order): %s" % (", ".join("%d=%s" % (i, c) for i, c in enumerate(cams)) or "none"))
    except Exception as e:
        out.append("cameras: probe failed %r" % e)
    try:
        from devices import camera_privacy
        out.append("camera privacy (None = not set = allowed): %s" % camera_privacy())
    except Exception as e:
        out.append("camera privacy: probe failed %r" % e)
    try:
        from dcsout import default_dcs_folder, hook_state
        from devices import dcs_folders
        out.append("dcs folders: %s" % (", ".join(str(p) for p in dcs_folders()) or "none"))
        folder = settings.get("dcs_folder") or default_dcs_folder()
        out.append("dcs folder used: %s, hook: %s" % (folder, hook_state(folder)))
    except Exception as e:
        out.append("dcs: probe failed %r" % e)
    try:
        from procs import process_running
        out.append("running: DCS %s; other trackers: %s" % (
            "yes" if process_running("DCS.exe") else "no",
            ", ".join(t for t in TRACKERS if process_running(t)) or "none"))
    except Exception as e:
        out.append("processes: probe failed %r" % e)
    out.append("settings: " + json.dumps(settings, sort_keys=True))
    return out
