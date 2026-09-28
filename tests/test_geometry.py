import math

import numpy as np
import pytest

from focus_guard.logic.geometry import (
    UNIT_SQUARE,
    CalibrationError,
    CalibrationModel,
    apply_homography,
    compute_homography,
    signed_distance,
    validate_quad,
)


def test_homography_maps_corners():
    src = [(0.40, 0.50), (0.60, 0.52), (0.62, 0.58), (0.38, 0.56)]
    h = compute_homography(src, UNIT_SQUARE)
    for s, d in zip(src, UNIT_SQUARE):
        assert apply_homography(h, s) == pytest.approx(d, abs=1e-9)


def test_homography_point_beyond_horizon_is_none():
    # prospettiva forte: la linea all'infinito passa vicino al quadrilatero
    src = [(0, 0), (1, 0), (0.6, 1), (0.4, 1)]
    h = compute_homography(src, UNIT_SQUARE)
    assert apply_homography(h, (0.5, 5.0)) is None


@pytest.mark.parametrize(
    "u, v, expected",
    [
        (0.5, 0.5, -0.5),
        (0.1, 0.5, -0.1),
        (0.5, 0.95, -0.05),
        (0.0, 0.3, 0.0),
        (1.2, 0.5, 0.2),
        (-0.3, 0.5, 0.3),
        (0.5, -0.1, 0.1),
        (1.3, 1.4, math.hypot(0.3, 0.4)),
    ],
)
def test_signed_distance(u, v, expected):
    assert signed_distance(u, v) == pytest.approx(expected)


@pytest.mark.parametrize(
    "quad",
    [
        [(0, 0), (1, 0), (0, 1), (1, 1)],  # incrociato
        [(0, 0), (1, 0), (2, 0), (0, 1)],  # tre punti allineati
        [(0, 0), (0, 0), (0, 0), (0, 0)],  # coincidenti
        [(0, 0), (1e-4, 0), (1e-4, 1e-4), (0, 1e-4)],  # area minuscola
    ],
)
def test_validate_quad_rejects_degenerate(quad):
    with pytest.raises(CalibrationError):
        validate_quad(quad)


def test_validate_quad_accepts_both_orientations():
    validate_quad([(0, 0), (1, 0), (1, 1), (0, 1)])
    validate_quad([(1, 0), (0, 0), (0, 1), (1, 1)])  # specchiato (webcam non ribaltata)


def _corners(iris, head=((0, 0),) * 4):
    names = ("top_left", "top_right", "bottom_right", "bottom_left")
    return {n: [i[0], i[1], h[0], h[1]] for n, i, h in zip(names, iris, head)}


# La webcam guarda l'utente: guardando a destra l'iride va a sinistra nell'immagine.
MIRRORED_IRIS = ((0.60, 0.40), (0.40, 0.40), (0.40, 0.46), (0.60, 0.46))


def test_model_eyes_only_center_and_outside():
    m = CalibrationModel.from_corners(_corners(MIRRORED_IRIS), head_weight=0.0)
    assert m.to_area((0.50, 0.43, 0, 0)) == pytest.approx((0.5, 0.5))
    assert m.distance((0.50, 0.43, 0, 0)) == pytest.approx(-0.5)
    # guardare oltre il bordo destro: iride ancora più a sinistra nell'immagine
    assert m.distance((0.30, 0.43, 0, 0)) == pytest.approx(0.5)


def test_model_head_sign_inferred_from_calibration():
    # l'utente ruota soprattutto la testa; yaw ha segno opposto all'iride
    iris = ((0.52, 0.40), (0.48, 0.40), (0.48, 0.44), (0.52, 0.44))
    head = ((-15, 10), (15, 10), (15, -10), (-15, -10))
    m = CalibrationModel.from_corners(_corners(iris, head), head_weight=0.01)
    assert m.sign_x == -1.0  # iride diminuisce mentre lo yaw cresce
    assert m.sign_y == -1.0  # iris_y cresce mentre il pitch diminuisce
    assert m.to_area((0.50, 0.42, 0, 0)) == pytest.approx((0.5, 0.5))
    # ruotare la testa oltre l'angolo destro porta fuori area
    assert m.distance((0.48, 0.42, 40, 0)) > 0.3


def test_model_head_only_movement_detected():
    iris = ((0.5, 0.42),) * 4
    head = ((-15, 10), (15, 10), (15, -10), (-15, -10))
    m = CalibrationModel.from_corners(_corners(iris, head), head_weight=0.01)
    assert m.distance((0.5, 0.42, 0, 0)) < 0
    assert m.distance((0.5, 0.42, 0, -30)) > 0.5


def test_model_rejects_degenerate_calibration():
    same = ((0.5, 0.4),) * 4
    with pytest.raises(CalibrationError):
        CalibrationModel.from_corners(_corners(same), head_weight=0.0)


def test_model_rejects_missing_or_invalid_corner():
    corners = _corners(MIRRORED_IRIS)
    del corners["top_left"]
    with pytest.raises(CalibrationError):
        CalibrationModel.from_corners(corners, head_weight=0.0)
    corners = _corners(MIRRORED_IRIS)
    corners["top_left"][0] = float("nan")
    with pytest.raises(CalibrationError):
        CalibrationModel.from_corners(corners, head_weight=0.0)


def test_homography_is_numpy_3x3():
    m = CalibrationModel.from_corners(_corners(MIRRORED_IRIS), head_weight=0.0)
    assert isinstance(m.homography, np.ndarray) and m.homography.shape == (3, 3)
