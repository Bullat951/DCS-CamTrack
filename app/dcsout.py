"""Output straight to DCS through the HeadTracker hook (no TrackIR / opentrack / driver).

Sends 'HTK1 <seq> <active> yaw pitch roll x y z' (values -1..1) to 127.0.0.1:4245 and listens for the
hook's 1 Hz status 'HTKS <version> <unit> <applying> <frames>' on 4246. Also installs the hook file
into Saved Games (only while DCS is not running - the standing rule).
"""
from __future__ import annotations

import filecmp
import shutil
import socket
import threading
import time
from pathlib import Path

from appdirs import resource_dir

HOOK_SRC = resource_dir() / "dcs" / "HeadTracker-hook.lua"
OUT_PORT, STATUS_PORT = 4245, 4246


def default_dcs_folder() -> Path:
    from devices import dcs_folders, saved_games_root
    found = dcs_folders()
    return found[0] if found else saved_games_root() / "DCS"


def dcs_running() -> bool:
    from procs import process_running
    return process_running("DCS.exe")


def hook_state(dcs_folder: Path | str | None = None) -> str:
    """'installed' | 'outdated' | 'missing' | 'folder not found' for a Saved Games\\DCS* folder."""
    base = Path(dcs_folder) if dcs_folder else default_dcs_folder()
    if not base.is_dir():
        return "folder not found"
    dst = base / "Scripts" / "Hooks" / HOOK_SRC.name
    if not dst.is_file():
        return "missing"
    return "installed" if filecmp.cmp(HOOK_SRC, dst, shallow=False) else "outdated"


def install_hook(dcs_folder: Path | str | None = None) -> str:
    if dcs_running():
        return "DCS is running - close it first (it loads hooks only at start)"
    base = Path(dcs_folder) if dcs_folder else default_dcs_folder()
    if not base.is_dir():
        return "DCS Saved Games folder not found: %s - start DCS once, or pick the folder" % base
    d = base / "Scripts" / "Hooks"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HOOK_SRC, d / HOOK_SRC.name)
    return "hook installed in %s - it loads at the next DCS start" % base


def pack(seq: int, active: bool, vals: list[float]) -> bytes:
    return ("HTK1 %d %d %s" % (seq, 1 if active else 0, " ".join("%.5f" % v for v in vals))).encode()


class DcsOutput:
    def __init__(self, status_port: int = STATUS_PORT):
        self.status_port = status_port
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0
        self.status = {"seen": 0.0, "version": "", "unit": "", "applying": False, "frames": 0}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True, name="dcs-status")
        self._thread.start()

    def send(self, vals: list[float], active: bool) -> None:
        self.seq += 1
        try:
            self.out.sendto(pack(self.seq, active, vals), ("127.0.0.1", OUT_PORT))
        except OSError:
            pass

    def _listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", self.status_port))
        except OSError:
            return
        s.settimeout(0.5)
        while not self._stop.is_set():
            try:
                data, _ = s.recvfrom(512)
            except (socket.timeout, OSError):
                continue
            p = data.decode(errors="replace").split()
            if len(p) == 5 and p[0] == "HTKS":
                self.status = {"seen": time.time(), "version": p[1], "unit": "" if p[2] == "-" else p[2],
                               "applying": p[3] == "1", "frames": int(p[4]) if p[4].isdigit() else 0}
        s.close()

    def connected(self) -> bool:
        return time.time() - self.status["seen"] < 3.0

    def close(self):
        self._stop.set()
        self.out.close()
