"""Area di lavoro come rettangolo sulla "mappa dello sguardo".

Lo sguardo grezzo (iris_x, iris_y, yaw_deg, pitch_deg) diventa un punto 2D
della mappa:

    gx = -(iris_x + head_weight * sign_x * yaw)     # ribaltato: destra = destra
    gy =   iris_y + head_weight * sign_y * pitch    # verso il basso = giù

La webcam non è specchiata, quindi guardando a destra l'iride si sposta a
sinistra nell'immagine: il segno meno rende la mappa intuitiva. sign_x e
sign_y indicano con che verso la rotazione della testa si somma all'iride e
vengono stimati dai dati (correlazione nei campioni registrati).

Il rettangolo si ottiene dai percentili dei campioni raccolti durante la
"registrazione libera". Le coordinate normalizzate (u, v) valgono 0..1
dentro l'area, e signed_distance restituisce la stessa distanza con segno
usata dalla macchina a stati (soglia, ritardo, isteresi).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Mapping, Sequence

import numpy as np

from focus_guard.config import CORNER_NAMES

RawGaze = tuple[float, float, float, float]

MIN_SAMPLES = 30
MIN_SIZE = 0.01  # lato minimo del rettangolo (unità della mappa)
MIN_CORRELATION = 0.3  # sotto questa soglia il verso della testa non viene stimato
_MIN_STD = 1e-6


class AreaError(ValueError):
    """Impossibile costruire un'area valida."""


def signed_distance(u: float, v: float) -> float:
    """Distanza dal bordo del quadrato unitario: >0 fuori (euclidea), <0 dentro."""
    dx = max(-u, 0.0, u - 1.0)
    dy = max(-v, 0.0, v - 1.0)
    if dx > 0.0 or dy > 0.0:
        return math.hypot(dx, dy)
    return -min(u, 1.0 - u, v, 1.0 - v)


@dataclass(frozen=True)
class GazeMapper:
    """Converte lo sguardo grezzo in un punto della mappa."""

    head_weight: float = 0.007
    sign_x: float = 1.0
    sign_y: float = 1.0

    def map(self, raw: Sequence[float]) -> tuple[float, float]:
        iris_x, iris_y, yaw, pitch = raw
        return (
            -(iris_x + self.head_weight * self.sign_x * yaw),
            iris_y + self.head_weight * self.sign_y * pitch,
        )


@dataclass(frozen=True)
class AreaModel:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    head_weight: float = 0.007
    sign_x: float = 1.0
    sign_y: float = 1.0

    def __post_init__(self) -> None:
        values = (self.x_min, self.y_min, self.x_max, self.y_max, self.head_weight)
        if not all(math.isfinite(v) for v in values):
            raise AreaError("valori dell'area non finiti")
        if self.x_max - self.x_min < MIN_SIZE or self.y_max - self.y_min < MIN_SIZE:
            raise AreaError("area troppo piccola")
        if self.sign_x not in (-1.0, 1.0) or self.sign_y not in (-1.0, 1.0):
            raise AreaError("sign_x e sign_y devono valere +1 o -1")

    @property
    def mapper(self) -> GazeMapper:
        return GazeMapper(self.head_weight, self.sign_x, self.sign_y)

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return self.x_min, self.y_min, self.x_max, self.y_max

    def with_rect(self, rect: Sequence[float]) -> "AreaModel":
        x0, y0, x1, y1 = rect
        return replace(self, x_min=x0, y_min=y0, x_max=x1, y_max=y1)

    def normalize(self, point: Sequence[float]) -> tuple[float, float]:
        gx, gy = point
        return (
            (gx - self.x_min) / (self.x_max - self.x_min),
            (gy - self.y_min) / (self.y_max - self.y_min),
        )

    def point_distance(self, point: Sequence[float]) -> float:
        return signed_distance(*self.normalize(point))

    def distance(self, raw: Sequence[float]) -> float:
        """Distanza con segno dello sguardo dal bordo: >0 fuori, <0 dentro."""
        return self.point_distance(self.mapper.map(raw))

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, float]) -> "AreaModel":
        try:
            return cls(**{k: float(data[k]) for k in cls.__dataclass_fields__})
        except KeyError as exc:
            raise AreaError(f"chiave mancante nell'area: {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise AreaError(f"area non valida: {exc}") from exc


def estimate_head_sign(iris: np.ndarray, head: np.ndarray, default: float) -> float:
    """Verso della testa rispetto all'iride stimato dalla correlazione.

    Quando si sposta lo sguardo su un'area, occhi e testa ruotano nello
    stesso verso: il segno della correlazione dice come combinarli. Se la
    correlazione è debole (es. testa ferma) si mantiene il default.
    """
    if iris.std() < _MIN_STD or head.std() < _MIN_STD:
        return default
    r = float(np.corrcoef(iris, head)[0, 1])
    if not math.isfinite(r) or abs(r) < MIN_CORRELATION:
        return default
    return 1.0 if r > 0 else -1.0


def build_area_from_samples(
    samples: Sequence[Sequence[float]],
    head_weight: float,
    percentiles: tuple[float, float] = (5.0, 95.0),
    default_signs: tuple[float, float] = (1.0, 1.0),
) -> AreaModel:
    """Rettangolo dai campioni della registrazione libera, outlier esclusi."""
    lo, hi = percentiles
    if not 0.0 <= lo < hi <= 100.0:
        raise AreaError("percentili non validi")
    data = np.asarray(samples, dtype=float)
    if data.size == 0:
        data = data.reshape(0, 4)
    if data.ndim != 2 or data.shape[1] != 4:
        raise AreaError("campioni non validi")
    data = data[np.all(np.isfinite(data), axis=1)]
    if len(data) < MIN_SAMPLES:
        raise AreaError(
            f"campioni insufficienti ({len(data)}/{MIN_SAMPLES}): "
            "controlla che il volto sia ben visibile"
        )
    sign_x = estimate_head_sign(data[:, 0], data[:, 2], default_signs[0])
    sign_y = estimate_head_sign(data[:, 1], data[:, 3], default_signs[1])
    mapper = GazeMapper(head_weight, sign_x, sign_y)
    points = np.array([mapper.map(row) for row in data])
    x0, x1 = np.percentile(points[:, 0], [lo, hi])
    y0, y1 = np.percentile(points[:, 1], [lo, hi])
    if x1 - x0 < MIN_SIZE or y1 - y0 < MIN_SIZE:
        raise AreaError(
            "area troppo piccola: durante la registrazione muovi lo sguardo "
            "su tutta la zona di lavoro"
        )
    return AreaModel(float(x0), float(y0), float(x1), float(y1), head_weight, sign_x, sign_y)


def area_from_legacy_corners(
    corners: Mapping[str, Sequence[float]], head_weight: float
) -> AreaModel:
    """Converte la vecchia calibrazione a 4 angoli nel rettangolo equivalente."""
    try:
        tl, tr, br, bl = (np.asarray(corners[n], dtype=float) for n in CORNER_NAMES)
    except KeyError as exc:
        raise AreaError(f"angolo mancante: {exc.args[0]}") from exc

    def axis_sign(iris_span: float, head_span: float) -> float:
        return -1.0 if iris_span * head_span < 0 else 1.0

    sign_x = axis_sign((tr[0] + br[0] - tl[0] - bl[0]) / 2, (tr[2] + br[2] - tl[2] - bl[2]) / 2)
    sign_y = axis_sign((bl[1] + br[1] - tl[1] - tr[1]) / 2, (bl[3] + br[3] - tl[3] - tr[3]) / 2)
    mapper = GazeMapper(head_weight, sign_x, sign_y)
    points = np.array([mapper.map(c) for c in (tl, tr, br, bl)])
    x0, y0 = points.min(axis=0)
    x1, y1 = points.max(axis=0)
    return AreaModel(float(x0), float(y0), float(x1), float(y1), head_weight, sign_x, sign_y)


# --- ritocco con il mouse (funzioni pure, in unità della mappa o pixel) ---

HANDLES = (
    "top_left", "top_right", "bottom_left", "bottom_right",
    "left", "right", "top", "bottom", "move",
)


def hit_test(
    rect: Sequence[float], x: float, y: float, tolerance: float
) -> str | None:
    """Quale parte del rettangolo (left, top, right, bottom) si trova sotto (x, y)."""
    left, top, right, bottom = rect
    in_x = left - tolerance <= x <= right + tolerance
    in_y = top - tolerance <= y <= bottom + tolerance
    if not (in_x and in_y):
        return None
    near_l = abs(x - left) <= tolerance
    near_r = abs(x - right) <= tolerance
    near_t = abs(y - top) <= tolerance
    near_b = abs(y - bottom) <= tolerance
    if near_t and near_l:
        return "top_left"
    if near_t and near_r:
        return "top_right"
    if near_b and near_l:
        return "bottom_left"
    if near_b and near_r:
        return "bottom_right"
    if near_l:
        return "left"
    if near_r:
        return "right"
    if near_t:
        return "top"
    if near_b:
        return "bottom"
    return "move"


def apply_drag(
    rect: Sequence[float], handle: str, dx: float, dy: float, min_size: float = MIN_SIZE
) -> tuple[float, float, float, float]:
    """Nuovo rettangolo dopo aver trascinato una maniglia di (dx, dy).

    I bordi non possono scavalcare quello opposto: vengono fermati alla
    dimensione minima.
    """
    if handle not in HANDLES:
        raise ValueError(f"maniglia sconosciuta: {handle}")
    x0, y0, x1, y1 = rect
    if handle == "move":
        return x0 + dx, y0 + dy, x1 + dx, y1 + dy
    if "left" in handle:
        x0 = min(x0 + dx, x1 - min_size)
    if "right" in handle:
        x1 = max(x1 + dx, x0 + min_size)
    if "top" in handle:
        y0 = min(y0 + dy, y1 - min_size)
    if "bottom" in handle:
        y1 = max(y1 + dy, y0 + min_size)
    return x0, y0, x1, y1


def fit_view(
    rect: Sequence[float], factor: float = 2.5, min_span: tuple[float, float] = (0.3, 0.2)
) -> tuple[float, float, float, float]:
    """Porzione di mappa da mostrare: il rettangolo al centro con margine attorno."""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w = max((x1 - x0) * factor, min_span[0]) / 2
    half_h = max((y1 - y0) * factor, min_span[1]) / 2
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h
