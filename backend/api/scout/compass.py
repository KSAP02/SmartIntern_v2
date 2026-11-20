"""Scout / Compass: the evidence map (job requirements vs your memory cards)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from backend.db import Job, get_session
from backend.job_schemas import RequirementOut
from backend.services import compass, job_views

router = APIRouter(prefix="/scout/compass", tags=["scout: compass"])


@router.get("/{job_id}", response_model=list[RequirementOut])
def evidence(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found.")
    return job_views.job_detail(session, job).requirements


@router.post("/remap")
def remap():
    """Recompute relevance + evidence for all jobs (e.g. after editing memory)."""
    return {"remapped": compass.remap_all()}
