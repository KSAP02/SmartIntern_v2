"""The host snapshot of app.db follows committed writes and is a self-contained file."""
import sqlite3

from sqlmodel import select

from backend import snapshots
from backend.config import get_settings
from backend.db import Meta, init_db, new_session, set_meta


def _read_meta(path, key):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()
    return (row[0] if row else None), mode


def test_commit_refreshes_snapshot():
    init_db()
    target = get_settings().snapshot_dir / snapshots.FILENAME

    with new_session() as s:
        set_meta(s, "snapshot_probe", "one")
        s.commit()
    snapshots.flush()
    assert _read_meta(target, "snapshot_probe") == ("one", "delete")

    with new_session() as s:
        set_meta(s, "snapshot_probe", "two")
        s.commit()
    snapshots.flush()
    assert _read_meta(target, "snapshot_probe")[0] == "two"


def test_read_only_session_does_not_schedule():
    init_db()
    snapshots.flush()
    with new_session() as s:
        s.exec(select(Meta)).all()
        s.commit()
    assert snapshots._pending is None
