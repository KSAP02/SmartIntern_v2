"""Host-readable copy of the SQLite DB (e.g. data_warehouse/snapshots/app.db for notebooks).

The live DB stays where the backend runs it (the Docker volume). After any commit that
changed data, a debounced job copies it with SQLite's online backup API (always a
consistent copy, even mid-write) into a temp file, then swaps it into place. Off when
SNAPSHOT_DIR is blank. Read-only for consumers: edits to the copy are overwritten.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path

from backend.config import get_settings, get_tuning

log = logging.getLogger(__name__)
FILENAME = "app.db"

_lock = threading.Lock()
_timer: threading.Timer | None = None
_pending: Path | None = None


def enabled() -> bool:
    return get_settings().snapshot_dir is not None


def write_snapshot(db_path: Path) -> Path | None:
    """Copy db_path to <SNAPSHOT_DIR>/app.db now. Returns the target, or None if disabled."""
    target_dir = get_settings().snapshot_dir
    if target_dir is None or not db_path.is_file():
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / FILENAME

    fd, local_tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    staged = target_dir / f".{FILENAME}.tmp"
    try:
        src = sqlite3.connect(db_path, timeout=30)
        dst = sqlite3.connect(local_tmp)
        try:
            src.backup(dst)
            # A single self-contained file: no -wal/-shm sidecars next to the copy.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
            src.close()
        shutil.copyfile(local_tmp, staged)
        os.replace(staged, target)
        return target
    finally:
        Path(local_tmp).unlink(missing_ok=True)
        staged.unlink(missing_ok=True)


def _run() -> None:
    global _timer, _pending
    with _lock:
        db_path, _pending, _timer = _pending, None, None
    if db_path is None:
        return
    try:
        write_snapshot(db_path)
    except Exception as e:  # noqa: BLE001 - a snapshot must never break the app
        # Typical cause: the copy is open in another program on Windows. Next change retries.
        log.warning("DB snapshot skipped: %s", e)


def schedule(db_path: Path) -> None:
    """Request a snapshot; bursts of commits within the debounce window become one copy."""
    global _timer, _pending
    if not enabled():
        return
    with _lock:
        _pending = db_path
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(get_tuning().snapshot.debounce_seconds, _run)
        _timer.daemon = True
        _timer.start()


def flush() -> None:
    """Write a scheduled snapshot now instead of waiting (tests, shutdown)."""
    with _lock:
        if _timer is not None:
            _timer.cancel()
    _run()
