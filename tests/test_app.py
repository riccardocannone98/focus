"""Integrazione del controller con webcam e audio finti (Qt offscreen)."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
QtGui = pytest.importorskip("PyQt6.QtGui")
QtTest = pytest.importorskip("PyQt6.QtTest")

from focus_guard import app as app_module  # noqa: E402
from focus_guard.ui import calibration as calibration_module  # noqa: E402
from focus_guard.vision.tracker import GazeSample  # noqa: E402

CORNERS = {
    "top_left": [0.60, 0.40, 0.0, 0.0],
    "top_right": [0.40, 0.40, 0.0, 0.0],
    "bottom_right": [0.40, 0.46, 0.0, 0.0],
    "bottom_left": [0.60, 0.46, 0.0, 0.0],
}
CENTER = (0.50, 0.43, 0.0, 0.0)
FAR_OUT = (0.20, 0.43, 0.0, 0.0)


class FakeWorker(QtCore.QObject):
    sample = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class FakeMusic:
    def __init__(self):
        self.calls = []

    def play(self):
        self.calls.append("play")

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def make_app(qapp, tmp_path):
    workers = []

    def factory(cfg):
        workers.append(FakeWorker())
        return workers[-1]

    def build(**cfg_overrides):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"smoothing_alpha": 1.0, **cfg_overrides}))
        guard = app_module.FocusGuardApp(path, worker_factory=factory, music=FakeMusic())
        guard.workers = workers
        return guard

    return build


def feed(guard, t, raw, blinking=False):
    guard.workers[-1].sample.emit(GazeSample(t, raw, blinking))


def test_alert_cycle(make_app):
    guard = make_app(calibration=CORNERS, activation_delay_s=2.0)
    guard.start()
    assert guard.workers[-1].running
    assert guard._calibration is None

    feed(guard, 0.0, CENTER)
    feed(guard, 1.0, FAR_OUT)
    feed(guard, 2.5, FAR_OUT)
    assert not guard.overlay.isVisible()
    feed(guard, 3.0, FAR_OUT)
    assert guard.overlay.isVisible()
    assert guard.music.calls == ["play"]

    feed(guard, 3.5, FAR_OUT, blinking=True)
    assert guard.overlay.isVisible()

    feed(guard, 4.0, CENTER)
    assert not guard.overlay.isVisible()
    assert guard.music.calls == ["play", "stop"]


def test_pause_stops_camera_and_alert(make_app):
    guard = make_app(calibration=CORNERS, activation_delay_s=0.0)
    guard.start()
    worker = guard.workers[-1]
    feed(guard, 0.0, FAR_OUT)
    assert guard.overlay.isVisible()

    guard.set_paused(True)
    assert not worker.running
    assert not guard.overlay.isVisible()
    assert guard.music.calls[-1] == "stop"

    guard.set_paused(False)
    assert guard.workers[-1].running and guard.workers[-1] is not worker


def test_camera_failure_turns_alert_off(make_app):
    guard = make_app(calibration=CORNERS, activation_delay_s=0.0)
    guard.start()
    feed(guard, 0.0, FAR_OUT)
    guard.workers[-1].failed.emit("boom")
    assert not guard.overlay.isVisible()


def _key(window, key):
    window.keyPressEvent(
        QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, QtCore.Qt.KeyboardModifier.NoModifier)
    )


def test_calibration_flow_saves_config(make_app, monkeypatch):
    monkeypatch.setattr(calibration_module, "COLLECT_SECONDS", 0.05)
    guard = make_app()
    guard.start()
    window = guard._calibration
    assert window is not None and guard.model is None

    for i, name in enumerate(calibration_module.CORNER_NAMES):
        _key(window, QtCore.Qt.Key.Key_Space)
        for k in range(calibration_module.MIN_SAMPLES + 2):
            feed(guard, i + k * 0.01, tuple(CORNERS[name]))
        QtTest.QTest.qWait(150)
    assert window._phase is calibration_module.Phase.VERIFY

    # durante la calibrazione niente allarmi
    feed(guard, 10.0, FAR_OUT)
    assert not guard.overlay.isVisible()

    _key(window, QtCore.Qt.Key.Key_Return)
    assert guard._calibration is None
    assert guard.model is not None
    saved = json.loads(guard.config_path.read_text())["calibration"]
    assert all(saved[k] == pytest.approx(v) for k, v in CORNERS.items())


def test_calibration_without_face_asks_retry(make_app, monkeypatch):
    monkeypatch.setattr(calibration_module, "COLLECT_SECONDS", 0.05)
    guard = make_app()
    guard.start()
    window = guard._calibration
    _key(window, QtCore.Qt.Key.Key_Space)
    feed(guard, 0.0, None)
    QtTest.QTest.qWait(150)
    assert window._phase is calibration_module.Phase.WAITING
    assert window._step == 0
    assert "riprova" in window._message
    _key(window, QtCore.Qt.Key.Key_Escape)
    assert guard._calibration is None and guard.model is None
