"""Remote-job feeds in the scan (Phase 2.7 C1): Himalayas, RemoteJobs.org, Remotive.

Same way as the company boards: one tick box per feed in Scan now, free (no request budget),
every request logged in `api_calls` (api = the feed) so "Requests and what they found", "Why
these results" and the per-source table cover it. A feed keeps only jobs **open to India**
(its own eligibility field, `FeedAdapter.open_to_india`) whose title matches your roles (the
board pre-check). Searchable feeds get one request per role of the scan (at most
`max_queries_per_feed`); Remotive gets one request for its software category, at most every
few hours (its terms). Feed jobs age out like JSearch jobs (they are not a company's live list).
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlmodel import Session, col, select

from backend.config import get_tuning
from backend.db import ApiCall, new_session, utcnow
from backend.job_schemas import FeedsSettings, NormalizedJob, PlanSource
from backend.services import employers, search_settings
from backend.services.sources import FEEDS, SourceError, SourceHttp
from backend.services.sources.feeds import FeedAdapter

log = logging.getLogger(__name__)


def settings() -> FeedsSettings:
    raw = ((get_tuning().scout or {}).get("search") or {}).get("feeds") or {}
    return FeedsSettings(**raw)


def _roles(session: Session, selection=None) -> list[str]:
    from backend.services.job_search import clean_roles

    roles = selection.roles if selection is not None else search_settings.get(session, "criteria").roles
    return clean_roles(roles)


def queries(session: Session, feed: FeedAdapter, selection=None) -> list[str | None]:
    """What one feed is asked this scan: one query per role, or the whole feed once."""
    if not feed.searchable:
        return [None]
    return list(_roles(session, selection)[: settings().max_queries_per_feed]) or [None]


def _last_read(session: Session, name: str):
    return session.exec(select(ApiCall.at).where(ApiCall.api == name, ApiCall.status == "ok")
                        .order_by(col(ApiCall.at).desc())).first()


def _wait_hours(session: Session, feed: FeedAdapter) -> float:
    """Hours until this feed may be read again (0 = now)."""
    if not feed.min_hours_between_reads:
        return 0.0
    last = _last_read(session, feed.name)
    if last is None:
        return 0.0
    if last.tzinfo is None:
        from datetime import UTC

        last = last.replace(tzinfo=UTC)
    left = last + timedelta(hours=feed.min_hours_between_reads) - utcnow()
    return max(0.0, left.total_seconds() / 3600)


def _chosen(selection, name: str) -> bool:
    return employers.chosen(selection, name)


def planned(session: Session, selection=None) -> int:
    """Requests the feeds will make this scan."""
    if not settings().enabled:
        return 0
    return sum(len(queries(session, f, selection)) for f in FEEDS.values()
               if _chosen(selection, f.name) and _wait_hours(session, f) == 0)


def plan_rows(session: Session, selection=None) -> list[PlanSource]:
    """Scan now: one tick box per feed."""
    on = settings().enabled
    rows = []
    for name, f in FEEDS.items():
        qs = queries(session, f, selection)
        wait = _wait_hours(session, f)
        pick = _chosen(selection, name)
        if not on:
            summary = "Switched off ([scout.search.feeds] enabled = false)"
        elif not pick:
            summary = "Skipped this scan"
        elif wait:
            summary = f"Read recently · next read in {wait:.0f} h (its terms allow a few reads a day)"
        else:
            n = len(qs)
            summary = f"{n} request{'s' if n != 1 else ''} · free · remote jobs open to India"
        details = [q for q in qs if q] or ["Software jobs"]
        rows.append(PlanSource(name=name, label=f.label, kind="feed", configured=True, enabled=on and not wait,
                               chosen=on and pick and not wait, requests=0, summary=summary, details=details))
    return rows


def precheck(feed: FeedAdapter, jobs: list[NormalizedJob], phrases) -> tuple[list[NormalizedJob], int, int]:
    """(kept, left out as not open to India, left out as title not matching)."""
    kept, out_scope, out_title = [], 0, 0
    for n in jobs:
        if not feed.open_to_india(n):
            out_scope += 1
        elif not employers.title_matches(n.title, phrases):
            out_title += 1
        else:
            kept.append(n)
    return kept, out_scope, out_title


def collect(scan_id: str, totals: dict[str, int], selection=None) -> list[int]:
    """① for remote feeds. Returns the api_calls ids used."""
    from backend.services.job_search import ingest, record_call_jobs

    cfg = settings()
    if not cfg.enabled:
        return []
    call_ids: list[int] = []
    with new_session() as s:
        phrases = employers.role_phrases(s)
        sched = search_settings.get(s, "schedule")
        lim = search_settings.get(s, "limits")
        work = [(f, q) for f in FEEDS.values() if _chosen(selection, f.name) and _wait_hours(s, f) == 0
                for q in queries(s, f, selection)]
        if not work:
            return []
        with SourceHttp(timeout=cfg.timeout_seconds, max_retries=1) as http:
            for i, (f, q) in enumerate(work):
                if i and cfg.delay_seconds:
                    time.sleep(cfg.delay_seconds)
                call = ApiCall(api=f.name, purpose="scan", scan_id=scan_id,
                               params={"query": f"{q or 'Software jobs'} · {f.label} (remote, open to India)",
                                       "feed": f.name, **({"q": q} if q else {})})
                s.add(call)
                s.commit()
                s.refresh(call)
                call_ids.append(int(call.id))
                try:
                    jobs = f.fetch(http, q)
                except SourceError as err:
                    call.status, call.error = "error", str(err)[:300]
                    s.add(call)
                    s.commit()
                    totals["feed_errors"] = totals.get("feed_errors", 0) + 1
                    continue
                kept, out_scope, out_title = precheck(f, jobs, phrases)
                returned, new = [], 0
                for n in kept:
                    result = ingest(s, n, call.id, sched.recency_days, lim.repost_window_days)
                    returned.append((n, result))
                    totals[result] = totals.get(result, 0) + 1
                    new += result == "new"
                s.commit()
                record_call_jobs(s, call.id, returned)
                call.status, call.http_status, call.results, call.new_jobs = "ok", 200, len(jobs), new
                call.skipped_scope, call.skipped_title = out_scope, out_title
                s.add(call)
                s.commit()
                totals["fetched"] = totals.get("fetched", 0) + len(kept)
                totals["feed_requests"] = totals.get("feed_requests", 0) + 1
    return call_ids
