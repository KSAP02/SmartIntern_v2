"""End-to-end through the API with the model and Milvus stubbed (see conftest.no_network)."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.tests.conftest import make_docx, make_pdf


@pytest.fixture
def client(no_network):
    with TestClient(app) as c:
        yield c


def test_full_phase1_flow(client):
    # Vault: upload two resumes; parsing runs as a background task (sync in TestClient).
    files = [
        ("files", ("Alex CV.docx", make_docx(), "application/octet-stream")),
        ("files", ("alex.pdf", make_pdf(), "application/pdf")),
    ]
    r = client.post("/records/vault", files=files)
    assert r.status_code == 202, r.text
    ids = [i["id"] for i in r.json()["items"]]
    resumes = client.get("/records/vault").json()
    assert {x["parse_status"] for x in resumes} == {"parsed"}
    assert sum(x["is_default"] for x in resumes) == 1

    # Uploading never touches the profile.
    assert client.get("/records/profile").json()["profile"]["personal"]["full_name"] is None

    # Me: preview, then apply excluding one field.
    prev = client.post("/records/profile/fill", json={"resume_id": ids[0], "preview": True}).json()
    assert any(c["path"] == "personal.phone" for c in prev["changes"])
    res = client.post("/records/profile/fill", json={"resume_id": ids[0], "preview": False,
                                                "exclude_fields": ["personal.phone"]}).json()
    me = res["view"]
    assert me["profile"]["personal"]["full_name"] == "Alex Example"
    assert me["profile"]["personal"]["phone"] is None
    assert me["field_origins"]["personal.full_name"] == f"resume:{ids[0]}"

    # Memory was built on first fill (cards are stored text; not embedded since Phase 2.6).
    mem = client.get("/records/memory").json()
    kinds = {c["kind"] for c in mem["cards"]}
    assert {"summary", "experience", "education", "skills"} <= kinds

    # Hand edit -> origin 'user'; profile now newer than memory -> stale hint.
    profile = me["profile"]
    profile["personal"]["phone"] = "+1 555 4242"
    me = client.put("/records/profile", json=profile).json()
    assert me["field_origins"]["personal.phone"] == "user"
    assert me["memory_stale"] is True

    # Edit a card, add a custom one, disable one; rebuild keeps edited/custom.
    exp = next(c for c in mem["cards"] if c["kind"] == "experience")
    edited = client.patch(f"/records/memory/{exp['id']}", json={"text": exp["text"] + "\n- Wrote FastAPI tests"}).json()
    assert edited["user_edited"] is True
    custom = client.post("/records/memory", json={"title": "Hackathon", "text": "Won a FastAPI hackathon"}).json()
    skills = next(c for c in mem["cards"] if c["kind"] == "skills")
    client.patch(f"/records/memory/{skills['id']}", json={"enabled": False})
    rebuilt = client.post("/records/memory/rebuild").json()
    rebuilt_ids = {c["id"] for c in rebuilt["cards"]}
    assert exp["id"] in rebuilt_ids and custom["id"] in rebuilt_ids
    assert rebuilt["memory_stale"] is False

    # "Test against a JD" moved to Memory -> Role contexts; without roles it says so.
    assert client.post("/records/memory/roles/test", json={"text": "Looking for a FastAPI intern, Python"}).status_code == 400

    # Desk + Switchboard.
    desk = client.get("/insight/desk").json()
    assert desk["first_name"] == "Alex" and desk["resumes"]["total"] == 2
    status = client.get("/system/status").json()
    assert status["llm"]["model"] == "gpt-6-luna" and status["config_loaded"] is True

    # Delete a resume: profile keeps its values; default moves.
    assert client.delete(f"/records/vault/{ids[0]}").status_code == 204
    assert client.get("/records/profile").json()["profile"]["personal"]["full_name"] == "Alex Example"
    assert sum(x["is_default"] for x in client.get("/records/vault").json()) == 1


def test_upload_rejects_bad_files(client):
    r = client.post("/records/vault", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 400
    assert "notes.txt" in r.json()["detail"]


def test_duplicate_upload_returns_existing(client):
    data = make_docx()
    first = client.post("/records/vault", files=[("files", ("dup.docx", data, "application/octet-stream"))]).json()
    again = client.post("/records/vault", files=[("files", ("dup-copy.docx", data, "application/octet-stream"))]).json()
    assert again["duplicates"] == [first["items"][0]["id"]]


def test_fill_requires_parsed_resume(client):
    assert client.post("/records/profile/fill", json={"resume_id": 9999}).status_code == 404
