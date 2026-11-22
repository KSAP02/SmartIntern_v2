"""Several profiles, one active (Phase 2.8).

Each profile is a `profile` row with its own details, memory cards, role contexts and roles you
search for. Everything else (jobs, locations, budget, boards) is shared. Switching sets meta
`active_profile_id`, then in the background: builds the profile's memory cards the first time,
writes role contexts its roles lack (one model call each), and re-scores the shared jobs against
it (no job requests). Plan: MD_files/project_build_phases/phase_2_8_multiple_profiles.md.
"""
from __future__ import annotations

import copy
import json
import logging
import threading

from sqlmodel import Session, delete, func, select

from backend.db import (
    ACTIVE_PROFILE_KEY, MemoryCard, ProfileRow, Resume, RoleContext, active_profile_id, get_meta, get_profile_row,
    new_session, set_meta, utcnow,
)
from backend.schemas import Profile, ProfilesOut, ProfileSummary, SwitchState
from backend.services import search_settings
from backend.services.profile_fill import apply_changes, completeness, compute_changes

log = logging.getLogger(__name__)

SWITCH_KEY = "profile_switch_state"
_state_lock = threading.Lock()


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


# ── reading ────────────────────────────────────────────────────────────────────


def _rows(session: Session) -> list[ProfileRow]:
    return list(session.exec(select(ProfileRow).order_by(ProfileRow.id)).all())


def _name(row: ProfileRow) -> str:
    return row.name or "My profile"


def switch_state(session: Session) -> SwitchState:
    raw = get_meta(session, SWITCH_KEY)
    try:
        return SwitchState(**json.loads(raw)) if raw else SwitchState()
    except Exception:  # noqa: BLE001 - a stale value must not break the page
        return SwitchState()


def _set_state(**kw) -> None:
    with _state_lock, new_session() as s:
        st = switch_state(s).model_copy(update=kw)
        set_meta(s, SWITCH_KEY, st.model_dump_json())
        s.commit()


def summaries(session: Session) -> ProfilesOut:
    get_profile_row(session)  # makes the first profile if there is none
    ensure_roles(session)
    active = active_profile_id(session)
    labels = {r.id: r.label for r in session.exec(select(Resume)).all()}
    live = search_settings.get(session, "criteria").roles  # the active profile's, as last saved
    counts = dict(session.exec(select(MemoryCard.profile_id, func.count()).group_by(MemoryCard.profile_id)).all())
    out = []
    for r in _rows(session):
        out.append(ProfileSummary(
            id=r.id, name=_name(r), resume_id=r.resume_id, resume_label=labels.get(r.resume_id),
            active=r.id == active, completeness=completeness(Profile.model_validate(r.data or {})),
            roles=list(live if r.id == active else r.roles or []), cards=counts.get(r.id, 0), created_at=r.created_at, updated_at=r.updated_at,
        ))
    return ProfilesOut(profiles=out, active_id=active, switching=switch_state(session))


def ensure_roles(session: Session) -> None:
    """Profiles made before Phase 2.8 have no roles of their own yet: they take the search
    criteria's (once), so switching never mixes up roles."""
    rows = [r for r in _rows(session) if r.roles is None or r.auto_roles is None]
    if not rows:
        return
    crit = search_settings.get(session, "criteria")
    for r in rows:
        r.roles = list(crit.roles) if r.roles is None else r.roles
        r.auto_roles = list(crit.auto_roles) if r.auto_roles is None else r.auto_roles
        session.add(r)
    session.commit()


# ── creating, renaming, deleting ───────────────────────────────────────────────


def _unique_name(session: Session, name: str, skip_id: int | None = None) -> str:
    taken = {_name(r).lower() for r in _rows(session) if r.id != skip_id}
    base, n = name.strip()[:80] or "Profile", 2
    out = base
    while out.lower() in taken:
        out, n = f"{base} ({n})", n + 1
    return out


def create(session: Session, name: str | None, resume_id: int | None, copy_of: int | None) -> ProfileRow:
    """A new profile from a parsed resume (all fields filled from it) or a copy of a profile.
    It starts with the active profile's roles; it isn't made active."""
    ensure_roles(session)
    crit = search_settings.get(session, "criteria")  # the active profile's roles, as last saved
    if copy_of is not None:
        src = session.get(ProfileRow, copy_of)
        if src is None:
            raise NotFound(f"Profile {copy_of} not found.")
        mine = src.id == active_profile_id(session)
        row = ProfileRow(
            name=_unique_name(session, name or f"{_name(src)} (copy)"), resume_id=src.resume_id,
            roles=list(crit.roles if mine else src.roles or []),
            auto_roles=list(crit.auto_roles if mine else src.auto_roles or []),
            data=copy.deepcopy(src.data or {}), field_origins=copy.deepcopy(src.field_origins or {}),
            last_filled_from_resume_id=src.last_filled_from_resume_id,
        )
    elif resume_id is not None:
        r = session.get(Resume, resume_id)
        if r is None:
            raise NotFound(f"Resume {resume_id} not found.")
        if r.parse_status != "parsed" or not r.parsed_data:
            raise Conflict(f"Resume '{r.label}' isn't parsed yet (status: {r.parse_status}).")
        empty = Profile()
        changes = compute_changes(empty, Profile.model_validate(r.parsed_data), {}, "replace")
        profile, origins, _ = apply_changes(empty, changes, set(), {}, resume_id)
        row = ProfileRow(
            name=_unique_name(session, name or r.label), resume_id=resume_id,
            roles=list(crit.roles), auto_roles=list(crit.auto_roles),
            data=profile.model_dump(), field_origins=origins, last_filled_from_resume_id=resume_id,
        )
    else:
        raise Conflict("Pick a resume to build the profile from, or a profile to copy.")
    row.created_at = row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def rename(session: Session, profile_id: int, name: str | None, resume_id: int | None) -> ProfileRow:
    row = session.get(ProfileRow, profile_id)
    if row is None:
        raise NotFound(f"Profile {profile_id} not found.")
    if name is not None and name.strip():
        row.name = _unique_name(session, name, skip_id=profile_id)
    if resume_id is not None:
        if session.get(Resume, resume_id) is None:
            raise NotFound(f"Resume {resume_id} not found.")
        row.resume_id = resume_id
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def remove(session: Session, profile_id: int) -> None:
    """Delete a profile with its cards and role contexts. Not the active one, not the last."""
    row = session.get(ProfileRow, profile_id)
    if row is None:
        raise NotFound(f"Profile {profile_id} not found.")
    if profile_id == active_profile_id(session):
        raise Conflict("Switch to another profile before deleting this one.")
    if len(_rows(session)) <= 1:
        raise Conflict("You need at least one profile.")
    session.exec(delete(MemoryCard).where(MemoryCard.profile_id == profile_id))
    session.exec(delete(RoleContext).where(RoleContext.profile_id == profile_id))
    session.delete(row)
    session.commit()


# ── switching ──────────────────────────────────────────────────────────────────


def activate(session: Session, profile_id: int) -> bool:
    """Make a profile the active one. Returns False if it already was. The follow-up work
    (cards, role contexts, re-scoring jobs) runs in a background thread."""
    if session.get(ProfileRow, profile_id) is None:
        raise NotFound(f"Profile {profile_id} not found.")
    ensure_roles(session)
    if profile_id == active_profile_id(session):
        return False
    old, new = get_profile_row(session), session.get(ProfileRow, profile_id)
    crit = search_settings.get(session, "criteria")
    old.roles, old.auto_roles = list(crit.roles), list(crit.auto_roles)  # what you last saved
    session.add(old)
    search_settings.swap_in_roles(session, new.roles or [], new.auto_roles or [])
    set_meta(session, ACTIVE_PROFILE_KEY, str(profile_id))
    session.commit()
    _set_state(running=True, profile_id=profile_id, step="Starting", error=None, finished_at=None)
    _start(profile_id)
    return True


def _start(pid: int) -> None:
    threading.Thread(target=after_switch, args=(pid,), name="profile-switch", daemon=True).start()


def _still(pid: int) -> bool:
    with new_session() as s:
        return active_profile_id(s) == pid


def after_switch(pid: int) -> None:
    """Build what the newly active profile needs, then re-score the shared jobs against it.
    Each step stops if you switched again meanwhile (that switch does its own)."""
    from backend.services import compass, job_search, memory, role_contexts

    try:
        with new_session() as s:
            row = get_profile_row(s)
            if row.id != pid:
                return
            if row.memory_built_at is None and row.data:
                _set_state(step="Building memory cards")
                memory.rebuild(s)
            roles = list(search_settings.get(s, "criteria").roles)
        if not _still(pid):
            return
        _set_state(step="Writing role contexts")
        try:
            role_contexts.ensure_for_roles(roles, profile_id=pid)
        except Exception as e:  # noqa: BLE001 - Memory -> Role contexts shows the failure / retry
            log.warning("role contexts after a profile switch failed: %s", e.__class__.__name__)
        if not _still(pid):
            return
        _set_state(step="Re-scoring jobs")
        with job_search.pipeline_lock:  # waits for a running scan
            if not _still(pid):
                return
            with new_session() as s:
                job_search.rescore_relevance(s, roles_changed=True)
                s.commit()
            compass.map_pending(force=True)
        if _still(pid):
            _set_state(running=False, step=None, finished_at=utcnow())
    except Exception as e:  # noqa: BLE001 - shown on My Profile; switching again retries
        log.warning("profile switch follow-up failed: %s", e.__class__.__name__)
        _set_state(running=False, step=None, error=f"{type(e).__name__}: {str(e)[:200]}", finished_at=utcnow())


def recover() -> None:
    """On start: profiles made before Phase 2.8 get their own roles, and a switch interrupted
    by a restart is finished."""
    with new_session() as s:
        get_profile_row(s)
        ensure_roles(s)
        for r in _rows(s):  # built on the resume it was last filled from
            if r.resume_id is None and r.last_filled_from_resume_id and s.get(Resume, r.last_filled_from_resume_id):
                r.resume_id = r.last_filled_from_resume_id
                s.add(r)
        s.commit()
        st = switch_state(s)
        pid = active_profile_id(s)
    if st.running:
        after_switch(pid)
