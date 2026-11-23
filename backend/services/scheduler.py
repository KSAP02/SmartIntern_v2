"""In-process timer (no extra service), every 30 s:
- picks up hand edits of settings/config.toml (re-embed / re-map if matching or models changed);
- starts a scheduled scan when one is due (System -> Admin settings -> Schedule; toggle on the
  Job Search Overview), only where AUTO_SCANS is true (.env; one backend per shared database);
- starts the next company-finder run while companies are waiting (`company_finder.auto_tick`)."""
from __future__ import annotations

import logging
import threading

from backend.db import new_session, utcnow
from backend.services import job_search, job_views, settings_effects

log = logging.getLogger(__name__)
_started = threading.Event()


def _tick() -> None:
    from backend.config import get_settings

    settings_effects.sync_config()
    if not get_settings().auto_scans:
        return
    with new_session() as s:
        due = job_views.next_scan_at(s)
    if due is not None and due <= utcnow() and job_search.running_scan_id() is None:
        log.info("auto-scan due (%s): starting", due.isoformat())
        try:
            job_search.start_scan("auto")
        except job_search.ScanRunning:
            pass


def _loop(stop: threading.Event) -> None:
    from backend.services import company_finder

    while not stop.wait(30):
        try:
            _tick()
        except Exception as e:  # noqa: BLE001 - the timer must keep running
            log.warning("auto-scan check failed: %s", e)
        try:
            company_finder.auto_tick()
        except Exception as e:  # noqa: BLE001
            log.warning("company finder check failed: %s", e)


def start(stop: threading.Event) -> None:
    if _started.is_set():
        return
    _started.set()
    threading.Thread(target=_loop, args=(stop,), name="autoscan", daemon=True).start()
