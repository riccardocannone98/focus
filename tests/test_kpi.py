from datetime import date, datetime, timezone

import pytest

from focus_guard.stats.kpi import (
    clip,
    compute_kpis,
    days_in,
    distractions_by_hour,
    focus_rate_by_day,
    intersect,
    merge,
    period_bounds,
    subtract,
    total,
)
from focus_guard.stats.store import DISTRACTION, GLANCE, PAUSE, SESSION, EventRow

UTC = timezone.utc
H = 3600.0


def ts(day, hour, minute=0, second=0):
    return datetime(2026, 9, day, hour, minute, second, tzinfo=UTC).timestamp()


def ev(kind, start, end, _id=[0]):
    _id[0] += 1
    return EventRow(_id[0], kind, start, end)


# --- intervalli ---------------------------------------------------------------

def test_merge():
    assert merge([(5, 6), (0, 2), (1, 3), (3, 4), (7, 7)]) == [(0, 4), (5, 6)]


def test_subtract():
    assert subtract([(0, 10)], [(2, 3), (5, 7)]) == [(0, 2), (3, 5), (7, 10)]
    assert subtract([(0, 10)], [(-5, 15)]) == []
    assert subtract([(0, 4), (6, 10)], [(3, 7)]) == [(0, 3), (7, 10)]
    assert subtract([(0, 10)], []) == [(0, 10)]


def test_intersect_clip_total():
    assert intersect([(0, 5), (8, 12)], [(3, 10)]) == [(3, 5), (8, 10)]
    assert clip([(0, 5), (8, 12)], 2, 9) == [(2, 5), (8, 9)]
    assert total([(0, 2), (5, 6)]) == 3


# --- KPI ----------------------------------------------------------------------

@pytest.fixture
def day_events():
    """Sessione 9:00-11:00 con pausa 10:00-10:30 → 90 min attivi."""
    return [
        ev(SESSION, ts(28, 9), ts(28, 11)),
        ev(PAUSE, ts(28, 10), ts(28, 10, 30)),
        ev(GLANCE, ts(28, 9, 5), ts(28, 9, 5, 1)),  # 1 s
        ev(GLANCE, ts(28, 9, 6), ts(28, 9, 6, 1)),  # 1 s
        ev(DISTRACTION, ts(28, 9, 20), ts(28, 9, 20, 10)),  # 10 s
        ev(DISTRACTION, ts(28, 10, 40), ts(28, 10, 40, 30)),  # 30 s
    ]


def test_compute_kpis(day_events):
    k = compute_kpis(day_events, ts(28, 0), ts(29, 0))
    assert k.active_min == pytest.approx(90)
    out_s = 1 + 1 + 10 + 30
    assert k.focus_rate_pct == pytest.approx(100 * (5400 - out_s) / 5400)
    assert (k.distractions, k.glances) == (2, 2)
    assert k.avg_distraction_s == pytest.approx(20)
    assert k.max_distraction_s == pytest.approx(30)
    # strisce senza distrazioni: 9:00-9:20, 9:20:10-10:00 (39m50s), 10:30-10:40, 10:40:30-11:00
    assert k.longest_streak_min == pytest.approx(39 + 50 / 60)
    assert k.distractions_per_hour == pytest.approx(2 / 1.5)


def test_kpis_clipped_to_period(day_events):
    k = compute_kpis(day_events, ts(28, 9, 30), ts(28, 10, 45))
    # attivo: 9:30-10:00 + 10:30-10:45 = 45 min
    assert k.active_min == pytest.approx(45)
    assert k.distractions == 1  # conta solo quella iniziata nel periodo
    assert k.focus_rate_pct == pytest.approx(100 * (2700 - 30) / 2700)


def test_kpis_empty_period():
    k = compute_kpis([], 0, H)
    assert k.active_min == 0
    assert k.focus_rate_pct is None
    assert k.avg_distraction_s is None and k.max_distraction_s is None
    assert k.distractions_per_hour is None
    assert k.longest_streak_min == 0


def test_out_time_during_pause_is_not_counted():
    events = [
        ev(SESSION, 0, 100),
        ev(PAUSE, 40, 60),
        ev(GLANCE, 35, 45),  # metà cade nella pausa
    ]
    k = compute_kpis(events, 0, 100)
    assert k.active_min == pytest.approx(80 / 60)
    assert k.focus_rate_pct == pytest.approx(100 * 75 / 80)


def test_overlapping_sessions_are_not_double_counted():
    events = [ev(SESSION, 0, 100), ev(SESSION, 50, 150)]
    assert compute_kpis(events, 0, 1000).active_min == pytest.approx(150 / 60)


# --- grafici --------------------------------------------------------------------

def test_distractions_by_hour(day_events):
    counts = distractions_by_hour(day_events, ts(28, 0), ts(29, 0), UTC)
    assert len(counts) == 24
    assert counts[9] == 1 and counts[10] == 1 and sum(counts) == 2


def test_focus_rate_by_day():
    events = [
        ev(SESSION, ts(26, 9), ts(26, 10)),
        ev(DISTRACTION, ts(26, 9, 30), ts(26, 9, 36)),  # 6 min su 60 → 90%
        ev(SESSION, ts(28, 23), ts(29, 1)),  # attraversa la mezzanotte
    ]
    rows = focus_rate_by_day(events, ts(26, 0), ts(29, 12), UTC)
    assert [d for d, _ in rows] == [date(2026, 9, d) for d in (26, 27, 28, 29)]
    rates = dict(rows)
    assert rates[date(2026, 9, 26)] == pytest.approx(90)
    assert rates[date(2026, 9, 27)] is None
    assert rates[date(2026, 9, 28)] == pytest.approx(100)
    assert rates[date(2026, 9, 29)] == pytest.approx(100)


def test_period_bounds():
    now = ts(28, 15, 30)
    assert period_bounds("today", now, UTC) == (ts(28, 0), now)
    assert period_bounds("7d", now, UTC) == (ts(22, 0), now)
    assert period_bounds("30d", now, UTC)[0] == datetime(2026, 8, 30, tzinfo=UTC).timestamp()
    with pytest.raises(KeyError):
        period_bounds("year", now, UTC)


def test_days_in():
    assert days_in(ts(28, 0), ts(29, 0), UTC) == [date(2026, 9, 28)]
    assert len(days_in(*period_bounds("7d", ts(28, 12), UTC), UTC)) == 7


# --- confronto con il periodo precedente -------------------------------------------

from focus_guard.stats.kpi import compare, previous_bounds  # noqa: E402


def test_previous_bounds_today_is_yesterday_until_same_hour():
    now = ts(28, 15, 30)
    assert previous_bounds("today", now, UTC) == (ts(27, 0), ts(27, 15, 30))


def test_previous_bounds_7d_and_30d_same_duration_just_before():
    now = ts(28, 15, 30)
    lo, hi = period_bounds("7d", now, UTC)
    plo, phi = previous_bounds("7d", now, UTC)
    assert (plo, phi) == (ts(15, 0), ts(21, 15, 30))
    assert phi - plo == hi - lo
    plo30, _ = previous_bounds("30d", now, UTC)
    assert plo30 == datetime(2026, 7, 31, tzinfo=UTC).timestamp()


def test_compare():
    up = compare(12, 10, higher_is_better=True)
    assert up.diff == 2 and up.relative == pytest.approx(0.2) and up.improved is True
    assert compare(12, 10, higher_is_better=False).improved is False  # es. più distrazioni
    assert compare(8, 10, higher_is_better=False).improved is True
    flat = compare(5, 5, True)
    assert flat.diff == 0 and flat.improved is None
    assert compare(3, 0, True).relative is None and compare(3, 0, True).improved is True
    assert compare(None, 4, True) == compare(4, None, True)
    assert compare(None, 4, True).diff is None
