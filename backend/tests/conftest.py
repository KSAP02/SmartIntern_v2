"""Test setup: a throwaway data dir, a fake key, and no network calls (model + Milvus stubbed)."""
import io
import os
import shutil
import tempfile

import pytest

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="smartintern-test-")
os.environ["LLM_API_KEY"] = "sk-test-not-real"
os.environ["VECTOR_DB_URI"] = os.path.join(os.environ["DATA_DIR"], "milvus-test.db")
# Never let tests overwrite the real snapshot (Compose mounts data_warehouse/snapshots).
os.environ["SNAPSHOT_DIR"] = os.path.join(os.environ["DATA_DIR"], "snapshots")
# Admin settings write config.toml: tests get their own copy, never the real file.
_cfg = os.path.join(os.environ["DATA_DIR"], "config.toml")
shutil.copyfile(os.path.join(os.path.dirname(__file__), "..", "..", "settings", "config.toml"), _cfg)
os.environ["CONFIG_FILE"] = _cfg
# Company job boards are real public APIs: off in tests, so a scan never reads a real board. Tests
# that need boards switch them on and fake every board's answer (test_boards_a1.py).
with open(_cfg, encoding="utf-8") as _f:
    _text = _f.read()
# Remote feeds (Himalayas, RemoteJobs.org, Remotive) and the company finder likewise: off, faked
# where tested (test_feeds_c1.py, test_finder_e.py).
for _section in ("[scout.search.boards]", "[scout.search.feeds]", "[scout.search.finder]"):
    _i = _text.index(_section)
    _j = _text.index("enabled = true", _i)
    _text = _text[:_j] + "enabled = false" + _text[_j + len("enabled = true"):]
with open(_cfg, "w", encoding="utf-8") as _f:
    _f.write(_text)

from backend.schemas import Profile  # noqa: E402

FAKE_RESUME_LINES = [
    "Alex Example",
    "alex.example@example.com | +1 555 0100 | Springfield, Freedonia",
    "Summary",
    "Backend developer who builds data-heavy web services with Python and FastAPI.",
    "Experience",
    "Software Engineering Intern, Acme Widgets (Jan 2024 - Jun 2024)",
    "- Built a FastAPI service for inventory search",
    "- Cut query latency by 40% with PostgreSQL indexes",
    "Education",
    "B.Tech in Computer Science, Example Institute of Technology, 2021 - 2025",
    "Skills: Python, FastAPI, PostgreSQL, Docker, React",
]


def make_docx() -> bytes:
    from docx import Document

    doc = Document()
    for line in FAKE_RESUME_LINES:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in FAKE_RESUME_LINES:
        page.insert_text((72, y), line, fontsize=10)
        y += 16
    return doc.tobytes()


def fake_profile(**overrides) -> Profile:
    data = {
        "personal": {"full_name": "Alex Example", "email": "alex.example@example.com", "phone": "+1 555 0100",
                     "address": {"city": "Springfield", "country": "Freedonia"}},
        "headline": {"current_title": "Backend developer", "summary": "Builds data-heavy web services."},
        "skills": {"skills": ["Python", "FastAPI", "PostgreSQL"], "tools": ["Docker"]},
        "work_history": [{"company": "Acme Widgets", "title": "Software Engineering Intern", "start": "Jan 2024",
                          "end": "Jun 2024", "bullets": ["Built a FastAPI service for inventory search"]}],
        "education": [{"institution": "Example Institute of Technology", "degree": "B.Tech", "field": "Computer Science"}],
    }
    data.update(overrides)
    return Profile.model_validate(data)


@pytest.fixture
def no_network(monkeypatch):
    """Stub the LLM and embeddings so tests are offline and deterministic. (Memory cards are not
    embedded since Phase 2.6; role contexts are stubbed in the job-search tests.)"""
    from backend.services import profile_extract, role_contexts

    def fake_embed(texts):
        # 3-dim vectors keyed off a keyword so similarity is predictable.
        return [[1.0, 0.0, 0.0] if "fastapi" in t.lower() else [0.0, 1.0, 0.0] for t in texts]

    monkeypatch.setattr(profile_extract, "chat_structured", lambda **_: _extracted())
    monkeypatch.setattr(role_contexts, "embed", fake_embed)
    return {}


def _extracted():
    from backend.services.profile_extract import ExtractedResume

    p = fake_profile().model_dump(exclude={"preferences"})
    for section in ("work_history", "education", "projects", "certifications"):
        for item in p[section]:
            item.pop("id")
    for g in p["skills"]["groups"]:
        g.pop("id")
    return ExtractedResume.model_validate(p)
