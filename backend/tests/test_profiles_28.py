"""Phase 2.8: several profiles, one active. Cards, role contexts and roles follow the active
profile; the job pool is shared and re-scored on a switch. Offline (fake model, fake JSearch)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import delete, select

from backend.db import (
    ACTIVE_PROFILE_KEY, Job, MemoryCard, ProfileRow, Resume, RoleContext, _migrate_profiles, new_session, set_meta,
)
from backend.job_schemas import SettingsPatch
from backend.services import profiles, search_settings
from backend.tests.conftest import fake_profile
from backend.tests.test_job_search import BACKEND_JD, NURSE_JD, env, nj, run_scan  # noqa: F401  (env is a fixture)


def _app():
    from backend.main import app

    return app


@pytest.fixture
def two(env, monkeypatch):
    monkeypatch.setattr(profiles, "_start", profiles.after_switch)  # the switch follow-up runs inline
    with new_session() as s:
        r = Resume(label="ML resume", original_filename="ml.pdf", mime_type="application/pdf", size_bytes=1,
                   sha256="p28-test-resume", storage_key="x", parse_status="parsed",
                   parsed_data=fake_profile(headline={"current_title": "ML engineer", "summary": "Trains models."}).model_dump())
        s.add(r)
        s.commit()
        resume_id = r.id
    yield env, resume_id
    with new_session() as s:
        set_meta(s, ACTIVE_PROFILE_KEY, "1")
        set_meta(s, profiles.SWITCH_KEY, "{}")
        s.exec(delete(MemoryCard).where(MemoryCard.profile_id != 1))
        s.exec(delete(RoleContext).where(RoleContext.profile_id != 1))
        s.exec(delete(ProfileRow).where(ProfileRow.id != 1))
        s.exec(delete(Resume).where(Resume.sha256 == "p28-test-resume"))
        s.commit()


def _roles() -> list[str]:
    with new_session() as s:
        return search_settings.get(s, "criteria").roles


def _set_roles(roles: list[str]) -> None:
    with new_session() as s:
        crit = search_settings.get(s, "criteria").model_copy(update={"roles": roles})
        search_settings.patch(s, SettingsPatch(criteria=crit))


def test_old_role_contexts_move_to_profile_1_and_become_unique_per_profile():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE memory_cards (id INTEGER PRIMARY KEY, profile_id INTEGER)"))
        c.execute(text("CREATE TABLE role_contexts (id INTEGER PRIMARY KEY, role_key VARCHAR, profile_id INTEGER)"))
        c.execute(text("CREATE UNIQUE INDEX ix_role_contexts_role_key ON role_contexts (role_key)"))
        c.execute(text("INSERT INTO memory_cards (id) VALUES (1)"))
        c.execute(text("INSERT INTO role_contexts (id, role_key) VALUES (1, 'backend engineer')"))
    _migrate_profiles(eng)
    _migrate_profiles(eng)  # idempotent
    with eng.begin() as c:
        assert c.execute(text("SELECT profile_id FROM memory_cards")).scalar() == 1
        assert c.execute(text("SELECT profile_id FROM role_contexts")).scalar() == 1
        # The same role in another profile is allowed; twice in one profile isn't.
        c.execute(text("INSERT INTO role_contexts (id, role_key, profile_id) VALUES (2, 'backend engineer', 2)"))
    with pytest.raises(Exception), eng.begin() as c:
        c.execute(text("INSERT INTO role_contexts (id, role_key, profile_id) VALUES (3, 'backend engineer', 2)"))


def test_switching_profile_switches_cards_role_contexts_and_roles(two):
    (feed, _), resume_id = two
    feed.jobs = [nj("f", "1", "Backend Engineer Intern", BACKEND_JD),
                 nj("f", "2", "Night Nurse", NURSE_JD, company="City Hospital", location="London, UK")]
    run_scan()
    with new_session() as s:
        backend = s.exec(select(Job).where(Job.title == "Backend Engineer Intern")).one()
        backend.decision = "selected"
        s.add(backend)
        s.commit()

    with TestClient(_app()) as c:
        first_cards = {x["id"] for x in c.get("/records/memory").json()["cards"]}
        out = c.post("/records/profile/profiles", json={"resume_id": resume_id})
        assert out.status_code == 201
        new = next(p for p in out.json()["profiles"] if not p["active"])
        assert new["name"] == "ML resume" and new["resume_id"] == resume_id and new["roles"] == ["Backend Engineer"]
        assert new["cards"] == 0  # built when it is first used

        sw = c.post(f"/records/profile/profiles/{new['id']}/activate")
        assert sw.status_code == 202 and sw.json()["active_id"] == new["id"]
        assert c.get("/records/profile").json()["profile"]["headline"]["current_title"] == "ML engineer"
        cards = c.get("/records/memory").json()["cards"]
        assert cards and not ({x["id"] for x in cards} & first_cards)  # its own cards
        # Its own "Backend Engineer" context, next to profile 1's.
        with new_session() as s:
            owners = {rc.profile_id for rc in s.exec(select(RoleContext).where(RoleContext.role_key == "backend engineer"))}
        assert owners == {1, new["id"]}
        assert c.get("/records/profile/profiles").json()["switching"]["running"] is False

        # Roles belong to the profile: change them here, switch back, and they come back with it.
        _set_roles(["Night Nurse"])
        c.post("/records/profile/profiles/1/activate")
        assert _roles() == ["Backend Engineer"]
        assert {x["id"] for x in c.get("/records/memory").json()["cards"]} == first_cards
        c.post(f"/records/profile/profiles/{new['id']}/activate")
        assert _roles() == ["Night Nurse"]

    # The shared jobs were re-scored for the Night Nurse role; your marks stayed.
    with new_session() as s:
        jobs = {j.title: j for j in s.exec(select(Job)).all()}
        n = jobs["Night Nurse"]
        assert n.pipeline_status in ("relevant", "mapped"), (n.status_reason, n.role_score, n.role_match, n.relevance)
        assert jobs["Backend Engineer Intern"].decision == "selected"


def test_create_copy_rename_and_delete_rules(two):
    with TestClient(_app()) as c:
        copy = c.post("/records/profile/profiles", json={"copy_of": 1}).json()["profiles"][-1]
        assert copy["name"].endswith("(copy)") and not copy["active"]
        assert c.post("/records/profile/profiles", json={}).status_code == 409  # neither resume nor copy
        renamed = c.patch(f"/records/profile/profiles/{copy['id']}", json={"name": "Data roles"}).json()
        assert any(p["name"] == "Data roles" for p in renamed["profiles"])
        assert c.delete("/records/profile/profiles/1").status_code == 409  # the active one
        assert c.delete(f"/records/profile/profiles/{copy['id']}").status_code == 204
        assert c.delete("/records/profile/profiles/1").status_code == 409  # still active (and the last)
        assert len(c.get("/records/profile/profiles").json()["profiles"]) == 1
