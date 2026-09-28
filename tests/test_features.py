import math

import numpy as np
import pytest

from focus_guard.logic.features import (
    GazeSmoother,
    iris_circles,
    head_angles,
    is_blinking,
    raw_gaze_from_landmarks,
)

W, H = 640, 480


def make_landmarks(iris_offset=(0.0, 0.0), swap_iris=False):
    """478 landmark sintetici: occhi orizzontali larghi 40 px, iride centrata + offset."""
    pts = np.full((478, 3), 0.5)

    def put(i, x, y):
        pts[i] = (x / W, y / H, 0.0)

    put(33, 260, 200)
    put(133, 300, 200)
    put(362, 340, 200)
    put(263, 380, 200)
    ox, oy = iris_offset
    a, b = (473, 468) if swap_iris else (468, 473)
    put(a, 280 + ox, 200 + oy)
    put(b, 360 + ox, 200 + oy)
    return pts


def test_centered_iris():
    raw = raw_gaze_from_landmarks(make_landmarks(), (W, H))
    assert raw == pytest.approx((0.5, 0.0, 0.0, 0.0))


def test_iris_offset_normalized_by_eye_width():
    raw = raw_gaze_from_landmarks(make_landmarks((4.0, 2.0)), (W, H))
    assert raw[0] == pytest.approx(0.6)
    assert raw[1] == pytest.approx(0.05)


def test_iris_index_convention_does_not_matter():
    a = raw_gaze_from_landmarks(make_landmarks((4.0, 0.0)), (W, H))
    b = raw_gaze_from_landmarks(make_landmarks((4.0, 0.0), swap_iris=True), (W, H))
    assert a == pytest.approx(b)


def test_head_roll_does_not_move_ratio():
    pts = make_landmarks((4.0, 0.0))
    # ruota tutti i punti di 20° attorno al centro dell'immagine (in pixel)
    theta = math.radians(20)
    rot = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    px = pts[:, :2] * [W, H] - [W / 2, H / 2]
    pts[:, :2] = (px @ rot.T + [W / 2, H / 2]) / [W, H]
    raw = raw_gaze_from_landmarks(pts, (W, H))
    assert raw[0] == pytest.approx(0.6, abs=1e-9)
    assert raw[1] == pytest.approx(0.0, abs=1e-9)


def test_missing_iris_landmarks_returns_none():
    assert raw_gaze_from_landmarks(np.zeros((468, 3)), (W, H)) is None


def test_degenerate_eye_returns_none():
    pts = make_landmarks()
    pts[133] = pts[33]
    assert raw_gaze_from_landmarks(pts, (W, H)) is None


def _rotation(yaw_deg, pitch_deg):
    y, p = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    m = np.eye(4)
    m[:3, :3] = ry @ rx
    return m


@pytest.mark.parametrize("yaw, pitch", [(0, 0), (20, 0), (0, -15), (-25, 10)])
def test_head_angles(yaw, pitch):
    assert head_angles(_rotation(yaw, pitch)) == pytest.approx((yaw, pitch), abs=1e-9)


def test_head_angles_none():
    assert head_angles(None) == (0.0, 0.0)


def test_head_angles_passed_through():
    raw = raw_gaze_from_landmarks(make_landmarks(), (W, H), _rotation(10, 5))
    assert raw[2:] == pytest.approx((10, 5))


def test_is_blinking():
    assert not is_blinking(None, 0.5)
    assert not is_blinking({"eyeBlinkLeft": 0.2, "eyeBlinkRight": 0.3}, 0.5)
    assert is_blinking({"eyeBlinkLeft": 0.2, "eyeBlinkRight": 0.7}, 0.5)


def test_smoother_ema_blink_hold_and_reset():
    s = GazeSmoother(alpha=0.5)
    assert s.update((0, 0, 0, 0)) == (0, 0, 0, 0)
    assert s.update((1, 1, 1, 1)) == pytest.approx((0.5,) * 4)
    # battito di ciglia: il valore anomalo viene ignorato
    assert s.update((9, 9, 9, 9), blinking=True) == pytest.approx((0.5,) * 4)
    # volto perso: stato azzerato
    assert s.update(None) is None
    assert s.update((1, 1, 1, 1), blinking=True) is None
    assert s.update((2, 2, 2, 2)) == (2, 2, 2, 2)


def test_smoother_invalid_alpha():
    with pytest.raises(ValueError):
        GazeSmoother(0.0)


def test_iris_circles():
    pts = make_landmarks((4.0, 0.0))
    for ring, center in (((469, 470, 471, 472), (284, 200)), ((474, 475, 476, 477), (364, 200))):
        for i, (dx, dy) in zip(ring, ((5, 0), (0, 5), (-5, 0), (0, -5))):
            pts[i] = ((center[0] + dx) / W, (center[1] + dy) / H, 0)
    circles = iris_circles(pts, (W, H))
    assert len(circles) == 2
    for (cx, cy, r), (px, py) in zip(circles, ((284, 200), (364, 200))):
        assert (cx * W, cy * H) == pytest.approx((px, py))
        assert r * W == pytest.approx(5)
    assert iris_circles(np.zeros((468, 3)), (W, H)) == ()
