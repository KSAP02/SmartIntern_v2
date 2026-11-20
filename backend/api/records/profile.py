"""Records / My Profile: the profile."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from backend.db import get_session
from backend.schemas import FillPreview, FillRequest, FillResult, Profile, ProfileOut, RegroupRequest, RegroupResult
from backend.services import memory, skill_groups
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
