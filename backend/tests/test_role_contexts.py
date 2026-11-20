"""Phase 2.6: role contexts (written per role, edited, used to judge jobs) and the query fixes
(wording, recency floor, operator-free role text, experience switch). Offline: fake model,
fake JSearch, bag-of-words embeddings."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from backend.db import ApiCall, AppSetting, Job, JobRequirement, RoleContext, SearchQuery, new_session
from backend.job_schemas import ScanSelection, ScheduleSettings, SearchCriteria
from backend.services import job_search, role_contexts, search_plan
from backend.services.sources.jsearch import build_query
from backend.tests.test_job_search import BACKEND_JD, NURSE_JD, env, nj, run_scan  # noqa: F401  (env is a fixture)

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


def _criteria(**extra):
    with new_session() as s:
        row = s.get(AppSetting, "criteria") or AppSetting(key="criteria")
        row.value = {"roles": ["Backend Engineer"], "locations": ["India"], **extra}
        s.add(row)
        s.commit()


def _app():
    from backend.main import app

    return app


# ── role contexts ──────────────────────────────────────────────────────────────


def test_context_is_written_cleaned_embedded_and_traceable(env):
    with new_session() as s:
        rc = s.exec(select(RoleContext).where(RoleContext.role_key == "backend engineer")).one()
        assert rc.status == "ready" and rc.embedding and rc.embedding_signature
        # Search titles: no characters Google reads as operators; the role itself first.
        assert rc.search_titles[0] == "Backend Engineer" and "Python Developer Backend" in rc.search_titles
        assert all("(" not in t for t in rc.search_titles + rc.keywords)
        assert rc.built_from["card_ids"] and rc.built_from["memory_version"]
        text = role_contexts.context_text(rc)
        assert text.startswith("Backend Engineer") and "Requirements:" in text and "PostgreSQL" in text


def test_scan_scores_jobs_against_the_role_context_and_ranks_by_it(env):
    feed, _ = env
    feed.jobs = [nj("f", "1", "Backend Engineer Intern", BACKEND_JD),
                 nj("f", "2", "Night Nurse", NURSE_JD, company="City Hospital", location="London, UK")]
    run_scan()
    with new_session() as s:
        jobs = {j.title: j for j in s.exec(select(Job)).all()}
        backend, nurse = jobs["Backend Engineer Intern"], jobs["Night Nurse"]
        assert backend.relevance is not None and backend.relevance > nurse.relevance
        assert backend.relevance_card_id is None  # cards aren't embedded any more
        # Evidence without vectors: named skills you have are met; the gap is listed; the rest isn't judged.
        reqs = s.exec(select(JobRequirement).where(JobRequirement.job_id == backend.id)).all()
        assert {r.method for r in reqs} <= {"exact_skill", "numeric", "none"}
        assert any(r.status == "met" for r in reqs) and all(not r.evidence for r in reqs)


def test_borderline_title_is_rescued_only_by_a_close_context(env):
    from backend.job_schemas import MatchingSettings

    m = MatchingSettings(role_threshold=0.72, borderline_role_threshold=0.60, borderline_context_threshold=0.55)
    assert job_search.gate_reason(Job(title="x", role_score=0.65, relevance=0.60), m, True) is None
    assert job_search.gate_reason(Job(title="x", role_score=0.65, relevance=None), m, True) == "Title doesn't match your roles"
    assert job_search.gate_reason(Job(title="x", role_score=0.1, relevance=None), m, False) is None  # no roles: all pass


def test_role_contexts_api_list_edit_regenerate_and_test(env):
    with TestClient(_app()) as c:
        rows = c.get("/records/memory/roles").json()
        assert [r["role"] for r in rows if r["in_roles"]] == ["Backend Engineer"]
        rc = rows[0]
        assert rc["status"] == "ready" and rc["cards"] and rc["text"].startswith("Backend Engineer")
        assert rc["memory_changed"] is False

        edited = c.patch(f"/records/memory/roles/{rc['id']}",
                         json={"keywords": ["Go", "gRPC"], "search_titles": ["Backend Engineer", "Go Developer (Backend)"]}).json()
        assert edited["edited"] is True and edited["keywords"] == ["Go", "gRPC"]
        assert edited["search_titles"] == ["Backend Engineer", "Go Developer Backend"]
        # A role context you edited is never rewritten without asking...
        role_contexts.ensure_for_roles(["Backend Engineer"])
        assert c.get("/records/memory/roles").json()[0]["keywords"] == ["Go", "gRPC"]
        # ...but Regenerate does.
        regen = c.post(f"/records/memory/roles/{rc['id']}/regenerate").json()
        assert regen["edited"] is False and regen["keywords"][0] == "Python"

        scores = c.post("/records/memory/roles/test", json={"text": BACKEND_JD}).json()
        assert scores[0]["role"] == "Backend Engineer" and 0 < scores[0]["score"] <= 1

        # A card changes -> the context says your memory changed (not rewritten).
        card = c.get("/records/memory").json()["cards"][0]
        c.patch(f"/records/memory/{card['id']}", json={"text": card["text"] + " Plus Rust."})
        assert c.get("/records/memory/roles").json()[0]["memory_changed"] is True


def test_adding_a_role_writes_its_context(env):
    with TestClient(_app()) as c:
        c.post("/scout/search/roles", json={"role": "Python Developer"})
        rows = {r["role"]: r for r in c.get("/records/memory/roles").json()}
    assert rows["Python Developer"]["status"] == "ready"


# ── query wording, recency floor, experience switch ───────────────────────────


def test_build_query_syntax():
    assert build_query(["Artificial Intelligence (AI) Associate"], "India") == "Artificial Intelligence AI Associate in India"
    assert build_query(["AI Engineer"], "India", exact=True) == '"AI Engineer" in India'
    assert build_query(["AI Engineer", "ML Engineer", "ai engineer"], "India", exact=True) == '("AI Engineer" OR "ML Engineer") in India'
    assert build_query(["A", "B"], "India") == "A OR B in India"
    assert build_query(["AI Engineer"], "India", exact=True, keywords=["LLM", "machine learning"]) == \
        '"AI Engineer" LLM "machine learning" in India'


def test_wording_styles_come_from_role_contexts(env):
    _criteria()
    with TestClient(_app()) as c:
        def first(**body):
            plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"], **body}).json()
            return plan["calls"][0]["query"], plan["variant"], plan["calls"][0]["params"]

        assert first()[0] == "Backend Engineer in India"
        assert first(wording="exact")[0] == '"Backend Engineer" in India'
        assert first(wording="titles")[0] == '("Backend Engineer" OR "Python Developer Backend" OR "Backend Developer") in India'
        q, variant, params = first(wording="titles_keywords", send_experience=False, experience_years=1)
        assert q.endswith(" Python in India") and variant == "titles_keywords · exp off" and "job_requirements" not in params
        _, variant, params = first(experience_years=1)
        assert variant == "plain · exp off" and "job_requirements" not in params  # never sent since 2026-11-20


def test_titles_wording_without_a_context_falls_back_to_the_role_name(env):
    _criteria(roles=["Backend Engineer", "Data Engineer"])
    with new_session() as s:
        plan, _ = search_plan.build(s, selection=ScanSelection(roles=["Data Engineer"], wording="titles"))
    assert plan.calls[0].query == '"Data Engineer" in India'
    assert any("No search titles yet for Data Engineer" in n for n in plan.notes)


def test_each_request_records_its_wording_and_analytics_groups_by_it(env):
    feed, _ = env
    feed.jobs = [nj("f", "w1", "Backend Engineer Intern", BACKEND_JD)]
    write = {("scout", "search", "criteria", "query_wording"): "titles"}
    from backend.config import write_tuning

    write_tuning(write)
    run_scan()
    with new_session() as s:
        call = s.exec(select(ApiCall)).one()
        assert call.variant == "titles · exp off"  # experience_years "any" in the fixture: nothing to send
        assert call.params["query"].startswith('("Backend Engineer" OR')
    with TestClient(_app()) as c:
        a = c.get("/system/jsearch").json()
        assert a["by_wording"][0]["variant"] == "titles · exp off" and a["by_wording"][0]["requests"] == 1
        assert a["recent"][0]["query"].startswith('("Backend Engineer"')


def test_recency_floor():
    c, sch = SearchCriteria(), ScheduleSettings(recency_days=30)
    yesterday = NOW - timedelta(hours=20)
    assert search_plan.date_posted(yesterday, c, sch, NOW) == "today"  # no floor (old behaviour)
    assert search_plan.date_posted(yesterday, c, sch, NOW, "week") == "week"
    assert search_plan.date_posted(None, c, sch, NOW, "week") == "month"
    # Posted within still wins over the floor.
    assert search_plan.date_posted(yesterday, SearchCriteria(posted_within_days=3), sch, NOW, "week") == "3days"


def test_repeat_search_uses_the_floor_from_settings(env):
    _criteria()
    with new_session() as s:
        q = search_plan.role_query(s, "Backend Engineer", "India", "IN")
        q.last_success_at = datetime.now(UTC) - timedelta(hours=10)
        s.add(q)
        s.commit()
    with TestClient(_app()) as c:
        plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"]}).json()
    assert plan["calls"][0]["params"]["date_posted"] == "week"
    with new_session() as s:
        assert s.exec(select(SearchQuery)).first() is not None
