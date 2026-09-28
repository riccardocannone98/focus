import math

import pytest

from focus_guard.logic.focus import FocusEvent, FocusMonitor, FocusState, Thresholds

IN = -0.2  # ben dentro l'area
EDGE = 0.05  # fuori dal bordo ma entro exit_margin (zona di isteresi)
OUT = 0.3  # oltre exit_margin


def feed(monitor, samples):
    """samples: lista di (t, distanza) -> lista di eventi non nulli con il loro tempo."""
    events = []
    for t, d in samples:
        ev = monitor.update(t, d)
        if ev is not None:
            events.append((t, ev))
    return events


@pytest.fixture
def monitor():
    return FocusMonitor(Thresholds(exit_margin=0.1, reentry_margin=0.0, activation_delay_s=2.0))


def test_inside_never_alerts(monitor):
    assert feed(monitor, [(t * 0.1, IN) for t in range(100)]) == []
    assert monitor.state is FocusState.FOCUSED


def test_alert_fires_only_after_activation_delay(monitor):
    assert monitor.update(0.0, OUT) is None
    assert monitor.state is FocusState.LEAVING
    assert monitor.update(1.99, OUT) is None
    assert monitor.update(2.0, OUT) is FocusEvent.ALERT_ON
    assert monitor.alert_active
    # nessun evento duplicato
    assert monitor.update(3.0, OUT) is None


def test_short_glance_away_is_ignored(monitor):
    events = feed(monitor, [(0.0, OUT), (1.5, OUT), (1.6, IN), (2.5, OUT), (4.0, OUT)])
    assert events == []  # il timer riparte da 2.5
    assert monitor.update(4.5, OUT) is FocusEvent.ALERT_ON


def test_edge_zone_below_exit_margin_does_not_trigger(monitor):
    assert feed(monitor, [(t, EDGE) for t in range(10)]) == []
    assert monitor.state is FocusState.FOCUSED


def test_hysteresis_on_reentry(monitor):
    feed(monitor, [(0.0, OUT), (2.0, OUT)])
    assert monitor.alert_active
    # nella zona di isteresi l'allarme resta acceso
    assert feed(monitor, [(3.0, EDGE), (10.0, EDGE)]) == []
    assert monitor.alert_active
    # rientro oltre reentry_margin: stop immediato (reentry_delay = 0)
    assert monitor.update(10.1, IN) is FocusEvent.ALERT_OFF
    assert monitor.state is FocusState.FOCUSED


def test_exactly_on_margins():
    m = FocusMonitor(Thresholds(exit_margin=0.1, reentry_margin=0.0, activation_delay_s=0.0))
    assert m.update(0.0, 0.1) is None  # uguale alla soglia = dentro
    assert m.update(0.1, 0.1000001) is FocusEvent.ALERT_ON
    assert m.update(0.2, 0.0) is FocusEvent.ALERT_OFF  # uguale alla soglia di rientro = rientrato


def test_zero_activation_delay_alerts_immediately():
    m = FocusMonitor(Thresholds(activation_delay_s=0.0))
    assert m.update(0.0, OUT) is FocusEvent.ALERT_ON


def test_reentry_delay_requires_staying_inside():
    m = FocusMonitor(Thresholds(activation_delay_s=0.0, reentry_delay_s=0.5))
    m.update(0.0, OUT)
    assert m.update(1.0, IN) is None
    assert m.state is FocusState.RETURNING
    assert m.alert_active
    # esce di nuovo prima dei 0.5 s: torna DISTRACTED
    assert m.update(1.3, OUT) is None
    assert m.state is FocusState.DISTRACTED
    assert m.update(2.0, IN) is None
    assert m.update(2.49, IN) is None
    assert m.update(2.5, IN) is FocusEvent.ALERT_OFF


def test_face_lost_counts_as_out_by_default(monitor):
    events = feed(monitor, [(0.0, None), (2.0, None)])
    assert events == [(2.0, FocusEvent.ALERT_ON)]


def test_face_lost_ignored_when_configured():
    m = FocusMonitor(Thresholds(activation_delay_s=1.0, face_lost_counts_as_out=False))
    assert feed(m, [(0.0, None), (5.0, None)]) == []
    assert m.state is FocusState.FOCUSED
    # e non interrompe un allarme già attivo
    feed(m, [(6.0, OUT), (7.0, OUT)])
    assert m.alert_active
    assert m.update(8.0, None) is None
    assert m.alert_active


def test_nan_and_inf_distances(monitor):
    assert feed(monitor, [(0.0, math.nan), (2.0, math.inf)]) == [(2.0, FocusEvent.ALERT_ON)]


def test_reset_turns_alert_off(monitor):
    feed(monitor, [(0.0, OUT), (2.0, OUT)])
    assert monitor.reset() is FocusEvent.ALERT_OFF
    assert monitor.state is FocusState.FOCUSED
    assert monitor.reset() is None


def test_clock_going_backwards_does_not_trigger(monitor):
    monitor.update(10.0, OUT)
    assert monitor.update(5.0, OUT) is None
    assert monitor.state is FocusState.LEAVING


def test_negative_reentry_margin_requires_deeper_return():
    m = FocusMonitor(Thresholds(exit_margin=0.1, reentry_margin=-0.1, activation_delay_s=0.0))
    m.update(0.0, OUT)
    assert m.update(1.0, -0.05) is None
    assert m.alert_active
    assert m.update(2.0, -0.15) is FocusEvent.ALERT_OFF


@pytest.mark.parametrize(
    "kwargs",
    [dict(exit_margin=0.0, reentry_margin=0.1), dict(activation_delay_s=-1), dict(reentry_delay_s=-1)],
)
def test_invalid_thresholds(kwargs):
    with pytest.raises(ValueError):
        Thresholds(**kwargs)
