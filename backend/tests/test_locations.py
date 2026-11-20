"""Location never excludes a job (2026-11-20); Matches shows whether a job is in the place searched."""
from __future__ import annotations

from backend.db import Job
from backend.job_schemas import SearchCriteria
from backend.services.job_facts import place_check
from backend.services.job_search import criteria_reason
from backend.tests.test_job_search import env  # noqa: F401  (fixture)


def test_place_check_state_city_country_and_remote():
    assert place_check("Karnataka, India", "Bengaluru, Karnataka, India", ["IN"], "onsite") == "match"
    assert place_check("Karnataka, India", "Pune, Maharashtra, India", ["IN"], "onsite") == "elsewhere"
    assert place_check("Karnataka, India", "Bengaluru, India", ["IN"], None) == "unknown"  # no state given
    assert place_check("Bengaluru, India", "Bangalore, Karnataka, India", ["IN"], None) == "match"  # alias
    assert place_check("Bengaluru, India", "Hyderabad, Telangana, India", ["IN"], None) == "elsewhere"
    assert place_check("India", "Chennai, Tamil Nadu, India", ["IN"], None) == "match"
    assert place_check("India", "Berlin, Germany", ["DE"], None) == "elsewhere"
    assert place_check("India", "Anywhere", [], "remote") == "remote"
    assert place_check(None, "Pune, India", ["IN"], None) is None


def test_location_and_years_never_exclude():
    c = SearchCriteria(locations=["Karnataka, India"], experience_years=1, keep_unknown_location=False)
    assert criteria_reason(Job(title="x", location_text="Berlin, Germany", country_codes=["DE"],
                               dedupe_key="k", content_hash="h"), c) is None
    assert criteria_reason(Job(title="x", location_text=None, dedupe_key="k", content_hash="h"), c) is None
    assert criteria_reason(Job(title="x", min_years_experience=3, dedupe_key="k", content_hash="h"), c) is None


def test_reapply_frees_jobs_the_criteria_used_to_exclude(env):
    from backend.db import new_session
    from backend.services.job_search import reapply_criteria
    from backend.tests.test_role_contexts import _criteria

    _criteria(experience_years=1)
    with new_session() as s:
        old = Job(title="Backend Engineer", location_text="Pune, India", min_years_experience=3, dedupe_key="a",
                  content_hash="a", pipeline_status="excluded", status_reason="Location: Pune, India")
        loc = Job(title="Backend Engineer", location_text="Berlin, Germany", dedupe_key="b", content_hash="b",
                  pipeline_status="excluded", status_reason="Location: Berlin, Germany")
        s.add(old)
        s.add(loc)
        s.commit()
        reapply_criteria(s)
        s.refresh(old)
        s.refresh(loc)
        assert old.pipeline_status == loc.pipeline_status == "new"  # back through the title check
        assert old.status_reason is None  # back through the title check


def test_matches_can_be_filtered_by_the_years_a_job_asks(env):
    from fastapi.testclient import TestClient

    from backend.db import new_session
    from backend.tests.test_role_contexts import _app

    with new_session() as s:
        for i, years in enumerate([None, 0, 2, 5]):
            s.add(Job(title=f"Backend Engineer {i}", min_years_experience=years, dedupe_key=f"y{i}",
                      content_hash=f"y{i}", pipeline_status="mapped"))
        s.commit()
    with TestClient(_app()) as c:
        def titles(**params):
            out = c.get("/scout/search/jobs", params=params).json()
            return sorted(j["title"] for j in out["fits"] + out["other"])

        assert len(titles()) == 4
        # Up to 2 years: 0 and 2 stay, 5 goes; a job that doesn't say stays.
        assert titles(max_years=2) == ["Backend Engineer 0", "Backend Engineer 1", "Backend Engineer 2"]
        assert c.get("/scout/search/jobs", params={"max_years": 2}).json()["fits"][0]["min_years_experience"] in (None, 0, 2)
