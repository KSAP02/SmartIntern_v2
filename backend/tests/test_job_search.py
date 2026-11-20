"""Job Search pipeline end to end, offline: fake JSearch client, bag-of-words embeddings, real Milvus Lite."""
import hashlib
import math
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import delete, select

from backend import vectors
from backend.config import get_settings, get_tuning, write_tuning
from backend.db import (
    ApiCall, ApiCallJob, AppSetting, FetchRun, Job, JobLedger, JobRequirement, JobSource, MemoryCard, RoleContext, Scan,
    SearchQuery, get_profile_row, init_db, new_session, utcnow,
)
from backend.job_schemas import ApplyPreset, NormalizedJob
from backend.services import compass, job_search, job_views, memory, role_contexts, search_plan
from backend.tests.conftest import fake_profile

DIMS = get_tuning().embedding.dimensions


def config_text() -> str:
    return get_settings().config_file.read_text(encoding="utf-8")


def restore_config(text: str) -> None:
    get_settings().config_file.write_text(text, encoding="utf-8")
    get_tuning.cache_clear()


def bow_embed(texts):
    """Deterministic 'embedding': hashed bag of words, unit length. Shared words -> high cosine."""
    out = []
    for t in texts:
        v = [0.0] * DIMS
        for w in re.findall(r"[a-z][a-z+#.]{1,}", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIMS] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


BACKEND_JD = """<p><strong>Requirements</strong></p><ul>
<li>Strong Python and FastAPI experience building web services</li>
<li>Experience with PostgreSQL databases and query tuning</li>
<li>2+ years of experience in backend development</li></ul>
<p><strong>Nice to have</strong></p><ul><li>Kubernetes in production</li></ul>"""
NURSE_JD = "<p>Care for patients in the ward. Administer medication, monitor vitals, night shifts in hospital.</p>"


def fake_role_draft(*, task, system, user, schema):
    """Stands in for the model writing a role context: a backend-flavoured posting."""
    assert task == "role_context" and "<candidate>" in user
    return schema(
        summary="Build and run backend web services and APIs.",
        responsibilities=["Design REST APIs in Python and FastAPI", "Tune PostgreSQL databases and queries"],
        requirements=["Python", "FastAPI or Django", "PostgreSQL", "Docker", "Kubernetes (Platform)"],
        nice_to_have=["Kubernetes in production", "AWS"],
        search_titles=["Backend Engineer", "Python Developer (Backend)", "Backend Developer"],
        keywords=["Python", "FastAPI", "REST APIs"],
    )


class Listing:
    """Jobs a test wants the fake JSearch to return (two of these stand in for two publishers)."""

    def __init__(self):
        self.jobs: list[NormalizedJob] = []


class FakeJSearch:
    """Stands in for the JSearch client: every request returns all listings' jobs."""

    name, label, kind, terms_url, env_keys = "jsearch", "JSearch", "feed", None, ()

    def __init__(self, *listings: Listing):
        self.listings = listings
        self.calls: list[dict] = []

    def configured(self):
        return True

    def search(self, http, params, provider="openwebninja"):
        self.calls.append(dict(params))
        jobs = [j for li in self.listings for j in li.jobs]
        return jobs, len(jobs)


def nj(source, sid, title, html, company="Acme Widgets", location="Remote", **kw):
    return NormalizedJob(source=source, source_job_id=sid, company_name=company, title=title, description_html=html,
                         location_text=location, job_url=f"https://jobs.example.com/{source}/{sid}", **kw)


@pytest.fixture
def env(monkeypatch):
    init_db()
    with new_session() as s:
        for model in (JobRequirement, Job, JobLedger, FetchRun, Scan, JobSource, AppSetting, MemoryCard, ApiCall, ApiCallJob, SearchQuery):
            s.exec(delete(model))
        row = get_profile_row(s)
        row.data, row.memory_built_at = fake_profile().model_dump(), None
        s.add(row)
        s.commit()
    original = config_text()
    # JSearch searches by role: one role -> one request per scan. "any" keeps old experience semantics.
    write_tuning({("scout", "search", "criteria", "roles"): ["Backend Engineer"],
                  ("scout", "search", "criteria", "experience_years"): "any"})
    vectors.reset("jobs")
    for mod in (job_search, role_contexts):
        monkeypatch.setattr(mod, "embed", bow_embed)
    monkeypatch.setattr(role_contexts, "chat_structured", fake_role_draft)
    with new_session() as s:
        s.exec(delete(RoleContext))
        s.commit()
    feed, feed2 = Listing(), Listing()
    fake = FakeJSearch(feed, feed2)
    feed.client = fake
    monkeypatch.setattr(job_search, "JSEARCH", fake)
    monkeypatch.setattr(search_plan, "JSEARCH", fake)
    with new_session() as s:
        memory.rebuild(s)
    role_contexts.generate("Backend Engineer")  # fake model: a backend-flavoured posting
    yield feed, feed2
    restore_config(original)


def run_scan(make_due: bool = True):
    """One scan. make_due: pretend a day has passed, so every search is due again."""
    if make_due:
        with new_session() as s:
            for q in s.exec(select(SearchQuery)).all():
                q.last_run_at = None
                s.add(q)
            s.commit()
    assert job_search._scan_lock.acquire(blocking=False)
    scan_id = f"t-{utcnow().timestamp()}"
    job_search._current["scan_id"] = scan_id
    with new_session() as s:
        s.add(Scan(id=scan_id, trigger="manual", totals={}))
        s.commit()
    job_search._run(scan_id, "manual")
    with new_session() as s:
        return s.get(Scan, scan_id)


def test_scan_dedupe_relevance_and_evidence(env):
    feed, feed2 = env
    feed.jobs = [
        nj("fakefeed", "1", "Backend Engineer Intern", BACKEND_JD),
        nj("fakefeed", "2", "Night Nurse", NURSE_JD, company="City Hospital", location="London, UK"),
    ]
    # Same backend job listed by a second source -> no second row.
    feed2.jobs = [nj("fakefeed2", "x9", "Backend Engineer Intern", BACKEND_JD)]

    scan = run_scan()
    assert scan.phase == "done", scan.error
    assert scan.totals["new"] == 2 and scan.totals["duplicate"] == 1

    with new_session() as s:
        jobs = {j.title: j for j in s.exec(select(Job)).all()}
        backend, nurse = jobs["Backend Engineer Intern"], jobs["Night Nurse"]
        assert {x["source"] for x in backend.seen_on} == {"fakefeed", "fakefeed2"}
        assert backend.category == "internship" and backend.field_sources.get("category") == "rules"
        assert backend.pipeline_status == "mapped" and nurse.pipeline_status == "not_relevant"
        assert backend.relevance > nurse.relevance

        reqs = s.exec(select(JobRequirement).where(JobRequirement.job_id == backend.id)).all()
        by_text = {r.text: r for r in reqs}
        py = next(r for t, r in by_text.items() if "FastAPI" in t)
        assert py.importance == "must" and py.status == "met" and py.method == "exact_skill"
        k8s = next(r for t, r in by_text.items() if "Kubernetes" in t)
        assert k8s.importance == "nice" and k8s.status in ("partial", "missing")
        assert backend.coverage["must_total"] >= 3 and backend.coverage["fit"] is not None

        detail = job_views.job_detail(s, backend)
        assert "kubernetes" in [s.lower() for s in detail.missing_skills]
        assert "python" in [s.lower() for s in detail.matched_skills]

    # Second scan: nothing new, nothing duplicated.
    scan2 = run_scan()
    assert scan2.totals.get("new", 0) == 0
    with new_session() as s:
        assert len(s.exec(select(Job)).all()) == 2


def test_criteria_exclude_and_preset_sorting(env):
    feed, _ = env
    feed.jobs = [
        nj("fakefeed", "a", "Backend Engineer Intern", BACKEND_JD, location="Bengaluru, India"),
        nj("fakefeed", "b", "Backend Engineer (Contract)", BACKEND_JD, category="contract", location="Remote",
           salary_min=10, salary_max=20, salary_currency="USD", salary_period="hour"),
    ]
    with new_session() as s:
        s.add(AppSetting(key="criteria", value={"job_types": ["internship", "full_time"]}))
        s.commit()
    run_scan()
    with new_session() as s:
        jobs = {j.source_published_at or j.title: j for j in s.exec(select(Job)).all()}
        contract = next(j for j in jobs.values() if "Contract" in j.title)
        assert contract.pipeline_status == "mapped"  # job types only shape the scan; the Jobs page filters
        intern = next(j for j in jobs.values() if "Intern" in j.title)
        assert intern.pipeline_status == "mapped"

        fits, misses = job_views.preset_check(intern, ApplyPreset(min_fit=101))
        assert not fits and misses and "Fit" in misses[0]
        fits, _ = job_views.preset_check(intern, ApplyPreset(pay=["paid"], include_unknown=True))
        assert fits  # pay unknown, unknowns included
        fits, misses = job_views.preset_check(intern, ApplyPreset(pay=["paid"], include_unknown=False))
        assert not fits and misses == ["Pay not stated"]


def test_only_discarded_jobs_are_deleted_and_never_come_back(env):
    feed, _ = env
    feed.jobs = [nj("fakefeed", "n1", "Night Nurse", NURSE_JD, company="City Hospital", location="London, UK"),
                 nj("fakefeed", "b1", "Backend Engineer Intern", BACKEND_JD)]
    run_scan()
    with new_session() as s:
        jobs = {j.title: j for j in s.exec(select(Job)).all()}
        nurse, backend = jobs["Night Nurse"], jobs["Backend Engineer Intern"]
        assert nurse.pipeline_status == "not_relevant"
        # Old and undecided: kept (only labelled expired), whatever its status.
        for j in (nurse, backend):
            j.status_changed_at = j.first_seen_at = utcnow() - timedelta(days=90)
            s.add(j)
        s.commit()
        out = job_search.prune(s)
        assert out == {"discarded": 0, "expired": 2} and len(s.exec(select(Job)).all()) == 2
        assert all(j.status == "expired" for j in s.exec(select(Job)).all())
        # Discarded: deleted once keep_discarded_days have passed; the ledger remembers it.
        job_search.decide(s, [nurse], "discarded")
        nurse.decided_at = utcnow() - timedelta(days=10)
        s.add(nurse)
        s.commit()
        assert job_search.prune(s)["discarded"] == 1
        assert [j.title for j in s.exec(select(Job)).all()] == ["Backend Engineer Intern"]
        led = s.exec(select(JobLedger).where(JobLedger.source_job_id == "n1")).one()
        assert led.job_id is None and led.outcome == "discarded"
    scan = run_scan()
    assert scan.totals.get("already_seen") == 1 and scan.totals.get("new", 0) == 0


def test_api_overview_jobs_settings(env):
    feed, _ = env
    feed.jobs = [nj("fakefeed", "1", "Backend Engineer Intern", BACKEND_JD)]
    run_scan()
    from backend.main import app

    with TestClient(app) as c:
        ov = c.get("/scout/search/overview").json()
        assert ov["memory_ready"] and ov["funnel"]["seen"] == 1 and ov["last_scan"]["phase"] == "done"
        jobs = c.get("/scout/search/jobs").json()
        assert jobs["counts"]["fits"] == 1
        job_id = jobs["fits"][0]["id"]
        detail = c.get(f"/scout/search/jobs/{job_id}").json()
        assert detail["requirements"] and detail["coverage"]["must_total"] >= 1

        st = c.get("/scout/search/settings").json()
        assert st["preset"]["include_unknown"] is True and st["matching"]["metric"] == "COSINE"
        st["preset"]["min_fit"] = 100
        st2 = c.patch("/scout/search/settings", json={"preset": st["preset"]}).json()
        assert st2["preset"]["min_fit"] == 100
        moved = c.get("/scout/search/jobs").json()
        assert moved["counts"]["fits"] + moved["counts"]["other"] == 1
        assert c.post("/scout/search/settings/reset", json={"section": "preset"}).json()["preset"]["min_fit"] is None

        assert c.patch(f"/scout/search/jobs/{job_id}", json={"decision": "discarded"}).json()["decision"] == "discarded"
        listed = c.get("/scout/search/jobs").json()
        assert listed["counts"]["discarded"] == 1 and listed["fits"] == [] and listed["other"] == []
        assert [j["id"] for j in c.get("/scout/search/jobs?view=discarded").json()["items"]] == [job_id]
        assert c.put("/scout/search/autoscan", json={"enabled": True}).json()["autoscan"] is True
        assert c.get("/scout/search/overview").json()["next_scan_at"] is not None
        assert c.get("/insight/desk").json()["job_search"]["relevant"] == 0  # the only job is discarded
        c.put("/scout/search/autoscan", json={"enabled": False})  # never let the timer hit real sources


def test_pipeline_lock_is_shared_and_reentrant():
    """Scans, remaps and settings effects take the same re-entrant lock (no interleaving)."""
    from backend.services import settings_effects

    assert compass.pipeline_lock is job_search.pipeline_lock is settings_effects.job_search.pipeline_lock
    with job_search.pipeline_lock:
        with job_search.pipeline_lock:  # re-entrant: scan -> map_pending must not deadlock
            pass


def test_roles_gate_uses_titles_and_rescores_on_change(env):
    feed, _ = env
    feed.jobs = [
        nj("fakefeed", "r1", "Backend Engineer Intern", BACKEND_JD),
        # Same backend-heavy JD, unrelated title: the profile gate keeps it, the roles gate must not.
        nj("fakefeed", "r2", "Sales Manager", BACKEND_JD),
    ]
    with new_session() as s:
        s.add(AppSetting(key="criteria", value={"roles": ["Backend Engineer"]}))
        s.commit()
    run_scan()
    with new_session() as s:
        jobs = {j.title: j for j in s.exec(select(Job)).all()}
        eng, sales = jobs["Backend Engineer Intern"], jobs["Sales Manager"]
        assert eng.role_match == "Backend Engineer" and eng.role_score > sales.role_score
        assert eng.pipeline_status == "mapped"
        assert sales.pipeline_status == "not_relevant" and sales.status_reason == "Title doesn't match your roles"

        # Roles cleared -> back to the whole-profile gate: the sales job (same JD) becomes relevant.
        s.get(AppSetting, "criteria").value = {"roles": []}
        s.commit()
        job_search.rescore_relevance(s, roles_changed=True)
        s.refresh(sales)
        assert sales.role_score is None and sales.pipeline_status == "relevant"


def test_add_missing_columns_on_old_table(tmp_path):
    """An existing DB gains new nullable model columns on start-up (create_all alone would not)."""
    from sqlalchemy import create_engine, inspect, text

    from backend.db import _add_missing_columns

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:
        c.execute(text('CREATE TABLE jobs (id INTEGER PRIMARY KEY, title VARCHAR)'))
    _add_missing_columns(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("jobs")}
    assert {"role_score", "role_match", "relevance"} <= cols


def test_admin_settings_round_trip_keeps_comments(env):
    from backend.main import app

    with TestClient(app) as c:
        out = c.get("/system/admin").json()
        assert out["settings"]["sources"]["monthly_limit"] == 200 and out["settings"]["sources"]["enabled"] is True
        assert out["settings"]["models"]["embedding"]["model"]

        st = out["settings"]
        st["matching"]["role_threshold"] = 0.61
        st["sources"]["reserve"] = 500  # a reserve above the monthly limit is refused
        assert c.put("/system/admin", json={"settings": st, "version": out["version"]}).status_code == 400
        st["sources"]["reserve"] = 10
        st["schedule"]["time"] = "25:00"
        assert c.put("/system/admin", json={"settings": st, "version": out["version"]}).status_code == 400
        st["schedule"]["time"] = "06:30"

        saved = c.put("/system/admin", json={"settings": st, "version": out["version"]})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["settings"]["matching"]["role_threshold"] == 0.61 and body["version"] != out["version"]
        text = config_text()
        assert "role_threshold = 0.61" in text and 'time = "06:30"' in text
        assert "# Cosine, job title vs your best-matching role (the title" in text  # comments kept

        # A save based on the old version is refused: the file changed meanwhile.
        assert c.put("/system/admin", json={"settings": st, "version": out["version"]}).status_code == 409

        # A hand edit of the file shows up on the next read (no restart).
        get_settings().config_file.write_text(text.replace("role_threshold = 0.61", "role_threshold = 0.57"),
                                              encoding="utf-8")
        assert c.get("/system/admin").json()["settings"]["matching"]["role_threshold"] == 0.57
        assert search_settings_load_matching().role_threshold == 0.57


def search_settings_load_matching():
    from backend.services import search_settings

    return search_settings.load("matching")


def test_jsearch_switched_off_spends_nothing(env):
    feed, _ = env
    feed.jobs = [nj("fakefeed", "1", "Backend Engineer Intern", BACKEND_JD)]
    write_tuning({("scout", "search", "sources", "enabled"): False})
    scan = run_scan()
    assert feed.client.calls == [] and scan.phase == "done"
    assert "switched off" in (scan_runs(scan.id)[0].error or "")


def scan_runs(scan_id):
    with new_session() as s:
        return s.exec(select(FetchRun).where(FetchRun.scan_id == scan_id)).all()


def test_broken_config_keeps_last_good_values():
    from backend.config import tuning_error

    good = config_text()
    try:
        before = get_tuning().embedding.model
        get_settings().config_file.write_text(good + "\n[broken\n", encoding="utf-8")
        assert get_tuning().embedding.model == before
        assert tuning_error()
    finally:
        restore_config(good)
    assert tuning_error() is None


def test_select_some_and_discard_the_rest(env):
    from backend.main import app

    feed, _ = env
    feed.jobs = [nj("fakefeed", f"s{i}", f"Backend Engineer {i}", BACKEND_JD, company=f"Co {i}") for i in range(3)]
    run_scan()
    with TestClient(app) as c:
        listed = c.get("/scout/search/jobs").json()
        ids = [j["id"] for j in listed["fits"] + listed["other"]]
        assert len(ids) == 3
        keep, rest = ids[:1], ids[1:]
        assert c.post("/scout/search/jobs/decide", json={"ids": keep, "decision": "selected"}).json()["updated"] == 1
        assert c.post("/scout/search/jobs/decide", json={"ids": rest, "decision": "discarded"}).json()["updated"] == 2
        after = c.get("/scout/search/jobs").json()
        assert after["fits"] == [] and after["other"] == []
        assert after["counts"]["selected"] == 1 and after["counts"]["discarded"] == 2
        assert [j["id"] for j in c.get("/scout/search/jobs?view=selected").json()["items"]] == keep
        assert c.get("/insight/desk").json()["job_search"]["selected"] == 1
        # Undo: back to undecided.
        c.post("/scout/search/jobs/decide", json={"ids": rest, "decision": None})
        assert c.get("/scout/search/jobs").json()["counts"]["discarded"] == 0


def test_add_job_title_to_roles_makes_it_relevant(env):
    from backend.main import app

    feed, _ = env
    feed.jobs = [nj("fakefeed", "py1", "Python Developer", BACKEND_JD)]
    run_scan()
    with TestClient(app) as c:
        nr = c.get("/scout/search/jobs?view=not_relevant").json()["items"]
        assert [j["title"] for j in nr] == ["Python Developer"]
        assert nr[0]["status_reason"] == "Title doesn't match your roles"
        out = c.post("/scout/search/roles", json={"role": "  Python   Developer "}).json()
        assert out["criteria"]["roles"] == ["Backend Engineer", "Python Developer"]
        again = c.post("/scout/search/roles", json={"role": "python developer"}).json()  # no duplicates
        assert again["criteria"]["roles"] == ["Backend Engineer", "Python Developer"]
        listed = c.get("/scout/search/jobs").json()
        assert [j["title"] for j in listed["fits"] + listed["other"]] == ["Python Developer"]
        plan = c.get("/scout/search/plan").json()
        assert "Python Developer in India" in [q["query"] for q in plan["queries"]]



def test_purge_other_sources_keeps_only_jsearch(env):
    feed, feed2 = env
    feed.jobs = [nj("jsearch", "j1", "Backend Engineer Intern", BACKEND_JD),
                 nj("remotive", "r1", "Night Nurse", NURSE_JD, company="City Hospital", location="London, UK")]
    # The same backend job also listed by an old source: kept, minus that listing.
    feed2.jobs = [nj("arbeitnow", "a1", "Backend Engineer Intern", BACKEND_JD)]
    run_scan()
    with new_session() as s:
        s.add(FetchRun(scan_id="old-scan", scan_date="2026-11-01", source="remotive", status="ok"))
        s.add(Scan(id="old-scan", trigger="manual", totals={}))
        s.commit()
    out = job_search.purge_other_sources("jsearch")
    assert out["jobs"] == 1 and out["jobs_trimmed"] == 1 and out["scans"] == 1
    with new_session() as s:
        jobs = s.exec(select(Job)).all()
        assert [j.title for j in jobs] == ["Backend Engineer Intern"]
        assert [x["source"] for x in jobs[0].seen_on] == ["jsearch"]
        assert {l.source for l in s.exec(select(JobLedger)).all()} == {"jsearch"}
        assert s.get(Scan, "old-scan") is None
        assert not s.exec(select(JobRequirement).where(JobRequirement.job_id != jobs[0].id)).all()


def test_your_relevance_call_beats_the_checks(env):
    from backend.main import app

    feed, _ = env
    feed.jobs = [nj("fakefeed", "o1", "Python Developer", BACKEND_JD),  # title doesn't match "Backend Engineer"
                 nj("fakefeed", "o2", "Backend Engineer Intern", BACKEND_JD, category="contract")]
    with new_session() as s:
        s.add(AppSetting(key="criteria", value={"job_types": ["internship"]}))
        s.commit()
    run_scan()
    with TestClient(app) as c:
        nr = c.get("/scout/search/jobs?view=not_relevant").json()["items"]
        ex = c.get("/scout/search/jobs?view=excluded").json()["items"]
        assert [j["title"] for j in nr] == ["Python Developer"] and ex == []  # criteria never exclude
        a = c.post(f"/scout/search/jobs/{nr[0]['id']}/relevance", json={"override": "relevant"}).json()
        assert a["relevance_override"] == "relevant" and a["pipeline_status"] == "mapped"
        matches = c.get("/scout/search/jobs").json()
        assert {j["title"] for j in matches["fits"] + matches["other"]} == {"Python Developer", "Backend Engineer Intern"}
        # A rescore (e.g. roles changed) keeps your call.
        with new_session() as s:
            job_search.rescore_relevance(s, roles_changed=True)
        assert c.get(f"/scout/search/jobs/{nr[0]['id']}").json()["pipeline_status"] == "mapped"
        # And the other way round, then undo.
        d = c.post(f"/scout/search/jobs/{nr[0]['id']}/relevance", json={"override": "not_relevant"}).json()
        assert d["pipeline_status"] == "not_relevant" and d["status_reason"] == "You marked it not relevant"
        u = c.post(f"/scout/search/jobs/{nr[0]['id']}/relevance", json={"override": None}).json()
        assert u["relevance_override"] is None and u["pipeline_status"] == "not_relevant"
        assert u["status_reason"] == "Title doesn't match your roles"


def test_borderline_title_rescued_by_strong_context_match():
    from backend.db import Job
    from backend.job_schemas import MatchingSettings

    m = MatchingSettings(role_threshold=0.72, borderline_role_threshold=0.60, borderline_context_threshold=0.50)
    assert job_search.gate_reason(Job(title="x", role_score=0.65, relevance=0.55), m, True) is None
    assert job_search.gate_reason(Job(title="x", role_score=0.65, relevance=0.45), m, True) == "Title doesn't match your roles"
    assert job_search.gate_reason(Job(title="x", role_score=0.55, relevance=0.90), m, True) == "Title doesn't match your roles"
    off = MatchingSettings(role_threshold=0.72, borderline_role_threshold=0)
    assert job_search.gate_reason(Job(title="x", role_score=0.65, relevance=0.9), off, True) == "Title doesn't match your roles"
