"""JSearch (Phase 2.5): client, query planner, request budget, budgeted scans. Offline; fake data."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlmodel import select

from backend.config import get_settings, write_tuning
from backend.db import ApiCall, AppSetting, Job, JobRequirement, SearchQuery, new_session
from backend.job_schemas import ScheduleSettings, SearchCriteria, SourcesSettings
from backend.services import api_budget, compass, search_plan
from backend.services.sources import JSEARCH
from backend.services.sources.base import SourceHttp
from backend.services.sources.jsearch import JSearchError
from backend.tests.test_job_search import BACKEND_JD, env, nj, run_scan  # noqa: F401  (env is a fixture)

REC = {
    "job_id": "abc123==",
    "employer_name": "Example Labs",
    "job_publisher": "LinkedIn",
    "job_employment_type": "FULLTIME",
    "job_employment_types": ["FULLTIME", "INTERN"],
    "job_title": "AI Engineer",
    "job_apply_link": "https://www.linkedin.com/jobs/view/1",
    "apply_options": [{"publisher": "Example Labs", "apply_link": "https://careers.example.com/ai-1", "is_direct": True}],
    "job_description": "We build LLM agents. You will ship RAG features.",
    "job_is_remote": False,
    "job_posted_at_datetime_utc": "2026-11-15T09:00:00.000Z",
    "job_city": "Bengaluru",
    "job_state": "Karnataka",
    "job_country": "IN",
    "job_min_salary": 1500000,
    "job_max_salary": 2500000,
    "job_salary_currency": "INR",
    "job_salary_period": "YEAR",
    "job_highlights": {
        "Qualifications": ["2+ years of Python", "Experience with RAG and vector databases"],
        "Responsibilities": ["Build LLM agents for customers"],
        "Benefits": ["Health insurance"],
    },
}


def cfg(**kw) -> SourcesSettings:
    """Budget settings for unit tests: no daily limit unless a test sets one."""
    kw.setdefault("daily_limit_on", kw.get("daily_limit", 0) > 0)
    return SourcesSettings(**{"daily_limit": 0, **kw})


@pytest.fixture
def clean_calls():
    """No logged calls and no stored provider usage (so the budget uses calendar months)."""
    from backend.db import set_meta
    from backend.services import jsearch_usage

    with new_session() as s:
        for c in s.exec(select(ApiCall)).all():
            s.delete(c)
        set_meta(s, jsearch_usage.KEY, "")
        s.commit()
    yield


# ── client ─────────────────────────────────────────────────────────────────────


def test_normalize_fields_highlights_and_direct_link():
    job = JSEARCH.normalize(REC)
    assert job.title == "AI Engineer" and job.company_name == "Example Labs"
    assert job.location_text == "Bengaluru, Karnataka, India"
    assert job.category == "full_time"  # first known type
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == (1500000, 2500000, "INR", "year")
    assert job.job_url == "https://careers.example.com/ai-1"  # direct apply option preferred
    assert job.highlights == {"Qualifications": REC["job_highlights"]["Qualifications"],
                              "Responsibilities": ["Build LLM agents for customers"], "Benefits": ["Health insurance"]}
    assert job.tags == ["via LinkedIn"]


def test_salary_without_currency_stays_unknown():
    job = JSEARCH.normalize({**REC, "job_salary_currency": None})
    assert job.salary_min is None and job.salary_currency is None


@pytest.mark.parametrize("payload", [{"data": [REC]}, {"data": {"jobs": [REC], "cursor": None}}])
def test_both_response_shapes(monkeypatch, payload):
    monkeypatch.setattr(get_settings(), "jsearch_api_key", "k")
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=payload)

    with SourceHttp(transport=httpx.MockTransport(handler), max_retries=3) as http:
        jobs, n = JSEARCH.search(http, {"query": "AI Engineer in India", "country": "in"})
    assert n == 1 and jobs[0].source_job_id == "abc123=="


def test_provider_picks_url_and_key_header(monkeypatch):
    monkeypatch.setattr(get_settings(), "jsearch_api_key", "k")
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"data": []})

    with SourceHttp(transport=httpx.MockTransport(handler)) as http:
        JSEARCH.search(http, {"query": "x"}, "openwebninja")
        JSEARCH.search(http, {"query": "x"}, "rapidapi")
    own, rapid = seen
    assert str(own.url).startswith("https://api.openwebninja.com/jsearch/search") and own.headers["x-api-key"] == "k"
    assert "X-RapidAPI-Key" not in own.headers
    assert rapid.url.host == "jsearch.p.rapidapi.com" and rapid.headers["X-RapidAPI-Key"] == "k"
    assert rapid.headers["X-RapidAPI-Host"] == "jsearch.p.rapidapi.com"


@pytest.mark.parametrize("code,match", [(401, "rejected the key"), (403, "rejected the key"), (429, "HTTP 429")])
def test_errors_are_clear_and_never_retried(monkeypatch, code, match):
    monkeypatch.setattr(get_settings(), "jsearch_api_key", "k")
    calls: list[httpx.Request] = []

    def handler(req):
        calls.append(req)
        return httpx.Response(code)

    with SourceHttp(transport=httpx.MockTransport(handler), max_retries=3) as http:
        with pytest.raises(JSearchError, match=match) as e:
            JSEARCH.search(http, {"query": "x"})
    assert len(calls) == 1 and e.value.http_status == code


# ── planner ────────────────────────────────────────────────────────────────────


NOW = datetime(2026, 11, 17, 9, tzinfo=UTC)


def q(**kw) -> SearchQuery:
    return SearchQuery(**{"key": "k", "role": "AI Engineer", "place": "India", "country": "IN", **kw})


def test_criteria_map_to_jsearch_params():
    c = SearchCriteria(roles=["AI Engineer"], job_types=["internship", "full_time", "freelance"], workplace=["remote"],
                       experience_years=2)
    p = search_plan.params_for(q(), c, ScheduleSettings(recency_days=30), cfg(excluded_publishers=["BeeBe", " "]), NOW)
    assert p == {"query": "AI Engineer in India", "country": "in", "page": 1, "num_pages": 1, "date_posted": "month",
                 "employment_types": "CONTRACTOR,FULLTIME,INTERN", "work_from_home": "true",
                 "exclude_job_publishers": "BeeBe"}  # no experience filter since 2026-11-20 (Jobs page filter)


def test_filters_jsearch_cannot_apply_are_not_sent():
    c = SearchCriteria(roles=["AI Engineer"], workplace=["remote", "hybrid"], experience_years=None)
    p = search_plan.params_for(q(), c, ScheduleSettings(), cfg(), NOW)
    assert "work_from_home" not in p and "job_requirements" not in p and "employment_types" not in p


@pytest.mark.parametrize("last,expected", [(None, "month"), (timedelta(hours=20), "today"), (timedelta(days=2), "3days"),
                                           (timedelta(days=6), "week"), (timedelta(days=20), "month")])
def test_date_posted_is_incremental(last, expected):
    since = None if last is None else NOW - last
    assert search_plan.date_posted(since, SearchCriteria(), ScheduleSettings(recency_days=30), NOW) == expected


def test_posted_within_caps_the_window():
    assert search_plan.date_posted(None, SearchCriteria(posted_within_days=3), ScheduleSettings(recency_days=30), NOW) == "3days"


def test_queries_are_role_x_place_and_default_country():
    c = SearchCriteria(roles=["AI Engineer", "Backend Engineer"], locations=["India", "Bengaluru"])
    assert search_plan.wanted_queries(c, cfg()) == [
        ("AI Engineer", "India", "IN"), ("Backend Engineer", "India", "IN"),
        ("AI Engineer", "Bengaluru", "IN"), ("Backend Engineer", "Bengaluru", "IN")]
    assert search_plan.wanted_queries(SearchCriteria(roles=["AI Engineer"]), cfg(api_country="IN")) == [("AI Engineer", "India", "IN")]


def test_due_and_backoff():
    fresh = q(last_run_at=NOW - timedelta(hours=10))
    assert not search_plan.is_due(fresh, NOW) and search_plan.is_due(q(), NOW)
    assert search_plan.is_due(q(last_run_at=NOW - timedelta(hours=23)), NOW)  # 2 h slack for a daily scan
    with new_session() as s:
        row = q(key="backoff-test")
        s.add(row)
        s.commit()
        for _ in range(3):
            search_plan.record_run(s, row.id, requests=1, results=10, new_jobs=0, ok=True, backoff_after_empty=3, now=NOW)
        s.refresh(row)
        assert row.zero_streak == 3 and row.interval_days == 3
        search_plan.record_run(s, row.id, requests=1, results=10, new_jobs=4, ok=True, backoff_after_empty=3, now=NOW)
        s.refresh(row)
        assert row.zero_streak == 0 and row.interval_days == 1
        s.delete(row)
        s.commit()


# ── budget ─────────────────────────────────────────────────────────────────────


def test_daily_limit_switch_and_period_figures(clean_calls):
    c = cfg(monthly_limit=40, reserve=10, daily_limit=2, max_per_scan=8)  # limit on
    nov1 = datetime(2026, 11, 1, 8, tzinfo=UTC)
    with new_session() as s:
        assert api_budget.quota(s, c, nov1).today_allowance == 2
    api_budget.reserve_call(c, purpose="scan", params={}, now=nov1)
    api_budget.reserve_call(c, purpose="scan", params={}, now=nov1)
    with pytest.raises(api_budget.BudgetExhausted, match="Requests per day"):
        api_budget.reserve_call(c, purpose="scan", params={}, now=nov1)
    api_budget.reserve_call(c, purpose="calibration", params={}, now=nov1)  # the reserve stays open
    with new_session() as s:
        q = api_budget.quota(s, c, nov1)
    # 30 days, 30 for scans: an even pace expects 1 by end of today; 2 used -> 1 ahead.
    assert (q.days_left, q.scan_budget, q.scan_used, q.scan_left) == (30, 30, 2, 28)
    assert (q.expected_by_today, q.ahead_by, q.even_pace) == (1, 1, 1)
    # Turned off: everything left may be spent today.
    with new_session() as s:
        assert api_budget.quota(s, cfg(monthly_limit=40, reserve=10, daily_limit=2, daily_limit_on=False),
                                nov1).today_allowance == 28
    # Back on the next day: the daily number applies again, however much was spent before.
    for _ in range(20):
        api_budget.reserve_call(cfg(monthly_limit=40, reserve=10, daily_limit_on=False), purpose="scan", params={},
                                now=nov1)
    with new_session() as s:
        q = api_budget.quota(s, c, datetime(2026, 11, 2, 8, tzinfo=UTC))
    assert q.today_allowance == 2 and q.ahead_by > 0
    # ...but never past what's left of the month for scans.
    with new_session() as s:
        assert api_budget.quota(s, cfg(monthly_limit=40, reserve=10, daily_limit=8),
                                datetime(2026, 11, 2, 8, tzinfo=UTC)).today_allowance == 8
        assert api_budget.quota(s, cfg(monthly_limit=35, reserve=10, daily_limit=8),
                                datetime(2026, 11, 2, 8, tzinfo=UTC)).today_allowance == 3


def test_reserve_and_hard_cap(clean_calls):
    c = cfg(monthly_limit=40, reserve=10, max_per_scan=8)  # no daily limit
    nov30 = datetime(2026, 11, 30, 8, tzinfo=UTC)
    with new_session() as s:
        qo = api_budget.quota(s, c, nov30)
    assert (qo.today_allowance, qo.scan_allowance, qo.resets_on) == (30, 8, "2026-12-01")
    for _ in range(10):
        api_budget.reserve_call(c, purpose="calibration", params={}, now=nov30)  # reserve used up: 10
    for _ in range(30):
        api_budget.reserve_call(c, purpose="scan", params={}, now=nov30)
    with pytest.raises(api_budget.BudgetExhausted, match="monthly limit"):
        api_budget.reserve_call(c, purpose="calibration", params={}, now=nov30)


def test_429_pauses_until_tomorrow(clean_calls):
    from backend.db import set_meta

    c = cfg()
    api_budget.block_for_today(NOW)
    try:
        with new_session() as s:
            assert api_budget.quota(s, c, NOW).today_allowance == 0
            assert api_budget.quota(s, c, NOW + timedelta(days=1)).today_allowance > 0
        with pytest.raises(api_budget.BudgetExhausted, match="paused"):
            api_budget.reserve_call(c, purpose="calibration", params={}, now=NOW)
    finally:
        with new_session() as s:
            set_meta(s, api_budget.BLOCK_KEY, "")
            s.commit()


# ── budgeted scans (fake JSearch, real pipeline) ───────────────────────────────


def test_scan_sends_the_plan_logs_calls_and_credits_relevance(env):
    feed, _ = env
    feed.jobs = [nj("jsearch", "1", "Backend Engineer Intern", BACKEND_JD)]
    scan = run_scan()
    assert scan.phase == "done" and scan.totals["requests"] == 1
    assert feed.client.calls[0]["query"] == "Backend Engineer in India"
    with new_session() as s:
        call = s.exec(select(ApiCall)).one()
        assert (call.status, call.results, call.new_jobs, call.relevant_jobs) == ("ok", 1, 1, 1)
        assert "key" not in str(call.params).lower()
        sq = s.exec(select(SearchQuery)).one()
        assert (sq.runs, sq.new_jobs, sq.relevant_jobs, sq.recent) == (1, 1, 1, [[1, 1, 1]])
        assert s.exec(select(Job)).one().api_call_id == call.id


def test_same_day_scan_spends_nothing(env):
    feed, _ = env
    feed.jobs = [nj("jsearch", "1", "Backend Engineer Intern", BACKEND_JD)]
    run_scan()
    second = run_scan(make_due=False)  # nothing is due again until tomorrow
    assert len(feed.client.calls) == 1 and second.totals.get("requests", 0) == 0


def test_smart_second_page_only_when_page_one_pays_off(env):
    feed, _ = env
    write_tuning({("scout", "search", "sources", "max_per_scan"): 2, ("scout", "search", "sources", "daily_limit_on"): False})
    feed.jobs = [nj("jsearch", f"p{i}", f"Backend Engineer {i}", BACKEND_JD, company=f"Co {i}") for i in range(10)]
    run_scan()
    assert [c["page"] for c in feed.client.calls] == [1, 2]  # 10 results, 10 new -> page 2
    feed.client.calls.clear()
    run_scan()  # same 10 again: nothing new -> no page 2
    assert [c["page"] for c in feed.client.calls] == [1]


def test_max_per_scan_caps_spending(env):
    feed, _ = env
    write_tuning({("scout", "search", "sources", "max_per_scan"): 2})
    with new_session() as s:
        s.add(AppSetting(key="criteria", value={"roles": ["Backend Engineer", "AI Engineer", "ML Engineer"]}))
        s.commit()
    feed.jobs = [nj("jsearch", "1", "Backend Engineer Intern", BACKEND_JD)]
    run_scan()
    assert len(feed.client.calls) == 2
    with new_session() as s:
        plan, _ = search_plan.build(s)
    assert any("wait for budget" in n for n in plan.notes) or len(plan.calls) == 1


def test_highlights_become_the_requirements(env):
    feed, _ = env
    job = JSEARCH.normalize({**REC, "job_title": "Backend Engineer", "job_description": "Short text without bullets."})
    feed.jobs = [job]
    run_scan()
    with new_session() as s:
        texts = [r.text for r in s.exec(select(JobRequirement)).all()]
    assert "2+ years of Python" in texts and "Experience with RAG and vector databases" in texts
    assert "Health insurance" not in texts


def test_plan_is_a_dry_run(env):
    with new_session() as s:
        plan, sends = search_plan.build(s)
        assert plan.configured and [c.query for c in plan.calls] == ["Backend Engineer in India"]
        assert s.exec(select(ApiCall)).all() == []  # nothing sent, nothing counted
    assert sends and compass is not None


# ── provider usage (OpenWeb Ninja /usage) ──────────────────────────────────────


def test_usage_fields_are_picked_by_name():
    from backend.services import jsearch_usage

    nested = {"status": "OK", "data": {"plan": "Free", "billing_period": {"start": "2026-11-01", "end": "2026-12-01"},
                                       "requests": {"limit": 200, "used": 37}}}
    p = jsearch_usage.parse(nested)
    assert (p["plan"], p["limit"], p["used"], p["remaining"]) == ("Free", 200, 37, 163)
    assert p["period_start"] == "2026-11-01" and p["period_end"] == "2026-12-01"
    assert jsearch_usage.parse({"quota_remaining": "12"})["remaining"] == 12
    assert jsearch_usage.parse({"nothing": "useful"})["remaining"] is None


@pytest.fixture
def usage_reset():
    from backend.db import set_meta
    from backend.services import jsearch_usage

    def clear():
        with new_session() as s:
            set_meta(s, jsearch_usage.KEY, "")
            s.commit()

    clear()
    yield
    clear()


def test_usage_refresh_calls_usage_endpoint_once_a_minute(monkeypatch, usage_reset, clean_calls):
    from backend.services import jsearch_usage
    from backend.services.sources import base

    monkeypatch.setattr(get_settings(), "jsearch_api_key", "k")
    seen: list[httpx.Request] = []
    real = base.SourceHttp.__init__

    def init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(200, json={"plan": "Free", "remaining": 150}))[1])
        real(self, *a, **kw)

    monkeypatch.setattr(base.SourceHttp, "__init__", init)
    out = jsearch_usage.refresh(force=True)
    assert out.remaining == 150 and out.plan == "Free" and out.error is None
    assert seen[0].url.path == "/usage" and seen[0].url.params["api_id"] == "jsearch" and seen[0].headers["x-api-key"] == "k"
    jsearch_usage.refresh(force=True)  # within a minute: served from the stored answer
    assert len(seen) == 1
    # The budget never plans past what the provider says is left (minus our calls since).
    with new_session() as s:
        assert jsearch_usage.remaining_now(s) == 150
    api_budget.reserve_call(cfg(), purpose="calibration", params={})
    with new_session() as s:
        assert jsearch_usage.remaining_now(s) == 149
        assert api_budget.quota(s, cfg(monthly_limit=1000, reserve=0)).today_allowance == 149


def test_usage_needs_openwebninja_provider(usage_reset, monkeypatch):
    from backend.services import jsearch_usage

    monkeypatch.setattr(get_settings(), "jsearch_api_key", "k")
    write_tuning({("scout", "search", "sources", "provider"): "rapidapi"})
    try:
        assert "OpenWeb Ninja" in (jsearch_usage.refresh(force=True).error or "")
    finally:
        write_tuning({("scout", "search", "sources", "provider"): "openwebninja"})


def test_analytics_endpoint(env):
    from fastapi.testclient import TestClient

    from backend.main import app

    feed, _ = env
    feed.jobs = [nj("jsearch", "1", "Backend Engineer Intern", BACKEND_JD)]
    run_scan()
    with TestClient(app) as c:
        out = c.get("/system/jsearch?days=7").json()
    assert len(out["per_day"]) == 7 and out["per_day"][-1]["requests"] == 1
    assert out["totals"]["requests"] == 1 and out["totals"]["relevant_jobs"] == 1
    assert out["per_request"]["relevant_jobs"] == 1.0 and out["queries"][0]["query"] == "Backend Engineer in India"
    assert out["recent"][0]["query"] == "Backend Engineer in India" and out["provider"] == "openwebninja"



def test_no_subscription_is_explained(monkeypatch):
    monkeypatch.setattr(get_settings(), "jsearch_api_key", "k")
    body = {"status": "ERROR", "error": {"message": "No active subscription for this API", "code": 404}}
    with SourceHttp(transport=httpx.MockTransport(lambda r: httpx.Response(404, json=body))) as http:
        with pytest.raises(JSearchError, match="no active subscription for JSearch"):
            JSEARCH.search(http, {"query": "x"})


OWN_USAGE = {"status": "OK", "data": {"api_id": "jsearch", "plan": {"id": "x", "key": "basic", "nickname": "Basic", "is_free": True},
             "status": "active", "term": "month", "period_start": "2026-11-17T19:59:00.000Z", "period_end": "2026-12-17T19:59:00.000Z",
             "quotas": [{"name": "Requests", "limit": 200, "used": 3, "remaining": 197, "reset_at": "2026-12-17T19:59:00.000Z"}]}}


def test_openwebninja_usage_shape_and_billing_window(usage_reset, monkeypatch):
    """The real /usage answer (2026-11-18): plan name, quota, and the budget follows its period."""
    import json as _json

    from backend.db import set_meta
    from backend.services import jsearch_usage

    p = jsearch_usage.parse(OWN_USAGE)
    assert (p["plan"], p["limit"], p["used"], p["remaining"]) == ("Basic", 200, 3, 197)
    with new_session() as s:
        set_meta(s, jsearch_usage.KEY, _json.dumps({"fetched_at": "2026-11-20T10:00:00+00:00", "checked_at": "2026-11-20T10:00:00+00:00",
                                                    "data": OWN_USAGE, "error": None}))
        s.commit()
    monkeypatch.setattr(jsearch_usage, "utcnow", lambda: datetime(2026, 11, 20, 12, tzinfo=UTC))
    start, end = api_budget.billing_window(datetime(2026, 11, 20, 12, tzinfo=UTC))
    assert (start.day, end.day, end.month) == (17, 17, 12)
    with new_session() as s:
        q = api_budget.quota(s, cfg(), datetime(2026, 11, 20, 12, tzinfo=UTC))
    assert q.resets_on == "2026-12-17"


def test_daily_cap_limits_scans(clean_calls):
    c = cfg(monthly_limit=200, reserve=10, daily_limit=2, max_per_scan=8)
    for _ in range(2):
        api_budget.reserve_call(c, purpose="scan", params={}, now=NOW)
    with pytest.raises(api_budget.BudgetExhausted, match="Requests per day"):
        api_budget.reserve_call(c, purpose="scan", params={}, now=NOW)
    api_budget.reserve_call(c, purpose="calibration", params={}, now=NOW)  # tests use the reserve
    with new_session() as s:
        q = api_budget.quota(s, c, NOW + timedelta(days=1))
    assert q.today_allowance == 2 and q.daily_limit == 2


def test_one_request_per_scan_by_default(env):
    feed, _ = env
    with new_session() as s:
        s.add(AppSetting(key="criteria", value={"roles": ["Backend Engineer", "AI Engineer"]}))
        s.commit()
    write_tuning({("scout", "search", "sources", "max_per_scan"): 1})
    feed.jobs = [nj("jsearch", f"p{i}", f"Backend Engineer {i}", BACKEND_JD, company=f"Co {i}") for i in range(10)]
    run_scan()
    assert len(feed.client.calls) == 1  # one request, even though page 1 earned a page 2


def test_test_request_spends_one_from_reserve_and_keeps_the_jobs(env, monkeypatch):
    from backend.services import jsearch_calibration

    class FakeRaw:
        def configured(self):
            return True

        def fetch_raw(self, http, params, provider="openwebninja"):
            self.params = params
            return {"status": "OK", "data": [{**REC, "job_id": "t1", "job_title": "Backend Engineer"}]}

        def normalize(self, rec):
            return JSEARCH.normalize(rec)

    fake = FakeRaw()
    monkeypatch.setattr(jsearch_calibration, "JSEARCH", fake)
    out = jsearch_calibration.test_request()
    assert out["ok"] and out["results"] == 1 and out["new_jobs"] == 1 and out["query"] == "Backend Engineer in India"
    assert out["countries"] == {"IN": 1} and out["has_highlights"] == 1
    with new_session() as s:
        call = s.exec(select(ApiCall)).one()
        assert call.purpose == "calibration" and call.status == "ok"
        job = s.exec(select(Job)).one()
        assert job.api_call_id == call.id and job.pipeline_status in ("mapped", "not_relevant", "excluded")


def _set_roles(roles, **extra):
    with new_session() as s:
        row = s.get(AppSetting, "criteria") or AppSetting(key="criteria")
        row.value = {"roles": roles, **extra}
        s.add(row)
        s.commit()


def test_manual_scan_only_chosen_roles_one_request_each(env):
    from fastapi.testclient import TestClient

    from backend.main import app

    feed, _ = env
    _set_roles(["Backend Engineer", "AI Engineer", "ML Engineer"])
    feed.jobs = [nj("jsearch", "m1", "Backend Engineer Intern", BACKEND_JD)]
    with TestClient(app) as c:
        plan = c.post("/scout/search/plan", json={"roles": ["AI Engineer", "Backend Engineer"], "combine": False}).json()
        assert [x["query"] for x in plan["calls"]] == ["Backend Engineer in India", "AI Engineer in India"]
        assert plan["kind"] == "manual" and plan["mode"] == "separate" and plan["fits_budget"]
    from backend.job_schemas import ScanSelection
    from backend.services import job_search

    assert job_search._scan_lock.acquire(blocking=False)
    job_search._current["scan_id"] = "t-manual"
    with new_session() as s:
        from backend.db import Scan

        s.add(Scan(id="t-manual", trigger="manual", totals={}))
        s.commit()
    job_search._run("t-manual", "manual", ScanSelection(roles=["AI Engineer", "Backend Engineer"]))
    assert [x["query"] for x in feed.client.calls] == ["Backend Engineer in India", "AI Engineer in India"]


def test_manual_scan_combined_is_one_or_request_with_its_own_stats(env):
    from backend.job_schemas import ScanSelection
    from backend.services import job_search

    feed, _ = env
    _set_roles(["Backend Engineer", "AI Engineer", "ML Engineer"])
    feed.jobs = [nj("jsearch", "c1", "Backend Engineer Intern", BACKEND_JD)]
    assert job_search._scan_lock.acquire(blocking=False)
    job_search._current["scan_id"] = "t-or"
    with new_session() as s:
        from backend.db import Scan

        s.add(Scan(id="t-or", trigger="manual", totals={}))
        s.commit()
    job_search._run("t-or", "manual", ScanSelection(roles=["Backend Engineer", "AI Engineer", "ML Engineer"], combine=True))
    assert [x["query"] for x in feed.client.calls] == ["Backend Engineer OR AI Engineer OR ML Engineer in India"]
    with new_session() as s:
        combo = s.exec(select(SearchQuery).where(SearchQuery.key.startswith("or:"))).one()
        assert combo.roles == ["Backend Engineer", "AI Engineer", "ML Engineer"] and combo.runs == 1 and combo.new_jobs == 1


def test_scan_picker_changes_place_and_filters_for_this_scan_only(env):
    from fastapi.testclient import TestClient

    from backend.main import app

    _set_roles(["Backend Engineer", "AI Engineer"], locations=["India"])
    with TestClient(app) as c:
        body = {"roles": ["AI Engineer"], "combine": False, "locations": ["Bengaluru"],
                "job_types": ["internship"], "workplace": ["remote"], "experience_years": None}
        plan = c.post("/scout/search/plan", json=body).json()
        assert [x["query"] for x in plan["calls"]] == ["AI Engineer internship in Bengaluru"]  # only internships
        p = plan["calls"][0]["params"]
        assert p["country"] == "in" and p["employment_types"] == "INTERN" and p["work_from_home"] == "true"
        assert "job_requirements" not in p
        assert not any("saved Locations" in n for n in plan["notes"])  # Bengaluru is in India
        berlin = c.post("/scout/search/plan", json={**body, "locations": ["Germany"]}).json()
        assert [x["query"] for x in berlin["calls"]] == ["AI Engineer internship in Germany"] and berlin["calls"][0]["params"]["country"] == "de"
        assert not any("saved Locations" in n for n in berlin["notes"])  # location never excludes
        combined = c.post("/scout/search/plan", json={**body, "roles": ["AI Engineer", "Backend Engineer"], "combine": True}).json()
        assert [x["query"] for x in combined["calls"]] == ["Backend Engineer OR AI Engineer internship in Bengaluru"]
        assert "Can't place" in " ".join(c.post("/scout/search/plan", json={**body, "locations": ["Xyzzyville"]}).json()["notes"])
        # Without changes it's still your Search criteria, and the saved criteria are untouched.
        plain = c.post("/scout/search/plan", json={"roles": ["AI Engineer"], "combine": False}).json()
        assert [x["query"] for x in plain["calls"]] == ["AI Engineer in India"]
        assert c.get("/scout/search/settings").json()["criteria"]["locations"] == ["India"]


def test_experience_years_maps_to_jsearch_and_old_choices_convert():
    from backend.job_schemas import SearchCriteria
    from backend.services.sources.jsearch import employment_types, job_requirements

    assert [job_requirements(y) for y in (None, 0, 1, 2, 3, 7)] == [
        None, "no_experience", "under_3_years_experience,no_experience",
        "under_3_years_experience,no_experience", None, None]
    assert employment_types([]) is None and employment_types(["freelance", "contract", "internship"]) == "CONTRACTOR,INTERN"
    assert SearchCriteria(experience="under_3_years").experience_years == 2
    assert SearchCriteria(experience="no_experience").experience_years == 0
    assert SearchCriteria(experience="any").experience_years is None
    assert SearchCriteria(experience_years="").experience_years is None
    assert SearchCriteria(experience_years=-1).experience_years is None


def test_old_saved_experience_choice_wins_over_new_toml_default(env):
    from backend.db import AppSetting
    from backend.services import search_settings

    with new_session() as s:
        row = s.get(AppSetting, "criteria")
        value = {**(row.value if row else {}), "experience": "any"}
        value.pop("experience_years", None)
        if row is None:
            row = AppSetting(key="criteria", value=value)
        row.value = value
        s.add(row)
        s.commit()
        assert search_settings.get(s, "criteria").experience_years is None


def test_search_criteria_only_shape_the_scan(env):
    from backend.db import Job
    from backend.job_schemas import SearchCriteria
    from backend.services.job_search import criteria_reason

    job = Job(title="Engineer", min_years_experience=3, category="full_time", workplace_type="onsite")
    c = SearchCriteria(experience_years=2, job_types=["internship"], workplace=["remote"], exclude_title_words=["Engineer"])
    assert criteria_reason(job, c) is None


def test_manual_choice_over_budget_is_refused(env):
    from fastapi.testclient import TestClient

    from backend.main import app

    _set_roles(["Backend Engineer", "AI Engineer", "ML Engineer"])
    write_tuning({("scout", "search", "sources", "daily_limit"): 2, ("scout", "search", "sources", "daily_limit_on"): True})
    with TestClient(app) as c:
        separate = {"roles": ["Backend Engineer", "AI Engineer", "ML Engineer"], "combine": False}
        assert c.post("/scout/search/plan", json=separate).json()["fits_budget"] is False
        r = c.post("/scout/search/scan", json=separate)
        assert r.status_code == 400 and "only 2" in r.json()["detail"]
        combined = {**separate, "combine": True}  # the same roles in one request fit
        assert c.post("/scout/search/plan", json=combined).json()["fits_budget"] is True


def test_automatic_scan_modes(env):
    feed, _ = env
    feed.jobs = [nj("jsearch", "a1", "Backend Engineer Intern", BACKEND_JD)]
    write_tuning({("scout", "search", "sources", "max_per_scan"): 5})
    _set_roles(["Backend Engineer", "AI Engineer", "ML Engineer"], auto_roles=["AI Engineer", "ML Engineer"], auto_mode="combined")
    run_scan()
    assert [x["query"] for x in feed.client.calls] == ["AI Engineer OR ML Engineer in India"]
    feed.client.calls.clear()
    _set_roles(["Backend Engineer", "AI Engineer", "ML Engineer"], auto_roles=["AI Engineer", "ML Engineer"], auto_mode="each")
    run_scan()
    assert [x["query"] for x in feed.client.calls] == ["AI Engineer in India", "ML Engineer in India"]


def test_each_request_remembers_what_it_returned(env):
    from fastapi.testclient import TestClient

    from backend.main import app

    feed, _ = env
    feed.jobs = [nj("jsearch", "r1", "Backend Engineer Intern", BACKEND_JD),
                 nj("jsearch", "r2", "Night Nurse", "<p>Care for patients in the ward.</p>", company="City Hospital", location="London, UK")]
    run_scan()
    run_scan()  # same jobs again: "unchanged" the second time
    with TestClient(app) as c:
        calls = c.get("/scout/search/calls").json()
        assert len(calls) == 2
        first = c.get(f"/scout/search/calls/{calls[-1]['id']}/jobs").json()
        second = c.get(f"/scout/search/calls/{calls[0]['id']}/jobs").json()
    assert [(x["position"], x["title"], x["outcome"]) for x in first] == [(1, "Backend Engineer Intern", "new"), (2, "Night Nurse", "new")]
    assert [x["outcome"] for x in second] == ["unchanged", "unchanged"]
    assert first[0]["pipeline_status"] == "mapped" and first[1]["pipeline_status"] == "not_relevant"
    assert first[0]["job_id"] == second[0]["job_id"]


def test_manual_scan_never_adds_a_page_2(env):
    """Bug 2026-11-18: Scan now with 1 role said "1 request" but sent 2 (smart page 2 used the
    day's allowance). A manual scan sends exactly the planned requests."""
    from backend.db import Scan
    from backend.job_schemas import ScanSelection
    from backend.services import job_search

    feed, _ = env
    write_tuning({("scout", "search", "sources", "max_per_scan"): 1, ("scout", "search", "sources", "daily_limit"): 6})
    _set_roles(["Backend Engineer", "AI Engineer"])
    # A full, all-new page 1: exactly what triggers the smart page-2 rule.
    feed.jobs = [nj("jsearch", f"f{i}", f"Backend Engineer {i}", BACKEND_JD, company=f"Co {i}") for i in range(10)]
    assert job_search._scan_lock.acquire(blocking=False)
    job_search._current["scan_id"] = "t-one"
    with new_session() as s:
        s.add(Scan(id="t-one", trigger="manual", totals={}))
        s.commit()
    job_search._run("t-one", "manual", ScanSelection(roles=["AI Engineer"]))
    assert [(c["query"], c["page"]) for c in feed.client.calls] == [("AI Engineer in India", 1)]
