"""Phase 2.7 A1 + A2: company job boards (Greenhouse, Lever, Ashby, SmartRecruiters), the
Companies list, the India + title pre-check, collecting in the scan, closed postings, starter
list. Offline: fake HTTP responses, never a real board."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import delete, select

from backend.config import write_tuning
from backend.db import ApiCall, Employer, Job, Scan, new_session, utcnow
from backend.job_schemas import NormalizedJob, ScanSelection
from backend.services import employers, job_search
from backend.services.sources import BOARDS, SourceHttp, parse_careers_url
from backend.services.starter_companies import STARTER
from backend.tests.test_job_search import BACKEND_JD, env  # noqa: F401  (env is a fixture)
from backend.tests.test_role_contexts import _app


@pytest.fixture
def boards(env):
    from backend.db import set_meta

    with new_session() as s:
        s.exec(delete(Employer))
        # The app's start-up thread (TestClient) would add the starter list: mark it as done.
        set_meta(s, "starter_companies_version", employers._starter_version())
        s.commit()
    # Boards are off in tests (conftest); these tests switch them on and fake every board.
    write_tuning({("scout", "search", "boards", "delay_seconds"): 0, ("scout", "search", "boards", "enabled"): True})
    yield env
    with new_session() as s:  # never leave a company behind: a later scan would read its real board
        s.exec(delete(Employer))
        s.commit()


def http_with(routes: dict[str, object]) -> SourceHttp:
    """A SourceHttp whose responses come from `routes` (url path suffix -> JSON)."""
    def handler(request: httpx.Request) -> httpx.Response:
        for suffix, body in routes.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, content=json.dumps(body), headers={"content-type": "application/json"})
        return httpx.Response(404, content=b"{}")
    return SourceHttp(max_retries=0, transport=httpx.MockTransport(handler))


# ── links and adapters ─────────────────────────────────────────────────────────


def test_careers_links_are_recognised():
    p = parse_careers_url
    assert p("https://job-boards.greenhouse.io/postman/jobs/5854487003") == ("greenhouse", "postman")
    assert p("boards.greenhouse.io/phonepe") == ("greenhouse", "phonepe")
    assert p("https://job-boards.eu.greenhouse.io/groww/jobs/4528378101") == ("greenhouse", "eu:groww")
    assert p("https://boards-api.greenhouse.io/v1/boards/twilio/jobs") == ("greenhouse", "twilio")
    assert p("https://jobs.lever.co/ConverseNow/8154a882/apply") == ("lever", "ConverseNow")
    assert p("https://jobs.ashbyhq.com/level-ai/8f2dfd8d") == ("ashby", "level-ai")
    assert p("https://careers.smartrecruiters.com/Freshworks/pd") == ("smartrecruiters", "Freshworks")
    assert p("https://jobs.smartrecruiters.com/ixigo/744000143738909--software-engineer") == ("smartrecruiters", "ixigo")
    assert p("https://www.naukri.com/job-listings-1") is None and p("not a link") is None


def test_greenhouse_maps_jobs_and_its_form():
    body = {"jobs": [{"id": 11, "title": "Backend Engineer", "absolute_url": "https://acme.com/careers/11",
                      "location": {"name": "Bengaluru, India"}, "content": "&lt;p&gt;Build APIs&lt;/p&gt;",
                      "first_published": "2026-11-01T10:00:00Z"}]}
    with http_with({"/v1/boards/acme/jobs": body}) as http:
        [j] = BOARDS["greenhouse"].list_jobs(http, "acme", "Acme")
    assert (j.source, j.source_job_id, j.company_name) == ("greenhouse", "acme:11", "Acme")
    assert j.description_html == "<p>Build APIs</p>" and j.location_text == "Bengaluru, India"
    assert j.apply_url == "https://job-boards.greenhouse.io/acme/jobs/11"
    with http_with({"/v1/boards/groww/jobs": {"jobs": [{"id": 5, "title": "SDE"}]}}) as http:
        [eu] = BOARDS["greenhouse"].list_jobs(http, "eu:groww", "Groww")
    assert eu.apply_url == "https://job-boards.eu.greenhouse.io/groww/jobs/5" and eu.source_job_id == "eu:groww:5"


def test_lever_ashby_smartrecruiters_map_jobs():
    lever = [{"id": "a1", "text": "ML Engineer", "hostedUrl": "https://jobs.lever.co/acme/a1",
              "applyUrl": "https://jobs.lever.co/acme/a1/apply", "createdAt": 1762000000000, "workplaceType": "hybrid",
              "categories": {"location": "Pune", "commitment": "Full-time"}, "country": "IN",
              "description": "<p>Models</p>", "lists": [{"text": "Requirements", "content": "<li>Python</li>"}]}]
    with http_with({"/v0/postings/acme": lever}) as http:
        [j] = BOARDS["lever"].list_jobs(http, "acme", "Acme")
    assert j.location_text == "Pune, India" and j.workplace_type == "hybrid" and j.category == "full_time"
    assert "<li>Python</li>" in j.description_html and j.apply_url.endswith("/apply")

    ashby = {"jobs": [{"id": "x", "title": "AI Engineer", "location": "Bengaluru", "workplaceType": "Remote",
                       "employmentType": "Intern", "descriptionHtml": "<p>Agents</p>", "isListed": True,
                       "jobUrl": "https://jobs.ashbyhq.com/acme/x", "applyUrl": "https://jobs.ashbyhq.com/acme/x/application"},
                      {"id": "hidden", "title": "Hidden", "isListed": False}]}
    with http_with({"/job-board/acme": ashby}) as http:
        [a] = BOARDS["ashby"].list_jobs(http, "acme", "Acme")
    assert (a.workplace_type, a.category, a.title) == ("remote", "internship", "AI Engineer")

    sr_list = {"totalFound": 1, "content": [{"id": "744", "name": "Software Engineer 2 - Backend",
                                             "location": {"city": "Gurugram", "country": "in"},
                                             "typeOfEmployment": {"label": "Full-time"}, "releasedDate": "2026-11-10T00:00:00Z"}]}
    sr_detail = {"applyUrl": "https://jobs.smartrecruiters.com/oneclick-ui/company/ixigo/publication/744",
                 "jobAd": {"sections": {"jobDescription": {"title": "Job", "text": "<p>Payments</p>"}}}}
    with http_with({"/companies/ixigo/postings": sr_list, "/companies/ixigo/postings/744": sr_detail}) as http:
        [s] = BOARDS["smartrecruiters"].list_jobs(http, "ixigo", "ixigo")
        assert s.location_text == "Gurugram, India" and s.description_html is None
        s = BOARDS["smartrecruiters"].complete(http, "ixigo", s)
    assert "<p>Payments</p>" in s.description_html and "smartrecruiters.com" in s.apply_url


# ── the pre-check ──────────────────────────────────────────────────────────────


def nj(title: str, location: str | None, workplace=None) -> NormalizedJob:
    return NormalizedJob(source="greenhouse", source_job_id=f"acme:{title}|{location}", company_name="Acme", title=title,
                         location_text=location, workplace_type=workplace, description_text="Build things.")


def test_precheck_keeps_india_and_matching_titles(boards):
    with new_session() as s:
        phrases = employers.role_phrases(s)  # roles: Backend Engineer (+ its search titles)
    jobs = [nj("Backend Engineer II", "Bengaluru, Karnataka, India"),
            nj("Senior Software Engineer, Back-end", "Remote", "remote"),   # remote, no region: open to India
            nj("Backend Engineer", "Remote - US", "remote"),                # remote, US only
            nj("Backend Engineer", "London, UK"),
            nj("Account Executive", "Mumbai, India")]
    kept, out_scope, out_title = employers.precheck(jobs, phrases)
    assert [j.title for j in kept] == ["Backend Engineer II", "Senior Software Engineer, Back-end"]
    assert (out_scope, out_title) == (2, 1)
    assert employers.title_matches("Anything", []) is True  # no roles: everything matches


# ── Companies list + API ───────────────────────────────────────────────────────


def test_companies_api_add_check_starter_patch_delete(boards, monkeypatch):
    monkeypatch.setattr(BOARDS["greenhouse"], "list_jobs", lambda http, board, company: [
        nj("Backend Engineer", "Hyderabad, India"), nj("Backend Engineer", "Berlin, Germany"), nj("Recruiter", "Pune, India")])
    with TestClient(_app()) as c:
        a = c.post("/scout/search/companies", json={"url": "https://job-boards.greenhouse.io/acme"}).json()
        assert (a["name"], a["kind"], a["board"], a["enabled"], a["origin"]) == ("Acme", "greenhouse", "acme", True, "you")
        assert a["board_url"] == "https://job-boards.greenhouse.io/acme"
        dup = c.post("/scout/search/companies", json={"url": "boards.greenhouse.io/acme"})
        assert dup.status_code == 400 and "already" in dup.json()["detail"]
        assert c.post("/scout/search/companies", json={"url": "https://www.naukri.com/x"}).status_code == 400

        chk = c.post(f"/scout/search/companies/{a['id']}/check").json()
        assert (chk["found"], chk["in_scope"], chk["kept"]) == (3, 2, 1) and chk["examples"] == ["Backend Engineer · Hyderabad, India"]
        assert chk["employer"]["last_kept"] == 1
        with new_session() as s:
            assert s.exec(select(Job)).all() == []  # a check stores no jobs

        added = c.post("/scout/search/companies/starter").json()
        assert len(added) == len(STARTER) and not any(x["enabled"] for x in added)
        assert {x["origin"] for x in added} == {"starter"}
        assert c.post("/scout/search/companies/starter").json() == []  # only once
        off = c.patch(f"/scout/search/companies/{a['id']}", json={"enabled": False}).json()
        assert off["enabled"] is False
        assert c.delete(f"/scout/search/companies/{a['id']}").json() == {"ok": True}
        assert all(x["id"] != a["id"] for x in c.get("/scout/search/companies").json())


def test_every_starter_company_has_a_valid_board_link():
    seen = set()
    for row in STARTER:
        parsed = parse_careers_url(row["url"])
        assert parsed, row
        assert parsed not in seen
        seen.add(parsed)


# ── collecting in the scan ─────────────────────────────────────────────────────


def _scan(selection=None):
    assert job_search._scan_lock.acquire(blocking=False)
    scan_id = f"t-{utcnow().timestamp()}"
    job_search._current["scan_id"] = scan_id
    with new_session() as s:
        s.add(Scan(id=scan_id, trigger="manual", totals={}))
        s.commit()
    job_search._run(scan_id, "manual", selection)
    with new_session() as s:
        return s.get(Scan, scan_id)


def test_scan_collects_company_boards_and_closes_missing_postings(boards, monkeypatch):
    feed, _ = boards
    listing = [nj("Backend Engineer", "Bengaluru, India"), nj("Backend Engineer", "Austin, US"), nj("Designer", "Pune, India")]
    listing[0] = listing[0].model_copy(update={"description_text": BACKEND_JD,
                                               "apply_links": [{"url": "https://job-boards.greenhouse.io/acme/jobs/1", "direct": True}]})
    monkeypatch.setattr(BOARDS["greenhouse"], "list_jobs", lambda http, board, company: listing)
    with new_session() as s:
        employers.add(s, "https://job-boards.greenhouse.io/acme", "Acme")
        employers.add(s, "https://jobs.lever.co/off", "Off", enabled=False)
    with TestClient(_app()) as c:
        plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"], "sources": ["greenhouse"]}).json()
    names = [x["name"] for x in plan["sources"]]
    assert names == ["jsearch", "greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "keka", "darwinbox", "zohorecruit",
                     "himalayas", "remotejobs", "remotive"]  # one tick box per source
    row = next(x for x in plan["sources"] if x["name"] == "greenhouse")
    assert row["chosen"] and row["summary"] == "1 company · free" and row["details"] == ["Acme"]
    lever = next(x for x in plan["sources"] if x["name"] == "lever")
    assert not lever["chosen"] and lever["summary"].startswith("No companies yet")  # its one company is off
    assert plan["fits_budget"] is True and plan["calls"] == []  # boards only: JSearch skipped

    scan = _scan(ScanSelection(roles=["Backend Engineer"], sources=["greenhouse"]))
    assert scan.phase == "done" and feed.client.calls == []  # JSearch not called
    with new_session() as s:
        [job] = s.exec(select(Job)).all()
        assert job.apply_route == "form:greenhouse" and job.pipeline_status in ("relevant", "mapped")
        call = s.exec(select(ApiCall).where(ApiCall.api == "greenhouse")).one()
        assert (call.results, call.skipped_scope, call.skipped_title, call.new_jobs) == (3, 1, 1, 1)
        acme = s.exec(select(Employer).where(Employer.board == "acme")).one()
        assert (acme.last_found, acme.last_in_scope, acme.last_kept) == (3, 2, 1)
    with TestClient(_app()) as c:
        calls = c.get("/scout/search/calls").json()
        assert calls[0]["api"] == "greenhouse" and calls[0]["skipped_scope"] == 1
        why = c.get(f"/scout/search/calls/{calls[0]['id']}/explain").json()
        assert why["findings"][0] == "The board listed 3 open postings."
        by = {r["source"]: r for r in c.get("/system/jsearch").json()["by_source"]}
        assert by["greenhouse"]["jobs"] == 1 and by["greenhouse"]["agent_can_apply"] == 1

    # The posting disappears from the board: it closed, so the job is marked expired.
    monkeypatch.setattr(BOARDS["greenhouse"], "list_jobs", lambda http, board, company: listing[1:])
    scan = _scan(ScanSelection(roles=["Backend Engineer"], sources=["greenhouse"]))
    assert scan.totals.get("closed") == 1
    with new_session() as s:
        assert s.exec(select(Job)).one().status == "expired"


def test_board_errors_are_recorded_and_the_scan_goes_on(boards, monkeypatch):
    from backend.services.sources import SourceError

    def boom(http, board, company):
        raise SourceError("Greenhouse (gone): not found (HTTP 404)")

    monkeypatch.setattr(BOARDS["greenhouse"], "list_jobs", boom)
    with new_session() as s:
        employers.add(s, "https://job-boards.greenhouse.io/gone", "Gone")
    scan = _scan(ScanSelection(roles=["Backend Engineer"], sources=["greenhouse"]))
    assert scan.phase == "done" and scan.totals.get("board_errors") == 1
    with new_session() as s:
        gone = s.exec(select(Employer)).one()
        assert "404" in gone.last_error and gone.enabled is False  # a board that's gone: the system stops reading it
        assert s.exec(select(ApiCall)).one().status == "error"


def test_the_system_manages_the_company_list(boards):
    from backend.db import set_meta

    with new_session() as s:
        set_meta(s, "starter_companies_version", "")
        s.commit()
    assert employers.sync_starter() == len(STARTER)
    with new_session() as s:
        rows = s.exec(select(Employer)).all()
        assert len(rows) == len(STARTER) and all(e.enabled for e in rows)
        off = rows[0]
        off.enabled = False  # e.g. the system switched off a board that's gone
        s.add(off)
        set_meta(s, "starter_companies_version", "")
        s.commit()
        off_id = off.id
    assert employers.sync_starter() == 0  # nothing new; nothing switched back on
    assert employers.sync_starter() == 0  # once per list version
    with new_session() as s:
        assert s.get(Employer, off_id).enabled is False
