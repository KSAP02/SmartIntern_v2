"""Phase 2.7 A3: companies found automatically from the apply links of stored jobs; a found
company stays only while its board has jobs in India. Offline: boards are faked."""
from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from backend.db import Employer, Job, new_session, utcnow
from backend.job_schemas import ScanSelection
from backend.services import employers
from backend.services.sources import BOARDS
from backend.tests.test_boards_a1 import _scan, boards, nj  # noqa: F401  (boards is a fixture)
from backend.tests.test_job_search import BACKEND_JD, env  # noqa: F401


def _job(title: str, company: str, url: str, source: str = "jsearch") -> None:
    with new_session() as s:
        s.add(Job(title=title, company_name=company, apply_route_url=url, apply_url=url, job_url=url,
                  seen_on=[{"source": source, "source_job_id": f"{source}-{title}", "job_url": url}],
                  description_text="x", content_hash=f"h-{title}-{company}", dedupe_key=f"d-{title}-{company}",
                  pipeline_status="not_relevant"))
        s.commit()


def test_jobs_linking_to_a_board_add_the_company(boards):
    _job("Backend Engineer", "Acme Labs", "https://jobs.lever.co/acmelabs/123/apply")
    _job("ML Engineer", "Acme Labs", "https://jobs.lever.co/AcmeLabs/456")  # same board, other case
    _job("SDE", "Bigco", "https://www.naukri.com/job-listings-1")  # not a board
    _job("AI Engineer", "Known", "https://job-boards.greenhouse.io/known/jobs/9")
    with new_session() as s:
        employers.add(s, "https://job-boards.greenhouse.io/known", "Known")
    assert employers.discover() == ["Acme Labs"]
    with new_session() as s:
        e = s.exec(select(Employer).where(Employer.kind == "lever")).one()
        assert (e.board.lower(), e.origin, e.enabled, e.empty_scans) == ("acmelabs", "discovered", True, None)
        assert e.found_via_job_id is not None and "Found through" in e.note
    assert employers.discover() == []  # already known


def test_found_company_is_kept_only_with_jobs_in_india(boards, monkeypatch):
    _job("Backend Engineer", "Inco", "https://jobs.lever.co/inco/1")
    _job("Backend Engineer", "Usco", "https://jobs.ashbyhq.com/usco/2")
    monkeypatch.setattr(BOARDS["lever"], "list_jobs", lambda http, b, c: [
        nj("Backend Engineer", "Bengaluru, India").model_copy(update={"source": "lever", "description_text": BACKEND_JD})])
    monkeypatch.setattr(BOARDS["ashby"], "list_jobs", lambda http, b, c: [nj("Backend Engineer", "Austin, US")])
    scan = _scan(ScanSelection(roles=["Backend Engineer"], sources=["lever", "ashby"]))
    assert scan.phase == "done" and scan.totals["companies_found"] == 2 and scan.totals["companies_dropped"] == 1
    with new_session() as s:
        inco = s.exec(select(Employer).where(Employer.board == "inco")).one()
        usco = s.exec(select(Employer).where(Employer.board == "usco")).one()
        assert inco.enabled and inco.empty_scans == 0
        assert not usco.enabled and "no jobs in India" in usco.note and usco.last_error is None

    # Inco's India jobs go away: switched off after drop_after_empty_scans (3) reads in a row. (An
    # empty board is read weekly, Phase 2.7 E; switched off here so each scan reads it.)
    from backend.config import write_tuning

    write_tuning({("scout", "search", "boards", "quiet_board_days"): 0})
    monkeypatch.setattr(BOARDS["lever"], "list_jobs", lambda http, b, c: [nj("Backend Engineer", "Austin, US")])
    for _ in range(3):
        _scan(ScanSelection(roles=["Backend Engineer"], sources=["lever"]))
    with new_session() as s:
        inco = s.exec(select(Employer).where(Employer.board == "inco")).one()
        assert not inco.enabled and inco.empty_scans == 3
    write_tuning({("scout", "search", "boards", "quiet_board_days"): 7})

    # Not tried again soon; after retry_after_days, a job linking to it again switches it back on.
    assert employers.discover() == []
    with new_session() as s:
        for e in s.exec(select(Employer)).all():
            e.last_checked_at = utcnow() - timedelta(days=31)
            s.add(e)
        s.commit()
    assert sorted(employers.discover()) == ["Inco", "Usco"]


def test_a_gone_board_is_never_retried(boards):
    _job("Backend Engineer", "Gone", "https://jobs.lever.co/gone/1")
    with new_session() as s:
        s.add(Employer(name="Gone", kind="lever", board="gone", origin="discovered", enabled=False,
                       last_error="Lever (gone): not found (HTTP 404)", last_checked_at=utcnow() - timedelta(days=90)))
        s.commit()
    assert employers.discover() == []


def test_discovery_respects_the_cap_and_switch(boards):
    from backend.config import write_tuning

    for i in range(4):
        _job(f"Backend Engineer {i}", f"Co{i}", f"https://jobs.lever.co/co{i}/1")
    write_tuning({("scout", "search", "boards", "max_new_per_scan"): 2})
    assert len(employers.discover()) == 2
    write_tuning({("scout", "search", "boards", "discover"): False})
    assert employers.discover() == []
    write_tuning({("scout", "search", "boards", "discover"): True, ("scout", "search", "boards", "max_new_per_scan"): 10})
