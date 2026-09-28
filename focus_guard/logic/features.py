"""Estrazione dello sguardo grezzo dai landmark di MediaPipe Face Landmarker.

Modulo puro (solo numpy): non conosce webcam né MediaPipe, così si testa
con landmark sintetici.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from focus_guard.logic.geometry import RawGaze

# Indici del modello a 478 punti (468 volto + 10 iride)
EYE_CORNERS = ((33, 133), (362, 263))
IRIS_CENTERS = (468, 473)
NUM_LANDMARKS_WITH_IRIS = 478
BLINK_BLENDSHAPES = ("eyeBlinkLeft", "eyeBlinkRight")


def _iris_ratio(corner_a: np.ndarray, corner_b: np.ndarray, iris: np.ndarray) -> tuple[float, float]:
    """Posizione dell'iride nel sistema dell'occhio, normalizzata sulla larghezza.

    x: 0 = angolo più a sinistra nell'immagine, 1 = più a destra.
    y: perpendicolare all'asse degli angoli, positiva verso il basso.
    """
    left, right = (corner_a, corner_b) if corner_a[0] <= corner_b[0] else (corner_b, corner_a)
    axis = right - left
    width = float(np.hypot(*axis))
    if width < 1e-6:
        raise ValueError("occhio degenere")
    ex = axis / width
    ey = np.array([-ex[1], ex[0]])
    rel = iris - left
    return float(rel @ ex) / width, float(rel @ ey) / width


def head_angles(matrix: np.ndarray | None) -> tuple[float, float]:
    """(yaw, pitch) in gradi dalla matrice di trasformazione 4x4 del volto."""
    if matrix is None:
        return 0.0, 0.0
    r = np.asarray(matrix, dtype=float)[:3, :3]
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    yaw = math.degrees(math.atan2(-r[2, 0], math.hypot(r[2, 1], r[2, 2])))
    return yaw, pitch


def raw_gaze_from_landmarks(
    landmarks: np.ndarray,
    frame_size: tuple[int, int],
    transform: np.ndarray | None = None,
) -> RawGaze | None:
    """Landmark normalizzati (N, >=2) -> (iris_x, iris_y, yaw, pitch).

    Restituisce None se mancano i punti dell'iride o la geometria è degenere.
    """
    pts = np.asarray(landmarks, dtype=float)
    if pts.ndim != 2 or pts.shape[0] < NUM_LANDMARKS_WITH_IRIS:
        return None
    width, height = frame_size
    px = pts[:, :2] * np.array([width, height], dtype=float)

    eyes = [(px[a], px[b]) for a, b in EYE_CORNERS]
    irises = [px[i] for i in IRIS_CENTERS]
    # Abbina ogni iride all'occhio più vicino: non dipende dalla convenzione
    # destra/sinistra degli indici MediaPipe.
    mids = [(a + b) / 2 for a, b in eyes]
    direct = np.hypot(*(irises[0] - mids[0])) + np.hypot(*(irises[1] - mids[1]))
    swapped = np.hypot(*(irises[0] - mids[1])) + np.hypot(*(irises[1] - mids[0]))
    if swapped < direct:
        irises.reverse()

    try:
        ratios = [_iris_ratio(a, b, iris) for (a, b), iris in zip(eyes, irises)]
    except ValueError:
        return None
    iris_x = sum(r[0] for r in ratios) / 2
    iris_y = sum(r[1] for r in ratios) / 2
    yaw, pitch = head_angles(transform)
    return iris_x, iris_y, yaw, pitch


def is_blinking(blendshapes: Mapping[str, float] | None, threshold: float) -> bool:
    if not blendshapes:
        return False
    return any(blendshapes.get(name, 0.0) >= threshold for name in BLINK_BLENDSHAPES)


class GazeSmoother:
    """EMA sullo sguardo grezzo; durante un battito di ciglia mantiene l'ultimo valore."""

    def __init__(self, alpha: float) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha deve essere in (0, 1]")
        self.alpha = alpha
        self._state: np.ndarray | None = None

    def reset(self) -> None:
        self._state = None

    def update(self, raw: Sequence[float] | None, blinking: bool = False) -> RawGaze | None:
        if raw is None:
            # Volto perso: si riparte da zero quando ricompare.
            self._state = None
            return None
        if blinking:
            return self._as_tuple()
        value = np.asarray(raw, dtype=float)
        if self._state is None:
            self._state = value
        else:
            self._state = self.alpha * value + (1 - self.alpha) * self._state
        return self._as_tuple()

    def _as_tuple(self) -> RawGaze | None:
        if self._state is None:
            return None
        return tuple(float(v) for v in self._state)  # type: ignore[return-value]
