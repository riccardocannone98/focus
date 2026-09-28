"""Webcam + MediaPipe Face Landmarker.

Privacy: i frame vivono solo in memoria e non vengono mai scritti su disco
né inviati altrove. Di norma dal thread escono solo numeri (GazeSample);
solo mentre la finestra "Definisci area" è aperta viene emessa anche una
copia ridotta del frame per l'anteprima a schermo, poi scartata.
MediaPipe esegue il modello in locale; nessuna chiamata di rete.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from focus_guard.logic.features import iris_circles, is_blinking, raw_gaze_from_landmarks
from focus_guard.logic.area import RawGaze

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GazeSample:
    timestamp: float  # time.monotonic()
    raw: RawGaze | None  # None = volto non rilevato
    blinking: bool = False
    irises: tuple[tuple[float, float, float], ...] = ()  # solo per l'anteprima

    @property
    def face_found(self) -> bool:
        return self.raw is not None


class ModelNotFoundError(FileNotFoundError):
    pass


class FaceTracker:
    """Wrapper di MediaPipe Face Landmarker in modalità VIDEO."""

    def __init__(self, model_path: Path, blink_threshold: float = 0.5) -> None:
        if not model_path.is_file():
            raise ModelNotFoundError(
                f"Modello non trovato: {model_path}. Esegui: python scripts/download_model.py"
            )
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._blink_threshold = blink_threshold
        self._last_ts_ms = -1

    def process(self, rgb: np.ndarray, timestamp: float) -> GazeSample:
        ts_ms = max(int(timestamp * 1000), self._last_ts_ms + 1)  # deve crescere strettamente
        self._last_ts_ms = ts_ms
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, ts_ms)
        if not result.face_landmarks:
            return GazeSample(timestamp, None)

        landmarks = np.array([(p.x, p.y, p.z) for p in result.face_landmarks[0]])
        transform = (
            np.asarray(result.facial_transformation_matrixes[0])
            if result.facial_transformation_matrixes
            else None
        )
        blend = (
            {c.category_name: c.score for c in result.face_blendshapes[0]}
            if result.face_blendshapes
            else None
        )
        height, width = rgb.shape[:2]
        raw = raw_gaze_from_landmarks(landmarks, (width, height), transform)
        return GazeSample(
            timestamp,
            raw,
            is_blinking(blend, self._blink_threshold),
            iris_circles(landmarks, (width, height)),
        )

    def close(self) -> None:
        self._landmarker.close()


class CameraWorker(QThread):
    """Thread di cattura: emette un GazeSample per ogni frame elaborato."""

    sample = pyqtSignal(object)
    preview = pyqtSignal(object)  # np.ndarray RGB ridotto, solo in memoria
    failed = pyqtSignal(str)

    PREVIEW_WIDTH = 320

    MAX_CONSECUTIVE_READ_FAILURES = 30

    def __init__(
        self,
        camera_index: int,
        frame_size: tuple[int, int],
        target_fps: float,
        model_path: Path,
        blink_threshold: float,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._camera_index = camera_index
        self._frame_size = frame_size
        self._period = 1.0 / target_fps
        self._model_path = model_path
        self._blink_threshold = blink_threshold
        self._running = False
        # Anteprima attiva solo mentre la finestra "Definisci area" è aperta
        self.preview_enabled = False

    def stop(self) -> None:
        self._running = False
        self.wait(3000)

    def run(self) -> None:  # eseguito nel thread di cattura
        import cv2

        self._running = True
        try:
            tracker = FaceTracker(self._model_path, self._blink_threshold)
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self._camera_index, backend)
        try:
            if not cap.isOpened():
                self.failed.emit(f"Impossibile aprire la webcam {self._camera_index}")
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_size[1])
            failures = 0
            while self._running:
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    failures += 1
                    if failures >= self.MAX_CONSECUTIVE_READ_FAILURES:
                        self.failed.emit("La webcam non restituisce frame")
                        return
                    self.msleep(50)
                    continue
                failures = 0
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                del frame
                result = tracker.process(rgb, time.monotonic())
                if self.preview_enabled:
                    h, w = rgb.shape[:2]
                    size = (self.PREVIEW_WIDTH, max(1, h * self.PREVIEW_WIDTH // w))
                    self.preview.emit(cv2.resize(rgb, size, interpolation=cv2.INTER_AREA))
                del rgb  # il frame intero non sopravvive a questa iterazione
                self.sample.emit(result)
                remaining = self._period - (time.monotonic() - started)
                if remaining > 0:
                    self.msleep(int(remaining * 1000))
        finally:
            cap.release()
            tracker.close()
