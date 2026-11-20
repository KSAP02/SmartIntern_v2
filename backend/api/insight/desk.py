"""Insight / Desk: the dashboard summary."""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend.db import get_session, utcnow
from backend.schemas import DeskOut
from backend.services import job_search, job_views, memory, status, vault
from backend.services import profile as profile_service

router = APIRouter(prefix="/insight/desk", tags=["insight: desk"])


@router.get("", response_model=DeskOut)
def desk(session: Session = Depends(get_session)):
    profile_view = profile_service.profile_out(session)
    resumes = vault.list_resumes(session)
    cards = memory.list_cards(session)
    full_name = profile_view.profile.personal.full_name
    return DeskOut(
        first_name=full_name.split()[0] if full_name else None,
        completeness=profile_view.completeness,
        profile_confirmed=profile_view.confirmed_at is not None,
        resumes={
            "total": len(resumes),
            "parsed": sum(r.parse_status == "parsed" for r in resumes),
            "parsing": sum(r.parse_status in ("pending", "parsing") for r in resumes),
            "failed": sum(r.parse_status == "failed" for r in resumes),
        },
        cards={
            "total": len(cards),
            "enabled": sum(c.enabled for c in cards),
            "embedded": sum(c.embedding_status == "embedded" for c in cards),
            "failed": sum(c.embedding_status == "failed" for c in cards),
        },
        memory_stale=profile_view.memory_stale,
        status=status.components(),
        job_search=_job_search_tile(session),
    )


def _job_search_tile(session: Session) -> dict:
    ov = job_views.overview(session, job_search.running_scan_id())
    jobs = job_views.list_jobs(session)
    today = utcnow().date().isoformat()
    return {
        "found_today": sum(d.new for d in ov.per_day if d.date == today),
        "relevant": len(jobs.fits) + len(jobs.other),
        "fits_preset": len(jobs.fits),
        "selected": jobs.counts.get("selected", 0),
        "last_scan_at": ov.last_scan.finished_at.isoformat() if ov.last_scan and ov.last_scan.finished_at else None,
        "next_scan_at": ov.next_scan_at.isoformat() if ov.next_scan_at else None,
    }
