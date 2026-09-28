import math

import numpy as np
import pytest

from focus_guard.logic.area import (
    MIN_SAMPLES,
    MIN_SIZE,
    AreaError,
    AreaModel,
    GazeMapper,
    apply_drag,
    area_from_legacy_corners,
    build_area_from_samples,
    estimate_head_sign,
    fit_view,
    hit_test,
    signed_distance,
)


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


def test_mapper_mirrors_x_and_adds_head():
    m = GazeMapper(head_weight=0.01, sign_x=1.0, sign_y=-1.0)
    assert m.map((0.5, 0.1, 0.0, 0.0)) == pytest.approx((-0.5, 0.1))
    # l'iride che va a sinistra nell'immagine (guardo a destra) sposta il punto a destra
    assert m.map((0.4, 0.1, 0, 0))[0] > m.map((0.5, 0.1, 0, 0))[0]
    assert m.map((0.5, 0.1, 10.0, 5.0)) == pytest.approx((-0.6, 0.05))


def test_area_model_distance():
    area = AreaModel(-0.6, 0.0, -0.4, 0.1, head_weight=0.0)
    assert area.distance((0.5, 0.05, 0, 0)) == pytest.approx(-0.5)  # centro
    assert area.distance((0.3, 0.05, 0, 0)) == pytest.approx(0.5)  # gx=-0.3: mezzo lato a destra
    assert area.point_distance((-0.5, 0.15)) == pytest.approx(0.5)  # sotto


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(x_min=0, y_min=0, x_max=0.005, y_max=1),
        dict(x_min=0, y_min=0, x_max=1, y_max=0),
        dict(x_min=0, y_min=0, x_max=math.nan, y_max=1),
        dict(x_min=0, y_min=0, x_max=1, y_max=1, sign_x=0.5),
    ],
)
def test_area_model_validation(kwargs):
    with pytest.raises(AreaError):
        AreaModel(**kwargs)


def test_area_dict_roundtrip():
    area = AreaModel(-0.6, 0.0, -0.4, 0.1, 0.01, -1.0, 1.0)
    assert AreaModel.from_dict(area.to_dict()) == area
    with pytest.raises(AreaError):
        AreaModel.from_dict({"x_min": 0})


def _uniform_samples(n, x_range, y_range, rng, head=None):
    iris_x = rng.uniform(*x_range, n)
    iris_y = rng.uniform(*y_range, n)
    yaw = np.zeros(n) if head is None else head[0]
    pitch = np.zeros(n) if head is None else head[1]
    return np.column_stack([iris_x, iris_y, yaw, pitch])


def test_build_area_uses_percentiles_and_drops_outliers():
    rng = np.random.default_rng(0)
    samples = _uniform_samples(1000, (0.40, 0.60), (0.00, 0.10), rng)
    # 3% di outlier molto lontani (sguardo al telefono)
    samples[:30] = [0.95, 0.8, 0, 0]
    area = build_area_from_samples(samples, head_weight=0.0)
    # gx = -iris_x: x in [-0.60, -0.40]; con i percentili 5-95 il rettangolo si stringe un po'
    assert -0.60 < area.x_min < -0.57
    assert -0.43 < area.x_max < -0.40
    assert 0.0 < area.y_min < 0.02 and 0.08 < area.y_max < 0.10
    assert area.distance((0.95, 0.8, 0, 0)) > 1  # l'outlier resta fuori


def test_build_area_full_percentiles_is_bounding_box():
    rng = np.random.default_rng(1)
    samples = _uniform_samples(200, (0.40, 0.60), (0.0, 0.1), rng)
    area = build_area_from_samples(samples, 0.0, percentiles=(0, 100))
    assert area.x_min == pytest.approx(-samples[:, 0].max())
    assert area.y_max == pytest.approx(samples[:, 1].max())


def test_build_area_estimates_head_sign():
    rng = np.random.default_rng(2)
    n = 500
    # guardo verso destra: iride diminuisce e yaw aumenta (segni opposti)
    gaze = rng.uniform(-1, 1, n)
    samples = np.column_stack(
        [0.5 - 0.05 * gaze + rng.normal(0, 0.005, n), rng.uniform(0, 0.1, n), 15 * gaze, np.zeros(n)]
    )
    area = build_area_from_samples(samples, head_weight=0.01, default_signs=(1.0, -1.0))
    assert area.sign_x == -1.0
    assert area.sign_y == -1.0  # pitch costante: resta il default
    # con il segno giusto testa e occhi si sommano: area più larga che con sole iridi
    eyes_only = build_area_from_samples(samples, head_weight=0.0)
    assert area.x_max - area.x_min > 2 * (eyes_only.x_max - eyes_only.x_min)


def test_estimate_head_sign_weak_correlation_keeps_default():
    rng = np.random.default_rng(3)
    a, b = rng.normal(size=500), rng.normal(size=500)
    assert estimate_head_sign(a, b, default=-1.0) == -1.0
    assert estimate_head_sign(a, a * 2, default=-1.0) == 1.0
    assert estimate_head_sign(a, np.zeros(500), default=1.0) == 1.0


def test_build_area_errors():
    with pytest.raises(AreaError, match="insufficienti"):
        build_area_from_samples([], 0.0)
    with pytest.raises(AreaError, match="insufficienti"):
        build_area_from_samples([[0.5, 0.0, 0, 0]] * (MIN_SAMPLES - 1), 0.0)
    with pytest.raises(AreaError, match="troppo piccola"):
        build_area_from_samples([[0.5, 0.0, 0, 0]] * 100, 0.0)
    with pytest.raises(AreaError):
        build_area_from_samples([[0.5, 0.0, 0, 0]] * 100, 0.0, percentiles=(50, 40))
    # i NaN vengono scartati prima del conteggio
    rows = [[math.nan, 0, 0, 0]] * 100 + [[0.5, 0, 0, 0]] * 5
    with pytest.raises(AreaError, match="insufficienti"):
        build_area_from_samples(rows, 0.0)


def test_legacy_corners_migration():
    corners = {
        "top_left": [0.60, 0.40, 0.0, 0.0],
        "top_right": [0.40, 0.40, 0.0, 0.0],
        "bottom_right": [0.40, 0.46, 0.0, 0.0],
        "bottom_left": [0.60, 0.46, 0.0, 0.0],
    }
    area = area_from_legacy_corners(corners, 0.007)
    assert area.rect == pytest.approx((-0.60, 0.40, -0.40, 0.46))
    assert area.distance((0.50, 0.43, 0, 0)) < 0
    del corners["top_left"]
    with pytest.raises(AreaError):
        area_from_legacy_corners(corners, 0.007)


@pytest.mark.parametrize(
    "x, y, expected",
    [
        (100, 100, "top_left"),
        (300, 203, "bottom_right"),
        (102, 150, "left"),
        (200, 98, "top"),
        (297, 150, "right"),
        (200, 205, "bottom"),
        (200, 150, "move"),
        (50, 150, None),
        (200, 250, None),
    ],
)
def test_hit_test(x, y, expected):
    assert hit_test((100, 100, 300, 200), x, y, tolerance=6) == expected


def test_apply_drag_edges_and_corners():
    r = (0.0, 0.0, 1.0, 1.0)
    assert apply_drag(r, "left", 0.2, 5) == pytest.approx((0.2, 0, 1, 1))
    assert apply_drag(r, "bottom", 5, -0.3) == pytest.approx((0, 0, 1, 0.7))
    assert apply_drag(r, "top_right", 0.1, 0.1) == pytest.approx((0, 0.1, 1.1, 1))
    assert apply_drag(r, "move", 0.5, -0.5) == pytest.approx((0.5, -0.5, 1.5, 0.5))


def test_apply_drag_cannot_cross_opposite_edge():
    r = (0.0, 0.0, 1.0, 1.0)
    assert apply_drag(r, "left", 5.0, 0) == pytest.approx((1 - MIN_SIZE, 0, 1, 1))
    assert apply_drag(r, "top", 0, 5.0, min_size=0.1) == pytest.approx((0, 0.9, 1, 1))
    with pytest.raises(ValueError):
        apply_drag(r, "diagonal", 0, 0)


def test_fit_view_centers_rect_with_margin():
    v = fit_view((0.0, 0.0, 0.2, 0.1), factor=2.5, min_span=(0.1, 0.1))
    assert v == pytest.approx((-0.15, -0.075, 0.35, 0.175))
    small = fit_view((0.0, 0.0, 0.02, 0.02), min_span=(0.3, 0.2))
    assert small[2] - small[0] == pytest.approx(0.3)
