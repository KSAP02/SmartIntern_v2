"""System / JSearch analytics: request budget, the provider's usage, what the requests bought."""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend.db import get_session
from backend.job_schemas import JSearchAnalyticsOut, JSearchTestOut, ProviderUsageOut
from backend.services import jsearch_analytics, jsearch_calibration, jsearch_usage

router = APIRouter(prefix="/system/jsearch", tags=["system: jsearch analytics"])


@router.get("", response_model=JSearchAnalyticsOut)
def analytics(days: int = 30, session: Session = Depends(get_session)):
    """Everything on the analytics page. Calls nothing."""
    return jsearch_analytics.build(session, days)


@router.post("/usage", response_model=ProviderUsageOut)
def refresh_usage():
    """Ask OpenWeb Ninja for the plan, billing period and quota left (at most once a minute)."""
    return jsearch_usage.refresh(force=True)


@router.post("/test", response_model=JSearchTestOut)
def test_request():
    """Spend ONE request (from the reserve) exactly as a scan would for your top search; its
    jobs go through the normal pipeline. Returns what came back."""
    return jsearch_calibration.test_request()

