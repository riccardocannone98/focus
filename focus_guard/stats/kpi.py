"""KPI calcolati dagli eventi con aritmetica sugli intervalli (puro).

Definizioni (tutti i tempi ritagliati sul periodo selezionato):
    tempo attivo       = sessioni - pause
    tempo fuori area   = sguardi fuori + distrazioni, dentro il tempo attivo
    tasso di focus     = (tempo attivo - tempo fuori area) / tempo attivo
    striscia di focus  = intervallo attivo continuo più lungo senza distrazioni
                         (gli sguardi brevi sotto il ritardo di attivazione sono tollerati)
    durata distrazione = dall'uscita dello sguardo al rientro
Gli episodi sono contati nel periodo in cui iniziano.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Iterable, Sequence

from focus_guard.stats.store import DISTRACTION, GLANCE, PAUSE, SESSION, EventRow

Interval = tuple[float, float]

PERIODS = {"today": 1, "7d": 7, "30d": 30}


# --- aritmetica sugli intervalli ---------------------------------------------

def merge(intervals: Iterable[Interval]) -> list[Interval]:
    """Unione ordinata di intervalli (quelli sovrapposti o adiacenti si fondono)."""
    out: list[list[float]] = []
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def clip(intervals: Iterable[Interval], lo: float, hi: float) -> list[Interval]:
    return [(max(s, lo), min(e, hi)) for s, e in intervals if min(e, hi) > max(s, lo)]


def subtract(base: Sequence[Interval], cut: Sequence[Interval]) -> list[Interval]:
    """base meno cut (entrambi uniti e ordinati)."""
    result: list[Interval] = []
    cut = merge(cut)
    for s, e in merge(base):
        cursor = s
        for cs, ce in cut:
            if ce <= cursor or cs >= e:
                continue
            if cs > cursor:
                result.append((cursor, cs))
            cursor = max(cursor, ce)
            if cursor >= e:
                break
        if cursor < e:
            result.append((cursor, e))
    return result


def intersect(a: Sequence[Interval], b: Sequence[Interval]) -> list[Interval]:
    a, b = merge(a), merge(b)
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if e > s:
            out.append((s, e))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def total(intervals: Iterable[Interval]) -> float:
    return sum(e - s for s, e in intervals)


# --- periodi e giorni ---------------------------------------------------------

def _local(ts: float, tz: tzinfo | None) -> datetime:
    return datetime.fromtimestamp(ts, tz)


def _midnight(d: date, tz: tzinfo | None) -> float:
    return datetime.combine(d, time(0), tz).timestamp()


def period_bounds(period: str, now: float, tz: tzinfo | None = None) -> Interval:
    """[mezzanotte di N-1 giorni fa, adesso) per today / 7d / 30d."""
    days = PERIODS[period]
    first_day = _local(now, tz).date() - timedelta(days=days - 1)
    return _midnight(first_day, tz), now


def days_in(start: float, end: float, tz: tzinfo | None = None) -> list[date]:
    d, last = _local(start, tz).date(), _local(max(start, end - 1e-6), tz).date()
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


# --- KPI ------------------------------------------------------------------------

@dataclass(frozen=True)
class Kpis:
    active_min: float  # Tempo di sessione attiva [min]
    focus_rate_pct: float | None  # Tasso di focus [%]
    distractions: int  # N. distrazioni [n]
    glances: int  # N. sguardi fuori senza allarme [n]
    avg_distraction_s: float | None  # Durata media distrazione [s]
    max_distraction_s: float | None  # Distrazione più lunga [s]
    longest_streak_min: float  # Striscia di focus più lunga [min]
    distractions_per_hour: float | None  # Distrazioni per ora di sessione [n/h]


def _of(events: Iterable[EventRow], kind: str) -> list[Interval]:
    return [(e.start, e.end) for e in events if e.kind == kind]


def active_intervals(events: Sequence[EventRow], lo: float, hi: float) -> list[Interval]:
    return clip(subtract(merge(_of(events, SESSION)), merge(_of(events, PAUSE))), lo, hi)


def compute_kpis(events: Sequence[EventRow], lo: float, hi: float) -> Kpis:
    active = active_intervals(events, lo, hi)
    active_s = total(active)
    out = merge(_of(events, GLANCE) + _of(events, DISTRACTION))
    out_s = total(intersect(out, active))

    distractions = [e for e in events if e.kind == DISTRACTION and lo <= e.start < hi]
    glances = [e for e in events if e.kind == GLANCE and lo <= e.start < hi]
    durations = [e.duration for e in distractions]

    focus_segments = subtract(active, _of(events, DISTRACTION))
    longest = max((e - s for s, e in focus_segments), default=0.0)

    return Kpis(
        active_min=active_s / 60,
        focus_rate_pct=100 * (active_s - out_s) / active_s if active_s > 0 else None,
        distractions=len(distractions),
        glances=len(glances),
        avg_distraction_s=sum(durations) / len(durations) if durations else None,
        max_distraction_s=max(durations) if durations else None,
        longest_streak_min=longest / 60,
        distractions_per_hour=len(distractions) / (active_s / 3600) if active_s > 0 else None,
    )


def distractions_by_hour(
    events: Sequence[EventRow], lo: float, hi: float, tz: tzinfo | None = None
) -> list[int]:
    """Numero di distrazioni per fascia oraria (0-23, ora locale di inizio)."""
    counts = [0] * 24
    for e in events:
        if e.kind == DISTRACTION and lo <= e.start < hi:
            counts[_local(e.start, tz).hour] += 1
    return counts


def focus_rate_by_day(
    events: Sequence[EventRow], lo: float, hi: float, tz: tzinfo | None = None
) -> list[tuple[date, float | None]]:
    """Tasso di focus [%] per ciascun giorno del periodo (None se nessuna attività)."""
    result = []
    for d in days_in(lo, hi, tz):
        day_lo = max(lo, _midnight(d, tz))
        day_hi = min(hi, _midnight(d + timedelta(days=1), tz))
        rate = compute_kpis(events, day_lo, day_hi).focus_rate_pct
        result.append((d, rate))
    return result


# --- confronto con il periodo precedente ------------------------------------------

def previous_bounds(period: str, now: float, tz: tzinfo | None = None) -> Interval:
    """Stesso periodo spostato indietro della sua durata in giorni.

    Oggi → ieri dalla mezzanotte alla stessa ora; 7 giorni → i 7 giorni
    prima, fino alla stessa ora; idem per 30 giorni.
    """
    lo, hi = period_bounds(period, now, tz)
    days = timedelta(days=PERIODS[period])
    return (
        (_local(lo, tz) - days).timestamp(),
        (_local(hi, tz) - days).timestamp(),
    )


@dataclass(frozen=True)
class Delta:
    diff: float | None  # corrente - precedente (None se manca un valore)
    relative: float | None  # variazione relativa (None se precedente = 0 o mancante)
    improved: bool | None  # None = invariato o non confrontabile


def compare(current: float | None, previous: float | None, higher_is_better: bool) -> Delta:
    if current is None or previous is None:
        return Delta(None, None, None)
    diff = current - previous
    relative = diff / previous if previous else None
    if abs(diff) < 1e-9:
        return Delta(0.0, 0.0 if previous else None, None)
    return Delta(diff, relative, (diff > 0) == higher_is_better)
