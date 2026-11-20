"""The JSearch query plan: Search criteria -> exactly which requests a scan sends, and why.

Built before any call (a dry run builds the same plan and sends nothing):
1. Queries = one per *Roles you want* x place in Locations ("AI Engineer in India"); kept in
   `search_queries` with their yield history. Filters can change without losing history.
2. Parameters = everything JSearch can filter itself (§6 of the Phase 2.5 plan): country,
   job types -> employment_types, Remote-only -> work_from_home, Experience level ->
   job_requirements, recency -> date_posted (incremental: only since the query last ran),
   excluded publishers. The rest is filtered by our rules after the call.
3. Allocation = due searches, best first (staleness x yield), within the budget
   (`api_budget.quota().scan_allowance`). Searches that keep finding nothing back off.
"""
from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from backend.db import ApiCall, Job, SearchQuery, utcnow
from backend.job_schemas import (
    PlannedCall,
    QueryOut,
    ScanSelection,
    ScheduleSettings,
    SearchCriteria,
    SearchPlanOut,
    SourcesSettings,
)
from backend.services import api_budget, search_settings
from backend.services.job_facts import country_name, resolve_place
from backend.services.sources import JSEARCH
from backend.services.role_contexts import role_key, search_terms
from backend.services.sources.jsearch import build_query, employment_types

DUE_SLACK = timedelta(hours=2)  # a daily search scheduled at 07:00 is still due at 06:00 next day
RECENT_RUNS = 5
NEW_QUERY_PRIOR = 1.0  # assumed relevant jobs per request before a search has history


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


# ── 1. queries ─────────────────────────────────────────────────────────────────


def query_key(role: str, place: str, country: str) -> str:
    raw = "|".join(x.strip().lower() for x in (role, place, country))
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


MAX_COMBINED = 8  # roles in one OR query (Google ignores very long queries)


def clean_roles(roles: list[str]) -> list[str]:
    return list(dict.fromkeys(r.strip() for r in roles if r and r.strip()))


def places_for(criteria: SearchCriteria, sources: SourcesSettings) -> list[tuple[str, str]]:
    """(place as written, ISO country) per Location; no Locations -> the Search API country."""
    places: list[tuple[str, str]] = []
    for loc in criteria.locations:
        code, _city = resolve_place(loc)
        if code and (loc.strip(), code) not in places:
            places.append((loc.strip(), code))
    if not places:
        code = (sources.api_country or "IN").strip().upper()
        places = [(country_name(code) or code, code)]
    return places


def wanted_queries(criteria: SearchCriteria, sources: SourcesSettings) -> list[tuple[str, str, str]]:
    """(role, place, country) per role x place. Unplaceable locations are skipped."""
    roles = clean_roles(criteria.roles)
    return [(role, place, code) for place, code in places_for(criteria, sources) for role in roles]


def pick_roles(criteria: SearchCriteria, wanted: list[str] | None) -> list[str]:
    """`wanted` (or criteria.auto_roles; empty = all) limited to your roles, in your roles' order."""
    mine = clean_roles(criteria.roles)
    want = {w.strip().lower() for w in (wanted if wanted is not None else criteria.auto_roles) if w and w.strip()}
    return [r for r in mine if not want or r.lower() in want]


def role_query(session: Session, role: str, place: str, code: str) -> SearchQuery:
    """The search "<role> in <place>" (existing row and its history, or a new one). A place
    used only in one Scan now is deactivated again by the next `sync` (history kept)."""
    key = query_key(role, place, code)
    q = session.exec(select(SearchQuery).where(SearchQuery.key == key)).first()
    if q is None:
        q = SearchQuery(key=key, role=role, place=place, country=code)
    q.active = True
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def for_this_scan(criteria: SearchCriteria, selection: ScanSelection) -> SearchCriteria:
    """Your Search criteria with the Scan now picker's changes (this scan only)."""
    changes = {k: getattr(selection, k) for k in ("locations", "job_types", "workplace")
               if getattr(selection, k) is not None}
    if "experience_years" in selection.model_fields_set:  # sent, even empty (= any)
        changes["experience_years"] = selection.experience_years
    if "locations" in changes:
        changes["locations"] = list(dict.fromkeys(x.strip() for x in changes["locations"] if x and x.strip()))
    return criteria.model_copy(update=changes)


def combined_query(session: Session, roles: list[str], place: str, code: str) -> SearchQuery:
    """The search for "A OR B OR C in <place>" (one row per role set, so it keeps its own stats).
    A single role is just that role's normal search."""
    roles = roles[:MAX_COMBINED]
    if len(roles) == 1:
        return role_query(session, roles[0], place, code)
    else:
        key = "or:" + query_key("|".join(sorted(r.lower() for r in roles)), place, code)[:17]
        q = session.exec(select(SearchQuery).where(SearchQuery.key == key)).first()
        if q is None:
            q = SearchQuery(key=key, role=" OR ".join(roles), roles=list(roles), place=place, country=code)
    q.active = True
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def sync(session: Session, criteria: SearchCriteria, sources: SourcesSettings) -> list[SearchQuery]:
    """Make `search_queries` match the criteria: add new searches, (re)activate wanted ones,
    deactivate the rest (history kept, so re-adding a role resumes its stats)."""
    wanted = {query_key(*w): w for w in wanted_queries(criteria, sources)}
    rows = {q.key: q for q in session.exec(select(SearchQuery)).all() if not q.roles}  # combined: on demand
    for key, (role, place, code) in wanted.items():
        q = rows.get(key)
        if q is None:
            q = SearchQuery(key=key, role=role, place=place, country=code)
            rows[key] = q
        q.active = True
        session.add(q)
    for key, q in rows.items():
        if key not in wanted and q.active:
            q.active = False
            session.add(q)
    session.commit()
    return [rows[k] for k in wanted]


def query_text(q: SearchQuery, wording: str = "plain",
               terms: dict[str, tuple[list[str], list[str]]] | None = None, extra: list[str] | None = None) -> str:
    """The text sent as `query` (Phase 2.6 wording; the JSearch adapter writes the syntax).
    plain: the role(s) as written · exact: quoted · titles: each role's search titles (Memory
    -> Role contexts) quoted in one OR group · titles_keywords: + the first keyword."""
    roles = list(q.roles or []) or [q.role]
    titles: list[str] = []
    keywords: list[str] = []
    for r in roles:
        t, k = (terms or {}).get(role_key(r), ([], []))
        titles += (t or [r]) if wording in ("titles", "titles_keywords") else [r]
        keywords += k
    words = (keywords[:1] if wording == "titles_keywords" else []) + list(extra or [])
    return build_query(titles, q.place, exact=wording != "plain", keywords=words or None)


def query_extra(criteria: SearchCriteria) -> list[str]:
    """Words your criteria add to the default query: only internships -> "internship"."""
    return ["internship"] if criteria.job_types == ["internship"] else []


# ── 2. parameters ──────────────────────────────────────────────────────────────


BUCKETS = ("today", "3days", "week", "month", "all")


def _bucket(days: float) -> str:
    for limit, bucket in ((1, "today"), (3, "3days"), (7, "week"), (31, "month")):
        if days <= limit:
            return bucket
    return "all"


def _ago(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    return f"{max(1, round(hours))} hour{'s' if round(hours) > 1 else ''}" if hours < 48 else f"{round(hours / 24)} days"


def date_window(last_success_at: datetime | None, criteria: SearchCriteria, schedule: ScheduleSettings,
                now: datetime, floor: str = "today") -> tuple[str, str]:
    """(bucket, why in plain words). Smallest JSearch bucket covering the time since this search
    last succeeded, but never narrower than `floor` (min_date_posted; a 'today' window returned
    0-1 jobs), and never wider than Posted within / recency."""
    caps = [(d, why) for d, why in ((criteria.posted_within_days, "Posted within, Search criteria"),
                                    (schedule.recency_days, "recency limit, Admin → Schedule")) if d]
    cap_days, cap_why = min(caps) if caps else (31, "default")
    cap = _bucket(cap_days)
    window = cap_days
    last = _aware(last_success_at)
    if last is not None:
        window = min(window, max(1, math.ceil((now - last).total_seconds() / 86400)))
        why = f"This search last ran {_ago(now - last)} ago, so “{_bucket(window)}” covers what's new since"
    else:
        why = f"First run of this search: the widest allowed, {cap_days} days ({cap_why})"
    bucket = _bucket(window)
    floor = floor if floor in BUCKETS else "today"
    floor = min(floor, cap, key=BUCKETS.index)  # Posted within still wins over the floor
    out = max(bucket, floor, key=BUCKETS.index)
    if out != bucket:
        why += f"; raised to the recency floor “{floor}” (Admin → JSearch)"
    return out, why + "."


def date_posted(last_success_at: datetime | None, criteria: SearchCriteria, schedule: ScheduleSettings,
                now: datetime, floor: str = "today") -> str:
    return date_window(last_success_at, criteria, schedule, now, floor)[0]


WORDING_LABEL = {"plain": "Plain", "exact": "Exact title", "titles": "Title group", "titles_keywords": "Titles + keyword"}
LEVELS = {"no_experience": "no experience", "under_3_years_experience": "under 3 years"}


def clean_query(text: str) -> str:
    """A query you typed: whitespace collapsed, at most 300 characters (Google ignores long ones)."""
    return " ".join((text or "").split())[:300]


def param_sources(q: SearchQuery, p: dict, criteria: SearchCriteria, sources: SourcesSettings, *, wording: str,
                  default_query: str, date_why: str) -> dict[str, str]:
    """Where each sent value came from, in plain words (your settings -> this parameter)."""
    roles = list(q.roles or []) or [q.role]
    who = f"Role {roles[0]}" if len(roles) == 1 else f"Roles {', '.join(roles)} combined with OR"
    if p["query"] != default_query:
        query = f"Typed by you for this scan (default: “{default_query}”)."
    else:
        how = WORDING_LABEL.get(wording, wording)
        titles = ", with each role's search titles from Memory ▾ Role contexts" if wording.startswith("titles") else ""
        query = f"{who} + place “{q.place}” from Locations, worded {how}{titles} (Search criteria → Query wording)."
    out = {
        "query": query,
        "country": (f"Locations: “{q.place}” → {q.country.lower()}." if criteria.locations
                    else f"Locations is empty → the Search API country in Admin → JSearch ({q.country.lower()})."),
        "date_posted": date_why,
        "page": "Fixed: one page per request (each request costs 1 of your quota).",
        "num_pages": "Fixed: one page per request.",
    }
    if "job_requirements" in p:
        levels = " + ".join(LEVELS.get(x, x) for x in str(p["job_requirements"]).split(","))
        out["job_requirements"] = (f"Your years of experience ({criteria.experience_years}) → {levels}; sent because "
                                   "“Send the experience filter” is on.")
    if "employment_types" in p:
        out["employment_types"] = f"Job types: {', '.join(t.replace('_', '-') for t in criteria.job_types)}."
    if "work_from_home" in p:
        out["work_from_home"] = "Workplace: Remote / WFH only."
    if "exclude_job_publishers" in p:
        out["exclude_job_publishers"] = "Excluded publishers, Admin → JSearch."
    return out


def not_sent(criteria: SearchCriteria, send_exp: bool) -> list[str]:
    """Your settings that don't become a JSearch parameter, and why."""
    out = []
    if not criteria.job_types:
        out.append("Job types: empty (all types), nothing sent.")
    if criteria.workplace and criteria.workplace != ["remote"]:
        out.append(f"Workplace ({', '.join(criteria.workplace)}): JSearch can only ask for remote-only; filter "
                   "the rest on the Jobs page.")
    return out


def params_for(q: SearchQuery, criteria: SearchCriteria, schedule: ScheduleSettings, sources: SourcesSettings,
               now: datetime, page: int = 1, *, wording: str = "plain",
               terms: dict[str, tuple[list[str], list[str]]] | None = None, send_experience: bool = True,
               date_override: str | None = None) -> dict:
    p: dict = {"query": query_text(q, wording, terms, query_extra(criteria)), "country": q.country.lower(), "page": page, "num_pages": 1,
               "date_posted": date_override or date_posted(q.last_success_at, criteria, schedule, now,
                                                           sources.min_date_posted)}
    # Our criteria, translated into JSearch's filter values by the JSearch adapter.
    types = employment_types(criteria.job_types)
    if types:
        p["employment_types"] = types
    if criteria.workplace == ["remote"]:
        p["work_from_home"] = "true"
    # No experience filter since 2026-11-20: years are a filter on the Jobs page (Matches), and
    # JSearch's job_requirements hid every posting Google hadn't tagged. `send_experience` is kept
    # for old callers and ignored.
    pubs = [x.strip() for x in sources.excluded_publishers if x and x.strip()]
    if pubs:
        p["exclude_job_publishers"] = ",".join(pubs)
    return p


# ── 3. allocation ──────────────────────────────────────────────────────────────


def next_due_at(q: SearchQuery) -> datetime | None:
    last = _aware(q.last_run_at)
    return None if last is None else last + timedelta(days=max(1, q.interval_days)) - DUE_SLACK


def is_due(q: SearchQuery, now: datetime) -> bool:
    due = next_due_at(q)
    return due is None or now >= due


def recent_yield(q: SearchQuery) -> float | None:
    runs = [r for r in (q.recent or [])[-RECENT_RUNS:] if r and r[0]]
    reqs = sum(r[0] for r in runs)
    return round(sum(r[2] for r in runs) / reqs, 2) if reqs else None


def score(q: SearchQuery, now: datetime) -> float:
    last = _aware(q.last_run_at)
    staleness = 10.0 if last is None else (now - last).total_seconds() / (86400 * max(1, q.interval_days))
    y = recent_yield(q)
    return staleness * (0.5 + (NEW_QUERY_PRIOR if y is None else y))


def _reason(q: SearchQuery, now: datetime) -> str:
    last = _aware(q.last_run_at)
    if last is None:
        return "never run"
    days = (now - last).total_seconds() / 86400
    return f"due (last run {days:.0f} day{'s' if round(days) != 1 else ''} ago)"


def query_out(q: SearchQuery) -> QueryOut:
    return QueryOut(
        id=q.id, role=q.role, place=q.place, country=q.country, query=query_text(q), roles=list(q.roles or []),
        active=q.active,
        enabled=q.enabled, interval_days=q.interval_days, last_run_at=q.last_run_at, next_due_at=next_due_at(q),
        runs=q.runs, results=q.results, new_jobs=q.new_jobs, relevant_jobs=q.relevant_jobs,
        yield_per_request=recent_yield(q), zero_streak=q.zero_streak,
    )


def build(session: Session, now: datetime | None = None,
          selection: ScanSelection | None = None) -> tuple[SearchPlanOut, list[tuple[SearchQuery, dict]]]:
    """The plan for the next scan: (what to show, [(query, params)] to send). Sends nothing.

    No `selection` = an automatic scan: Search criteria -> auto_roles + auto_mode, capped by
    requests per scan. With a `selection` = Scan now with your choice of roles, one request per
    role (or one combined OR request per place), capped by what's left today."""
    now = _aware(now or utcnow())
    criteria = search_settings.get(session, "criteria")
    sources = search_settings.get(session, "sources")
    schedule = search_settings.get(session, "schedule")
    queries = sync(session, criteria, sources)
    quota = api_budget.quota(session, sources, now)
    notes: list[str] = []
    configured = JSEARCH.configured()
    if not configured:
        notes.append("JSearch key missing: add JSEARCH_API_KEY to the root .env, then docker compose up -d --force-recreate backend.")
    if not sources.enabled:
        notes.append("JSearch is switched off in Admin settings.")
    if not criteria.roles:
        notes.append("Add Roles you want: JSearch searches by role.")
    live = configured and sources.enabled
    manual = selection is not None
    saved = criteria
    if manual:
        criteria = for_this_scan(criteria, selection)
        places = places_for(criteria, sources)
        unknown = [x for x in criteria.locations if not resolve_place(x)[0]]
        if unknown:
            notes.append(f"Can't place {', '.join(unknown)}: try a country or a bigger city name.")
    roles = pick_roles(criteria, selection.roles if manual else None)
    mode = ("combined" if selection.combine else "separate") if manual else criteria.auto_mode
    allowance = quota.today_allowance if manual else quota.scan_allowance
    if manual and not roles:
        notes.append("None of the chosen roles are in your Roles you want.")
    reasons: dict[int, str] = {}
    if mode == "combined" and len(roles) > 1:
        if len(roles) > MAX_COMBINED:
            notes.append(f"A combined search takes at most {MAX_COMBINED} roles; the first {MAX_COMBINED} are used.")
        candidates = [combined_query(session, roles, place, code) for place, code in places_for(criteria, sources)]
        for q in candidates:
            reasons[q.id] = f"{len(q.roles)} roles in one request"
    elif manual:  # separate: every chosen role, in your order, for each place chosen this time
        candidates = [role_query(session, role, place, code) for place, code in places for role in roles]
    else:
        pool = [q for q in queries if q.role.lower() in {r.lower() for r in roles}]
        if mode == "rotate":
            due = sorted((q for q in pool if is_due(q, now)), key=lambda q: score(q, now), reverse=True)
            if pool and not due:
                nxt = min(d for d in (next_due_at(q) for q in pool) if d)
                notes.append(f"All included searches ran recently; next one is due {nxt:%Y-%m-%d %H:%M} UTC.")
            candidates = due
        else:  # each: every included role, in your order
            candidates = pool
    take = candidates[:allowance] if live else []
    if manual and live and len(candidates) > allowance:
        notes.append(f"Your choice needs {len(candidates)} requests but only {allowance} can be spent today. "
                     "Choose fewer roles or combine them into one request.")
    if quota.blocked_until:
        notes.append(f"Paused after HTTP 429 until {quota.blocked_until:%Y-%m-%d %H:%M} UTC.")
    elif not manual and len(candidates) > len(take) and live:
        waiting = len(candidates) - len(take)
        notes.append(f"{waiting} search{'es' if waiting != 1 else ''} wait for budget (next scan / tomorrow).")
    wording = (selection.wording if manual and selection.wording else None) or criteria.query_wording
    send_exp = selection.send_experience if manual and selection.send_experience is not None         else sources.send_experience_filter
    terms = search_terms(session)
    if wording in ("titles", "titles_keywords"):
        missing = [r for r in roles if role_key(r) not in terms]
        if missing:
            notes.append(f"No search titles yet for {', '.join(missing)} (its role context isn't written): "
                         "searched by the role name.")
    date_override = selection.date_posted if manual else None
    typed = {int(k): clean_query(v) for k, v in ((selection.query_texts or {}) if manual else {}).items()}
    sends, calls = [], []
    for q in take:
        p = params_for(q, criteria, schedule, sources, now, wording=wording, terms=terms, send_experience=send_exp,
                       date_override=date_override)
        default_query = p["query"]
        if typed.get(q.id):
            p["query"] = typed[q.id]
        date_why = ("Chosen for this scan (Date posted in Scan now)." if date_override else
                    date_window(q.last_success_at, criteria, schedule, now, sources.min_date_posted)[1])
        sends.append((q, p))
        calls.append(PlannedCall(query_id=q.id, query=p["query"], default_query=default_query,
                                 custom=p["query"] != default_query, page=1, params=p,
                                 reason=reasons.get(q.id) or _reason(q, now),
                                 sources=param_sources(q, p, criteria, sources, wording=wording,
                                                       default_query=default_query, date_why=date_why)))
    exp_sent = any("job_requirements" in p for _, p in sends)
    shown = "custom" if any(c.custom for c in calls) else wording
    variant = f"{shown} · exp {'on' if exp_sent else 'off'}"
    plan = SearchPlanOut(
        configured=configured, enabled=sources.enabled, kind="manual" if manual else "auto", mode=mode,
        allowance=allowance, fits_budget=not manual or (live and 0 < len(candidates) <= allowance),
        calls=calls, queries=[query_out(q) for q in queries], quota=quota, notes=notes, variant=variant,
        not_sent=not_sent(criteria, send_exp),
    )
    from backend.services import request_explain

    request_explain.annotate(session, plan, criteria)
    return plan, sends


# ── after the calls ────────────────────────────────────────────────────────────


def record_run(session: Session, query_id: int, *, requests: int, results: int, new_jobs: int, ok: bool,
               backoff_after_empty: int, now: datetime | None = None) -> None:
    """Update a search after this scan's request(s): stats, recent window, back-off."""
    now = _aware(now or utcnow())
    q = session.get(SearchQuery, query_id)
    if q is None:
        return
    q.last_run_at = now
    q.runs += requests
    if ok:
        q.last_success_at = now
        q.results += results
        q.new_jobs += new_jobs
        q.zero_streak = q.zero_streak + 1 if new_jobs == 0 else 0
        b = max(1, backoff_after_empty)
        q.interval_days = 1 if q.zero_streak < b else (3 if q.zero_streak < 2 * b else 7)
        q.recent = [*(q.recent or []), [requests, new_jobs, 0]][-RECENT_RUNS:]
    session.add(q)
    session.commit()


def attribute_relevance(session: Session, call_ids: list[int]) -> None:
    """After the relevance gate: credit each request (and its search) with the relevant new jobs
    it found, so allocation learns which searches pay off."""
    if not call_ids:
        return
    per_query: dict[int, int] = {}
    for call in session.exec(select(ApiCall).where(col(ApiCall.id).in_(call_ids))).all():
        rel = len(session.exec(select(Job.id).where(Job.api_call_id == call.id,
                                                    col(Job.pipeline_status).in_(["relevant", "mapped"]))).all())
        call.relevant_jobs = rel
        session.add(call)
        if call.query_id:
            per_query[call.query_id] = per_query.get(call.query_id, 0) + rel
    for qid, rel in per_query.items():
        q = session.get(SearchQuery, qid)
        if q:
            q.relevant_jobs += rel
            if q.recent:
                last = list(q.recent[-1])
                last[2] = last[2] + rel
                q.recent = [*q.recent[:-1], last]
            session.add(q)
    session.commit()
