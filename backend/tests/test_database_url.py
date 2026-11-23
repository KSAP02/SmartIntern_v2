"""DATABASE_URL picks the database (SQLite fallback); AUTO_SCANS gates automatic scans (2026-11-23)."""
import pytest

from backend import db
from backend.config import get_settings


@pytest.fixture
def env(monkeypatch):
    def set_(**values):
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield set_
    get_settings.cache_clear()


def test_blank_or_sqlite_means_the_sqlite_file(env):
    env(DATABASE_URL="sqlite")
    assert db.postgres_url() is None and not db.is_postgres()
    assert db.db_check().startswith("SQLite at")


def test_postgres_urls_use_the_psycopg_driver(env):
    for given in ("postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"):
        env(DATABASE_URL=given)
        assert db.postgres_url() == "postgresql+psycopg://u:p@h:5432/d"
    env(DATABASE_URL="mysql://u:p@h/d")
    with pytest.raises(RuntimeError):
        db.postgres_url()


def test_tests_refuse_a_real_postgres(env, monkeypatch):
    monkeypatch.delenv("ALLOW_TEST_POSTGRES", raising=False)
    env(DATABASE_URL="postgresql://u:p@h:5432/d")
    db.get_engine.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            db.get_engine()
    finally:
        monkeypatch.setenv("DATABASE_URL", "sqlite")
        get_settings.cache_clear()
        db.get_engine.cache_clear()


def test_auto_scans_false_never_starts_a_scan(env, monkeypatch):
    from backend.services import job_search, job_views, scheduler, settings_effects

    started = []
    monkeypatch.setattr(settings_effects, "sync_config", lambda: None)
    monkeypatch.setattr(job_views, "next_scan_at", lambda s: db.utcnow())
    monkeypatch.setattr(job_search, "running_scan_id", lambda: None)
    monkeypatch.setattr(job_search, "start_scan", lambda trigger: started.append(trigger))
    env(AUTO_SCANS="false")
    scheduler._tick()
    assert started == []
    env(AUTO_SCANS="true")
    scheduler._tick()
    assert started == ["auto"]
