"""My Profile: read, save with edit tracking, fill from a resume, confirm."""
from __future__ import annotations

from sqlmodel import Session, select

from backend.db import ProfileRow, Resume, get_profile_row, utcnow
from backend.schemas import FillPreview, ProfileOut, Profile
from backend.services import memory
from backend.services.profile_fill import apply_changes, completeness, compute_changes, mark_user_edits


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


def _profile(row: ProfileRow) -> Profile:
    return Profile.model_validate(row.data or {})


def _origins(row: ProfileRow) -> dict[str, str]:
    """Field origins, with pre-skill-group paths ("skills.skills" / "skills.tools") folded into "skills.groups"."""
    o = dict(row.field_origins or {})
    legacy = o.pop("skills.skills", None) or o.pop("skills.tools", None)
    o.pop("skills.tools", None)
    if legacy and "skills.groups" not in o:
        o["skills.groups"] = legacy
    return o


def profile_out(session: Session) -> ProfileOut:
    row = get_profile_row(session)
    profile = _profile(row)
    labels = {str(r.id): r.label for r in session.exec(select(Resume)).all()}
    return ProfileOut(
        profile=profile,
        field_origins=_origins(row),
        resume_labels=labels,
        last_filled_from_resume_id=row.last_filled_from_resume_id,
        confirmed_at=row.confirmed_at,
        updated_at=row.updated_at,
        completeness=completeness(profile),
        memory_stale=memory.is_stale(session),
        profile_id=row.id,
        profile_name=row.name or "My profile",
        resume_id=row.resume_id,
    )


def save(session: Session, new: Profile) -> ProfileOut:
    row = get_profile_row(session)
    old = _profile(row)
    if new.model_dump() != old.model_dump():
        row.field_origins = mark_user_edits(old, new, _origins(row))
        row.data = new.model_dump()
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
    return profile_out(session)


def _parsed_resume(session: Session, resume_id: int) -> tuple[Resume, Profile]:
    r = session.get(Resume, resume_id)
    if r is None:
        raise NotFound(f"Resume {resume_id} not found.")
    if r.parse_status != "parsed" or not r.parsed_data:
        raise Conflict(f"Resume '{r.label}' isn't parsed yet (status: {r.parse_status}).")
    return r, Profile.model_validate(r.parsed_data)


def fill_preview(session: Session, resume_id: int, mode: str) -> FillPreview:
    r, incoming = _parsed_resume(session, resume_id)
    row = get_profile_row(session)
    changes = compute_changes(_profile(row), incoming, _origins(row), mode)
    return FillPreview(resume_id=resume_id, resume_label=r.label, mode=mode, changes=changes)  # type: ignore[arg-type]


def fill_apply(session: Session, resume_id: int, mode: str, exclude: list[str]) -> tuple[int, bool]:
    """Apply a fill. Returns (changes applied, whether this was the first build of Memory)."""
    _, incoming = _parsed_resume(session, resume_id)
    row = get_profile_row(session)
    current = _profile(row)
    changes = compute_changes(current, incoming, _origins(row), mode)
    profile, origins, applied = apply_changes(current, changes, set(exclude), _origins(row), resume_id)
    first_build = False
    if applied:
        row.data = profile.model_dump()
        row.field_origins = origins
        row.last_filled_from_resume_id = resume_id
        if row.resume_id is None:
            row.resume_id = resume_id  # the profile is now built on this resume
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
        if row.memory_built_at is None:
            memory.rebuild(session)
            first_build = True
    return applied, first_build


def confirm(session: Session) -> ProfileOut:
    row = get_profile_row(session)
    row.confirmed_at = utcnow()
    session.add(row)
    session.commit()
    return profile_out(session)
