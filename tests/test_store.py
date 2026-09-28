import csv
import sqlite3
from datetime import datetime

import pytest

from focus_guard.stats.store import DISTRACTION, GLANCE, PAUSE, SESSION, EventLog


@pytest.fixture
def log(tmp_path):
    db = EventLog(tmp_path / "sub" / "events.db")
    yield db
    db.close()


def test_creates_parent_folder_and_schema(tmp_path):
    path = tmp_path / "a" / "b" / "events.db"
    EventLog(path).close()
    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(events)")]
    assert cols == ["id", "kind", "start_ts", "end_ts"]  # solo tempi, nessun dato binario
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1


def test_begin_touch_finish(log):
    sid = log.begin(SESSION, 100.0)
    log.touch(sid, 130.0)
    log.finish(sid, 160.0)
    [row] = log.query()
    assert (row.kind, row.start, row.end, row.duration) == (SESSION, 100.0, 160.0, 60.0)


def test_end_never_before_start(log):
    eid = log.add(GLANCE, 100.0, 90.0)
    log.touch(eid, 50.0)
    assert log.query()[0].end == 100.0


def test_unknown_kind_rejected(log):
    with pytest.raises(ValueError):
        log.add("screenshot", 0, 1)


def test_query_overlapping_period(log):
    log.add(SESSION, 0, 100)
    log.add(PAUSE, 10, 20)
    log.add(DISTRACTION, 150, 160)
    log.add(GLANCE, 300, 301)
    assert [r.kind for r in log.query(50, 200)] == [SESSION, DISTRACTION]
    assert [r.kind for r in log.query(start=155)] == [DISTRACTION, GLANCE]
    assert len(log.query()) == 4


def test_persistence(tmp_path):
    path = tmp_path / "events.db"
    db = EventLog(path)
    db.add(DISTRACTION, 1, 2)
    db.close()
    db = EventLog(path)
    assert len(db.query()) == 1
    db.close()


def test_export_csv_excel_italian(log, tmp_path):
    start = datetime(2026, 9, 28, 9, 0, 0).timestamp()
    log.add(SESSION, start, start + 3600)
    log.add(DISTRACTION, start + 60, start + 72.5)
    out = tmp_path / "eventi.csv"
    assert log.export_csv(out) == 2
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM: Excel riconosce l'UTF-8
    with open(out, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))
    assert rows[0] == ["id", "tipo", "inizio", "fine", "durata [s]"]
    assert rows[1][1:] == ["sessione", "2026-09-28 09:00:00", "2026-09-28 10:00:00", "3600,0"]
    assert rows[2][1] == "distrazione" and rows[2][4] == "12,5"


def test_export_csv_period_filter(log, tmp_path):
    log.add(GLANCE, 0, 1)
    log.add(GLANCE, 1000, 1001)
    assert log.export_csv(tmp_path / "x.csv", start=500, end=2000) == 1
