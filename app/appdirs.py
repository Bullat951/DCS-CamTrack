"""Where things live. Resources (face model, DCS hook) ship with the program - in the PyInstaller bundle or
next to the sources; user data (settings, personal face model, test results, log) is per user in
%APPDATA%\\HeadTracker, so an update or a re-unzip never overwrites it."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

DEV_ROOT = Path(__file__).resolve().parent.parent


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", DEV_ROOT))


def data_dir() -> Path:
    d = Path(os.environ.get("APPDATA", str(Path.home()))) / "HeadTracker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def migrate_dev_data() -> list[str]:
    """First run: bring the development folder's settings / personal face model / results over."""
    moved = []
    d = data_dir()
    for src, dst in ((DEV_ROOT / "settings.json", d / "settings.json"),
                     (DEV_ROOT / "models" / "personal_face.npz", d / "personal_face.npz"),
                     (DEV_ROOT / "test_results.txt", d / "test_results.txt")):
        # missing -> copy; and from the dev folder (not the packaged exe) also when the old version saved newer
        if src.is_file() and (not dst.exists() or (not frozen() and src.stat().st_mtime > dst.stat().st_mtime + 1)):
            shutil.copyfile(src, dst)
            moved.append(dst.name)
    return moved
