"""Job Search pipeline (Phase 2), no LLM:

  ① discover (source adapters) → ② dedupe against the ledger → ③ facts by rules + search
  criteria → ④ relevance gate (job title vs your roles; job text vs that role's context,
  Phase 2.6) → ⑤⑥ requirements + evidence map (services/compass.py) → ⑧ prune.

The apply preset (⑦) is applied when jobs are listed (services/job_views.py), never stored.
Plan: MD_files/project_build_phases/phase_2_job_discovery_and_understanding.md
"""
from __future__ import annotations

import logging
import math
import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, delete, select

from backend import vectors
from backend.db import (
    FetchRun, Job, JobLedger, JobRequirement, JobSource, MemoryCard, Scan, get_meta, new_session, set_meta, utcnow,
)
from backend.job_schemas import NormalizedJob, SearchCriteria
from backend.model import embed
from backend.services import role_contexts, search_settings
from backend.services.job_facts import derive_facts
from backend.services.job_text import (
    canonical_url, content_hash, dedupe_key, expand_abbreviations, job_plain_text, title_variants,
)
from backend.services.sources import ADAPTERS, JSEARCH, JSearchError, SourceHttp
from backend.services.sources.jsearch import PAGE_SIZE

log = logging.getLogger(__name__)

DIGEST_CHARS = 2000
# Bump when digest() changes: stored job vectors are rebuilt on start (reembed_jobs_if_needed).
DIGEST_VERSION = "2"
DIGEST_KEY = "job_digest_version"
FACT_FIELDS = (
    "category", "workplace_type", "country_codes", "remote_regions", "compensation_type", "salary_min",
    "salary_max", "salary_currency", "salary_period", "seniority", "min_years_experience",
    "internship_duration", "visa_sponsorship", "start_date", "apply_deadline",
)
_scan_lock = threading.Lock()
# One writer of pipeline state at a time: a scan, a settings re-apply and a remap must not
# interleave (a remap working from a stale job list would undo a criteria exclusion).
# Re-entrant, because a scan calls compass.map_pending, which takes it too.
pipeline_lock = threading.RLock()
_current: dict[str, str | None] = {"scan_id": None}


class ScanRunning(RuntimeError):
    pass


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _outcome(pipeline_status: str) -> str:
    return {"excluded": "excluded", "not_relevant": "not_relevant"}.get(pipeline_status, "active")


def _set_status(session: Session, job: Job, status: str, reason: str | None = None) -> None:
    job.pipeline_status, job.status_reason, job.status_changed_at, job.updated_at = status, reason, utcnow(), utcnow()
    session.add(job)
    for led in session.exec(select(JobLedger).where(JobLedger.job_id == job.id)).all():
        led.outcome = job.decision or _outcome(status)
        led.relevance, led.category, led.workplace_type = job.relevance, job.category, job.workplace_type
        led.country = (job.country_codes or [None])[0]
        led.updated_at = utcnow()
        session.add(led)


# ── sources (DB rows for adapters) ─────────────────────────────────────────────


def ensure_sources(session: Session) -> None:
    for name in ADAPTERS:
        if session.get(JobSource, name) is None:
            session.add(JobSource(name=name, enabled=True))
    session.commit()


# ── ① + ② : ingest one fetched job ────────────────────────────────────────────


def _apply_facts(job: Job, n: NormalizedJob, text: str) -> None:
    facts = derive_facts(n, text)
    for f in FACT_FIELDS:
        setattr(job, f, facts.get(f) if f not in ("country_codes", "remote_regions") else list(facts.get(f) or []))
    job.field_sources = dict(facts.get("field_sources") or {})


def ingest(session: Session, n: NormalizedJob, api_call_id: int | None, recency_days: int, repost_days: int) -> str:
    """Store one fetched job. Returns: new | updated | unchanged | duplicate | already_seen | too_old."""
    now = utcnow()
    published = _aware(n.source_published_at)
    if published and recency_days and published < now - timedelta(days=recency_days):
        return "too_old"

    led = session.exec(
        select(JobLedger).where(JobLedger.source == n.source, JobLedger.source_job_id == n.source_job_id)
    ).first()
    text = job_plain_text(n)
    chash = content_hash(n.title, text)

    if led is not None:
        job = session.get(Job, led.job_id) if led.job_id else None
        if job is None:
            return "already_seen"  # pruned or applied: the ledger remembers it
        job.last_seen_at = now
        if job.status == "expired":
            job.status = "active"
        if n.highlights and job.highlights != n.highlights:
            job.highlights = n.highlights
        if job.content_hash != chash:
            job.title, job.description_text, job.content_hash = n.title, text, chash
            _apply_facts(job, n, text)
            _reset_processing(session, job)
            session.add(job)
            return "updated"
        session.add(job)
        return "unchanged"

    url = canonical_url(n.apply_url or n.job_url)
    dkey = dedupe_key(n.company_name, n.title, n.location_text)
    match = None
    if url:
        match = session.exec(select(JobLedger).where(JobLedger.canonical_url == url).order_by(col(JobLedger.id))).first()
    if match is None:
        match = session.exec(select(JobLedger).where(JobLedger.dedupe_key == dkey).order_by(col(JobLedger.id))).first()

    repost_of: str | None = None
    if match is not None:
        existing = session.get(Job, match.job_id) if match.job_id else None
        if existing is not None:
            existing.seen_on = [*existing.seen_on, {"source": n.source, "source_job_id": n.source_job_id, "job_url": n.job_url}]
            existing.last_seen_at = now
            session.add(existing)
            session.add(JobLedger(source=n.source, source_job_id=n.source_job_id, dedupe_key=dkey, canonical_url=url,
                                  job_id=existing.id, first_seen_date=now.date().isoformat(), outcome=match.outcome,
                                  category=match.category, workplace_type=match.workplace_type, country=match.country,
                                  is_duplicate=True))
            return "duplicate"
        first = datetime.fromisoformat(match.first_seen_date).replace(tzinfo=UTC)
        if first > now - timedelta(days=repost_days):
            session.add(JobLedger(source=n.source, source_job_id=n.source_job_id, dedupe_key=dkey, canonical_url=url,
                                  first_seen_date=now.date().isoformat(), outcome=match.outcome, is_duplicate=True))
            return "already_seen"
        repost_of = match.first_seen_date

    job = Job(
        seen_on=[{"source": n.source, "source_job_id": n.source_job_id, "job_url": n.job_url}],
        dedupe_key=dkey, canonical_url=url, content_hash=chash, company_name=n.company_name,
        api_call_id=api_call_id, highlights=n.highlights, title=n.title, location_text=n.location_text,
        description_text=text,
        tags=list(n.tags), job_url=n.job_url, apply_url=n.apply_url, source_published_at=published,
        first_seen_at=now, last_seen_at=now, raw_payload=n.raw, repost_of=repost_of,
    )
    _apply_facts(job, n, text)
    session.add(job)
    session.flush()
    session.add(JobLedger(source=n.source, source_job_id=n.source_job_id, dedupe_key=dkey, canonical_url=url,
                          job_id=job.id, first_seen_date=now.date().isoformat(), outcome="active",
                          category=job.category, workplace_type=job.workplace_type,
                          country=(job.country_codes or [None])[0]))
    return "new"


def _reset_processing(session: Session, job: Job) -> None:
    """Forget derived data so the pipeline redoes the job (text changed / vectors reset)."""
    reqs = session.exec(select(JobRequirement.id).where(JobRequirement.job_id == job.id)).all()
    if reqs:
        try:
            vectors.delete("requirements", list(reqs))
        except Exception:  # noqa: BLE001 - stale vectors are harmless; ids are never reused for other text
            pass
        session.exec(delete(JobRequirement).where(JobRequirement.job_id == job.id))
    job.coverage, job.mapped_memory_version, job.relevance, job.relevance_card_id = None, None, None, None
    job.embedding_status = "pending"
    job.pipeline_status, job.status_reason, job.status_changed_at = "new", None, utcnow()


# ── ③ search criteria ──────────────────────────────────────────────────────────


def criteria_reason(job: Job, c: SearchCriteria) -> str | None:  # noqa: ARG001
    """Why the search criteria exclude this job: never, since 2026-11-20. Search criteria only shape
    the scan (query, country, date, JSearch filters); every job whose title matches your roles is
    listed, and the Jobs page filters (type, workplace) and the apply preset sort them. Kept as the
    pipeline's ③ step so a future rule has one place to live."""
    return None


# ── ④ relevance gate ───────────────────────────────────────────────────────────


def enabled_cards(session: Session) -> dict[int, MemoryCard]:
    """Your enabled memory cards (text only: since Phase 2.6 cards aren't embedded)."""
    return {c.id: c for c in session.exec(select(MemoryCard).where(MemoryCard.enabled == True)).all()  # noqa: E712
            if c.id is not None}


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb) if na and nb else 0.0


def clean_roles(roles: list[str]) -> list[str]:
    return [r.strip() for r in roles if r and r.strip()]


def score_roles(jobs: list[Job], roles: list[str]) -> None:
    """Job title vs each of "Roles you want": the best cosine and that role go on the job.
    Titles discriminate far better than the whole JD (every tech JD looks alike to a profile).
    The title is compared part by part (job_text.title_variants) and roles with abbreviations
    expanded ("ML Engineer" -> "machine learning Engineer"), so long titles and short forms
    don't blur the score."""
    roles = clean_roles(roles)
    if not roles or not jobs:
        for j in jobs:
            j.role_score, j.role_match = None, None
        return
    role_vecs = embed([expand_abbreviations(r) for r in roles])
    for i in range(0, len(jobs), 100):
        batch = jobs[i : i + 100]
        variants = [title_variants(j.title) for j in batch]
        flat = [v for vs in variants for v in vs]
        vecs = iter(embed(flat))
        for job, vs in zip(batch, variants, strict=True):
            best, who = 0.0, 0
            for _ in vs:
                tv = next(vecs)
                for k, rv in enumerate(role_vecs):
                    c = _cos(tv, rv)
                    if c > best:
                        best, who = c, k
            job.role_score, job.role_match = round(best, 4), roles[who]


def gate_reason(job: Job, m, roles_on: bool) -> str | None:
    """④ Why a job is not relevant, or None. Your override wins. The title decides (or a
    borderline title whose text also matches that role's context). No roles: nothing to judge
    by, so everything passes."""
    if job.relevance_override == "relevant":
        return None
    if job.relevance_override == "not_relevant":
        return "You marked it not relevant"
    if not roles_on:
        return None
    title, context = job.role_score or 0.0, job.relevance or 0.0
    if title >= m.role_threshold:
        return None
    if (m.borderline_role_threshold and title >= m.borderline_role_threshold
            and context >= m.borderline_context_threshold):
        return None
    return "Title doesn't match your roles"


def digest(job: Job) -> str:
    """The job text that is embedded and compared with role contexts: title + JSearch's
    Responsibilities / Qualifications when given (the posting's substance, not the company
    blurb), else the description."""
    hl = job.highlights or {}
    parts = [f"{k}:\n" + "\n".join(f"- {x}" for x in hl[k]) for k in ("Responsibilities", "Qualifications") if hl.get(k)]
    body = "\n\n".join(parts) if parts else (job.description_text or "")
    return f"{job.title}\n\n{body}"[:DIGEST_CHARS]


def context_score(job: Job, vec: list[float], ctx: dict[str, list[float]]) -> float | None:
    """Job text vs the context of the role its title matched (None: no context for that role)."""
    c = ctx.get(role_contexts.role_key(job.role_match or ""))
    return round(_cos(vec, c), 4) if c is not None and len(c) == len(vec) else None


def process_new(session: Session, totals: dict[str, int]) -> None:
    """③ criteria and ④ relevance for every job in `new`."""
    criteria = search_settings.get(session, "criteria")
    m = search_settings.get(session, "matching")
    jobs = list(session.exec(select(Job).where(Job.pipeline_status == "new", Job.status == "active")).all())
    keep: list[Job] = []
    for job in jobs:
        reason = criteria_reason(job, criteria)
        if reason:
            _set_status(session, job, "excluded", reason)
            totals["excluded"] = totals.get("excluded", 0) + 1
        else:
            keep.append(job)
    session.commit()

    if not keep:
        return
    roles = clean_roles(criteria.roles)
    ctx = role_contexts.context_vectors(session)
    for i in range(0, len(keep), 200):
        batch = keep[i : i + 200]
        vecs = embed([digest(j) for j in batch])
        vectors.upsert("jobs", [(j.id, v) for j, v in zip(batch, vecs, strict=True)])
        score_roles(batch, roles)
        for job, vec in zip(batch, vecs, strict=True):
            job.embedding_status = "embedded"
            job.relevance, job.relevance_card_id = context_score(job, vec, ctx), None
            reason = gate_reason(job, m, bool(roles))
            if reason is None:
                _set_status(session, job, "relevant")
                totals["relevant"] = totals.get("relevant", 0) + 1
            else:
                _set_status(session, job, "not_relevant", reason)
                totals["not_relevant"] = totals.get("not_relevant", 0) + 1
        session.commit()


def rescore_relevance(session: Session, roles_changed: bool = False) -> int:
    """Role contexts, thresholds or roles changed: recompute relevance from stored job vectors
    (no JD embedding). Titles are (re)embedded only when the roles changed or a job has no role
    score."""
    m = search_settings.get(session, "matching")
    roles = clean_roles(search_settings.get(session, "criteria").roles)
    jobs = list(session.exec(select(Job).where(
        col(Job.pipeline_status).in_(["relevant", "mapped", "not_relevant"]), Job.embedding_status == "embedded"
    )).all())
    if not jobs:
        return 0
    stored = vectors.get_vectors("jobs", [j.id for j in jobs])
    jobs = [j for j in jobs if j.id in stored]
    score_roles([j for j in jobs if roles_changed or (roles and j.role_score is None)], roles)
    ctx = role_contexts.context_vectors(session)
    for job in jobs:
        job.relevance, job.relevance_card_id = context_score(job, stored[job.id], ctx), None
        reason = gate_reason(job, m, bool(roles))
        if reason is None and job.pipeline_status == "not_relevant":
            _set_status(session, job, "relevant")
        elif reason is not None and job.pipeline_status != "not_relevant":
            _set_status(session, job, "not_relevant", reason)
        elif reason is not None:
            job.status_reason = reason
        session.add(job)
    session.commit()
    return len(jobs)


def reapply_criteria(session: Session) -> None:
    """Criteria changed: excluded jobs that now pass go back through the pipeline, and vice versa."""
    criteria = search_settings.get(session, "criteria")
    for job in session.exec(select(Job).where(Job.status == "active")).all():
        reason = criteria_reason(job, criteria)
        if reason and (job.pipeline_status != "excluded" or job.status_reason != reason):
            _set_status(session, job, "excluded", reason)  # also refreshes a stale reason
        elif not reason and job.pipeline_status == "excluded":
            _set_status(session, job, "new")
    session.commit()


# ── ⑧ prune ────────────────────────────────────────────────────────────────────


def delete_jobs(session: Session, jobs: list[Job], outcome: str | None = None) -> int:
    if not jobs:
        return 0
    ids = [j.id for j in jobs if j.id is not None]
    req_ids = list(session.exec(select(JobRequirement.id).where(col(JobRequirement.job_id).in_(ids))).all())
    try:
        vectors.delete("jobs", ids)
        vectors.delete("requirements", req_ids)
    except Exception as e:  # noqa: BLE001 - orphan vectors are harmless (ids never reused for other text)
        log.warning("prune: vector delete failed: %s", e)
    session.exec(delete(JobRequirement).where(col(JobRequirement.job_id).in_(ids)))
    for led in session.exec(select(JobLedger).where(col(JobLedger.job_id).in_(ids))).all():
        if outcome:
            led.outcome = outcome
        led.job_id = None
        led.updated_at = utcnow()
        session.add(led)
    for j in jobs:
        session.delete(j)
    session.commit()
    return len(ids)


def prune(session: Session) -> dict[str, int]:
    """Housekeeping after a scan. Only jobs YOU discarded are deleted; old jobs are only labelled
    "expired" (by posting age), and old raw records are dropped to keep the DB small."""
    lim = search_settings.get(session, "limits")
    now = utcnow()
    days = lambda n: now - timedelta(days=n)  # noqa: E731

    expired = 0
    for job in session.exec(select(Job).where(Job.status == "active")).all():
        posted = _aware(job.source_published_at) or _aware(job.first_seen_at)
        if posted and posted < days(lim.expire_after_days):
            job.status, job.status_changed_at = "expired", now
            session.add(job)
            expired += 1
    for job in session.exec(select(Job).where(Job.raw_payload != None, Job.first_seen_at < days(lim.raw_payload_days))).all():  # noqa: E711
        job.raw_payload = None
        session.add(job)
    session.commit()
    discarded = list(session.exec(select(Job).where(Job.decision == "discarded",
                                                    col(Job.decided_at) < days(lim.keep_discarded_days))).all())
    return {"discarded": delete_jobs(session, discarded, "discarded"), "expired": expired}


def decide(session: Session, jobs: list[Job], decision: str | None) -> None:
    """Your call on jobs: selected (agent applies later) | discarded | applied | None (undo)."""
    now = utcnow()
    for job in jobs:
        job.decision, job.decided_at = decision, (now if decision else None)
        job.hidden = decision == "discarded"
        _set_status(session, job, job.pipeline_status, job.status_reason)
    session.commit()


def record_call_jobs(session: Session, call_id: int, results: list[tuple[NormalizedJob, str]]) -> None:
    """Remember what one request returned, in JSearch's order, and what happened to each job."""
    from backend.db import ApiCallJob

    for pos, (n, outcome) in enumerate(results, start=1):
        led = session.exec(select(JobLedger).where(JobLedger.source == n.source, JobLedger.source_job_id == n.source_job_id)
                           .order_by(col(JobLedger.id).desc())).first()
        session.add(ApiCallJob(call_id=call_id, position=pos, source_job_id=n.source_job_id,
                               job_id=led.job_id if led else None, title=n.title, company_name=n.company_name,
                               location_text=n.location_text, outcome=outcome))
    session.commit()


def backfill_call_jobs() -> int:
    """One-off (start-up): requests made before api_call_jobs existed get their list rebuilt from
    the jobs they created (outcome "new"; jobs they returned that we already had are unknown)."""
    from backend.db import ApiCall, ApiCallJob

    added = 0
    with new_session() as s:
        recorded = set(s.exec(select(ApiCallJob.call_id)).all())
        for call in s.exec(select(ApiCall).where(ApiCall.status == "ok")).all():
            if call.id in recorded:
                continue
            for pos, j in enumerate(s.exec(select(Job).where(Job.api_call_id == call.id).order_by(Job.id)).all(), start=1):
                sid = next((x.get("source_job_id") for x in j.seen_on or [] if x.get("source") == "jsearch"), "") or ""
                s.add(ApiCallJob(call_id=call.id, position=pos, source_job_id=sid, job_id=j.id, title=j.title,
                                 company_name=j.company_name, location_text=j.location_text, outcome="new"))
                added += 1
        s.commit()
    return added


def purge_other_sources(keep: str = "jsearch") -> dict[str, int]:
    """Delete everything gathered by sources other than `keep` (Phase 2.5: JSearch only):
    their jobs (+ requirements and vectors), ledger rows, fetch runs, and scans left without
    any fetch run. A job also listed by `keep` stays, minus the other listings. Back up first."""
    with pipeline_lock, new_session() as s:
        jobs = list(s.exec(select(Job)).all())
        drop, trimmed = [], 0
        for j in jobs:
            mine = [x for x in (j.seen_on or []) if x.get("source") == keep]
            if not mine:
                drop.append(j)
            elif len(mine) != len(j.seen_on or []):
                j.seen_on = mine
                s.add(j)
                trimmed += 1
        s.commit()
        out = {"jobs": delete_jobs(s, drop), "jobs_trimmed": trimmed}
        out["ledger"] = len(s.exec(select(JobLedger.id).where(JobLedger.source != keep)).all())
        s.exec(delete(JobLedger).where(JobLedger.source != keep))
        out["fetch_runs"] = len(s.exec(select(FetchRun.id).where(FetchRun.source != keep)).all())
        s.exec(delete(FetchRun).where(FetchRun.source != keep))
        live = set(s.exec(select(FetchRun.scan_id)).all())
        old_scans = [sc for sc in s.exec(select(Scan)).all() if sc.id not in live and sc.id != _current["scan_id"]]
        for sc in old_scans:
            s.delete(sc)
        out["scans"] = len(old_scans)
        s.exec(delete(JobSource).where(JobSource.name != keep))
        s.commit()
    return out


TITLE_SCORING_VERSION = "2"  # bump when score_roles changes: existing jobs are re-scored on start
CRITERIA_VERSION = "4"  # bump when criteria_reason changes: jobs are re-checked on start (2: no location; 3: fresh reasons; 4: criteria never exclude)


def set_relevance_override(job_id: int, override: str | None) -> None:
    """Your call on a job's relevance, then re-run the checks for it (its override wins)."""
    from backend.services import compass

    with pipeline_lock:
        with new_session() as s:
            job = s.get(Job, job_id)
            if job is None:
                return
            job.relevance_override = override
            _reset_processing(s, job)  # back through ③ criteria and ④ gate with the override
            s.commit()
            process_new(s, {})
        compass.map_pending()


def rescore_titles_if_needed() -> None:
    """Start-up: re-score every job's title when the scoring method changed (embeddings only)."""
    from backend.db import get_meta, set_meta
    from backend.services import compass

    with new_session() as s:
        if get_meta(s, "title_scoring_version") == TITLE_SCORING_VERSION:
            return
    with pipeline_lock:
        with new_session() as s:
            rescore_relevance(s, roles_changed=True)
            set_meta(s, "title_scoring_version", TITLE_SCORING_VERSION)
            s.commit()
        compass.map_pending()


def reapply_criteria_if_needed() -> None:
    """Start-up: what the criteria exclude changed (CRITERIA_VERSION) -> re-check every job; jobs no
    longer excluded go through the title check again."""
    from backend.db import get_meta, set_meta
    from backend.services import compass

    with new_session() as s:
        if get_meta(s, "criteria_version") == CRITERIA_VERSION:
            return
    with pipeline_lock:
        with new_session() as s:
            reapply_criteria(s)
            process_new(s, {})
            set_meta(s, "criteria_version", CRITERIA_VERSION)
            s.commit()
        compass.map_pending()


def reembed_jobs_if_needed() -> int:
    """On start: the job text that is embedded changed (DIGEST_VERSION) -> re-embed stored jobs
    and re-score them against the role contexts. A few hundred jobs cost well under a cent."""
    with new_session() as s:
        if get_meta(s, DIGEST_KEY) == DIGEST_VERSION:
            return 0
    done = 0
    with pipeline_lock:
        with new_session() as s:
            jobs = list(s.exec(select(Job).where(Job.embedding_status == "embedded")).all())
            for i in range(0, len(jobs), 200):
                batch = jobs[i : i + 200]
                vecs = embed([digest(j) for j in batch])
                vectors.upsert("jobs", [(j.id, v) for j, v in zip(batch, vecs, strict=True)])
                done += len(batch)
            if jobs:
                rescore_relevance(s)
            set_meta(s, DIGEST_KEY, DIGEST_VERSION)
            s.commit()
    return done


def migrate_hidden_to_decision() -> None:
    """One-off (start-up): jobs hidden before decisions existed become "discarded"."""
    with new_session() as s:
        rows = list(s.exec(select(Job).where(Job.hidden == True, Job.decision == None)).all())  # noqa: E711, E712
        for job in rows:
            job.decision, job.decided_at = "discarded", job.hidden_at or utcnow()
            s.add(job)
        if rows:
            s.commit()


# ── the scan ───────────────────────────────────────────────────────────────────


def running_scan_id() -> str | None:
    return _current["scan_id"]


def start_scan(trigger: str = "manual", selection=None) -> str:
    """Start a scan in the background. `selection` (ScanSelection) = Scan now with your choice
    of roles; None = the automatic-scan plan."""
    if not _scan_lock.acquire(blocking=False):
        raise ScanRunning("A scan is already running.")
    scan_id = utcnow().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    _current["scan_id"] = scan_id
    with new_session() as s:
        s.add(Scan(id=scan_id, trigger=trigger, phase="fetching", totals={}))
        s.commit()
    threading.Thread(target=_run, args=(scan_id, trigger, selection), name=f"scan-{scan_id}", daemon=True).start()
    return scan_id


def _set_phase(scan_id: str, phase: str, totals: dict[str, int], error: str | None = None, done: bool = False) -> None:
    with new_session() as s:
        scan = s.get(Scan, scan_id)
        if scan:
            scan.phase, scan.totals, scan.error = phase, dict(totals), error
            if done:
                scan.finished_at = utcnow()
            s.add(scan)
            s.commit()


def fetch_jsearch(scan_id: str, trigger: str, totals: dict[str, int], selection=None) -> list[int]:
    """① for JSearch: build the plan, then spend at most the scan's allowance on it.
    Page 1 for each planned search first; then, with what's left, page 2 for searches whose
    page 1 was full and mostly new ("smart" pages policy). Returns the api_calls ids used."""
    from backend.services import api_budget, jsearch_usage, search_plan

    jsearch_usage.refresh_if_stale()  # provider's quota view (not a job search)
    today = utcnow().date().isoformat()
    call_ids: list[int] = []
    with new_session() as s:
        cfg = search_settings.get(s, "sources")
        sched = search_settings.get(s, "schedule")
        lim = search_settings.get(s, "limits")
        plan, sends = search_plan.build(s, selection=selection)
        totals["planned"] = len(sends)
        run = FetchRun(scan_id=scan_id, scan_date=today, trigger=trigger, source=JSEARCH.name,
                       company=f"{len(sends)} planned")
        s.add(run)
        s.commit()
        s.refresh(run)
        if not sends:
            run.status, run.error = "ok", ("; ".join(plan.notes) or None)
            run.finished_at = utcnow()
            s.add(run)
            s.commit()
            return call_ids

        # Manual scans (Scan now with your choice) send exactly what the picker showed: no extra
        # page 2. Automatic scans may add a page 2 only within requests per scan.
        budget = len(sends) if plan.kind == "manual" else plan.allowance
        spent = 0
        page2: list[tuple[int, dict]] = []
        error: str | None = None  # the source failed (shown as source health)
        stop: str | None = None  # the budget stopped us (not an error)
        with SourceHttp(timeout=cfg.timeout_seconds, max_retries=0) as http:
            work: list[tuple[int, dict, int]] = [(q.id, params, 1) for q, params in sends]
            while work and spent < budget and error is None and stop is None:
                qid, params, page = work.pop(0)
                params = {**params, "page": page}
                try:
                    call_id = api_budget.reserve_call(cfg, purpose="scan", params=params, page=page,
                                                      query_id=qid, scan_id=scan_id, variant=plan.variant)
                except api_budget.BudgetExhausted as e:
                    stop = str(e)
                    break
                spent += 1
                call_ids.append(call_id)
                try:
                    jobs, n_results = JSEARCH.search(http, params, cfg.provider)
                except JSearchError as e:
                    api_budget.finish_call(call_id, ok=False, http_status=e.http_status, error=str(e))
                    search_plan.record_run(s, qid, requests=1, results=0, new_jobs=0, ok=False,
                                           backoff_after_empty=cfg.backoff_after_empty)
                    if e.http_status == 429:
                        api_budget.block_for_today()
                    error = str(e)  # any failure stops JSearch for this scan: don't spend more
                    break
                new = 0
                returned: list[tuple[NormalizedJob, str]] = []
                for n in jobs:
                    result = ingest(s, n, call_id, sched.recency_days, lim.repost_window_days)
                    returned.append((n, result))
                    key = {"new": "new", "updated": "updated", "duplicate": "duplicates", "already_seen": "already_seen"}.get(result)
                    if key:
                        setattr(run, key, getattr(run, key) + 1)
                    totals[result] = totals.get(result, 0) + 1
                    new += result == "new"
                s.commit()
                record_call_jobs(s, call_id, returned)
                run.fetched += len(jobs)
                totals["fetched"] = totals.get("fetched", 0) + len(jobs)
                totals["requests"] = totals.get("requests", 0) + 1
                api_budget.finish_call(call_id, ok=True, results=n_results, new_jobs=new)
                search_plan.record_run(s, qid, requests=1, results=n_results, new_jobs=new, ok=True,
                                       backoff_after_empty=cfg.backoff_after_empty)
                if (page == 1 and cfg.pages_policy == "smart" and n_results >= PAGE_SIZE
                        and new >= cfg.page2_min_new):
                    page2.append((qid, params))
                if not work and page2:
                    work = [(qid, p, 2) for qid, p in page2]
                    page2 = []
        run.status = "failed" if error else "ok"
        run.error = error or stop
        run.company = f"{spent} request{'s' if spent != 1 else ''}"
        run.finished_at = utcnow()
        s.add(run)
        _mark_health(s, error)
        s.commit()
    return call_ids


def _mark_health(s: Session, error: str | None) -> None:
    src = s.get(JobSource, JSEARCH.name)
    if src is None:
        src = JobSource(name=JSEARCH.name)
    if error:
        src.last_error_at, src.last_error = utcnow(), error
    else:
        src.last_success_at, src.last_error = utcnow(), None
    s.add(src)


def _run(scan_id: str, trigger: str, selection=None) -> None:
    from backend.services import compass

    totals: dict[str, int] = {}
    try:
        with new_session() as s:
            ensure_sources(s)
        call_ids = fetch_jsearch(scan_id, trigger, totals, selection)
        _set_phase(scan_id, "fetching", totals)
        with pipeline_lock:
            _set_phase(scan_id, "processing", totals)
            with new_session() as s:
                process_new(s, totals)
            from backend.services import search_plan

            with new_session() as s:
                search_plan.attribute_relevance(s, call_ids)
            _set_phase(scan_id, "mapping", totals)
            totals["mapped"] = compass.map_pending()
            _set_phase(scan_id, "pruning", totals)
            with new_session() as s:
                totals.update({f"pruned_{k}": v for k, v in prune(s).items()})
        _set_phase(scan_id, "done", totals, done=True)
    except Exception as e:  # noqa: BLE001 - recorded on the scan, shown in the UI
        log.exception("scan %s failed", scan_id)
        _set_phase(scan_id, "failed", totals, error=f"{type(e).__name__}: {e}"[:300], done=True)
    finally:
        _current["scan_id"] = None
        _scan_lock.release()


def recover_interrupted() -> None:
    """Scans cut off by a restart are marked failed."""
    with new_session() as s:
        for scan in s.exec(select(Scan).where(Scan.finished_at == None)).all():  # noqa: E711
            scan.phase, scan.error, scan.finished_at = "failed", "Interrupted by a restart", utcnow()
            s.add(scan)
        for run in s.exec(select(FetchRun).where(FetchRun.status == "running")).all():
            run.status, run.error, run.finished_at = "failed", "Interrupted by a restart", utcnow()
            s.add(run)
        s.commit()


def reset_job_vectors() -> None:
    """Embedding model / metric changed: drop job vectors; every job is processed again."""
    vectors.reset("jobs")
    vectors.reset("requirements")
    with new_session() as s:
        for job in s.exec(select(Job).where(col(Job.pipeline_status).in_(["relevant", "mapped", "not_relevant"]))).all():
            _reset_processing(s, job)
            s.add(job)
        s.commit()
