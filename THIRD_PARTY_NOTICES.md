# Third-party software

DCS-CamTrack itself is MIT licensed (see `LICENSE`). It uses and, in the release zip, redistributes:

| Component | License | Notes |
|---|---|---|
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) (Google) | Apache 2.0 | face landmark tracking |
| MediaPipe **Face Landmarker** model (`models/face_landmarker.task`, Google) | Apache 2.0 | unmodified, from Google's model storage |
| [OpenCV](https://opencv.org) (`opencv-python`, `opencv-contrib-python`) | Apache 2.0 | camera capture, image processing, solvePnP |
| [NumPy](https://numpy.org) | BSD-3-Clause | |
| [Pillow](https://python-pillow.org) | MIT-CMU (HPND) | preview image in the window |
| [Matplotlib](https://matplotlib.org) | PSF-based (Matplotlib license) | imported by MediaPipe |
| [pygrabber](https://github.com/andreaschiavinato/python_grabber) | MIT | camera names (DirectShow) |
| [comtypes](https://github.com/enthought/comtypes) | MIT | used by pygrabber |
| [PyWinRT](https://github.com/pywinrt/pywinrt) (`winrt-*`) | MIT | camera controls through Windows' camera API |
| [Python](https://www.python.org) 3.14 | PSF License | bundled interpreter |
| [PyInstaller](https://pyinstaller.org) bootloader | GPL-2.0 with the PyInstaller exception | the exception allows distributing the bundled program under its own license |
| Microsoft Visual C++ runtime DLLs | Microsoft redistributable | app-local copies, so a fresh Windows works |

The full license texts of the bundled Python packages ship inside the release zip
(`_internal\*.dist-info\`). DCS World is a trademark of Eagle Dynamics; this project is not affiliated with it.
