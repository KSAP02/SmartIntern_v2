"""What a settings change sets in motion (runs in the background).

- Search Settings (criteria) saved in the app: `apply()`.
- config.toml changed, from System -> Admin settings or by hand: `sync_config()`. It compares
  what the pipeline was last run with (kept in `meta`) against the file, so a change made
  while the app was down is caught on the next start too.
"""
from __future__ import annotations

import json
import logging

from backend.config import get_tuning, tuning_stamp
from backend.db import get_meta, new_session, set_meta
from backend.job_schemas import SearchSettings
from backend.services import compass, job_search, memory, role_contexts, search_settings

log = logging.getLogger(__name__)

APPLIED_KEY = "config_applied"  # meta: {"matching": {...}, "embedding": {...}} last acted on
_seen = {"stamp": None}


def apply(before: SearchSettings, after: SearchSettings, changed: set[str]) -> None:
    if "criteria" in changed and before.criteria.roles != after.criteria.roles:
        # New roles get their role context first (one model call each), so the re-score below
        # already compares jobs with it. Written outside the pipeline lock: scans aren't blocked.
        try:
            role_contexts.ensure_for_roles(after.criteria.roles)
        except Exception as e:  # noqa: BLE001 - Memory -> Role contexts shows the failure / retry
            log.warning("writing role contexts failed: %s", e.__class__.__name__)
    with job_search.pipeline_lock:  # waits for a running scan / remap to finish
        _apply(before, after, changed)


def _apply(before: SearchSettings, after: SearchSettings, changed: set[str]) -> None:
    try:
        if "criteria" in changed:
            with new_session() as s:
                job_search.reapply_criteria(s)
                job_search.process_new(s, {})
                if before.criteria.roles != after.criteria.roles:
                    job_search.rescore_relevance(s, roles_changed=True)
                    s.commit()
            compass.map_pending()
    except Exception as e:  # noqa: BLE001 - background work; the next scan retries
        log.warning("applying settings change failed: %s", e)


def _snapshot() -> dict:
    return {
        "matching": search_settings.load("matching").model_dump(),
        "embedding": get_tuning().embedding.model_dump(),
    }


def sync_config(force: bool = False) -> bool:
    """Act on config.toml changes that matter right away. Returns True if anything ran.

    Embedding model / dimensions or the metric changed -> rebuild vectors, re-embed, re-map.
    Other matching values changed -> re-score relevance and re-map. Sources, schedule, limits
    and the LLM settings are read when used, so they need nothing here.
    """
    stamp = tuning_stamp()
    if not force and stamp == _seen["stamp"]:
        return False
    _seen["stamp"] = stamp
    now = _snapshot()
    with new_session() as s:
        saved = get_meta(s, APPLIED_KEY)
    prev = json.loads(saved) if saved else None
    if prev == now:
        return False
    with job_search.pipeline_lock:
        try:
            search_settings.apply_metric()
            rebuilt = memory.check_embedding_signature()  # model, dimensions or metric changed
            if rebuilt:
                with new_session() as s:
                    job_search.process_new(s, {})
                compass.map_pending()
            elif prev is not None and prev.get("matching") != now["matching"]:
                compass.remap_all()
        except Exception as e:  # noqa: BLE001 - retried on the next change / start
            log.warning("applying config.toml change failed: %s", e)
            _seen["stamp"] = None
            return False
        with new_session() as s:
            set_meta(s, APPLIED_KEY, json.dumps(now, sort_keys=True))
            s.commit()
    log.info("config.toml change applied")
    return True
