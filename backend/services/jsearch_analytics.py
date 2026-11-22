"""Admin -> JSearch analytics: the request budget, the provider's own count, and what the
requests bought (jobs returned / new / relevant), per day and per search. Read-only: building
this page never calls JSearch (refreshing the provider's usage is a separate, explicit action)."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from backend.db import ApiCall, Job, Scan, SearchQuery, utcnow
from backend.job_schemas import ApiCallOut, JSearchAnalyticsOut, ScanRequestsOut, SourceYield, UsageDay, WordingYield
from backend.services import api_budget, jsearch_usage, search_plan, search_settings
from backend.services.sources import JSEARCH


def variant_of(c: ApiCall) -> str:
    """The wording a request used. Requests before Phase 2.6 were all plain."""
    if c.variant:
        return c.variant
    return f"plain · exp {'on' if 'job_requirements' in (c.params or {}) else 'off'}"


def call_out(c: ApiCall, queries: dict[int, str]) -> ApiCallOut:
    from backend.services.sources import SOURCES

    src = SOURCES.get(c.api)
    # The text actually sent beats the search's label (wording may differ per request).
    return ApiCallOut(
        source_kind=src.kind if src else "search", source_label=src.label if src else c.api,id=c.id, at=c.at, query=(c.params or {}).get("query") or queries.get(c.query_id or -1),
                      purpose=c.purpose, page=c.page, params=c.params or {}, status=c.status,
                      http_status=c.http_status, results=c.results, new_jobs=c.new_jobs,
                      relevant_jobs=c.relevant_jobs, error=c.error,
                      variant=variant_of(c) if c.api == "jsearch" else None, api=c.api,
                      skipped_scope=c.skipped_scope, skipped_title=c.skipped_title, scan_id=c.scan_id)


def scan_history(session: Session, limit: int = 10) -> list[ScanRequestsOut]:
    """The last `limit` scans, each with every request it sent (JSearch, company boards, remote
    feeds), newest first. Requests sent outside a scan in that window are entries of their own."""
    texts = query_texts(session)
    scans = list(session.exec(select(Scan).order_by(col(Scan.started_at).desc()).limit(limit)).all())
    out: list[ScanRequestsOut] = []
    if scans:
        ids = [sc.id for sc in scans]
        by_scan: dict[str, list[ApiCall]] = defaultdict(list)
        for c in session.exec(select(ApiCall).where(col(ApiCall.scan_id).in_(ids)).order_by(col(ApiCall.id))).all():
            by_scan[c.scan_id].append(c)
        for sc in scans:
            calls = by_scan.get(sc.id, [])
            if not calls and sc.phase == "done":
                continue  # nothing was read (e.g. every source switched off)
            out.append(ScanRequestsOut(scan_id=sc.id, trigger=sc.trigger, phase=sc.phase,
                                       started_at=sc.started_at, finished_at=sc.finished_at,
                                       error=sc.error, totals=sc.totals or {},
                                       calls=[call_out(c, texts) for c in calls]))
    since = _aware(scans[-1].started_at) if len(scans) >= limit else None
    q = select(ApiCall).where(col(ApiCall.scan_id).is_(None))
    if since is not None:
        q = q.where(col(ApiCall.at) >= since)
    for c in session.exec(q.order_by(col(ApiCall.at).desc()).limit(limit)).all():
        out.append(ScanRequestsOut(scan_id=None, trigger=None, phase=c.status, started_at=c.at,
                                   finished_at=c.at, calls=[call_out(c, texts)]))
    out.sort(key=lambda r: _aware(r.started_at), reverse=True)
    return out[:limit]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def by_wording(calls: list[ApiCall]) -> list[WordingYield]:
    acc: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for c in calls:
        if c.status != "ok" or c.purpose != "scan":
            continue
        a = acc[variant_of(c)]
        a[0] += 1
        a[1] += c.results
        a[2] += c.new_jobs
        a[3] += c.relevant_jobs
    out = [WordingYield(variant=k, requests=r, results=res, new_jobs=new, relevant_jobs=rel,
                        relevant_per_request=round(rel / r, 2) if r else None)
           for k, (r, res, new, rel) in acc.items()]
    return sorted(out, key=lambda w: (-(w.relevant_per_request or 0), -w.requests))


def query_texts(session: Session) -> dict[int, str]:
    return {q.id: search_plan.query_text(q) for q in session.exec(select(SearchQuery)).all()}


def by_source(session: Session, start: datetime) -> list[SourceYield]:
    """One row per registered source: its requests since `start`, and the jobs it found."""
    from backend.services.job_views import LISTED
    from backend.services.sources import SOURCES

    calls = session.exec(select(ApiCall).where(col(ApiCall.at) >= start)).all()
    jobs = session.exec(select(Job).where(Job.status == "active")).all()
    out = []
    for name, a in SOURCES.items():
        mine = [c for c in calls if c.api == name]
        found = [j for j in jobs if any(x.get("source") == name for x in j.seen_on or [])]
        out.append(SourceYield(
            source=name, label=a.label, requests=len(mine), results=sum(c.results for c in mine),
            new_jobs=sum(c.new_jobs for c in mine), jobs=len(found),
            in_matches=sum(1 for j in found if j.pipeline_status in LISTED and j.decision is None),
            applied=sum(1 for j in found if j.decision == "applied"),
            agent_can_apply=sum(1 for j in found if (j.apply_route or "").startswith("form:")),
        ))
    return out


def build(session: Session, days: int = 30, now: datetime | None = None) -> JSearchAnalyticsOut:
    now = now or utcnow()
    days = max(1, min(days, 120))
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    cfg = search_settings.get(session, "sources")
    calls = list(session.exec(select(ApiCall).where(ApiCall.api == "jsearch", col(ApiCall.at) >= start)).all())

    by_day: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    totals = dict.fromkeys(("requests", "ok", "errors", "scan", "calibration", "results", "new_jobs", "relevant_jobs"), 0)
    for c in calls:
        at = c.at if c.at.tzinfo else c.at.replace(tzinfo=UTC)
        d = by_day[at.date().isoformat()]
        d[0] += 1
        d[1] += c.status == "error"
        d[2] += c.results
        d[3] += c.new_jobs
        d[4] += c.relevant_jobs
        totals["requests"] += 1
        totals["ok"] += c.status == "ok"
        totals["errors"] += c.status == "error"
        totals[c.purpose if c.purpose in ("scan", "calibration") else "scan"] += 1
        totals["results"] += c.results
        totals["new_jobs"] += c.new_jobs
        totals["relevant_jobs"] += c.relevant_jobs
    per_day = []
    for i in range(days):
        key = (start + timedelta(days=i)).date().isoformat()
        r, e, res, new, rel = by_day.get(key, [0, 0, 0, 0, 0])
        per_day.append(UsageDay(date=key, requests=r, errors=e, results=res, new_jobs=new, relevant_jobs=rel))
    n = totals["ok"]
    per_request = {k: (round(totals[k] / n, 2) if n else None) for k in ("results", "new_jobs", "relevant_jobs")}

    queries = sorted(session.exec(select(SearchQuery)).all(), key=lambda q: (not q.active, -q.relevant_jobs, q.id or 0))
    texts = {q.id: search_plan.query_text(q) for q in queries}
    return JSearchAnalyticsOut(
        configured=JSEARCH.configured(), provider=cfg.provider,
        quota=api_budget.quota(session, cfg, now), usage=jsearch_usage.summary(),
        per_day=per_day, totals=totals, per_request=per_request,
        queries=[search_plan.query_out(q) for q in queries],
        recent=[call_out(c, texts) for c in api_budget.recent_calls(session, 50)],
        by_wording=by_wording(calls),
        by_source=by_source(session, start),
    )
