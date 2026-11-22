"""Memory (context cards): built from the profile, edited by you, stored as text.

Since Phase 2.6 cards are **not embedded**. They are the material each role context is
written from (services/role_contexts.py) and the proof behind exact skill matches in the
evidence map (services/compass.py). Changing cards re-checks job evidence and marks role
contexts "memory changed" (they are rewritten only when you click Regenerate).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from sqlmodel import Session, select

from backend import vectors
from backend.config import get_tuning
from backend.db import MemoryCard, active_profile_id, get_meta, get_profile_row, new_session, set_meta, utcnow
from backend.model import embedding_signature
from backend.schemas import CardOut, MemoryOut, Profile

log = logging.getLogger(__name__)
SIGNATURE_KEY = "embedding_signature"


@dataclass
class CardSpec:
    kind: str
    title: str
    text: str
    source_ref: str


# ── building cards from the profile (deterministic, no LLM) ────────────────────


def _clip(text: str) -> str:
    limit = get_tuning().records.memory.max_card_chars
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _span(start: str | None, end: str | None, current: bool = False) -> str:
    end_txt = "Present" if current else end
    return " – ".join(x for x in (start, end_txt) if x)


def build_specs(p: Profile) -> list[CardSpec]:
    specs: list[CardSpec] = []
    h = p.headline
    if h.current_title or h.summary:
        bits = [h.current_title or ""]
        if h.years_experience is not None:
            bits.append(f"{h.years_experience:g} years of experience")
        head = ", ".join(b for b in bits if b)
        text = "\n".join(x for x in (head, h.summary) if x)
        specs.append(CardSpec("summary", "Summary", _clip(text), "headline"))

    for w in p.work_history:
        title = " at ".join(x for x in (w.title, w.company) if x) or "Role"
        meta = " · ".join(x for x in (w.location, _span(w.start, w.end, w.is_current)) if x)
        lines = [title + (f" ({meta})" if meta else "")] + [f"- {b}" for b in w.bullets]
        specs.append(CardSpec("experience", title, _clip("\n".join(lines)), f"work_history:{w.id}"))

    for pr in p.projects:
        name = pr.name or "Project"
        lines = [name]
        if pr.description:
            lines.append(pr.description)
        if pr.tech:
            lines.append("Tech: " + ", ".join(pr.tech))
        specs.append(CardSpec("project", name, _clip("\n".join(lines)), f"projects:{pr.id}"))

    for e in p.education:
        title = ", ".join(x for x in (" in ".join(y for y in (e.degree, e.field) if y), e.institution) if x)
        title = title or "Education"
        meta = " · ".join(x for x in (_span(e.start, e.end), e.grade) if x)
        specs.append(CardSpec("education", title, _clip(title + (f" ({meta})" if meta else "")), f"education:{e.id}"))

    # One card per themed skill group (set on the Me page), so a JD hits the relevant theme.
    for g in p.skills.groups:
        if g.items:
            name = g.name or "Skills"
            specs.append(CardSpec("skills", name, _clip(f"{name}: " + ", ".join(g.items)), f"skills:{g.id}"))
    if p.skills.languages:
        specs.append(CardSpec("skills", "Languages", _clip("Languages: " + ", ".join(p.skills.languages)), "skills:languages"))

    if p.certifications:
        lines = [
            " · ".join(x for x in (c.name, c.issuer, c.date) if x) for c in p.certifications if c.name or c.issuer
        ]
        if lines:
            specs.append(CardSpec("certification", "Certifications", _clip("Certifications:\n" + "\n".join(lines)), "certifications"))
    return specs


# ── queries ────────────────────────────────────────────────────────────────────


def card_out(c: MemoryCard) -> CardOut:
    return CardOut.model_validate(c, from_attributes=True)


def list_cards(session: Session) -> list[MemoryCard]:
    """The active profile's cards (Phase 2.8)."""
    q = select(MemoryCard).where(MemoryCard.profile_id == active_profile_id(session))
    return list(session.exec(q.order_by(MemoryCard.position, MemoryCard.id)).all())


def is_stale(session: Session) -> bool:
    row = get_profile_row(session)
    if row.memory_built_at is None:
        return bool(row.data)
    return bool(row.updated_at and row.updated_at > row.memory_built_at)


def memory_out(session: Session) -> MemoryOut:
    row = get_profile_row(session)
    return MemoryOut(cards=[card_out(c) for c in list_cards(session)], built_at=row.memory_built_at, memory_stale=is_stale(session))


# ── rebuild ────────────────────────────────────────────────────────────────────


def rebuild(session: Session) -> None:
    """Regenerate untouched generated cards from the profile; keep custom and edited cards."""
    row = get_profile_row(session)
    profile = Profile.model_validate(row.data or {})
    cards = list_cards(session)
    kept_refs = {c.source_ref for c in cards if c.origin == "generated" and c.user_edited}
    stale = [c for c in cards if c.origin == "generated" and not c.user_edited]
    by_ref = {c.source_ref: c for c in stale}
    specs = [s for s in build_specs(profile) if s.source_ref not in kept_refs]
    wanted = {s.source_ref for s in specs}

    gone = [c for c in stale if c.source_ref not in wanted]
    for c in gone:
        session.delete(c)

    for pos, spec in enumerate(specs):
        card = by_ref.get(spec.source_ref)
        if card is None:
            card = MemoryCard(kind=spec.kind, title=spec.title, text=spec.text, source_ref=spec.source_ref,
                              profile_id=row.id)
        elif card.title == spec.title and card.text == spec.text and card.kind == spec.kind:
            card.position = pos
            session.add(card)
            continue
        card.kind, card.title, card.text, card.position = spec.kind, spec.title, spec.text, pos
        card.embedding_status, card.embedding_error, card.updated_at = "pending", None, utcnow()
        session.add(card)

    # Custom and edited cards go after generated ones, keeping their relative order.
    offset = len(specs)
    for n, c in enumerate(x for x in cards if x.origin == "user" or x.user_edited):
        c.position = offset + n
        session.add(c)

    row.memory_built_at = utcnow()
    session.add(row)
    session.commit()


# ── after a change ─────────────────────────────────────────────────────────────


def version_of(cards) -> str:
    """Fingerprint of your enabled cards (ids + edit times): tells evidence and role contexts
    whether your memory changed since they were made."""
    sig = "|".join(f"{c.id}:{c.updated_at.isoformat() if c.updated_at else ''}" for c in sorted(cards, key=lambda c: c.id))
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


def cards_version(session: Session) -> str:
    return version_of([c for c in list_cards(session) if c.enabled and c.id is not None])


def vector_signature() -> str:
    """Embedding model + dimensions + metric: vectors built under another signature can't be compared."""
    return f"{embedding_signature()}|{vectors.metric()}"


def after_change() -> None:
    """Cards or profile changed: re-check job evidence and relevance (no embeddings). Role
    contexts notice by themselves (memory_changed) and are rewritten only on Regenerate."""
    try:
        from backend.services import compass

        compass.remap_all()
    except Exception as e:  # noqa: BLE001 - jobs re-map on the next scan anyway
        log.warning("re-mapping jobs after a memory change failed: %s", e.__class__.__name__)


def check_embedding_signature() -> bool:
    """On startup: if the embedding model/dimensions/metric changed, drop job vectors (they are
    re-embedded on the next scan / start; role contexts re-embed themselves when used).

    Returns True when job vectors were reset.
    """
    with new_session() as session:
        saved = get_meta(session, SIGNATURE_KEY)
        legacy = saved == embedding_signature() and vectors.metric() == "COSINE"  # pre-Phase-2 format
        if saved is None or saved == vector_signature() or legacy:
            set_meta(session, SIGNATURE_KEY, vector_signature())
            session.commit()
            return False
        log.info("vector signature changed (%s -> %s); re-embedding jobs", saved, vector_signature())
        from backend.services import job_search

        job_search.reset_job_vectors()
        set_meta(session, SIGNATURE_KEY, vector_signature())
        session.commit()
        return True


UNUSED_COLLECTIONS_KEY = "phase26_dropped_collections"


def drop_unused_vectors() -> None:
    """Once, after Phase 2.6: the memory-card and requirement-chunk collections are no longer used."""
    with new_session() as session:
        if get_meta(session, UNUSED_COLLECTIONS_KEY):
            return
        for kind in ("memory", "requirements"):
            try:
                vectors.drop(kind)
            except Exception as e:  # noqa: BLE001 - harmless leftovers; tried again next start
                log.warning("dropping the %s collection failed: %s", kind, e.__class__.__name__)
                return
        for c in list_cards(session):
            c.embedding_status, c.embedding_error = "none", None
            session.add(c)
        set_meta(session, UNUSED_COLLECTIONS_KEY, utcnow().isoformat())
        session.commit()
