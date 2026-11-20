"""Admin -> JSearch analytics: the request budget, the provider's own count, and what the
requests bought (jobs returned / new / relevant), per day and per search. Read-only: building
this page never calls JSearch (refreshing the provider's usage is a separate, explicit action)."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from backend.db import ApiCall, SearchQuery, utcnow
from backend.job_schemas import ApiCallOut, JSearchAnalyticsOut, UsageDay, WordingYield
from backend.services import api_budget, jsearch_usage, search_plan, search_settings
from backend.services.sources import JSEARCH


def variant_of(c: ApiCall) -> str:
    """The wording a request used. Requests before Phase 2.6 were all plain."""
    if c.variant:
        return c.variant
    return f"plain · exp {'on' if 'job_requirements' in (c.params or {}) else 'off'}"


def call_out(c: ApiCall, queries: dict[int, str]) -> ApiCallOut:
    # The text actually sent beats the search's label (wording may differ per request).
    return ApiCallOut(id=c.id, at=c.at, query=(c.params or {}).get("query") or queries.get(c.query_id or -1),
                      purpose=c.purpose, page=c.page, params=c.params or {}, status=c.status,
                      http_status=c.http_status, results=c.results, new_jobs=c.new_jobs,
                      relevant_jobs=c.relevant_jobs, error=c.error, variant=variant_of(c))


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
    )
