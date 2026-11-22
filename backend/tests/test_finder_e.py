"""Phase 2.7 E: the company finder (seed list, careers pages, name guesses, Common Crawl index),
the Indian board systems (Keka, Darwinbox, Zoho Recruit) and the board read schedule. Offline:
every page and board answer is faked; fixtures are trimmed copies of real public responses."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlmodel import delete, select

from backend.db import CompanyLead, Employer, new_session, utcnow
from backend.job_schemas import FinderSettings
from backend.services import apply_route, company_finder, crawl_index, employers
from backend.services.sources import BOARDS, SourceHttp, parse_careers_url
from backend.tests.test_boards_a1 import boards  # noqa: F401  (fixture)
from backend.tests.test_job_search import env  # noqa: F401

FIX = Path(__file__).parent / "fixtures" / "indian_ats"
CFG = FinderSettings(delay_seconds=0, crawl_delay_seconds=1)


def fake_http(routes: dict[str, object]) -> SourceHttp:
    """A SourceHttp answering from `routes`: "host/path" (or a path suffix) -> JSON-able / text."""
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.host + request.url.path
        for k, body in routes.items():
            if key == k or key.endswith(k):
                if isinstance(body, str):
                    return httpx.Response(200, text=body, headers={"content-type": "text/html"})
                return httpx.Response(200, content=json.dumps(body), headers={"content-type": "application/json"})
        return httpx.Response(404, content=b"{}")
    return SourceHttp(max_retries=0, transport=httpx.MockTransport(handler))


@pytest.fixture
def finder(boards, monkeypatch):
    monkeypatch.setattr(company_finder.time, "sleep", lambda s: None)
    monkeypatch.setattr(crawl_index.time, "sleep", lambda s: None)
    with new_session() as s:
        s.exec(delete(CompanyLead))
        s.commit()
    yield boards
    with new_session() as s:
        s.exec(delete(CompanyLead))
        s.exec(delete(Employer))
        s.commit()


# ── Indian board systems ───────────────────────────────────────────────────────


def test_indian_board_links_are_recognised():
    p = parse_careers_url
    assert p("https://pennanttech.keka.com/careers") == ("keka", "pennanttech")
    assert p("https://spyneai.keka.com/careers/jobdetails/123") == ("keka", "spyneai")
    assert p("https://www.keka.com/pricing") is None  # Keka's own site, not a careers page
    assert p("https://cars24.darwinbox.in/ms/candidate/careers") == ("darwinbox", "cars24")
    assert p("https://moneyforward.zohorecruit.in/jobs/Careers") == ("zohorecruit", "moneyforward.in")
    assert p("https://increff.zohorecruit.com/careers") == ("zohorecruit", "increff.com")
    assert BOARDS["zohorecruit"].board_url("increff.com") == "https://increff.zohorecruit.com/jobs/Careers"
    # Their forms have a CAPTCHA / OTP: these jobs are "needs you", never the agent's.
    for url in ("https://x.keka.com/careers/jobdetails/1", "https://x.darwinbox.in/ms/candidate/careers/a1",
                "https://x.zohorecruit.in/jobs/Careers/1/a"):
        assert apply_route.route_of(url, direct=True).startswith("account:"), url
    assert not BOARDS["keka"].agent_can_apply and BOARDS["lever"].agent_can_apply


def test_indian_boards_map_real_responses():
    keka = json.loads((FIX / "keka_jobs.json").read_text(encoding="utf-8"))
    with fake_http({"acme.keka.com/careers/api/jobs/default/active": keka}) as http:
        [k, _] = BOARDS["keka"].list_jobs(http, "acme", "Acme")
    assert k.title == "Chief Delivery Officer" and k.location_text == "Hyderabad, TG, India"
    assert k.category == "full_time" and k.job_url.startswith("https://acme.keka.com/careers/jobdetails/")
    assert k.source_published_at is not None and employers.in_scope(k)

    jobs = json.loads((FIX / "darwinbox_jobs.json").read_text(encoding="utf-8"))
    detail = json.loads((FIX / "darwinbox_job.json").read_text(encoding="utf-8"))
    jid = jobs["message"]["jobs"][0]["id"]
    with fake_http({"acme.darwinbox.in/ms/candidateapi/job": jobs, f"acme.darwinbox.in/ms/candidateapi/job/{jid}": detail}) as http:
        listed = BOARDS["darwinbox"].list_jobs(http, "acme", "Acme")
        full = BOARDS["darwinbox"].complete(http, "acme", listed[0])
    assert len(listed) == 2 and listed[0].location_text == "Gurgaon, Haryana, India" and listed[0].category == "full_time"
    assert listed[0].description_html is None and full.description_html == "<p>Own procurement.</p>"

    page = (FIX / "zohorecruit_careers.html").read_text(encoding="utf-8")
    with fake_http({"acme.zohorecruit.in/jobs/Careers": page}) as http:
        z = BOARDS["zohorecruit"].list_jobs(http, "acme.in", "Acme")
    assert z[1].title.startswith("Senior AI QA Engineer") and z[1].location_text.endswith("India")
    assert z[1].job_url.startswith("https://acme.zohorecruit.in/jobs/Careers/") and z[1].category == "full_time"


def test_smartrecruiters_asks_for_india_only():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"content": [], "totalFound": 0})

    with SourceHttp(max_retries=0, transport=httpx.MockTransport(handler)) as http:
        BOARDS["smartrecruiters"].list_jobs(http, "Acme", "Acme")
    assert seen[0]["country"] == "in"


# ── working out a board ────────────────────────────────────────────────────────


def test_careers_page_links_and_name_guesses():
    page = """<a href="/about">About</a><iframe src="https://acme.keka.com/careers"></iframe>
              <script>var u = "https://jobs.lever.co/acme/abc-123";</script>"""
    assert {(k, b) for k, b, _ in company_finder.board_links(page, "https://acme.com/careers")} == {("keka", "acme"), ("lever", "acme")}
    assert company_finder.slug_candidates("Acme Technologies Pvt Ltd", "acmehq.com") == ["acmehq", "acme"]
    assert company_finder.slug_candidates("Big Basket", None) == ["bigbasket", "big-basket"]
    assert company_finder.slug_candidates("Jar", "jar.app") == []  # too short to be sure


def _lever(*places: str) -> list[dict]:
    return [{"id": f"j{i}", "text": "Backend Engineer", "categories": {"location": p}, "hostedUrl": f"https://jobs.lever.co/acme/j{i}"}
            for i, p in enumerate(places)]


def test_a_seed_company_found_through_its_careers_page_is_kept(finder):
    with new_session() as s:
        lead = CompanyLead(name="Acme", domain="acme.com", origin="seed")
        s.add(lead)
        s.commit()
        routes = {"acme.com/careers": '<a href="https://jobs.lever.co/acme">Open roles</a>',
                  "api.lever.co/v0/postings/acme": _lever("Bengaluru, India", "Austin, TX")}
        with fake_http(routes) as http:
            status = company_finder.check_lead(s, http, lead, employers.role_phrases(s), CFG)
        s.commit()
        assert status == "kept" and (lead.kind, lead.board, lead.how) == ("lever", "acme", "careers_page")
        assert (lead.total_jobs, lead.india_jobs, lead.matching_jobs) == (2, 1, 1)
        e = s.get(Employer, lead.employer_id)
        assert e.enabled and e.origin == "discovered" and "careers page" in e.note


def test_a_guessed_board_without_india_jobs_waits_for_a_recheck(finder):
    with new_session() as s:
        lead = CompanyLead(name="Globex Corp", origin="seed")  # no website: the name is tried
        s.add(lead)
        s.commit()
        with fake_http({"api.lever.co/v0/postings/globexcorp": _lever("Berlin, Germany")}) as http:
            status = company_finder.check_lead(s, http, lead, employers.role_phrases(s), CFG)
        s.commit()
        assert status == "no_india_jobs" and lead.how == "guessed" and lead.kind == "lever"
        assert lead.next_check_at is not None and s.exec(select(Employer)).first() is None
        # ...and it isn't due again until the re-check date.
        assert lead not in company_finder.due_leads(s, 10)

        nothing = CompanyLead(name="Initech Labs", origin="seed")
        s.add(nothing)
        s.commit()
        with fake_http({}) as http:
            assert company_finder.check_lead(s, http, nothing, [], CFG) == "no_board"
        assert nothing.kind is None and nothing.next_check_at > utcnow() + timedelta(days=80)


# ── the Common Crawl index ─────────────────────────────────────────────────────


def test_crawl_index_pages_become_leads(finder):
    with new_session() as s:
        s.add(Employer(name="Known", kind="lever", board="known", enabled=True))
        s.commit()
    page = "\n".join(json.dumps({"url": u, "status": "200"}) for u in (
        "https://jobs.lever.co/newco/abc", "https://jobs.lever.co/newco/def", "https://jobs.lever.co/known/x",
        "https://jobs.lever.co/", "https://example.com/nothing"))
    routes = {"index.commoncrawl.org/collinfo.json": [{"id": "CC-MAIN-2026-43", "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-43-index"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("collinfo.json"):
            return httpx.Response(200, json=routes["index.commoncrawl.org/collinfo.json"])
        p = request.url.params
        if p.get("showNumPages"):
            return httpx.Response(200, json={"pages": 1 if p["url"] == "jobs.lever.co/*" else 0})
        return httpx.Response(200, text=page)

    with SourceHttp(max_retries=0, transport=httpx.MockTransport(handler)) as http:
        added = crawl_index.harvest(FinderSettings(crawl_delay_seconds=1, crawl_pages_per_run=50), http)
    assert added == 1  # newco; "known" is already a company
    with new_session() as s:
        [lead] = s.exec(select(CompanyLead)).all()
        assert (lead.origin, lead.kind, lead.board, lead.name) == ("crawl", "lever", "newco", "Newco")
        prog = crawl_index.progress(s)
        assert prog.collection == "CC-MAIN-2026-43" and prog.leads == 1
    with SourceHttp(max_retries=0, transport=httpx.MockTransport(handler)) as http:
        assert crawl_index.harvest(FinderSettings(crawl_delay_seconds=1), http) == 0  # finished: nothing re-read


# ── the board read schedule ────────────────────────────────────────────────────


def test_quiet_boards_are_read_weekly_until_your_roles_change(finder, monkeypatch):
    from backend.job_schemas import ScanSelection
    from backend.tests.test_boards_a1 import _scan

    reads = []

    def lever(http, board, company):
        reads.append(board)
        return []  # nothing matching your roles: the board turns quiet

    monkeypatch.setattr(BOARDS["lever"], "list_jobs", lever)
    with new_session() as s:
        s.add(Employer(name="Quiet", kind="lever", board="quiet", enabled=True))
        s.commit()
    _scan(ScanSelection(roles=["Backend Engineer"], sources=["lever"]))
    with new_session() as s:
        e = s.exec(select(Employer)).one()
        assert e.next_read_at is not None and not employers.due(e)
        [row] = [r for r in employers.plan_rows(s) if r.name == "lever"]
        assert "none due" in row.summary and employers.planned(s) == 0
    scan = _scan(ScanSelection(roles=["Backend Engineer"], sources=["lever"]))
    assert reads == ["quiet"] and scan.totals.get("boards_quiet") == 1
    with new_session() as s:  # your roles changed: every board is due again
        from backend.db import set_meta

        set_meta(s, "boards_roles_key", "something else")
        s.commit()
        assert employers.planned(s) == 1
