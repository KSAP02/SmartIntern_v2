"""The middle layer (Phase 2 ⑤⑥): job requirements ↔ evidence in your memory cards. No LLM,
no embeddings (since Phase 2.6 cards aren't embedded; the role context does the fuzzy part).

Each job description is split into chunks (bullets / sentences, tagged must / nice by the
heading they sit under), and each chunk is checked against your enabled memory cards:
  - exact: skills named in the chunk that your cards / profile have (skills vocabulary +
    aliases) -> met (all) / partial (some) / missing (none): the missing ones are your gaps
  - numeric: "N+ years" vs your years of experience
  - anything else is "not judged" (a deeper, AI-written gap note is Phase 3)
The result is evidence and a coverage summary, not a score.
"""
from __future__ import annotations

import logging
import re

from sqlmodel import Session, col, delete, select

from backend.db import Job, JobRequirement, MemoryCard, get_profile_row, new_session
from backend.job_schemas import MatchingSettings
from backend.schemas import Profile
from backend.services import search_settings
from backend.services.job_search import _set_status, enabled_cards, pipeline_lock
from backend.services.job_text import chunk_requirements, chunks_from_highlights
from backend.services.skills_vocab import find_skills, normalize_skill

log = logging.getLogger(__name__)

SKIP_SECTIONS = {"about", "benefits", "other"}
MAX_CHUNKS = 40
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)\b", re.I)


# ── your side: what the memory holds ──────────────────────────────────────────


class Evidence:
    """Snapshot of the memory side used for one mapping run."""

    def __init__(self, session: Session):
        self.cards = enabled_cards(session)
        profile = Profile.model_validate(get_profile_row(session).data or {})
        self.years = profile.headline.years_experience
        self.terms = tuple(sorted({s for g in profile.skills.groups for s in g.items}
                                  | {t for p in profile.projects for t in p.tech}))
        # skill -> card holding it (skill-group cards first, then any card mentioning it)
        self.skill_card: dict[str, int] = {}
        ordered = sorted(self.cards.values(), key=lambda c: (c.kind != "skills", c.position))
        for c in ordered:
            for s in find_skills(f"{c.title}\n{c.text}", extra_terms=self.terms):
                self.skill_card.setdefault(normalize_skill(s), c.id)
        self.version = memory_version(self.cards)


def memory_version(cards: dict[int, MemoryCard]) -> str:
    from backend.services.memory import version_of

    return version_of(cards.values())


def current_memory_version(session: Session) -> str:
    return memory_version(enabled_cards(session))


# ── mapping one job ────────────────────────────────────────────────────────────


def _chunks_for(job: Job) -> list:
    # The source's own Qualifications / Responsibilities lists beat splitting the text ourselves.
    chunks = chunks_from_highlights(job.highlights)
    if any(c.section == "requirements" for c in chunks):
        return [c for c in chunks if c.section not in SKIP_SECTIONS][:MAX_CHUNKS]
    chunks = chunk_requirements(job.description_text or "")
    keep = [c for c in chunks if c.section not in SKIP_SECTIONS]
    if not keep:  # unstructured posting: fall back to chunks that name skills, then anything
        keep = [c for c in chunks if find_skills(c.text)] or [c for c in chunks if c.section != "other"]
    return keep[:MAX_CHUNKS]


def _ensure_requirements(session: Session, job: Job, ev: Evidence) -> list[JobRequirement]:
    reqs = list(session.exec(select(JobRequirement).where(JobRequirement.job_id == job.id).order_by(JobRequirement.position)).all())
    chunks = _chunks_for(job)
    # Reuse stored chunks only if chunking still gives the same result (the chunker may have improved).
    same = [(r.text, r.section, r.importance) for r in reqs] == [(c.text, c.section, c.importance) for c in chunks]
    if reqs and same:
        for r in reqs:  # your skills may have changed: re-spot skills in the chunk
            r.skills = find_skills(r.text, extra_terms=ev.terms)
        return reqs
    if reqs:
        session.exec(delete(JobRequirement).where(JobRequirement.job_id == job.id))
    reqs = [JobRequirement(job_id=job.id, section=c.section, importance=c.importance, text=c.text, position=c.position,
                           skills=find_skills(c.text, extra_terms=ev.terms), embedding_status="none") for c in chunks]
    if reqs:
        session.add_all(reqs)
        session.flush()
    return reqs


def judge(r: JobRequirement, ev: Evidence) -> None:
    """Set status / method / proving card on one requirement: named skills you have (exact),
    then years. Anything else stays "unknown" (not judged)."""
    r.evidence, r.best_card_id, r.best_score = [], None, None
    status, method = "unknown", "none"
    skills = [normalize_skill(s) for s in (r.skills or [])]
    if skills:
        have = [s for s in skills if s in ev.skill_card]
        if have:
            status, method = ("met" if len(have) == len(skills) else "partial"), "exact_skill"
            r.best_card_id, r.best_score = ev.skill_card[have[0]], 1.0
        else:
            status, method = "missing", "exact_skill"

    yrs = _YEARS.search(r.text)
    if yrs and re.search(r"experience|exp\b", r.text, re.I):
        if ev.years is None:
            status, method = ("unknown" if status == "missing" else status), method
        elif ev.years < float(yrs.group(1)):
            status, method = "missing", "numeric"
        elif status != "met" and ev.years >= float(yrs.group(1)) and not skills:
            status, method = "met", "numeric"
    r.status, r.method = status, method


def coverage(reqs: list[JobRequirement]) -> dict:
    must = [r for r in reqs if r.importance == "must"]
    if not must:  # no "must" headings: everything that isn't nice-to-have counts
        must = [r for r in reqs if r.importance != "nice"]
    nice = [r for r in reqs if r.importance == "nice"]
    met = sum(r.status == "met" for r in must)
    partial = sum(r.status == "partial" for r in must)
    missing = sum(r.status == "missing" for r in must)
    judged = met + partial + missing  # "unknown" (not judged) doesn't count either way
    fit = round(100 * (met + 0.5 * partial) / judged) if judged else None
    return {"must_total": len(must), "must_met": met, "must_partial": partial, "must_missing": missing,
            "nice_total": len(nice), "nice_met": sum(r.status == "met" for r in nice), "fit": fit}


def map_job(session: Session, job: Job, ev: Evidence, m: MatchingSettings | None = None) -> None:
    reqs = _ensure_requirements(session, job, ev)
    for r in reqs:
        judge(r, ev)
        session.add(r)
    job.coverage = coverage(reqs) if reqs else None
    job.mapped_memory_version = ev.version
    _set_status(session, job, "mapped")


def map_pending(force: bool = False) -> int:
    """Map relevant jobs that aren't mapped yet, or were mapped against older memory."""
    with pipeline_lock:
        return _map_pending(force)


def _map_pending(force: bool) -> int:
    done = 0
    with new_session() as s:
        m = search_settings.get(s, "matching")
        ev = Evidence(s)
        if not ev.cards:
            return 0
        q = select(Job).where(col(Job.pipeline_status).in_(["relevant", "mapped"]), Job.status == "active")
        jobs = [j for j in s.exec(q).all() if force or j.pipeline_status == "relevant" or j.mapped_memory_version != ev.version]
        for job in jobs:
            try:
                map_job(s, job, ev, m)
                s.commit()
                done += 1
            except Exception as e:  # noqa: BLE001 - one bad posting must not stop the rest
                s.rollback()
                log.warning("mapping job %s failed: %s", job.id, e)
                job = s.get(Job, job.id)
                if job:
                    _set_status(s, job, "failed", f"Mapping failed: {type(e).__name__}")
                    s.commit()
    return done


def remap_all() -> int:
    """Memory, role contexts or matching settings changed: recompute relevance and evidence (no
    new job embeddings)."""
    from backend.services.job_search import rescore_relevance

    with pipeline_lock:
        with new_session() as s:
            rescore_relevance(s)
        return map_pending(force=True)

