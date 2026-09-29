"""Messaggi del banner: ironici ma mai offensivi, scelti a rotazione."""

from __future__ import annotations

import random

MESSAGES = (
    "Ehi, lo schermo è da questa parte! 👀",
    "Il soffitto è interessante, ma il lavoro di più.",
    "Il telefono può aspettare. Davvero.",
    "Houston, abbiamo perso lo sguardo.",
    "Guardare fuori dalla finestra non conta come brainstorming.",
    "Le mosche sulla parete non pagano le fatture.",
    "Pausa panoramica finita: si torna in pista!",
    "Il tuo lavoro ti manca. Tantissimo.",
    "Lo so, fuori è più bello. Ancora un piccolo sforzo!",
    "Occhi sul pezzo, campione!",
)


class MessagePicker:
    """Scelta casuale senza ripetere il messaggio precedente."""

    def __init__(self, messages: tuple[str, ...] = MESSAGES, rng: random.Random | None = None):
        if not messages:
            raise ValueError("serve almeno un messaggio")
        self._messages = messages
        self._rng = rng or random.Random()
        self._last: str | None = None

    def pick(self) -> str:
        candidates = [m for m in self._messages if m != self._last] or list(self._messages)
        self._last = self._rng.choice(candidates)
        return self._last


def format_elapsed(seconds: float) -> str:
    """Tempo trascorso come m:ss (oppure h:mm:ss oltre l'ora)."""
    total = max(0, int(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
