from focus_guard.logic.episodes import DISTRACTION, GLANCE, EpisodeTracker
from focus_guard.logic.focus import FocusMonitor, Thresholds

OUT, IN = 0.5, -0.2


def run(samples, **thresholds):
    """Fa girare monitor + tracker su (t, distanza) e restituisce gli episodi."""
    monitor = FocusMonitor(Thresholds(**thresholds))
    tracker = EpisodeTracker()
    episodes = []
    for t, d in samples:
        prev = monitor.state
        monitor.update(t, d)
        ep = tracker.observe(prev, monitor.state, t)
        if ep:
            episodes.append(ep)
    return episodes, tracker


def test_short_glance():
    eps, _ = run([(0, IN), (1, OUT), (2, OUT), (2.5, IN)], activation_delay_s=2.0)
    assert [(e.kind, e.start, e.end) for e in eps] == [(GLANCE, 1, 2.5)]
    assert eps[0].duration == 1.5


def test_distraction_spans_from_exit_to_return():
    eps, _ = run([(0, IN), (1, OUT), (3, OUT), (7, OUT), (8, IN)], activation_delay_s=2.0)
    assert [(e.kind, e.start, e.end) for e in eps] == [(DISTRACTION, 1, 8)]


def test_zero_delay_goes_straight_to_distraction():
    eps, _ = run([(0, IN), (1, OUT), (2, IN)], activation_delay_s=0.0)
    assert [(e.kind, e.start, e.end) for e in eps] == [(DISTRACTION, 1, 2)]


def test_reentry_delay_bounce_is_one_episode():
    samples = [(0, OUT), (2, OUT), (3, IN), (3.2, OUT), (4, IN), (5, IN)]
    eps, _ = run(samples, activation_delay_s=2.0, reentry_delay_s=0.5)
    assert [(e.kind, e.start, e.end) for e in eps] == [(DISTRACTION, 0, 5)]


def test_close_open_episode_on_pause():
    eps, tracker = run([(0, IN), (1, OUT), (3.5, OUT)], activation_delay_s=2.0)
    assert eps == [] and tracker.open
    ep = tracker.close(4.0)
    assert (ep.kind, ep.start, ep.end) == (DISTRACTION, 1, 4.0)
    assert tracker.close(5.0) is None


def test_multiple_episodes():
    samples = [(0, OUT), (0.5, IN), (1, OUT), (4, OUT), (5, IN), (6, OUT), (6.1, IN)]
    eps, _ = run(samples, activation_delay_s=2.0)
    assert [e.kind for e in eps] == [GLANCE, DISTRACTION, GLANCE]
