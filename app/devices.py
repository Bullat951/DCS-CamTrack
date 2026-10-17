"""Cameras (by name, in DirectShow order = OpenCV's index) and DCS Saved Games folders."""
from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

# resolution x fps choices; > 60 fps uses the Media Foundation path (only some cameras offer it)
MODES = [(1280, 720, 60), (1280, 720, 30), (640, 480, 60), (640, 480, 30), (1920, 1080, 30), (1280, 720, 90)]


def mode_label(m) -> str:
    w, h, f = m
    return "%dx%d @ %d fps%s" % (w, h, f, " (experimental)" if f > 60 else "")


def list_cameras() -> list[str]:
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())
    except Exception:
        return []


def camera_index(name: str, fallback: int = 0) -> int:
    if name:
        cams = list_cameras()
        if name in cams:
            return cams.index(name)
    return fallback


# ---------------------------------------------------------------- Saved Games
_FOLDERID_SavedGames = uuid.UUID("{4C5C32FF-BB9D-43b0-B5B4-2D72E54EAAA4}")


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def saved_games_root() -> Path:
    """The real Saved Games folder (it can be moved to OneDrive / another drive)."""
    try:
        g = _GUID()
        b = _FOLDERID_SavedGames.bytes_le
        ctypes.memmove(ctypes.byref(g), b, 16)
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
            path = Path(p.value)
            ctypes.windll.ole32.CoTaskMemFree(p)
            return path
    except Exception:
        pass
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Saved Games"


def dcs_folders() -> list[Path]:
    """Saved Games\\DCS* folders that DCS has used (have Config or Scripts) - DCS, DCS.openbeta, ..."""
    root = saved_games_root()
    out = []
    try:
        for d in sorted(root.iterdir()):
            if d.is_dir() and d.name.lower().startswith("dcs") and ((d / "Config").is_dir() or (d / "Scripts").is_dir()):
                out.append(d)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- camera privacy
_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"


def camera_privacy() -> dict:
    """Windows' camera privacy switches: {'device': .., 'user': .., 'desktop_apps': ..} = 'Allow' / 'Deny' / None
    (None = not set = allowed). 'desktop_apps' is 'Let desktop apps access your camera' - this program's switch."""
    import winreg
    out = {}
    for key, hive, sub in (("device", winreg.HKEY_LOCAL_MACHINE, _CONSENT), ("user", winreg.HKEY_CURRENT_USER, _CONSENT),
                           ("desktop_apps", winreg.HKEY_CURRENT_USER, _CONSENT + r"\NonPackaged")):
        try:
            with winreg.OpenKey(hive, sub) as k:
                out[key] = str(winreg.QueryValueEx(k, "Value")[0])
        except OSError:
            out[key] = None
    return out


def privacy_blocks(p: dict) -> list[str]:
    return [k for k, v in p.items() if (v or "").lower() == "deny"]
