"""Phase 2.7 C1 (remote feeds open to India) + the Workable / Recruitee boards. Offline: fake
HTTP responses or faked fetches, never a real feed or board."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.config import write_tuning
from backend.db import ApiCall, Job, new_session
from backend.job_schemas import NormalizedJob, ScanSelection
from backend.services import remote_feeds
from backend.services.sources import BOARDS, FEEDS, parse_careers_url
from backend.services.sources.feeds import open_text
from backend.tests.test_boards_a1 import _scan, boards, http_with  # noqa: F401  (boards is a fixture)
from backend.tests.test_job_search import BACKEND_JD, env  # noqa: F401
from backend.tests.test_role_contexts import _app


@pytest.fixture
def feeds(boards):
    write_tuning({("scout", "search", "feeds", "enabled"): True, ("scout", "search", "feeds", "delay_seconds"): 0})
    yield boards
    write_tuning({("scout", "search", "feeds", "enabled"): False})


# ── who may apply: the India check ─────────────────────────────────────────────


def test_free_text_location_rules():
    for ok in ("", "Worldwide", "Anywhere in the World", "APAC", "Asia", "India", "USA, India", "Remote", "Europe, Asia"):
        assert open_text(ok), ok
    for no in ("USA Only", "Europe", "UK, Canada", "Americas", "EMEA Only", "Germany"):
        assert not open_text(no), no


def _raw(name: str, raw: dict) -> NormalizedJob:
    return NormalizedJob(source=name, source_job_id="1", company_name="C", title="T", raw=raw)


def test_each_feed_reads_its_own_eligibility_field():
    h, r, rj = FEEDS["himalayas"], FEEDS["remotive"], FEEDS["remotejobs"]
    assert h.open_to_india(_raw("himalayas", {"locationRestrictions": []}))  # empty = worldwide
    assert h.open_to_india(_raw("himalayas", {"locationRestrictions": [{"alpha2": "IN"}, {"alpha2": "US"}]}))
    assert not h.open_to_india(_raw("himalayas", {"locationRestrictions": [{"alpha2": "US"}]}))
    assert r.open_to_india(_raw("remotive", {"candidate_required_location": "Worldwide"}))
    assert not r.open_to_india(_raw("remotive", {"candidate_required_location": "USA Only"}))
    assert rj.open_to_india(_raw("remotejobs", {"location_normalization": {"scope": "worldwide"}}))
    assert not rj.open_to_india(_raw("remotejobs", {"location_normalization": {"allowed_countries": ["US", "CA"]}}))
    assert not rj.open_to_india(_raw("remotejobs", {"location_normalization": {"excluded_countries": ["IN"]}}))
    assert rj.open_to_india(_raw("remotejobs", {}))  # the server already filtered on country=IN


def test_feeds_map_jobs():
    hima = {"jobs": [{"guid": "https://himalayas.app/companies/acme/jobs/ai-engineer", "title": "AI Engineer",
                      "companyName": "Acme", "employmentType": "Full Time", "description": "<p>LLMs</p>",
                      "pubDate": 1763000000, "applicationLink": "https://jobs.lever.co/acme/9/apply",
                      "locationRestrictions": [{"alpha2": "IN", "name": "India"}]}]}
    with http_with({"/jobs/api/search": hima}) as http:
        [j] = FEEDS["himalayas"].fetch(http, "AI Engineer")
    assert (j.title, j.company_name, j.category, j.location_text) == ("AI Engineer", "Acme", "full_time", "Remote (India)")
    assert j.job_url.startswith("https://himalayas.app/") and j.apply_url == "https://jobs.lever.co/acme/9/apply"

    rem = {"jobs": [{"id": 7, "url": "https://remotive.com/remote-jobs/software-dev/x-7", "title": "Backend Engineer",
                     "company_name": "Beta", "job_type": "full_time", "publication_date": "2026-11-20T10:00:00",
                     "candidate_required_location": "Worldwide", "description": "<p>Go</p>"}]}
    with http_with({"/api/remote-jobs": rem}) as http:
        [r] = FEEDS["remotive"].fetch(http, None)
    assert (r.source_job_id, r.location_text, r.workplace_type) == ("7", "Remote (Worldwide)", "remote")

    rj = {"jobs": [{"id": "abc", "title": "ML Engineer", "company": {"name": "Gamma"}, "url": "https://remotejobs.org/jobs/abc",
                    "apply_url": "https://remotejobs.org/jobs/abc/apply", "posted_at": "2026-11-19T00:00:00Z",
                    "employment_types": ["full-time"], "location": "Remote (Worldwide)"}]}
    with http_with({"/api/v1/jobs": rj}) as http:
        [m] = FEEDS["remotejobs"].fetch(http, "ML Engineer")
    assert (m.company_name, m.category, m.location_text) == ("Gamma", "full_time", "Remote (Worldwide)")


# ── in the scan ────────────────────────────────────────────────────────────────


def _feed_job(source: str, jid: str, title: str, where: str, apply: str | None = None) -> NormalizedJob:
    return NormalizedJob(source=source, source_job_id=jid, company_name=f"Co {jid}", title=title,
                         description_text=BACKEND_JD, location_text=f"Remote ({where})", workplace_type="remote",
                         is_remote=True, job_url=f"https://{source}.example/{jid}", apply_url=apply,
                         apply_links=[{"url": apply, "direct": False}] if apply else [],
                         raw={"candidate_required_location": where, "locationRestrictions": [] if where == "Worldwide"
                              else [{"alpha2": "US"}]})


def test_scan_collects_feeds_open_to_india_and_finds_their_companies(feeds, monkeypatch):
    asked = []

    def hima(http, q):
        asked.append(q)
        return [_feed_job("himalayas", "h1", "Backend Engineer", "Worldwide", "https://jobs.lever.co/fromfeed/1/apply"),
                _feed_job("himalayas", "h2", "Backend Engineer", "USA Only"),
                _feed_job("himalayas", "h3", "Designer", "Worldwide")]

    monkeypatch.setattr(FEEDS["himalayas"], "fetch", hima)
    monkeypatch.setattr(BOARDS["lever"], "list_jobs", lambda http, b, c: [])
    with TestClient(_app()) as c:
        plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"], "sources": ["himalayas"]}).json()
    row = next(x for x in plan["sources"] if x["name"] == "himalayas")
    assert row["kind"] == "feed" and row["chosen"] and row["details"] == ["Backend Engineer"]
    assert row["summary"].startswith("1 request · free")
    assert plan["fits_budget"] is True

    scan = _scan(ScanSelection(roles=["Backend Engineer"], sources=["himalayas", "lever"]))
    assert scan.phase == "done" and asked == ["Backend Engineer"] and scan.totals["feed_requests"] == 1
    with new_session() as s:
        [job] = s.exec(select(Job)).all()
        assert job.apply_route == "form:lever"  # the feed linked to the company's own form
        call = s.exec(select(ApiCall).where(ApiCall.api == "himalayas")).one()
        assert (call.results, call.skipped_scope, call.skipped_title, call.new_jobs) == (3, 1, 1, 1)
        # ...and that company's board is now read on every scan (Phase 2.7 A3).
        assert scan.totals.get("companies_found") == 1
    with TestClient(_app()) as c:
        calls = c.get("/scout/search/calls").json()
        feed_call = next(x for x in calls if x["api"] == "himalayas")
        assert feed_call["source_kind"] == "feed" and feed_call["source_label"] == "Himalayas"
        why = c.get(f"/scout/search/calls/{feed_call['id']}/explain").json()
        assert why["findings"][0] == "The feed returned 3 remote jobs."
        assert "not open to candidates in India" in why["findings"][1]
        # Scan Jobs → Scans and what they found: one entry for the scan, every source inside it.
        [entry] = c.get("/scout/search/scan-requests").json()
        assert entry["scan_id"] == scan.id and entry["trigger"] == "manual"
        assert sorted(x["api"] for x in entry["calls"]) == ["himalayas", "lever"]
        board = next(x for x in entry["calls"] if x["api"] == "lever")
        assert board["source_kind"] == "board" and board["params"]["company"] and board["scan_id"] == scan.id


def test_remotive_is_read_at_most_every_few_hours(feeds, monkeypatch):
    monkeypatch.setattr(FEEDS["remotive"], "fetch", lambda http, q: [_feed_job("remotive", "r1", "Backend Engineer", "Worldwide")])
    _scan(ScanSelection(roles=["Backend Engineer"], sources=["remotive"]))
    with new_session() as s:
        assert remote_feeds.planned(s, ScanSelection(roles=["Backend Engineer"], sources=["remotive"])) == 0
        [row] = [r for r in remote_feeds.plan_rows(s) if r.name == "remotive"]
        assert not row.chosen and row.summary.startswith("Read recently")
    scan = _scan(ScanSelection(roles=["Backend Engineer"], sources=["remotive"]))
    assert scan.totals.get("feed_requests") is None  # skipped: no second read


# ── Workable + Recruitee boards ────────────────────────────────────────────────


def test_workable_and_recruitee_links_and_jobs():
    p = parse_careers_url
    assert p("https://apply.workable.com/acme/j/AB12CD34/") == ("workable", "acme")
    assert p("https://apply.workable.com/api/v1/widget/accounts/acme") == ("workable", "acme")
    assert p("https://apply.workable.com/j/AB12CD34") is None  # share link: no account in it
    assert p("https://acme.recruitee.com/o/backend-engineer") == ("recruitee", "acme")
    assert p("https://support.recruitee.com/en/articles/1") is None

    wk = {"name": "Acme", "jobs": [{"title": "Backend Engineer", "shortcode": "AB12", "employment_type": "Full-time",
                                    "telecommuting": False, "published_on": "2026-11-18",
                                    "url": "https://apply.workable.com/acme/j/AB12/",
                                    "application_url": "https://apply.workable.com/acme/j/AB12/apply/",
                                    "locations": [{"city": "Pune", "region": "Maharashtra", "country": "India",
                                                   "countryCode": "IN"}], "description": "<p>APIs</p>"}]}
    with http_with({"/api/v1/widget/accounts/acme": wk}) as http:
        [w] = BOARDS["workable"].list_jobs(http, "acme", "Acme")
    assert (w.source_job_id, w.location_text, w.category) == ("acme:AB12", "Pune, Maharashtra, India", "full_time")
    assert w.apply_url.endswith("/apply/")

    rc = {"offers": [{"id": 5, "slug": "ml-engineer", "title": "ML Engineer", "status": "published",
                      "description": "<p>Models</p>", "requirements": "<ul><li>PyTorch</li></ul>", "remote": True,
                      "hybrid": False, "on_site": False, "employment_type_code": "fulltime_permanent",
                      "published_at": "2026-11-17 10:00:00 UTC",
                      "careers_url": "https://acme.recruitee.com/o/ml-engineer",
                      "careers_apply_url": "https://acme.recruitee.com/o/ml-engineer/c/new",
                      "locations": [{"city": "Bengaluru", "country": "India", "name": "Bengaluru, India"}]},
                     {"id": 6, "title": "Draft", "status": "draft"}]}
    with http_with({"/api/offers/": rc}) as http:
        [r] = BOARDS["recruitee"].list_jobs(http, "acme", "Acme")
    assert (r.workplace_type, r.category, r.location_text) == ("remote", "full_time", "Bengaluru, India")
    assert "PyTorch" in r.description_html and r.apply_url.endswith("/c/new")
