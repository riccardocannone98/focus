"""Episodi "fuori area" ricavati dalle transizioni della macchina a stati.

Un episodio inizia quando lo sguardo esce (FOCUSED -> LEAVING) e finisce
quando si torna a FOCUSED. Se nel frattempo è scattato l'allarme è una
*distrazione*, altrimenti un semplice *sguardo fuori* (glance).
"""

from __future__ import annotations

from dataclasses import dataclass

from focus_guard.logic.focus import FocusState

GLANCE = "glance"
DISTRACTION = "distraction"

_ALERT_STATES = (FocusState.DISTRACTED, FocusState.RETURNING)


@dataclass(frozen=True)
class Episode:
    kind: str  # GLANCE o DISTRACTION
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class EpisodeTracker:
    def __init__(self) -> None:
        self._start: float | None = None
        self._alarmed = False

    @property
    def open(self) -> bool:
        return self._start is not None

    @property
    def started_at(self) -> float | None:
        """Inizio dell'episodio aperto (stesso orologio dei campioni), None se chiuso."""
        return self._start

    def observe(self, prev: FocusState, new: FocusState, now: float) -> Episode | None:
        """Da chiamare dopo ogni update del monitor (anche senza cambi di stato)."""
        if prev is FocusState.FOCUSED and new is not FocusState.FOCUSED:
            self._start = now
            self._alarmed = False
        if new in _ALERT_STATES:
            self._alarmed = True
        if new is FocusState.FOCUSED and prev is not FocusState.FOCUSED:
            return self.close(now)
        return None

    def close(self, now: float) -> Episode | None:
        """Chiude l'episodio aperto (rientro, pausa o stop del tracking)."""
        if self._start is None:
            return None
        kind = DISTRACTION if self._alarmed else GLANCE
        episode = Episode(kind, self._start, max(now, self._start))
        self._start = None
        self._alarmed = False
        return episode
