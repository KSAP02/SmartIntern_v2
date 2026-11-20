"""What the provider says about our JSearch quota: OpenWeb Ninja's /usage endpoint.

GET https://api.openwebninja.com/usage?api_id=jsearch (header x-api-key) returns your plan,
billing period and remaining quota. It is not a job search; we still call it sparingly: on
demand from Admin -> JSearch analytics (at most once a minute) and before a scan when the
stored answer is older than `STALE_AFTER`.

The answer's exact shape isn't documented where we could read it, so it is stored raw and the
common fields (plan, period, limit, used, remaining) are picked out by name. When "remaining"
is known, the request budget never plans past it (`api_budget.quota`).
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import col, func, select

from backend.db import ApiCall, get_meta, new_session, set_meta, utcnow
from backend.job_schemas import ProviderUsageOut

KEY = "jsearch_provider_usage"
MIN_INTERVAL = timedelta(seconds=60)
STALE_AFTER = timedelta(hours=6)
TRUST_FOR = timedelta(days=7)  # older answers are shown but no longer cap the budget


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _load() -> dict | None:
    with new_session() as s:
        raw = get_meta(s, KEY)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _flatten(data: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(data, dict):
        return [kv for k, v in data.items() for kv in _flatten(v, f"{prefix}.{k}" if prefix else str(k))]
    if isinstance(data, list):
        return [kv for i, v in enumerate(data) for kv in _flatten(v, f"{prefix}[{i}]")]
    return [(prefix, data)]


def _num(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\d+(\.\d+)?\s*", v):
        return int(float(v))
    return None


def _pick(flat: list[tuple[str, Any]], pattern: str, *, numeric: bool, exclude: str | None = None):
    rx, ex = re.compile(pattern, re.I), re.compile(exclude, re.I) if exclude else None
    for path, v in flat:
        leaf = path.rsplit(".", 1)[-1]
        if rx.search(leaf) and not (ex and ex.search(leaf)):
            if numeric:
                n = _num(v)
                if n is not None:
                    return n
            elif isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _plan_name(flat: list[tuple[str, Any]]) -> str | None:
    """OpenWeb Ninja nests it: data.plan.nickname ("Basic"); fall back to any plan/tier string."""
    for want in ("nickname", "name", "key"):
        for path, v in flat:
            parts = path.lower().split(".")
            if parts[-1] == want and any(p in ("plan", "tier", "subscription") for p in parts[:-1]) and isinstance(v, str) and v.strip():
                return v.strip()
    return _pick(flat, r"^(plan|tier|subscription)$", numeric=False)


def period() -> tuple[datetime, datetime] | None:
    """The provider's current billing period (start, end) if known and still running."""
    c = _load()
    if not c or c.get("data") is None:
        return None
    p = parse(c["data"])
    try:
        start = _aware(datetime.fromisoformat(str(p["period_start"]).replace("Z", "+00:00")))
        end = _aware(datetime.fromisoformat(str(p["period_end"]).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None
    return (start, end) if start <= utcnow() < end else None


def parse(data: Any) -> dict:
    """Pick the common fields out of whatever /usage returned."""
    flat = _flatten(data)
    remaining = _pick(flat, r"remain|left|available", numeric=True)
    limit = _pick(flat, r"limit|quota|allowance|included|total", numeric=True, exclude=r"remain|left|used")
    used = _pick(flat, r"used|usage|consumed|spent", numeric=True, exclude=r"remain|left")
    if remaining is None and limit is not None and used is not None:
        remaining = max(0, limit - used)
    return {
        "plan": _plan_name(flat),
        "period_start": _pick(flat, r"(period|billing|cycle).*start|start", numeric=False),
        "period_end": _pick(flat, r"(period|billing|cycle).*end|end|reset|renew", numeric=False),
        "limit": limit, "used": used, "remaining": remaining,
    }


def summary() -> ProviderUsageOut:
    c = _load() or {}
    parsed = parse(c.get("data")) if c.get("data") is not None else {}
    fetched = c.get("fetched_at")
    return ProviderUsageOut(
        fetched_at=fetched, error=c.get("error"), **parsed,
        raw=[(p, v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
             for p, v in _flatten(c.get("data"))] if c.get("data") is not None else [],
    )


def remaining_now(session) -> int | None:
    """Provider's remaining quota minus our requests since it answered; None if unknown/old."""
    c = _load()
    if not c or c.get("error") or c.get("data") is None or not c.get("fetched_at"):
        return None
    rem = parse(c["data"]).get("remaining")
    fetched = _aware(datetime.fromisoformat(c["fetched_at"]))
    if rem is None or utcnow() - fetched > TRUST_FOR:
        return None
    since = int(session.exec(select(func.count()).select_from(ApiCall)
                             .where(ApiCall.api == "jsearch", col(ApiCall.at) > fetched)).one())
    return max(0, rem - since)


def refresh(force: bool = False) -> ProviderUsageOut:
    """Ask OpenWeb Ninja. `force` still respects the one-a-minute floor."""
    from backend.services import search_settings
    from backend.services.sources import JSEARCH, JSearchError, SourceHttp

    c = _load() or {}
    last = c.get("checked_at")
    if last and utcnow() - _aware(datetime.fromisoformat(last)) < MIN_INTERVAL:
        return summary()
    if not force and c.get("fetched_at") and utcnow() - _aware(datetime.fromisoformat(c["fetched_at"])) < STALE_AFTER:
        return summary()
    cfg = search_settings.load("sources")
    now = utcnow().isoformat()
    if cfg.provider != "openwebninja":
        c.update(checked_at=now, error="Usage can only be read with an OpenWeb Ninja key (provider = openwebninja).")
    elif not JSEARCH.configured():
        c.update(checked_at=now, error="JSEARCH_API_KEY is not set in the root .env.")
    else:
        try:
            with SourceHttp(timeout=cfg.timeout_seconds, max_retries=0) as http:
                data = JSEARCH.usage(http)
            c = {"checked_at": now, "fetched_at": now, "data": data, "error": None}
        except JSearchError as e:
            c.update(checked_at=now, error=str(e))
    with new_session() as s:
        set_meta(s, KEY, json.dumps(c, default=str))
        s.commit()
    return summary()


def refresh_if_stale() -> None:
    """Before a scan: refresh a stale answer; never let this stop the scan."""
    try:
        refresh(force=False)
    except Exception:  # noqa: BLE001
        pass
