"""Macchina a stati soglia / ritardo / isteresi.

    FOCUSED --(d > exit_margin)--> LEAVING --(per activation_delay_s)--> DISTRACTED [ALERT_ON]
    LEAVING --(d <= exit_margin)--> FOCUSED
    DISTRACTED --(d <= reentry_margin)--> RETURNING --(per reentry_delay_s)--> FOCUSED [ALERT_OFF]
    RETURNING --(d > reentry_margin)--> DISTRACTED

d è la distanza con segno dal bordo dell'area (>0 fuori). Con
reentry_margin < exit_margin, per spegnere l'allarme bisogna rientrare
più a fondo di quanto serva per accenderlo: niente sfarfallio sul bordo.
Il tempo è passato dall'esterno (secondi monotoni), quindi è testabile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class FocusState(Enum):
    FOCUSED = "focused"
    LEAVING = "leaving"
    DISTRACTED = "distracted"
    RETURNING = "returning"


class FocusEvent(Enum):
    ALERT_ON = "alert_on"
    ALERT_OFF = "alert_off"


@dataclass(frozen=True)
class Thresholds:
    exit_margin: float = 0.10
    reentry_margin: float = 0.0
    activation_delay_s: float = 2.0
    reentry_delay_s: float = 0.0
    face_lost_counts_as_out: bool = True

    def __post_init__(self) -> None:
        if self.reentry_margin > self.exit_margin:
            raise ValueError("reentry_margin deve essere <= exit_margin")
        if self.activation_delay_s < 0 or self.reentry_delay_s < 0:
            raise ValueError("i ritardi devono essere >= 0")


class FocusMonitor:
    def __init__(self, thresholds: Thresholds) -> None:
        self.thresholds = thresholds
        self.state = FocusState.FOCUSED
        self._since = 0.0

    @property
    def alert_active(self) -> bool:
        return self.state in (FocusState.DISTRACTED, FocusState.RETURNING)

    def reset(self) -> FocusEvent | None:
        """Torna a FOCUSED (es. pausa). Restituisce ALERT_OFF se l'allarme era attivo."""
        was_active = self.alert_active
        self.state = FocusState.FOCUSED
        return FocusEvent.ALERT_OFF if was_active else None

    def update(self, now: float, distance: float | None) -> FocusEvent | None:
        """Elabora un campione. distance=None significa volto non rilevato."""
        t = self.thresholds
        if distance is None or math.isnan(distance):
            if not t.face_lost_counts_as_out:
                return None  # campione ignorato: lo stato resta invariato
            distance = math.inf

        s = self.state
        if s is FocusState.FOCUSED:
            if distance > t.exit_margin:
                self._enter(FocusState.LEAVING, now)
                return self._check_activation(now)
        elif s is FocusState.LEAVING:
            if distance <= t.exit_margin:
                self._enter(FocusState.FOCUSED, now)
            else:
                return self._check_activation(now)
        elif s is FocusState.DISTRACTED:
            if distance <= t.reentry_margin:
                self._enter(FocusState.RETURNING, now)
                return self._check_reentry(now)
        elif s is FocusState.RETURNING:
            if distance > t.reentry_margin:
                self._enter(FocusState.DISTRACTED, now)
            else:
                return self._check_reentry(now)
        return None

    def _enter(self, state: FocusState, now: float) -> None:
        self.state = state
        self._since = now

    def _elapsed(self, now: float) -> float:
        return max(0.0, now - self._since)

    def _check_activation(self, now: float) -> FocusEvent | None:
        if self._elapsed(now) >= self.thresholds.activation_delay_s:
            self._enter(FocusState.DISTRACTED, now)
            return FocusEvent.ALERT_ON
        return None

    def _check_reentry(self, now: float) -> FocusEvent | None:
        if self._elapsed(now) >= self.thresholds.reentry_delay_s:
            self._enter(FocusState.FOCUSED, now)
            return FocusEvent.ALERT_OFF
        return None
