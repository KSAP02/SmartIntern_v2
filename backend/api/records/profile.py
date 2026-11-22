"""Records / My Profile: the active profile, and (Phase 2.8) the list of profiles."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlmodel import Session

from backend.db import get_session
from backend.schemas import (
    FillPreview, FillRequest, FillResult, Profile, ProfileCreate, ProfileOut, ProfileRename, ProfilesOut, RegroupRequest,
    RegroupResult,
)
from backend.services import memory, profiles, skill_groups
from backend.services import profile as svc

router = APIRouter(prefix="/records/profile", tags=["records: profile"])


@router.get("", response_model=ProfileOut)
def get_profile(session: Session = Depends(get_session)):
    return svc.profile_out(session)


@router.put("", response_model=ProfileOut)
def put_profile(profile: Profile, session: Session = Depends(get_session)):
    return svc.save(session, profile)


@router.post("/fill", response_model=FillPreview | FillResult)
def fill(body: FillRequest, background: BackgroundTasks, session: Session = Depends(get_session)):
    """'Fill in using resume'. preview=true -> the field diff; preview=false -> apply it."""
    try:
        if body.preview:
            return svc.fill_preview(session, body.resume_id, body.mode)
        applied, first_build = svc.fill_apply(session, body.resume_id, body.mode, body.exclude_fields)
    except svc.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except svc.Conflict as e:
        raise HTTPException(409, str(e)) from e
    if first_build:
        background.add_task(memory.after_change)
    return FillResult(applied=applied, view=svc.profile_out(session))


@router.post("/skills/regroup", response_model=RegroupResult)
def regroup_skills(body: RegroupRequest):
    """'Group by theme': propose themed skill groups. Nothing is saved; the UI puts the
    proposal into the unsaved profile so the user can adjust it and Save."""
    return RegroupResult(groups=skill_groups.regroup(body.groups))


@router.post("/confirm", response_model=ProfileOut)
def confirm(session: Session = Depends(get_session)):
    return svc.confirm(session)


# ── several profiles (Phase 2.8) ───────────────────────────────────────────────


def _errors(fn):
    try:
        return fn()
    except profiles.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except profiles.Conflict as e:
        raise HTTPException(409, str(e)) from e


@router.get("/profiles", response_model=ProfilesOut)
def list_profiles(session: Session = Depends(get_session)):
    """Every profile, which one is active, and the switch in progress (if any)."""
    return profiles.summaries(session)


@router.post("/profiles", response_model=ProfilesOut, status_code=status.HTTP_201_CREATED)
def create_profile(body: ProfileCreate, session: Session = Depends(get_session)):
    """New profile from a resume (`resume_id`) or a copy (`copy_of`). It isn't made active."""
    _errors(lambda: profiles.create(session, body.name, body.resume_id, body.copy_of))
    return profiles.summaries(session)


@router.patch("/profiles/{profile_id}", response_model=ProfilesOut)
def rename_profile(profile_id: int, body: ProfileRename, session: Session = Depends(get_session)):
    _errors(lambda: profiles.rename(session, profile_id, body.name, body.resume_id))
    return profiles.summaries(session)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: int, session: Session = Depends(get_session)):
    _errors(lambda: profiles.remove(session, profile_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/profiles/{profile_id}/activate", response_model=ProfilesOut, status_code=status.HTTP_202_ACCEPTED)
def activate_profile(profile_id: int, session: Session = Depends(get_session)):
    """Switch: cards, role contexts and roles follow at once; jobs are re-scored in the background."""
    _errors(lambda: profiles.activate(session, profile_id))
    session.expire_all()
    return profiles.summaries(session)
