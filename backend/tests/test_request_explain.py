"""What a JSearch request does in plain words: before sending (Scan now / plan) and after
(why a request returned what it did). Offline: reads only our own records."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from backend.db import ApiCall, ApiCallJob, Job, new_session
from backend.services import request_explain, search_plan
from backend.services.sources.jsearch import explain_param
from backend.tests.test_job_search import env  # noqa: F401  (fixture)
from backend.tests.test_role_contexts import _app, _criteria

EXP = "under_3_years_experience,no_experience"


def test_each_parameter_is_explained():
    meaning, narrows, warn = explain_param("job_requirements", EXP)
    assert narrows and warn and "under 3 years" in meaning and "Fresher" in meaning
    assert explain_param("query", "AI Engineer in India")[1] is False  # plain: loose
    meaning, narrows, _ = explain_param("query", '"AI Engineer" in India')
    assert narrows and "word for word" in meaning and '"India" is read as the place' in meaning
    assert "last 7 days" in explain_param("date_posted", "week")[0]
    assert explain_param("employment_types", "FULLTIME,INTERN")[0] == "Only these job types: Full-time, Internship."


def test_key_words_name_the_field():
    assert request_explain.key_words('"AI Engineer" in India') == {"ai", "artificial", "intelligence"}
    assert "ml" in request_explain.key_words("Machine Learning Engineer in India")
    assert request_explain.on_topic("Data Engineer - AI/ML Products", {"ai"})
    assert not request_explain.on_topic("Mechanical Engineer - Fresher", {"ai", "artificial", "intelligence"})


def _past_call(s, query_id, params, results, relevant=0, days=1):
    c = ApiCall(query_id=query_id, params=params, status="ok", results=results, relevant_jobs=relevant,
                at=datetime.now(UTC) - timedelta(days=days), variant="plain · exp on")
    s.add(c)
    s.commit()
    s.refresh(c)
    return c


def test_plan_explains_parameters_history_and_what_we_check_after(env):
    _criteria(experience_years=1)
    with new_session() as s:
        q = search_plan.role_query(s, "Backend Engineer", "India", "IN")
        base = {"query": "Backend Engineer in India", "country": "in", "page": 1, "num_pages": 1, "date_posted": "month"}
        _past_call(s, q.id, base, results=2, days=1)
        _past_call(s, q.id, {**base, "date_posted": "week"}, results=0, days=2)
    with TestClient(_app()) as c:
        plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"]}).json()
    call = plan["calls"][0]
    keys = [p["key"] for p in call["explain"]]
    assert keys[:2] == ["query", "country"] and "job_requirements" not in keys  # years: a Jobs-page filter now
    assert [h["results"] for h in call["history"]] == [2, 0]
    assert call["history"][0]["differs"] == [] and call["history"][1]["differs"] == ["date_posted: week"]
    assert any("with these exact filters returned 2 jobs" in n for n in plan["notes"])
    assert any(a.startswith("Title check:") and "Backend Engineer" in a for a in plan["after"])
    assert any("don't remove jobs" in a for a in plan["after"])


def test_past_request_says_why_it_returned_what_it_did(env):
    with new_session() as s:
        call = _past_call(s, None, {"query": "AI Engineer in India", "country": "in", "page": 1, "num_pages": 1,
                                    "date_posted": "week", "job_requirements": EXP}, results=3)
        rows = [("Remote Chemistry Researcher (PhD)", "Anywhere", "not_relevant", None),
                ("Mechanical Engineer - Fresher", "Changodar, Gujarat, India", "not_relevant", None),
                ("Data Engineer - AI/ML Products", "Hyderabad, India", "excluded", "Asks for 3+ years of experience")]
        for i, (title, loc, status, reason) in enumerate(rows, 1):
            j = Job(title=title, location_text=loc, dedupe_key=f"k{i}", content_hash=f"h{i}",
                    pipeline_status=status, status_reason=reason)
            s.add(j)
            s.commit()
            s.refresh(j)
            s.add(ApiCallJob(call_id=call.id, position=i, source_job_id=f"s{i}", job_id=j.id, title=title,
                             location_text=loc, outcome="new"))
        s.commit()
        cid = call.id
    with TestClient(_app()) as c:
        out = c.get(f"/scout/search/calls/{cid}/explain").json()
        assert c.get("/scout/search/calls/9999/explain").status_code == 404
    text = " | ".join(out["findings"])
    assert "Only 3 of a possible 10" in text
    assert "1 of 3 were remote “Anywhere” listings, not jobs listed in IN" in text
    assert "2 of 3 titles contain none of the search's key words" in text
    assert "1 was a generic “Fresher”" in text
    assert "2 of 3 failed the title check" in text and "Asks for 3+ years of experience" in text
    assert "even with the experience filter on" in text and out["findings"][-1] == "0 of 3 reached your Matches."
    tips = " | ".join(out["suggestions"])
    assert "Turn off “Send the experience filter”" in tips and "“Exact title” or “Title group”" in tips
    assert out["params"][0]["key"] == "query"


def test_scan_now_shows_where_each_value_comes_from(env):
    _criteria(experience_years=1)
    with TestClient(_app()) as c:
        plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"]}).json()
    call = plan["calls"][0]
    assert call["custom"] is False and call["default_query"] == call["query"] == "Backend Engineer in India"
    src = {p["key"]: p["source"] for p in call["explain"]}
    assert src["query"].startswith("Role Backend Engineer + place “India” from Locations, worded Plain")
    assert src["country"] == "Locations: “India” → in."
    assert src["date_posted"].startswith("First run of this search: the widest allowed, 30 days")
    assert "job_requirements" not in src
    assert any(x.startswith("Job types: empty") for x in plan["not_sent"])


def test_scan_now_sends_the_query_you_typed_and_the_date_you_chose(env):
    from backend.db import Scan, utcnow
    from backend.job_schemas import ScanSelection
    from backend.services import job_search

    feed, _ = env
    _criteria(experience_years=1)
    with TestClient(_app()) as c:
        qid = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"]}).json()["calls"][0]["query_id"]
        body = {"roles": ["Backend Engineer"], "query_texts": {str(qid): '  "Backend Engineer"   Python in India '},
                "date_posted": "month", "send_experience": False}
        plan = c.post("/scout/search/plan", json=body).json()
    call = plan["calls"][0]
    assert call["query"] == call["params"]["query"] == '"Backend Engineer" Python in India' and call["custom"]
    assert call["params"]["date_posted"] == "month" and "job_requirements" not in call["params"]
    assert plan["variant"] == "custom · exp off"
    src = {p["key"]: p["source"] for p in call["explain"]}
    assert src["query"].startswith("Typed by you for this scan") and src["date_posted"].startswith("Chosen for this scan")

    # The scan sends exactly that.
    assert job_search._scan_lock.acquire(blocking=False)
    scan_id = f"t-{utcnow().timestamp()}"
    job_search._current["scan_id"] = scan_id
    with new_session() as s:
        s.add(Scan(id=scan_id, trigger="manual", totals={}))
        s.commit()
    job_search._run(scan_id, "manual", ScanSelection(**body))
    sent = feed.client.calls[-1]
    assert sent["query"] == '"Backend Engineer" Python in India' and sent["date_posted"] == "month"
    with new_session() as s:
        assert s.exec(select(ApiCall)).one().variant == "custom · exp off"


def test_location_picker_countries_and_a_state_in_the_query(env):
    _criteria(locations=["India", "Karnataka, India"])
    with TestClient(_app()) as c:
        india = next(x for x in c.get("/scout/search/places").json() if x["code"] == "IN")
        assert india["name"] == "India" and "Karnataka" in india["places"] and "Bengaluru" in india["places"]
        plan = c.post("/scout/search/plan", json={"roles": ["Backend Engineer"], "locations": ["Karnataka, India"],
                                                  "date_posted": "week"}).json()
    call = plan["calls"][0]
    assert call["query"] == "Backend Engineer in Karnataka, India"
    assert call["params"]["country"] == "in" and call["params"]["date_posted"] == "week"
    assert not any("isn't in your saved Locations" in n for n in plan["notes"])
