"""Integrazione del controller con webcam, audio e orologi finti (Qt offscreen)."""

import json
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("matplotlib")

from focus_guard import app as app_module  # noqa: E402
from focus_guard.stats.store import DISTRACTION, GLANCE, PAUSE, SESSION, EventLog  # noqa: E402
from focus_guard.ui.area_window import Phase  # noqa: E402
from focus_guard.vision.tracker import GazeSample  # noqa: E402

AREA = {"x_min": -0.60, "y_min": 0.40, "x_max": -0.40, "y_max": 0.46,
        "head_weight": 0.0, "sign_x": 1.0, "sign_y": 1.0}
CENTER = (0.50, 0.43, 0.0, 0.0)
FAR_OUT = (0.20, 0.43, 0.0, 0.0)


class FakeWorker(QtCore.QObject):
    sample = QtCore.pyqtSignal(object)
    preview = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = False
        self.preview_enabled = False

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


class Clock:
    """Orologio condiviso: epoch = 1_000_000 + monotonic."""

    def __init__(self):
        self.mono = 0.0

    def wall(self):
        return 1_000_000.0 + self.mono


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def make_app(qapp, tmp_path):
    workers = []
    created = []

    def factory(cfg):
        workers.append(FakeWorker())
        return workers[-1]

    def build(**cfg_overrides):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"smoothing_alpha": 1.0, **cfg_overrides}))
        clock = Clock()
        guard = app_module.FocusGuardApp(
            path,
            worker_factory=factory,
            music=FakeMusic(),
            event_log=EventLog(":memory:"),
            wall_clock=clock.wall,
            mono_clock=lambda: clock.mono,
        )
        guard.workers = workers
        guard.clock = clock
        created.append(guard)
        return guard

    yield build
    for guard in created:
        if guard.area_window is not None:
            guard.area_window.cancel()
        guard.dashboard.hide()
        guard.overlay.hide()


def feed(guard, t, raw, blinking=False):
    guard.clock.mono = t
    guard.workers[-1].sample.emit(GazeSample(t, raw, blinking))


def kinds(guard):
    return [(r.kind, round(r.duration, 3)) for r in guard.event_log.query()]


def test_startup_opens_dashboard_and_session(make_app):
    guard = make_app(area=AREA)
    guard.start()
    assert guard.dashboard.isVisible()
    assert guard.area_window is None
    assert guard.tracking and guard.workers[-1].running
    assert kinds(guard) == [(SESSION, 0.0)]
    assert guard.dashboard.toggle_button.text() == "Ferma tracking"


def test_closing_dashboard_keeps_app_running(make_app):
    guard = make_app(area=AREA)
    guard.start()
    guard.dashboard.close()
    assert not guard.dashboard.isVisible()
    assert guard.tracking and guard.workers[-1].running
    guard.tray.dashboard_requested.emit()
    assert guard.dashboard.isVisible()


def test_alert_cycle_logs_distraction_and_glance(make_app):
    guard = make_app(area=AREA, activation_delay_s=2.0)
    guard.start(show_dashboard=False)
    feed(guard, 0.0, CENTER)
    feed(guard, 1.0, FAR_OUT)
    feed(guard, 1.5, CENTER)  # sguardo breve
    feed(guard, 10.0, FAR_OUT)
    feed(guard, 12.0, FAR_OUT)
    assert guard.overlay.isVisible() and guard.music.calls == ["play"]
    assert guard.status().inside is False and guard.status().face is True
    feed(guard, 12.5, FAR_OUT, blinking=True)
    assert guard.overlay.isVisible()
    feed(guard, 15.0, CENTER)
    assert not guard.overlay.isVisible() and guard.music.calls == ["play", "stop"]
    assert guard.status().inside is True
    assert kinds(guard) == [(SESSION, 0.0), (GLANCE, 0.5), (DISTRACTION, 5.0)]
    ep = guard.event_log.query()[2]
    assert ep.start == pytest.approx(1_000_010.0)  # convertito da monotonic a epoch


def test_timed_pause_stops_camera_logs_and_resumes(make_app):
    guard = make_app(area=AREA, activation_delay_s=0.0)
    guard.start(show_dashboard=False)
    feed(guard, 1.0, FAR_OUT)
    assert guard.overlay.isVisible()
    worker = guard.workers[-1]

    guard.clock.mono = 3.0
    guard.pause(15)
    assert guard.paused and not worker.running
    assert not guard.overlay.isVisible()
    assert guard.paused_until == pytest.approx(guard.clock.wall() + 900)
    assert guard._resume_timer.isActive()
    assert guard.dashboard.resume_button.isEnabled()

    guard.clock.mono = 63.0
    guard._resume_timer.timeout.emit()  # scadenza simulata
    assert not guard.paused and guard.workers[-1].running
    assert kinds(guard) == [(SESSION, 0.0), (DISTRACTION, 2.0), (PAUSE, 60.0)]


def test_stop_tracking_closes_session(make_app):
    guard = make_app(area=AREA)
    guard.start(show_dashboard=False)
    guard.clock.mono = 120.0
    guard._touch_open_rows()  # battito periodico
    assert guard.event_log.query()[0].duration == 120.0
    guard.clock.mono = 300.0
    guard.stop_tracking()
    assert not guard.tracking and not guard.workers[-1].running
    assert kinds(guard) == [(SESSION, 300.0)]
    assert guard.dashboard.toggle_button.text() == "Avvia tracking"
    assert not guard.dashboard.pause_buttons[0].isEnabled()


def test_sliders_update_thresholds_and_config(make_app):
    guard = make_app(area=AREA, reentry_margin=0.05)
    guard.start(show_dashboard=False)
    assert guard.dashboard.margin_slider.minimum() == 5
    guard.dashboard.delay_slider.setValue(7)  # 3.5 s
    guard.dashboard.margin_slider.setValue(20)
    assert guard.monitor.thresholds.activation_delay_s == 3.5
    assert guard.monitor.thresholds.exit_margin == pytest.approx(0.2)
    guard._save_timer.timeout.emit()
    saved = json.loads(guard.config_path.read_text())
    assert saved["activation_delay_s"] == 3.5 and saved["exit_margin"] == pytest.approx(0.2)


def test_legacy_calibration_is_migrated(make_app):
    corners = {
        "top_left": [0.60, 0.40, 0.0, 0.0],
        "top_right": [0.40, 0.40, 0.0, 0.0],
        "bottom_right": [0.40, 0.46, 0.0, 0.0],
        "bottom_left": [0.60, 0.46, 0.0, 0.0],
    }
    guard = make_app(calibration=corners)
    assert guard.area is not None
    saved = json.loads(guard.config_path.read_text())
    assert saved["calibration"] is None
    assert saved["area"]["x_min"] == pytest.approx(-0.60)


def _record(guard, window, samples):
    window.start_recording()
    for i, raw in enumerate(samples):
        feed(guard, 100 + i * 0.05, raw)
    window.finish_recording()


def test_define_area_flow(make_app):
    guard = make_app(activation_delay_s=0.0)
    guard.start()
    window = guard.area_window
    assert window is not None and guard.area is None
    assert guard.workers[-1].preview_enabled

    guard.workers[-1].preview.emit(np.zeros((240, 320, 3), np.uint8))
    assert window.preview._image is not None

    rng = np.random.default_rng(0)
    samples = [(x, y, 0.0, 0.0) for x, y in zip(rng.uniform(0.4, 0.6, 200), rng.uniform(0.40, 0.46, 200))]
    _record(guard, window, samples)
    assert window.phase is Phase.EDIT
    assert window.map.area_rect is not None and window.map.editable

    # durante la definizione dell'area niente allarmi
    feed(guard, 200.0, FAR_OUT)
    assert not guard.overlay.isVisible()
    assert window.map.point_inside is False
    feed(guard, 200.1, CENTER)
    assert window.map.point_inside is True

    # ritocco: allargo il bordo destro di 0.05
    x0, y0, x1, y1 = window.map.area_rect
    window.map.rect_changed.emit((x0, y0, x1 + 0.05, y1))
    window.save()
    assert guard.area_window is None
    assert guard.area.x_max == pytest.approx(x1 + 0.05)
    assert not guard.workers[-1].preview_enabled
    assert json.loads(guard.config_path.read_text())["area"]["x_max"] == pytest.approx(x1 + 0.05)
    # il tempo passato a definire l'area è registrato come pausa
    assert [k for k, _ in kinds(guard)] == [SESSION, PAUSE]

    feed(guard, 300.0, FAR_OUT)
    assert guard.overlay.isVisible()


def test_define_area_recording_errors(make_app):
    guard = make_app()
    guard.start(show_dashboard=False)
    window = guard.area_window
    _record(guard, window, [None] * 50)  # volto mai rilevato
    assert window.phase is Phase.IDLE
    assert "insufficienti" in window.info.text()
    assert not window.save_button.isEnabled()
    window.cancel()
    assert guard.area is None and guard.area_window is None


def test_redefine_existing_area_starts_in_edit(make_app):
    guard = make_app(area=AREA)
    guard.start(show_dashboard=False)
    guard.dashboard.define_area.emit()
    window = guard.area_window
    assert window.phase is Phase.EDIT
    assert window.map.area_rect == pytest.approx((-0.60, 0.40, -0.40, 0.46))
    window.cancel()
    assert guard.area.x_min == -0.60


def test_define_area_while_stopped_uses_camera_only_temporarily(make_app):
    guard = make_app(area=AREA)
    guard.start(show_dashboard=False)
    guard.stop_tracking()
    guard.open_area_window()
    assert guard.workers[-1].running
    guard.area_window.cancel()
    assert not guard.workers[-1].running
    assert [k for k, _ in kinds(guard)] == [SESSION]


def test_camera_failure_turns_alert_off(make_app):
    guard = make_app(area=AREA, activation_delay_s=0.0)
    guard.start(show_dashboard=False)
    feed(guard, 0.0, FAR_OUT)
    guard.workers[-1].failed.emit("boom")
    assert not guard.overlay.isVisible()
    assert kinds(guard)[-1][0] == DISTRACTION


def test_dashboard_kpis_and_csv(make_app, tmp_path):
    guard = make_app(area=AREA, activation_delay_s=1.0)
    guard.clock.mono = 0.0
    guard.start(show_dashboard=False)
    # simulo eventi di oggi reali (epoch attuale) direttamente nel registro
    import time
    now = time.time()
    log = guard.event_log
    log.add(SESSION, now - 3600, now)
    log.add(DISTRACTION, now - 1800, now - 1790)
    guard.dashboard.refresh_stats()
    k = guard.dashboard.last_kpis
    assert k.distractions == 1 and k.active_min >= 60
    assert guard.dashboard.tiles["distractions"].value.text() == "1"
    assert guard.dashboard.tiles["max_distraction_s"].value.text() == "10,0"
    out = guard.dashboard.export_csv(tmp_path / "e.csv")
    assert "distrazione" in out.read_text(encoding="utf-8-sig")


def test_gaze_map_mouse_drag(qapp):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    from focus_guard.ui.area_window import GazeMap

    m = GazeMap()
    m.resize(400, 240)
    m.view = (0.0, 0.0, 4.0, 2.4)  # 100 px per unità
    m.area_rect = (1.0, 0.5, 3.0, 1.5)
    m.editable = True
    changes = []
    m.rect_changed.connect(changes.append)
    m.show()
    QTest.mousePress(m, Qt.MouseButton.LeftButton, pos=QPoint(300, 100))  # bordo destro
    QTest.mouseMove(m, QPoint(350, 100))
    QTest.mouseRelease(m, Qt.MouseButton.LeftButton, pos=QPoint(350, 100))
    assert m.area_rect == pytest.approx((1.0, 0.5, 3.5, 1.5))
    QTest.mousePress(m, Qt.MouseButton.LeftButton, pos=QPoint(200, 100))  # interno: sposta
    QTest.mouseMove(m, QPoint(200, 150))
    QTest.mouseRelease(m, Qt.MouseButton.LeftButton, pos=QPoint(200, 150))
    assert m.area_rect == pytest.approx((1.0, 1.0, 3.5, 2.0))
    assert len(changes) == 2
    m.hide()
