"""Phase 2.7 A0: the source contract, budget per source, apply route per job, Sources in the scan
plan, per-source analytics. Offline (fake JSearch)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select

from backend.db import Job, new_session, set_meta
from backend.job_schemas import SourcesSettings
from backend.services import api_budget, apply_route, job_search
from backend.services.sources import SOURCES
from backend.tests.test_job_search import BACKEND_JD, env, nj, run_scan  # noqa: F401  (env is a fixture)
from backend.tests.test_role_contexts import _app, _criteria

GH = "https://boards.greenhouse.io/acme/jobs/123"


def test_every_source_follows_the_contract():
    for name, a in SOURCES.items():
        assert a.name == name and a.label and a.kind in ("search", "board", "feed", "page")
        assert isinstance(a.quota, bool) and isinstance(a.env_keys, tuple) and isinstance(a.configured(), bool)


def test_apply_route_of_a_link():
    r = apply_route.route_of
    assert r(GH) == "form:greenhouse"
    assert r("https://jobs.lever.co/acme/abc") == "form:lever"
    assert r("https://jobs.ashbyhq.com/acme/1") == "form:ashby"
    assert r("https://acme.wd3.myworkdayjobs.com/en-US/careers/job/1") == "account:workday"
    assert r("https://in.linkedin.com/jobs/view/1") == "platform:linkedin"
    assert r("https://www.naukri.com/job-listings-1") == "platform:naukri"
    assert r("https://in.jooble.org/desc/1") == "aggregator:jooble"
    assert r("https://www.someboard.in/job/1") == "aggregator:someboard"
    assert r("https://jobs.gsk.com/en-gb/jobs/1", company="GSK") == "direct"  # the employer's own site
    assert r("https://careers-inc.nttdata.com/job/1", company="NTT DATA") == "direct"
    assert r("https://anything.example/apply", direct=True) == "direct"  # the source says so
    assert r(None) is None and r("not a url") is None


def test_best_route_wins_and_better():
    links = [("https://in.linkedin.com/jobs/view/1", False), ("https://in.jooble.org/desc/1", False), (GH, False)]
    assert apply_route.best(links, "Acme") == ("form:greenhouse", GH)
    assert apply_route.best([], "Acme") == (None, None)
    assert apply_route.better("form:lever", "aggregator:jooble") and not apply_route.better("platform:x", "direct")
    assert apply_route.better("direct", None) and not apply_route.better(None, "direct")


def test_scan_stores_the_apply_route_and_upgrades_it(env):
    feed, _ = env
    feed.jobs = [nj("jsearch", "r1", "Backend Engineer Intern", BACKEND_JD,
                    apply_links=[{"url": "https://in.jooble.org/desc/9", "direct": False}])]
    run_scan()
    with new_session() as s:
        job = s.exec(select(Job)).one()
        assert job.apply_route == "aggregator:jooble"
    # Seen again with a company form among its links: the better route is kept.
    feed.jobs = [nj("jsearch", "r1", "Backend Engineer Intern", BACKEND_JD,
                    apply_links=[{"url": "https://in.jooble.org/desc/9", "direct": False}, {"url": GH, "direct": False}])]
    run_scan()
    with new_session() as s:
        job = s.exec(select(Job)).one()
        assert (job.apply_route, job.apply_route_url) == ("form:greenhouse", GH)
    with TestClient(_app()) as c:
        assert [j["apply_route"] for j in c.get("/scout/search/jobs", params={"apply": "form"}).json()["fits"]] == ["form:greenhouse"]
        out = c.get("/scout/search/jobs", params={"apply": "platform"}).json()
        assert out["fits"] + out["other"] == []


def test_routes_are_derived_on_start_from_stored_raw_records(env):
    raw = {"apply_options": [{"apply_link": "https://in.linkedin.com/jobs/view/1", "is_direct": False},
                             {"apply_link": "https://jobs.lever.co/acme/1", "is_direct": False}]}
    with new_session() as s:
        s.add(Job(title="Backend Engineer", dedupe_key="a", content_hash="a", raw_payload=raw, company_name="Acme"))
        s.add(Job(title="Backend Engineer 2", dedupe_key="b", content_hash="b", job_url="https://www.naukri.com/x"))
        set_meta(s, "apply_route_version", "0")
        s.commit()
    assert job_search.apply_routes_if_needed() == 2
    assert job_search.apply_routes_if_needed() == 0  # once per rules version
    with new_session() as s:
        routes = sorted(j.apply_route for j in s.exec(select(Job)).all())
    assert routes == ["form:lever", "platform:naukri"]


def test_scan_plan_lists_sources_and_one_can_be_skipped(env):
    _criteria()
    with TestClient(_app()) as c:
        plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"]}).json()
        js = plan["sources"][0]
        assert js["name"] == "jsearch" and js["chosen"] and js["requests"] == 1 and js["summary"].startswith("1 request")
        skipped = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"], "sources": []}).json()
        assert skipped["calls"] == [] and skipped["fits_budget"] is False
        assert skipped["sources"][0]["summary"] == "Skipped this scan"
        assert any("No source ticked" in n for n in skipped["notes"])
        assert c.post("/scout/search/scan", json={"roles": ["Backend Engineer"], "sources": []}).status_code == 400


def test_budget_is_counted_per_source(env):
    cfg = SourcesSettings(monthly_limit=50, reserve=0, daily_limit_on=False)
    api_budget.reserve_call(cfg, purpose="scan", params={}, api="othersource", label="Other")
    with new_session() as s:
        assert api_budget.quota(s, cfg).month_used == 0  # JSearch's count is untouched
        assert api_budget.quota(s, cfg, api="othersource").month_used == 1


def test_analytics_has_a_row_per_source(env):
    feed, _ = env
    feed.jobs = [nj("jsearch", "y1", "Backend Engineer Intern", BACKEND_JD, apply_links=[{"url": GH, "direct": False}])]
    run_scan()
    with TestClient(_app()) as c:
        rows = c.get("/system/jsearch").json()["by_source"]
    assert rows[0]["source"] == "jsearch" and {r["source"] for r in rows} >= {"greenhouse", "lever", "ashby", "smartrecruiters"}
    assert rows[0]["requests"] == 1 and rows[0]["jobs"] == 1 and rows[0]["agent_can_apply"] == 1
