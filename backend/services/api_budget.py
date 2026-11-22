"""Request budget for JSearch (free plan: 200 requests a month; one request = 10 jobs).

Usage is counted from `api_calls`, never kept as a loose counter. A call is written with
status "sending" *before* the HTTP request goes out (under a lock), so two scans or a crash
can't overspend: a request that may have reached JSearch is always counted.

Rules (config.toml [scout.search.sources], Admin settings -> JSearch):
- `monthly_limit`: hard cap per calendar month (UTC), all purposes together.
- `reserve`: kept back from scans for calibration / manual tests.
- `daily_limit_on` + `daily_limit`: on = scans spend at most this many requests a day, from
  today, whatever was spent before (overspending earlier never blocks a day); off = scans may use
  everything left. The quota also reports the even pace and how far ahead / behind it you are.
- `max_per_scan`: one scan never spends more.
- After an HTTP 429 JSearch is paused until the next UTC day.
"""
from __future__ import annotations

import calendar
import json
import threading
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, func, select

from backend.db import ApiCall, get_meta, new_session, set_meta, utcnow
from backend.job_schemas import QuotaOut, SourcesSettings

API = "jsearch"
BLOCK_KEY = "jsearch_blocked_until"
_lock = threading.Lock()


class BudgetExhausted(Exception):
    """No request may be spent now; the message says why and when it frees up."""


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(now: datetime) -> datetime:
    days = calendar.monthrange(now.year, now.month)[1]
    return month_start(now) + timedelta(days=days)


def day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _count(session: Session, since: datetime, purpose: str | None = None, api: str = API) -> int:
    q = select(func.count()).select_from(ApiCall).where(ApiCall.api == api, col(ApiCall.at) >= since)
    if purpose:
        q = q.where(ApiCall.purpose == purpose)
    return int(session.exec(q).one())


def _block_key(api: str) -> str:
    return BLOCK_KEY if api == API else f"{api}_blocked_until"


def blocked_until(session: Session, now: datetime, api: str = API) -> datetime | None:
    raw = get_meta(session, _block_key(api))
    if not raw:
        return None
    try:
        until = _aware(datetime.fromisoformat(json.loads(raw)))
    except (ValueError, TypeError):
        return None
    return until if until > now else None


def block_for_today(now: datetime | None = None, api: str = API) -> None:
    now = now or utcnow()
    with new_session() as s:
        set_meta(s, _block_key(api), json.dumps((day_start(now) + timedelta(days=1)).isoformat()))
        s.commit()


def billing_window(now: datetime, api: str = API) -> tuple[datetime, datetime]:
    """The quota period: the provider's billing period when known (JSearch via OpenWeb Ninja:
    from your subscription day, e.g. the 17th to the 17th), else the calendar month (UTC)."""
    if api == API:
        from backend.services import jsearch_usage  # local: avoids an import cycle

        p = jsearch_usage.period()
        if p and p[0] <= now < p[1]:
            return p
    return month_start(now), next_month_start(now)


def quota(session: Session, cfg: SourcesSettings, now: datetime | None = None, api: str = API) -> QuotaOut:
    """One metered source's budget right now (`api` = the source's name; its settings in `cfg`)."""
    now = _aware(now or utcnow())
    m0, m1 = billing_window(now, api)
    d0 = day_start(now)
    month_used = _count(session, m0, api=api)
    scan_used = _count(session, m0, "scan", api)
    today_scan = _count(session, d0, "scan", api)
    hard_left = max(0, cfg.monthly_limit - month_used)
    scan_left = max(0, min(cfg.monthly_limit - cfg.reserve - scan_used, hard_left))
    if cfg.daily_limit_on:
        allowance = max(0, min(scan_left, cfg.daily_limit - today_scan))
    else:
        allowance = scan_left
    # How the period is going, for Admin settings (shown whether the limit is on or off).
    days_left = max(1, (day_start(m1 - timedelta(seconds=1)) - d0).days + 1)
    total_days = max(1, (day_start(m1 - timedelta(seconds=1)) - day_start(m0)).days + 1)
    elapsed = min(total_days, (d0 - day_start(m0)).days + 1)
    scan_budget = max(0, cfg.monthly_limit - cfg.reserve)
    even_pace = -(-(scan_left + today_scan) // days_left)  # ceil
    expected = round(scan_budget * elapsed / total_days)
    provider_left = None
    if api == API:  # only JSearch reports its own remaining quota (OpenWeb Ninja /usage)
        from backend.services import jsearch_usage  # local: it imports the db / sources layer

        provider_left = jsearch_usage.remaining_now(session)
    if provider_left is not None:  # the provider's count wins when it is lower than ours
        allowance = min(allowance, provider_left)
        hard_left = min(hard_left, provider_left)
    blocked = blocked_until(session, now, api)
    if blocked or not cfg.enabled:
        allowance = 0
    return QuotaOut(
        month_used=month_used, monthly_limit=cfg.monthly_limit, reserve=cfg.reserve,
        today_used=_count(session, d0, api=api), today_allowance=allowance,
        scan_allowance=min(allowance, max(0, cfg.max_per_scan)),
        daily_limit=cfg.daily_limit, daily_limit_on=cfg.daily_limit_on, max_per_scan=cfg.max_per_scan,
        resets_on=m1.date().isoformat(), blocked_until=blocked,
        days_left=days_left, scan_budget=scan_budget, scan_used=scan_used, scan_left=scan_left,
        even_pace=even_pace, expected_by_today=expected, ahead_by=scan_used - expected,
        provider_remaining=provider_left,
    )


def reserve_call(cfg: SourcesSettings, *, purpose: str, params: dict, page: int = 1,
                 query_id: int | None = None, scan_id: str | None = None, now: datetime | None = None,
                 variant: str | None = None, api: str = API, label: str = "JSearch") -> int:
    """Count one request before it is sent. Returns the api_calls id. Raises BudgetExhausted.

    Scans may spend today's allowance; calibration may also use the reserve; nothing may pass
    the monthly limit. `api` / `label` = the metered source (JSearch by default)."""
    with _lock, new_session() as s:
        q = quota(s, cfg, now, api)
        if q.blocked_until:
            raise BudgetExhausted(f"{label} is paused until {q.blocked_until:%Y-%m-%d %H:%M} UTC (HTTP 429).")
        if q.provider_remaining is not None and q.provider_remaining <= 0:
            raise BudgetExhausted(f"The provider reports no {label} requests left in your plan.")
        if q.month_used >= cfg.monthly_limit:
            raise BudgetExhausted(f"{label} monthly limit reached ({q.month_used}/{cfg.monthly_limit}); resets {q.resets_on}.")
        if purpose == "scan" and q.today_allowance <= 0:
            raise BudgetExhausted(f"{label}: today's requests (Requests per day) are used; it continues tomorrow.")
        call = ApiCall(api=api, purpose=purpose, params=dict(params), page=page, query_id=query_id,
                       scan_id=scan_id, at=_aware(now or utcnow()), variant=variant)
        s.add(call)
        s.commit()
        s.refresh(call)
        return int(call.id)


def finish_call(call_id: int, *, ok: bool, results: int = 0, new_jobs: int = 0,
                http_status: int | None = None, error: str | None = None) -> None:
    with new_session() as s:
        call = s.get(ApiCall, call_id)
        if call:
            call.status = "ok" if ok else "error"
            call.results, call.new_jobs = results, new_jobs
            call.http_status = http_status if http_status is not None else (200 if ok else None)
            call.error = (error or None) and error[:300]
            s.add(call)
            s.commit()


def recent_calls(session: Session, limit: int = 50, api: str | None = API) -> list[ApiCall]:
    """Newest first; `api=None` = every source."""
    q = select(ApiCall)
    if api is not None:
        q = q.where(ApiCall.api == api)
    return list(session.exec(q.order_by(col(ApiCall.at).desc()).limit(limit)).all())
