"""Mappatura dello sguardo nelle coordinate dell'area calibrata.

Lo sguardo grezzo è una tupla (iris_x, iris_y, yaw_deg, pitch_deg). Viene
combinato in un punto 2D nello "spazio feature" e poi proiettato con
un'omografia sul quadrato unitario: (0,0) angolo in alto a sinistra
dell'area, (1,1) angolo in basso a destra.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from focus_guard.config import CORNER_NAMES

RawGaze = tuple[float, float, float, float]

UNIT_SQUARE = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))  # stesso ordine di CORNER_NAMES
MIN_QUAD_AREA = 1e-5
_EPS = 1e-9


class CalibrationError(ValueError):
    """Calibrazione degenere (angoli coincidenti, allineati o incrociati)."""


def compute_homography(
    src: Sequence[Sequence[float]], dst: Sequence[Sequence[float]]
) -> np.ndarray:
    """Omografia 3x3 che porta i 4 punti src sui 4 punti dst (h33 = 1)."""
    if len(src) != 4 or len(dst) != 4:
        raise ValueError("servono esattamente 4 coppie di punti")
    a = np.zeros((8, 8))
    b = np.zeros(8)
    for i, ((x, y), (u, v)) in enumerate(zip(src, dst)):
        a[2 * i] = [x, y, 1, 0, 0, 0, -u * x, -u * y]
        a[2 * i + 1] = [0, 0, 0, x, y, 1, -v * x, -v * y]
        b[2 * i] = u
        b[2 * i + 1] = v
    try:
        h = np.linalg.solve(a, b)
    except np.linalg.LinAlgError as exc:
        raise CalibrationError("punti di calibrazione degeneri") from exc
    hom = np.append(h, 1.0).reshape(3, 3)
    # Normalizza il segno: w > 0 sui punti sorgente, così un w <= 0 indica
    # un punto oltre l'orizzonte proiettivo (quindi molto fuori area).
    if (hom @ np.array([src[0][0], src[0][1], 1.0]))[2] < 0:
        hom = -hom
    return hom


def apply_homography(h: np.ndarray, point: Sequence[float]) -> tuple[float, float] | None:
    """Proietta un punto; None se cade oltre la linea all'infinito."""
    x, y = point
    u, v, w = h @ np.array([x, y, 1.0])
    if w < _EPS:
        return None
    return float(u / w), float(v / w)


def validate_quad(points: Sequence[Sequence[float]]) -> None:
    """Il quadrilatero deve essere convesso e non degenere."""
    pts = np.asarray(points, dtype=float)
    crosses = []
    for i in range(4):
        p0, p1, p2 = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        e1, e2 = p1 - p0, p2 - p1
        crosses.append(e1[0] * e2[1] - e1[1] * e2[0])
    if not (all(c > 0 for c in crosses) or all(c < 0 for c in crosses)):
        raise CalibrationError(
            "gli angoli non formano un quadrilatero convesso: ripeti la calibrazione"
        )
    x, y = pts[:, 0], pts[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    if area < MIN_QUAD_AREA:
        raise CalibrationError("area calibrata troppo piccola: ripeti la calibrazione")


def signed_distance(u: float, v: float) -> float:
    """Distanza dal bordo del quadrato unitario: >0 fuori (euclidea), <0 dentro."""
    dx = max(-u, 0.0, u - 1.0)
    dy = max(-v, 0.0, v - 1.0)
    if dx > 0.0 or dy > 0.0:
        return math.hypot(dx, dy)
    return -min(u, 1.0 - u, v, 1.0 - v)


def _axis_sign(iris_span: float, head_span: float) -> float:
    """+1 se iride e testa si muovono nello stesso verso, -1 altrimenti."""
    return -1.0 if iris_span * head_span < 0 else 1.0


@dataclass(frozen=True)
class CalibrationModel:
    homography: np.ndarray
    head_weight: float
    sign_x: float
    sign_y: float

    @classmethod
    def from_corners(
        cls, corners: Mapping[str, Sequence[float]], head_weight: float
    ) -> "CalibrationModel":
        try:
            raw = np.array([corners[name] for name in CORNER_NAMES], dtype=float)
        except KeyError as exc:
            raise CalibrationError(f"angolo mancante: {exc.args[0]}") from exc
        if raw.shape != (4, 4) or not np.all(np.isfinite(raw)):
            raise CalibrationError("valori di calibrazione non validi")

        tl, tr, br, bl = raw
        # Il verso con cui la testa contribuisce viene dedotto dai dati:
        # evita di dipendere dalla convenzione di segno di MediaPipe.
        sign_x = _axis_sign(
            (tr[0] + br[0] - tl[0] - bl[0]) / 2, (tr[2] + br[2] - tl[2] - bl[2]) / 2
        )
        sign_y = _axis_sign(
            (bl[1] + br[1] - tl[1] - tr[1]) / 2, (bl[3] + br[3] - tl[3] - tr[3]) / 2
        )
        partial = cls(np.eye(3), head_weight, sign_x, sign_y)
        feats = [partial.feature(tuple(r)) for r in raw]
        validate_quad(feats)
        return cls(compute_homography(feats, UNIT_SQUARE), head_weight, sign_x, sign_y)

    def feature(self, raw: RawGaze) -> tuple[float, float]:
        iris_x, iris_y, yaw, pitch = raw
        return (
            iris_x + self.head_weight * self.sign_x * yaw,
            iris_y + self.head_weight * self.sign_y * pitch,
        )

    def to_area(self, raw: RawGaze) -> tuple[float, float] | None:
        """Coordinate nell'area: (0,0) alto-sinistra, (1,1) basso-destra."""
        return apply_homography(self.homography, self.feature(raw))

    def distance(self, raw: RawGaze) -> float:
        uv = self.to_area(raw)
        if uv is None:
            return math.inf
        return signed_distance(*uv)
