"""Registro eventi in SQLite locale.

Contiene solo tipi di evento e timestamp (secondi epoch): nessuna immagine,
nessun dato biometrico. Il file resta sul disco locale (data/focus_guard.db).

Tipi di evento (tutti intervalli start_ts..end_ts):
    session      tracking attivo (da Avvia a Ferma/uscita)
    pause        pausa dentro una sessione
    glance       sguardo fuori area rientrato prima dell'allarme
    distraction  uscita che ha fatto scattare l'allarme (dall'uscita al rientro)

Le righe di sessione e pausa vengono create all'inizio e la loro fine
viene aggiornata periodicamente (touch): se l'app si chiude di colpo si
perde al massimo l'ultimo intervallo di aggiornamento.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SESSION = "session"
PAUSE = "pause"
GLANCE = "glance"
DISTRACTION = "distraction"
KINDS = (SESSION, PAUSE, GLANCE, DISTRACTION)

CSV_LABELS = {
    SESSION: "sessione",
    PAUSE: "pausa",
    GLANCE: "sguardo_fuori",
    DISTRACTION: "distrazione",
}

SCHEMA_VERSION = 1
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT NOT NULL CHECK (kind IN ({", ".join(repr(k) for k in KINDS)})),
    start_ts REAL NOT NULL,
    end_ts   REAL NOT NULL CHECK (end_ts >= start_ts)
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events (start_ts);
CREATE INDEX IF NOT EXISTS idx_events_end ON events (end_ts);
"""


@dataclass(frozen=True)
class EventRow:
    id: int
    kind: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class EventLog:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), isolation_level=None)  # autocommit
        self._db.executescript(_SCHEMA)
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _check_kind(kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"tipo di evento sconosciuto: {kind}")

    def add(self, kind: str, start: float, end: float) -> int:
        self._check_kind(kind)
        cur = self._db.execute(
            "INSERT INTO events (kind, start_ts, end_ts) VALUES (?, ?, ?)",
            (kind, start, max(start, end)),
        )
        return int(cur.lastrowid)

    def begin(self, kind: str, ts: float) -> int:
        """Apre un intervallo (sessione o pausa); la fine va aggiornata con touch/finish."""
        return self.add(kind, ts, ts)

    def touch(self, event_id: int, ts: float) -> None:
        self._db.execute(
            "UPDATE events SET end_ts = MAX(start_ts, ?) WHERE id = ?", (ts, event_id)
        )

    finish = touch  # stessa operazione, nome più leggibile a fine intervallo

    def query(self, start: float | None = None, end: float | None = None) -> list[EventRow]:
        """Eventi che si sovrappongono a [start, end)."""
        sql = "SELECT id, kind, start_ts, end_ts FROM events WHERE 1=1"
        params: list[float] = []
        if end is not None:
            sql += " AND start_ts < ?"
            params.append(end)
        if start is not None:
            sql += " AND end_ts >= ?"
            params.append(start)
        sql += " ORDER BY start_ts, id"
        return [EventRow(*row) for row in self._db.execute(sql, params)]

    def export_csv(
        self, path: Path, start: float | None = None, end: float | None = None
    ) -> int:
        """CSV per Excel italiano: separatore ';', decimali con virgola, UTF-8 con BOM."""
        rows = self.query(start, end)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["id", "tipo", "inizio", "fine", "durata [s]"])
            for r in rows:
                writer.writerow(
                    [
                        r.id,
                        CSV_LABELS[r.kind],
                        _fmt_ts(r.start),
                        _fmt_ts(r.end),
                        f"{r.duration:.1f}".replace(".", ","),
                    ]
                )
        return len(rows)


def _fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
