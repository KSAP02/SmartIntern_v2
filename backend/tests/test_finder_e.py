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

from backend.db import CompanyLead, Employer, FinderRun, new_session, set_meta, utcnow
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
    def reset(s):
        s.exec(delete(CompanyLead))
        s.exec(delete(FinderRun))
        set_meta(s, crawl_index.STATE_KEY, "{}")
        set_meta(s, company_finder.STATE_KEY, "{}")

    with new_session() as s:
        reset(s)
        s.commit()
    yield boards
    with new_session() as s:
        reset(s)
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


def _row(url: str) -> str:
    from urllib.parse import urlparse

    u = urlparse(url)
    host = ",".join(reversed(u.netloc.split(".")))
    return f"{host}){u.path} 20261010000000 " + json.dumps({"url": url, "status": "200"})


def fake_crawl(blocks: list[list[str]], filler: int = 0):
    """A Common Crawl index: collinfo.json, cluster.idx and one cdx file, served by byte range."""
    import gzip

    data, lines = b"", [f"aa,filler{i:04d})/ 2026\tcdx-00000.gz\t0\t1\t{i}" for i in range(filler)]
    for i, rows in enumerate(blocks):
        gz = gzip.compress("\n".join(rows).encode())
        lines.append(f"{rows[0].split(' ', 1)[0]} 2026\tcdx-00000.gz\t{len(data)}\t{len(gz)}\t{filler + i}")
        data += gz
    files = {"cluster.idx": ("\n".join(lines) + "\n").encode(), "cdx-00000.gz": data}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("collinfo.json"):
            return httpx.Response(200, json=[{"id": "CC-MAIN-2026-43"}])
        body = files[path.rsplit("/", 1)[1]]
        seen.append(path.rsplit("/", 1)[1])
        start, end = (int(x) for x in request.headers["Range"].removeprefix("bytes=").split("-"))
        return httpx.Response(206, content=body[start:end + 1], headers={"Content-Range": f"bytes {start}-{end}/{len(body)}"})

    return handler, seen


def test_board_ids_become_readable_names():
    assert crawl_index.board_name("content-whale-in.in") == "Content Whale"
    assert crawl_index.board_name("incubyte-incubyte-in.in") == "Incubyte"
    assert crawl_index.board_name("ashnik.in") == "Ashnik"
    assert crawl_index.board_name("newco") == "Newco"
    assert crawl_index.board_name("acruxsearch.com") == "Acruxsearch"


def test_crawl_index_files_become_leads(finder, monkeypatch):
    monkeypatch.setattr(crawl_index, "SPAN", 512)  # small reads, so the binary search runs too
    monkeypatch.setattr(crawl_index, "PROBE", 256)
    with new_session() as s:
        s.add(Employer(name="Known", kind="lever", board="known", enabled=True))
        s.commit()
    handler, seen = fake_crawl([
        # The block before the first lever line ends with lever rows: they count.
        [_row("https://example.co/"), _row("https://jobs.lever.co/oldco/1")],
        [_row("https://jobs.lever.co/newco/abc"), _row("https://jobs.lever.co/newco/def"),
         _row("https://jobs.lever.co/known/x"), _row("https://jobs.lever.co/")],
        [_row("https://zzz.com/")],
    ], filler=200)
    with SourceHttp(max_retries=0, transport=httpx.MockTransport(handler)) as http:
        added = crawl_index.harvest(FinderSettings(crawl_delay_seconds=0, crawl_pages_per_run=50), http)
    assert added == 2  # oldco and newco; "known" is already a company
    with new_session() as s:
        leads = {x.board: x for x in s.exec(select(CompanyLead)).all()}
        assert set(leads) == {"oldco", "newco"}
        assert (leads["newco"].origin, leads["newco"].kind, leads["newco"].name) == ("crawl", "lever", "Newco")
        prog = crawl_index.progress(s)
        assert prog.collections_done == ["CC-MAIN-2026-43"] and prog.leads == 2 and prog.last_error is None
        assert next(h for h in prog.hosts if h["host"] == "jobs.lever.co")["pages"] == 2
    seen.clear()
    with SourceHttp(max_retries=0, transport=httpx.MockTransport(handler)) as http:
        assert crawl_index.harvest(FinderSettings(crawl_delay_seconds=0), http) == 0  # read: nothing re-read
    assert seen == []


def test_a_busy_index_stops_the_run_and_carries_on_next_time(finder):
    handler, _ = fake_crawl([[_row("https://jobs.lever.co/newco/abc")]])
    busy = {"on": True}

    def flaky(request: httpx.Request) -> httpx.Response:
        if busy["on"] and request.url.path.endswith(".gz"):
            return httpx.Response(504)
        return handler(request)

    with SourceHttp(max_retries=0, transport=httpx.MockTransport(flaky)) as http:
        assert crawl_index.harvest(FinderSettings(crawl_delay_seconds=0), http) == 0
    with new_session() as s:
        assert "504" in crawl_index.progress(s).last_error
    busy["on"] = False
    with SourceHttp(max_retries=0, transport=httpx.MockTransport(flaky)) as http:
        assert crawl_index.harvest(FinderSettings(crawl_delay_seconds=0), http) == 1


# ── the YC list, the order, the run ────────────────────────────────────────────


def test_yc_companies_in_india_become_leads(finder):
    data = [
        {"name": "Acme AI", "website": "https://www.acme.ai", "status": "Active", "regions": ["India", "Asia"]},
        {"name": "Bharat Labs", "website": "https://bharat.in", "status": "Active", "all_locations": "Bengaluru, KA, India"},
        {"name": "Gone Co", "website": "https://gone.in", "status": "Inactive", "regions": ["India"]},
        {"name": "Elsewhere", "website": "https://else.com", "status": "Active", "regions": ["United States"]},
        {"name": "Razorpay", "website": "https://razorpay.com", "status": "Active", "regions": ["India"]},
    ]
    assert [r["name"] for r in company_finder.yc_rows(data)] == ["Acme AI", "Bharat Labs", "Razorpay"]
    with new_session() as s:
        set_meta(s, company_finder.YC_KEY, "")
        s.add(CompanyLead(name="Razorpay", domain="razorpay.com", origin="seed"))
        s.commit()
        with fake_http({"yc-oss.github.io/api/companies/all.json": data}) as http:
            assert company_finder.sync_yc(http, s) == 2  # Razorpay is already a lead
            assert company_finder.sync_yc(http, s) == 0  # read at most weekly
        acme = s.exec(select(CompanyLead).where(CompanyLead.name == "Acme AI")).one()
        assert (acme.origin, acme.domain, acme.category) == ("yc", "acme.ai", "startup")
        set_meta(s, company_finder.YC_KEY, "")
        s.commit()


def test_startups_and_indian_boards_are_checked_first(finder):
    with new_session() as s:
        for name, origin, category, kind in [("Global", "seed", "global", None), ("Crawl GH", "crawl", None, "greenhouse"),
                                             ("Unicorn", "seed", "unicorn", None), ("Startup", "seed", "startup", None),
                                             ("Keka Co", "crawl", None, "keka"), ("YC Co", "yc", "startup", None)]:
            s.add(CompanyLead(name=name, origin=origin, category=category, kind=kind, board=name.lower() if kind else None))
        s.commit()
        assert [x.name for x in company_finder.due_leads(s, 10)] == ["Startup", "Keka Co", "YC Co", "Unicorn", "Crawl GH", "Global"]
        assert [x.name for x in company_finder.due_leads(s, 10, board_known=True)] == ["Keka Co", "Crawl GH"]
        assert [x.name for x in company_finder.due_leads(s, 2, board_known=False)] == ["Startup", "YC Co"]


def test_a_run_checks_each_board_system_in_its_own_worker(finder, monkeypatch):
    import threading

    monkeypatch.setattr(company_finder, "settings", lambda: FinderSettings(crawl=False, yc_list=False, delay_seconds=0,
                                                                          leads_per_run=5, board_checks_per_run=10))
    seen: dict[str, set[str]] = {}

    def fake_check(s, http, lead, phrases, cfg):
        seen.setdefault(lead.kind or "search", set()).add(threading.current_thread().name)
        lead.status = "no_india_jobs" if lead.kind else "no_board"
        lead.next_check_at = utcnow() + timedelta(days=30)
        s.add(lead)
        return lead.status

    monkeypatch.setattr(company_finder, "check_lead", fake_check)
    monkeypatch.setattr(company_finder, "sync_seed", lambda s: 0)
    with new_session() as s:
        for i in range(3):
            s.add(CompanyLead(name=f"L{i}", origin="crawl", kind="lever", board=f"l{i}"))
            s.add(CompanyLead(name=f"G{i}", origin="crawl", kind="greenhouse", board=f"g{i}"))
        s.add(CompanyLead(name="Seed", origin="seed", category="startup"))
        s.commit()
    counts = company_finder.run()
    assert counts["checked"] == 7 and counts["no_india_jobs"] == 6 and counts["no_board"] == 1
    assert set(seen) == {"lever", "greenhouse", "search"}
    assert all(len(t) == 1 for t in seen.values()) and len(set().union(*seen.values())) == 3  # one worker each
    # The run is recorded for the analytics, with its breakdowns.
    with new_session() as s:
        [r] = s.exec(select(FinderRun)).all()
        assert (r.status, r.trigger, r.planned) == ("done", "manual", 7)
        assert r.counts == {"checked": 7, "no_india_jobs": 6, "no_board": 1}
        assert r.by_kind["lever"]["checked"] == 3 and r.by_kind["none"]["checked"] == 1
        assert r.by_origin == {"crawl": {"checked": 6, "kept": 0, "india_jobs": 0, "matching_jobs": 0},
                               "seed": {"checked": 1, "kept": 0, "india_jobs": 0, "matching_jobs": 0}}
        assert all(x.run_id == r.id for x in s.exec(select(CompanyLead)).all())
        d = company_finder.dashboard(s)
        assert [x.id for x in d.runs] == [r.id] and d.runs[0].duration_seconds is not None
        assert {x.key: x.no_india_jobs for x in d.by_kind}["greenhouse"] == 3
        assert {x.key: x.total for x in d.by_origin} == {"crawl": 6, "seed": 1}
    # Nothing left to do: an idle run leaves no row.
    company_finder.run("auto")
    with new_session() as s:
        assert len(s.exec(select(FinderRun)).all()) == 1


def test_a_server_with_company_finder_false_never_runs_it(finder, monkeypatch):
    """The deployed backend (COMPANY_FINDER=false) only reads the companies found locally."""
    from backend.config import get_settings

    monkeypatch.setenv("COMPANY_FINDER", "false")
    get_settings.cache_clear()
    try:
        cfg = company_finder.settings()
        assert cfg.enabled is False and cfg.auto is False
        assert company_finder.start("manual") is False
        with new_session() as s:
            s.add(CompanyLead(name="Waiting", origin="seed"))
            s.commit()
        assert company_finder.auto_tick() is False
        with new_session() as s:
            st = company_finder.status(s)
        assert st.enabled is False and st.server_allows is False
    finally:
        monkeypatch.delenv("COMPANY_FINDER")
        get_settings.cache_clear()
    assert company_finder.server_allows() is True


def test_runs_follow_each_other_by_themselves(finder, monkeypatch):
    from backend.services import job_search

    cfg = FinderSettings(enabled=True, auto=True, crawl=False, pause_between_runs_seconds=30, idle_check_hours=6,
                         error_backoff_minutes=15)
    monkeypatch.setattr(company_finder, "settings", lambda: cfg)
    started = []
    monkeypatch.setattr(company_finder, "start", lambda trigger: started.append(trigger) or True)
    monkeypatch.setattr(job_search, "running_scan_id", lambda: None)

    def ended(seconds_ago: float, error: str | None = None):
        company_finder._save_state(finished_at=(utcnow() - timedelta(seconds=seconds_ago)).isoformat(), error=error)

    with new_session() as s:
        s.add(CompanyLead(name="Waiting", origin="seed"))
        s.commit()
    ended(10)
    assert company_finder.auto_tick() is False  # the pause between runs
    ended(31)
    assert company_finder.auto_tick() is True and started == ["auto"]
    ended(60, error="boom")
    assert company_finder.auto_tick() is False  # after a failure: wait
    ended(16 * 60, error="boom")
    assert company_finder.auto_tick() is True
    monkeypatch.setattr(job_search, "running_scan_id", lambda: "scan-1")
    assert company_finder.auto_tick() is False  # never during a scan
    monkeypatch.setattr(job_search, "running_scan_id", lambda: None)
    with new_session() as s:  # nothing waiting: only the 6-hourly look
        s.exec(delete(CompanyLead))
        s.commit()
    ended(3600)
    assert company_finder.auto_tick() is False
    ended(7 * 3600)
    assert company_finder.auto_tick() is True
    monkeypatch.setattr(company_finder, "settings", lambda: cfg.model_copy(update={"auto": False}))
    assert company_finder.auto_tick() is False


def test_a_restart_marks_the_run_interrupted_and_keeps_its_counts(finder, monkeypatch):
    monkeypatch.setattr(company_finder, "sync_seed", lambda s: 0)
    with new_session() as s:
        s.add(FinderRun(trigger="auto", counts={"checked": 20, "kept": 3}, message="Checked 20 of 500"))
        s.commit()
    company_finder._save_state(running=True)
    company_finder.recover()
    with new_session() as s:
        r = s.exec(select(FinderRun)).one()
        assert r.status == "interrupted" and r.counts == {"checked": 20, "kept": 3} and r.finished_at is not None
        assert company_finder._state(s)["running"] is False


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
