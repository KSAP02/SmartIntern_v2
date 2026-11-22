"""Jobs page: filter by the day a job was found, counted in your timezone. Offline (fake JSearch)."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlmodel import select

from backend.db import Job, new_session
from backend.tests.test_job_search import BACKEND_JD, env, nj, run_scan  # noqa: F401  (env is a fixture)


def _app():
    from backend.main import app

    return app


def test_jobs_filter_by_day_found_in_your_timezone(env):
    feed, _ = env
    feed.jobs = [nj("f", "1", "Backend Engineer Intern", BACKEND_JD, company="Acme"),
                 nj("f", "2", "Backend Engineer", BACKEND_JD, company="Globex")]
    run_scan()
    with new_session() as s:
        jobs = {j.company_name: j for j in s.exec(select(Job)).all()}
        # 20:00 UTC on the 22nd is 01:30 on the 23rd in India.
        jobs["Acme"].first_seen_at = datetime(2026, 11, 22, 20, 0, tzinfo=UTC)
        jobs["Globex"].first_seen_at = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
        s.add_all(jobs.values())
        s.commit()

    with TestClient(_app()) as c:
        def get(**params) -> dict:
            return c.get("/scout/search/jobs", params=params).json()

        def companies(out: dict) -> set[str]:
            return {j["company_name"] for j in out["fits"] + out["other"]}

        out = get(tz="Asia/Kolkata")
        assert out["days"] == [{"date": "2026-11-23", "count": 1}, {"date": "2026-11-20", "count": 1}]
        assert companies(out) == {"Acme", "Globex"}
        # One day, in your timezone...
        assert companies(get(tz="Asia/Kolkata", found_from="2026-11-23", found_to="2026-11-23")) == {"Acme"}
        # ...the same moment is the 22nd in UTC.
        assert [d["date"] for d in get()["days"]] == ["2026-11-22", "2026-11-20"]
        # A range; the day list still shows every day so you can pick another.
        week = get(tz="Asia/Kolkata", found_from="2026-11-19", found_to="2026-11-21")
        assert companies(week) == {"Globex"} and len(week["days"]) == 2
        assert companies(get(tz="Not/AZone", found_from="2026-11-22")) == {"Acme"}  # unknown zone → UTC
