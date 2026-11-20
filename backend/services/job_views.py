"""Read side of Job Search: lists (apply preset ⑦), detail, overview numbers."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, col, func, select

from backend.db import FetchRun, Job, JobLedger, JobRequirement, JobSource, MemoryCard, Scan, utcnow
from backend.job_schemas import (
    ApplyPreset,
    CardRef,
    Coverage,
    DayCount,
    FetchRunOut,
    JobCard,
    JobDetail,
    JobsOut,
    OverviewOut,
    RequirementOut,
    ScanOut,
    SeenOn,
    SourceOut,
)
from backend.services import role_contexts, search_settings
from backend.services.job_text import normalize_company
from backend.services.skills_vocab import normalize_skill
from backend.services.sources import ADAPTERS

PERIOD_PER_YEAR = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}
LISTED = ("relevant", "mapped")


# ── apply preset ───────────────────────────────────────────────────────────────


def _yearly_usd(amount: float | None, currency: str | None, period: str | None, rates: dict[str, float]) -> float | None:
    if amount is None or not currency or currency.upper() not in rates:
        return None
    return amount * rates[currency.upper()] * PERIOD_PER_YEAR.get(period or "year", 1)


def _months(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(month|week)", text, re.I)
    if not m:
        return None
    n = float(m.group(1))
    return n if m.group(2).lower().startswith("month") else n / 4.33


def preset_check(job: Job, p: ApplyPreset) -> tuple[bool, list[str]]:
    """(fits, reasons it doesn't). Unknown values fit unless include_unknown is off."""
    misses: list[str] = []

    def unknown(label: str) -> None:
        if not p.include_unknown:
            misses.append(f"{label} not stated")

    if p.pay:
        if job.compensation_type is None:
            unknown("Pay")
        elif job.compensation_type not in p.pay:
            misses.append({"unpaid": "Unpaid", "stipend": "Stipend only", "paid": "Paid"}[job.compensation_type])
    if p.salary_min is not None or p.salary_max is not None:
        rates = search_settings.currency_rates()
        lo = _yearly_usd(job.salary_min if job.salary_min is not None else job.salary_max, job.salary_currency, job.salary_period, rates)
        hi = _yearly_usd(job.salary_max if job.salary_max is not None else job.salary_min, job.salary_currency, job.salary_period, rates)
        want_lo = _yearly_usd(p.salary_min, p.salary_currency, p.salary_period, rates)
        want_hi = _yearly_usd(p.salary_max, p.salary_currency, p.salary_period, rates)
        if lo is None:
            unknown("Salary")
        elif want_lo is not None and hi is not None and hi < want_lo:
            misses.append("Pays below your range")
        elif want_hi is not None and lo > want_hi:
            misses.append("Pays above your range")
    if p.min_fit is not None:
        fit = (job.coverage or {}).get("fit")
        if fit is None:
            unknown("Fit")
        elif fit < p.min_fit:
            misses.append(f"Fit {fit}% (< {p.min_fit}%)")
    if p.seniority:
        if job.seniority is None:
            unknown("Seniority")
        elif job.seniority not in p.seniority:
            misses.append(f"Seniority: {job.seniority}")
    if p.max_years_experience is not None:
        if job.min_years_experience is None:
            unknown("Experience")
        elif job.min_years_experience > p.max_years_experience:
            misses.append(f"Asks {job.min_years_experience:g}+ years")
    if p.needs_visa_sponsorship:
        if job.visa_sponsorship is None:
            unknown("Visa sponsorship")
        elif job.visa_sponsorship == "no":
            misses.append("No visa sponsorship")
    if p.max_internship_months is not None and job.category == "internship":
        months = _months(job.internship_duration)
        if months is None:
            unknown("Internship duration")
        elif months > p.max_internship_months:
            misses.append(f"Internship {months:g} months")
    if p.only_companies:
        wanted = {normalize_company(x) for x in p.only_companies}
        if normalize_company(job.company_name) not in wanted:
            misses.append("Not in your company list")
    return not misses, misses


# ── cards and detail ───────────────────────────────────────────────────────────


def _card_titles(session: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {c.id: c.title for c in session.exec(select(MemoryCard).where(col(MemoryCard.id).in_(ids))).all()}


def searched_places(session: Session, jobs: list[Job]) -> dict[int, str]:
    """api_call_id -> the place that request searched (its search's place)."""
    from backend.db import ApiCall, SearchQuery

    ids = {j.api_call_id for j in jobs if j.api_call_id}
    if not ids:
        return {}
    calls = session.exec(select(ApiCall).where(col(ApiCall.id).in_(ids))).all()
    qids = {c.query_id for c in calls if c.query_id}
    places = {q.id: q.place for q in session.exec(select(SearchQuery).where(col(SearchQuery.id).in_(qids))).all()} if qids else {}
    return {c.id: places[c.query_id] for c in calls if c.query_id in places}


def job_card(job: Job, preset: ApplyPreset, titles: dict[int, str], places: dict[int, str] | None = None) -> JobCard:
    from backend.services.job_facts import place_check

    fits, misses = preset_check(job, preset)
    place = (places or {}).get(job.api_call_id) if job.api_call_id else None
    return JobCard(
        id=job.id, title=job.title, company_name=job.company_name, location_text=job.location_text,
        category=job.category, workplace_type=job.workplace_type, country_codes=job.country_codes or [],
        remote_regions=job.remote_regions or [], compensation_type=job.compensation_type,
        salary_min=job.salary_min, salary_max=job.salary_max, salary_currency=job.salary_currency,
        salary_period=job.salary_period, seniority=job.seniority, min_years_experience=job.min_years_experience,
        first_seen_at=job.first_seen_at,
        source_published_at=job.source_published_at,
        seen_on=[SeenOn(source=s.get("source", ""), job_url=s.get("job_url")) for s in job.seen_on or []],
        relevance=job.relevance,
        role_score=job.role_score, role_match=job.role_match,
        coverage=Coverage(**job.coverage) if job.coverage else None, pipeline_status=job.pipeline_status,
        status_reason=job.status_reason, decision=job.decision, decided_at=job.decided_at,
        relevance_override=job.relevance_override,
        searched_place=place,
        place_check=place_check(place, job.location_text, job.country_codes, job.workplace_type),
        expired=job.status == "expired",
        fits_preset=fits, preset_misses=misses, job_url=job.job_url, apply_url=job.apply_url,
    )


def _view_filter(view: str):
    """Which jobs a Jobs-page tab shows. Undecided relevant jobs are "matches"; a decision moves a
    job to its own tab whatever its pipeline status (you may override the filters)."""
    if view in ("selected", "applied", "discarded"):
        return Job.decision == view
    if view in ("not_relevant", "excluded"):
        return (Job.pipeline_status == view) & (Job.decision == None)  # noqa: E711
    return col(Job.pipeline_status).in_(LISTED) & (Job.decision == None)  # noqa: E711


def list_jobs(session: Session, q: str | None = None, category: str | None = None, workplace: str | None = None,
              view: str = "matches", max_years: float | None = None) -> JobsOut:
    preset = search_settings.get(session, "preset")
    jobs = list(session.exec(select(Job).where(_view_filter(view)).order_by(col(Job.first_seen_at).desc())).all())
    if category:
        jobs = [j for j in jobs if j.category == category]
    if workplace:
        jobs = [j for j in jobs if j.workplace_type == workplace]
    if max_years is not None and view == "matches":  # Matches only; jobs that don't state years stay
        jobs = [j for j in jobs if j.min_years_experience is None or j.min_years_experience <= max_years]
    if q:
        needle = q.lower()
        jobs = [j for j in jobs if needle in f"{j.title} {j.company_name or ''} {j.location_text or ''}".lower()]
    titles = _card_titles(session, {j.relevance_card_id for j in jobs if j.relevance_card_id})
    places = searched_places(session, jobs)
    cards = [job_card(j, preset, titles, places) for j in jobs]
    # Phase 2.6: best match with the role's context first, then the title match.
    key = lambda c: ((c.relevance if c.relevance is not None else -1), c.role_score or 0)  # noqa: E731
    fits, other, items = [], [], []
    if view == "matches":
        fits = sorted([c for c in cards if c.fits_preset], key=key, reverse=True)
        other = sorted([c for c in cards if not c.fits_preset], key=key, reverse=True)
    elif view in ("selected", "applied", "discarded"):
        items = sorted(cards, key=lambda c: c.decided_at or c.first_seen_at, reverse=True)
    else:
        items = sorted(cards, key=lambda c: (c.role_score or 0, c.relevance if c.relevance is not None else -1), reverse=True)
    counts: dict[str, int] = {}
    undecided = list(session.exec(select(Job).where(_view_filter("matches"))).all())
    counts["fits"] = sum(preset_check(j, preset)[0] for j in undecided)
    counts["other"] = len(undecided) - counts["fits"]
    for v in ("selected", "applied", "discarded", "not_relevant", "excluded"):
        counts[v] = int(session.exec(select(func.count()).select_from(Job).where(_view_filter(v))).one())
    return JobsOut(view=view, fits=fits, other=other, items=items, counts=counts)


def job_detail(session: Session, job: Job) -> JobDetail:
    preset = search_settings.get(session, "preset")
    reqs = list(session.exec(select(JobRequirement).where(JobRequirement.job_id == job.id).order_by(JobRequirement.position)).all())
    ids = {job.relevance_card_id} | {r.best_card_id for r in reqs} | {e["card_id"] for r in reqs for e in r.evidence or []}
    titles = _card_titles(session, {i for i in ids if i})
    card = job_card(job, preset, titles, searched_places(session, [job]))

    def ref(card_id: int | None, score: float | None) -> CardRef | None:
        if card_id is None or card_id not in titles:
            return None
        return CardRef(card_id=card_id, title=titles[card_id], score=round(score or 0.0, 4))

    out_reqs = [RequirementOut(
        id=r.id, section=r.section, importance=r.importance, text=r.text, skills=r.skills or [], status=r.status,
        method=r.method, best=ref(r.best_card_id, r.best_score),
        evidence=[x for x in (ref(e["card_id"], e["score"]) for e in r.evidence or []) if x],
    ) for r in reqs]
    asked = {normalize_skill(s): s for r in reqs for s in r.skills or []}
    matched = {normalize_skill(s) for r in reqs if r.method == "exact_skill" for s in r.skills or []
               if r.status in ("met", "partial")}
    from backend.services.compass import Evidence  # local: compass imports job_search

    have = set(Evidence(session).skill_card)
    return JobDetail(
        **card.model_dump(), description_text=job.description_text or "", field_sources=job.field_sources or {},
        snippet_only=bool(job.seen_on) and all(
            getattr(ADAPTERS.get(x.get("source")), "snippet_only", False) for x in job.seen_on),
        internship_duration=job.internship_duration,
        visa_sponsorship=job.visa_sponsorship, start_date=job.start_date, apply_deadline=job.apply_deadline,
        tags=job.tags or [], requirements=out_reqs,
        matched_skills=sorted(asked[s] for s in asked if s in have or s in matched),
        missing_skills=sorted(asked[s] for s in asked if s not in have and s not in matched),
    )


# ── scans and overview ─────────────────────────────────────────────────────────


def scan_out(session: Session, scan: Scan) -> ScanOut:
    runs = session.exec(select(FetchRun).where(FetchRun.scan_id == scan.id).order_by(FetchRun.id)).all()
    return ScanOut(
        scan_id=scan.id, trigger=scan.trigger, phase=scan.phase, started_at=scan.started_at,
        finished_at=scan.finished_at, totals=scan.totals or {}, error=scan.error,
        runs=[FetchRunOut(source=r.source, company=r.company, status=r.status, fetched=r.fetched, new=r.new,
                          updated=r.updated, duplicates=r.duplicates, already_seen=r.already_seen, error=r.error,
                          started_at=r.started_at, finished_at=r.finished_at) for r in runs],
    )


def recent_scans(session: Session, limit: int = 20) -> list[ScanOut]:
    return [scan_out(session, s) for s in session.exec(select(Scan).order_by(col(Scan.started_at).desc()).limit(limit)).all()]


def sources_out(session: Session) -> list[SourceOut]:
    active = Counter()
    for job in session.exec(select(Job).where(Job.status == "active")).all():
        for s in {x.get("source") for x in job.seen_on or []}:
            active[s] += 1
    out = []
    src = search_settings.get(session, "sources")
    for name, a in ADAPTERS.items():
        row = session.get(JobSource, name)
        out.append(SourceOut(
            name=name, label=a.label, kind=a.kind, enabled=src.enabled, terms_url=a.terms_url,
            last_success_at=row.last_success_at if row else None, last_error_at=row.last_error_at if row else None,
            last_error=row.last_error if row else None, active_jobs=active[name],
            configured=getattr(a, "configured", lambda: True)(),
            setup_hint=f"Add {' and '.join(a.env_keys)} to the root .env, then docker compose up -d --force-recreate backend."
            if getattr(a, "env_keys", None) and not getattr(a, "configured", lambda: True)() else None,
        ))
    return out


def next_scan_at(session: Session, now: datetime | None = None) -> datetime | None:
    sched = search_settings.get(session, "schedule")
    if not sched.autoscan:
        return None
    try:
        tz = ZoneInfo(sched.timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local = (now or utcnow()).astimezone(tz)
    hh, mm = (int(x) for x in (sched.time or "07:00").split(":")[:2])
    slots = [local.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(hours=h)
             for h in range(-24, 49, sched.every_hours)]
    last_auto = session.exec(select(Scan).where(Scan.trigger == "auto").order_by(col(Scan.started_at).desc())).first()
    last = last_auto.started_at if last_auto else None
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=ZoneInfo("UTC"))
    # The next slot not already covered by an auto scan. A slot missed by up to 30 minutes
    # (e.g. the app was restarting) is still due.
    floor = local - timedelta(minutes=30)
    for slot in sorted(slots):
        if slot <= floor or (last is not None and last >= slot):
            continue
        return slot
    return None


def _quota(session: Session):
    from backend.services import api_budget

    return api_budget.quota(session, search_settings.get(session, "sources"))


def overview(session: Session, running_id: str | None) -> OverviewOut:
    since = (utcnow() - timedelta(days=30)).date().isoformat()
    per_day: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in session.exec(select(FetchRun).where(FetchRun.scan_date >= since)).all():
        per_day[(r.scan_date, r.source)][0] += r.fetched
        per_day[(r.scan_date, r.source)][1] += r.new
    ledger = Counter(session.exec(
        select(JobLedger.outcome).where(JobLedger.first_seen_date >= since, JobLedger.is_duplicate == False)  # noqa: E712
    ).all())
    current = list(session.exec(select(Job).where(col(Job.pipeline_status).in_(LISTED))).all())
    preset = search_settings.get(session, "preset")
    relevant = [j for j in current if j.decision != "discarded"]
    breakdown = {
        "category": Counter(j.category or "unknown" for j in relevant),
        "workplace": Counter(j.workplace_type or "unknown" for j in relevant),
        "country": Counter((j.country_codes or ["unknown"])[0] for j in relevant),
    }
    seen = sum(ledger.values())
    last = session.exec(select(Scan).where(Scan.finished_at != None).order_by(col(Scan.started_at).desc())).first()  # noqa: E711
    running = session.get(Scan, running_id) if running_id else None
    # Phase 2.6: jobs are judged against role contexts; ready = every role has one.
    roles = search_settings.get(session, "criteria").roles
    ready = role_contexts.for_roles(session, roles)
    memory_ready = all(ready.get(role_contexts.role_key(r)) is not None and ready[role_contexts.role_key(r)].status == "ready"
                       for r in roles)
    return OverviewOut(
        running=scan_out(session, running) if running else None,
        last_scan=scan_out(session, last) if last else None,
        autoscan=search_settings.get(session, "schedule").autoscan,
        next_scan_at=next_scan_at(session),
        per_day=[DayCount(date=d, source=s, found=v[0], new=v[1]) for (d, s), v in sorted(per_day.items())],
        funnel={
            "seen": seen,
            "excluded": ledger.get("excluded", 0),
            "not_relevant": ledger.get("not_relevant", 0),
            "relevant": seen - ledger.get("excluded", 0) - ledger.get("not_relevant", 0),
            "mapped": sum(j.pipeline_status == "mapped" for j in relevant),
            "fits_preset": sum(preset_check(j, preset)[0] for j in relevant),
        },
        breakdown={k: dict(v.most_common(12)) for k, v in breakdown.items()},
        sources=sources_out(session),
        quota=_quota(session),
        memory_ready=memory_ready,
    )
