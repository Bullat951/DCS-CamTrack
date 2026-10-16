"""MediaPipe face landmarker -> 4x4 head transform per frame (VIDEO mode: it tracks the face between
frames, re-detecting only when lost - faster and steadier than detecting every frame)."""
from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from appdirs import resource_dir

MODEL = resource_dir() / "models" / "face_landmarker.task"


class FaceTracker:
    def __init__(self, model: Path = MODEL, min_conf: float = 0.5):
        opts = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=min_conf,
            min_face_presence_confidence=min_conf,
            min_tracking_confidence=min_conf,
            output_facial_transformation_matrixes=True,
        )
        self.lm = mp.tasks.vision.FaceLandmarker.create_from_options(opts)
        self._last_ms = -1

    def process(self, frame_bgr: np.ndarray, t_sec: float):
        """(4x4 transform or None, landmarks or None)."""
        ms = int(t_sec * 1000)
        if ms <= self._last_ms:
            ms = self._last_ms + 1  # VIDEO mode needs increasing timestamps
        self._last_ms = ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        res = self.lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
        if not res.facial_transformation_matrixes:
            return None, None
        m = np.array(res.facial_transformation_matrixes[0], dtype=np.float64).reshape(4, 4)
        return m, res.face_landmarks[0]

    def close(self):
        self.lm.close()
