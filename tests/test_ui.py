"""Parte grafica: tema, messaggi, banner, indicatore di stato, variazioni KPI."""

import json
import os
import random
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("qtawesome")
pytest.importorskip("matplotlib")

from focus_guard.stats.store import DISTRACTION, SESSION, EventLog  # noqa: E402
from focus_guard.ui import theme as theme_module  # noqa: E402
from focus_guard.ui.messages import MESSAGES, MessagePicker, format_elapsed  # noqa: E402
from focus_guard.ui.theme import DARK, LIGHT, theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


# --- messaggi ----------------------------------------------------------------

def test_ten_messages_in_rotation_without_repeats():
    assert len(MESSAGES) == 10 and len(set(MESSAGES)) == 10
    picker = MessagePicker(rng=random.Random(1))
    picks = [picker.pick() for _ in range(100)]
    assert all(a != b for a, b in zip(picks, picks[1:]))
    assert set(picks) == set(MESSAGES)


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (12.7, "0:12"), (75, "1:15"), (3725, "1:02:05"), (-3, "0:00")])
def test_format_elapsed(seconds, text):
    assert format_elapsed(seconds) == text


# --- tema ----------------------------------------------------------------------

def test_tokens_both_modes_complete_and_valid():
    from PyQt6.QtGui import QColor

    for mode in (DARK, LIGHT):
        t = theme_module.tokens_for(mode)
        assert t.mode == mode
        for name, value in vars(t).items():
            if isinstance(value, str) and value.startswith("#"):
                assert QColor(value).isValid(), (mode, name)
    assert theme_module.DARK_TOKENS.accent == "#60cdff"  # azzurro Windows
    assert theme_module.LIGHT_TOKENS.accent == "#005fb8"


def test_spacing_grid_multiples_of_8():
    assert [theme_module.S1, theme_module.S2, theme_module.S3, theme_module.S4, theme_module.S5] == [8, 16, 24, 32, 40]


def test_apply_sets_stylesheet_and_emits(qapp):
    seen = []
    theme.changed.connect(seen.append)
    try:
        theme.apply(LIGHT)
        assert theme.mode == LIGHT and "#005fb8" in qapp.styleSheet()
        theme.apply(DARK)
        assert theme.is_dark and "#60cdff" in qapp.styleSheet()
    finally:
        theme.changed.disconnect(seen.append)
    assert [t.mode for t in seen] == [LIGHT, DARK]


# --- banner ----------------------------------------------------------------------

def test_overlay_hides_immediately_and_fades_with_ghost(qapp, tmp_path):
    from focus_guard.ui.overlay import AlertOverlay

    o = AlertOverlay(0.6)
    o.show_alert(None, "Torna a concentrarti!", elapsed_s=2.0)
    assert o.isVisible()
    assert o.headline in MESSAGES
    assert o.elapsed_text == "0:02"
    o.hide_alert()
    assert not o.isVisible()  # lo stato dell'allarme è subito esatto
    assert len(o._ghosts) == 1 and o._ghosts[0].isVisible()  # la dissolvenza continua a parte
    o._ghosts[0].close()
    o.hide_alert()  # già nascosto: nessun nuovo fantasma
    assert len(o._ghosts) <= 1


# --- dashboard ----------------------------------------------------------------------

def _dashboard(qapp):
    from focus_guard.ui.dashboard import Dashboard

    return Dashboard(EventLog(":memory:"))


def test_status_pill_states(qapp):
    from focus_guard.ui.dashboard import TrackingStatus

    d = _dashboard(qapp)
    cases = [
        (TrackingStatus(), "stopped"),
        (TrackingStatus(tracking=True, paused=True), "paused"),
        (TrackingStatus(tracking=True), "no_area"),
        (TrackingStatus(tracking=True, area_defined=True, inside=True, face=True), "focus"),
        (TrackingStatus(tracking=True, area_defined=True, inside=False, face=True), "leaving"),
        (TrackingStatus(tracking=True, area_defined=True, inside=False, face=True, alert=True), "distracted"),
    ]
    for status, key in cases:
        d.set_status(status)
        assert d.status_pill.key == key
    assert d.status_pill.text == "Distratto"
    assert d.toggle_button.isChecked()


def test_kpi_delta_vs_previous_period(qapp):
    d = _dashboard(qapp)
    log = d._log
    now = time.time()
    day = 86400
    # ieri: 2 distrazioni; oggi: 1 distrazione (nella stessa fascia di tempo)
    log.add(SESSION, now - 1800, now)
    log.add(DISTRACTION, now - 900, now - 890)
    log.add(SESSION, now - day - 1800, now - day)
    log.add(DISTRACTION, now - day - 900, now - day - 880)
    log.add(DISTRACTION, now - day - 600, now - day - 590)
    d.refresh_stats()
    tile = d.tiles["distractions"]
    assert tile.value.text() == "1"
    assert tile.delta_text.text() == "−1"  # −1
    assert tile.delta_text._role == "good"  # meno distrazioni = miglioramento
    assert d.tiles["active_min"].delta_text.text() == "invariato"


def test_theme_switch_saves_config(qapp, tmp_path):
    from focus_guard.app import FocusGuardApp
    from tests.test_app import FakeMusic, FakeWorker

    path = tmp_path / "config.json"
    path.write_text(json.dumps({}))
    guard = FocusGuardApp(path, worker_factory=lambda cfg: FakeWorker(), music=FakeMusic(),
                          event_log=EventLog(":memory:"))
    assert theme.mode == DARK  # predefinito: scuro
    guard.dashboard.theme_switch.click()
    assert theme.mode == LIGHT
    assert json.loads(path.read_text())["theme"] == LIGHT
    assert not guard.dashboard.settings_theme_switch.isChecked()  # interruttori sincronizzati
    guard.dashboard.settings_theme_switch.click()
    assert theme.mode == DARK and guard.dashboard.theme_switch.isChecked()
    guard.dashboard.hide()


def test_tray_icons_differ_per_state(qapp):
    from focus_guard.ui.icons import TRAY_STATES, render_mark

    images = {state: render_mark(32, state=state).toImage() for state in TRAY_STATES}
    assert images["focused"] != images["distracted"] != images["paused"]
    assert images["paused"] != images["stopped"]  # stesso colore, simbolo diverso


def test_config_theme_default_and_validation(tmp_path):
    from focus_guard.config import Config, ConfigError, load_config

    assert Config().theme == DARK
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": "blu"}))
    with pytest.raises(ConfigError):
        load_config(path)
