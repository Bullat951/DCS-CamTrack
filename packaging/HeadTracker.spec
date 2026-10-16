# PyInstaller spec - portable one-folder build of Head Tracker (run scripts\build.ps1, not this directly)
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
APP = ROOT / "app"

datas = [
    (str(ROOT / "models" / "face_landmarker.task"), "models"),
    (str(ROOT / "dcs" / "HeadTracker-hook.lua"), "dcs"),
]
datas += collect_data_files("mediapipe", includes=["**/*.binarypb", "**/*.tflite", "**/*.txt"])
binaries = collect_dynamic_libs("mediapipe") + collect_dynamic_libs("cv2")
hidden = (collect_submodules("winrt") + collect_submodules("pygrabber") + collect_submodules("comtypes")
          + ["PIL.ImageTk", "PIL._tkinter_finder"])

a = Analysis(
    [str(APP / "ui.py")],
    pathex=[str(APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    # (not matplotlib: mediapipe.tasks.vision imports it at load time)
    excludes=["IPython", "pytest", "tkinter.test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Head Tracker",
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Head Tracker")
