"""SQLite engine, session and tables (single user). Postgres replaces SQLite at deploy."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import JSON, Column, Text, event, inspect, text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from backend import snapshots
from backend.config import data_dir


def utcnow() -> datetime:
    return datetime.now(UTC)


class Resume(SQLModel, table=True):
    __tablename__ = "resumes"

    id: int | None = Field(default=None, primary_key=True)
    label: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str = Field(index=True, unique=True)
    storage_key: str
    parse_status: str = "pending"
    parse_error: str | None = None
    extracted_text: str | None = Field(default=None, sa_column=Column(Text))
    parsed_data: dict | None = Field(default=None, sa_column=Column(JSON))
    is_default: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProfileRow(SQLModel, table=True):
    __tablename__ = "profile"

    id: int = Field(default=1, primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    field_origins: dict = Field(default_factory=dict, sa_column=Column(JSON))
    last_filled_from_resume_id: int | None = None
    confirmed_at: datetime | None = None
    updated_at: datetime | None = None
    memory_built_at: datetime | None = None


class MemoryCard(SQLModel, table=True):
    __tablename__ = "memory_cards"

    id: int | None = Field(default=None, primary_key=True)
    kind: str
    title: str
    text: str = Field(sa_column=Column(Text))
    enabled: bool = True
    pinned: bool = False
    origin: str = "generated"
    user_edited: bool = False
    source_ref: str | None = None
    embedding_status: str = "pending"
    embedding_error: str | None = None
    embedded_at: datetime | None = None
    position: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RoleContext(SQLModel, table=True):
    """Phase 2.6: one AI-written, job-description-style context per role in "Roles you want".
    Written when the role is added, editable; its text is embedded once (vector kept in the
    row) and compared with every fetched job of that role."""

    __tablename__ = "role_contexts"

    id: int | None = Field(default=None, primary_key=True)
    role: str  # as written in Roles you want
    role_key: str = Field(index=True, unique=True)  # lowercased, spaces collapsed
    status: str = "pending"  # pending | ready | failed
    error: str | None = None
    summary: str = Field(default="", sa_column=Column(Text))
    responsibilities: list = Field(default_factory=list, sa_column=Column(JSON))
    requirements: list = Field(default_factory=list, sa_column=Column(JSON))
    nice_to_have: list = Field(default_factory=list, sa_column=Column(JSON))
    search_titles: list = Field(default_factory=list, sa_column=Column(JSON))  # for queries, not embedded
    keywords: list = Field(default_factory=list, sa_column=Column(JSON))  # for queries, not embedded
    # What it was drafted from: card_ids, job_ids (example JDs), memory_version, model.
    built_from: dict = Field(default_factory=dict, sa_column=Column(JSON))
    edited: bool = False  # you changed it after it was written
    embedding: list | None = Field(default=None, sa_column=Column(JSON))
    embedding_signature: str | None = None  # embedding model + dims it was made with
    generated_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class Meta(SQLModel, table=True):
    """Small key/value store, e.g. which embedding model built the vectors."""

    __tablename__ = "meta"

    key: str = Field(primary_key=True)
    value: str


# ── Job Search (Phase 2). Shapes of JSON columns: backend/job_schemas.py ─────────


class AppSetting(SQLModel, table=True):
    """Settings edited in the UI (one row per section). config.toml gives the defaults."""

    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)  # section name, e.g. "criteria", "preset", "matching"
    value: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)


class JobSource(SQLModel, table=True):
    """Health of the job source (only "jsearch" since Phase 2.5)."""

    __tablename__ = "job_sources"

    name: str = Field(primary_key=True)  # source name
    enabled: bool = True  # unused: on/off lives in config.toml
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None


class SearchQuery(SQLModel, table=True):
    """One planned JSearch search (role x place) and how well it pays off. Kept across scans:
    the planner decides from this which searches to spend the request budget on."""

    __tablename__ = "search_queries"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)  # hash of role + place + country (filters can change)
    role: str  # one role, or "A OR B OR C" for a combined search
    roles: list = Field(default_factory=list, sa_column=Column(JSON))  # combined search: its roles; [] = single role
    place: str  # as written in Locations, or the country name
    country: str  # ISO code, e.g. "IN"
    active: bool = True  # part of the current plan (follows Search criteria)
    enabled: bool = True  # you can pause one search
    interval_days: int = 1  # grows with back-off when it keeps finding nothing new
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    runs: int = 0  # requests made
    results: int = 0  # jobs returned
    new_jobs: int = 0
    relevant_jobs: int = 0
    zero_streak: int = 0  # consecutive runs with no new job
    recent: list = Field(default_factory=list, sa_column=Column(JSON))  # last 5 runs: [requests, new, relevant]
    created_at: datetime = Field(default_factory=utcnow)


class ApiCallJob(SQLModel, table=True):
    """What one JSearch request returned, job by job (in the order JSearch ranked them), and what
    happened to each. Kept for the request's history even after a job is discarded."""

    __tablename__ = "api_call_jobs"

    id: int | None = Field(default=None, primary_key=True)
    call_id: int = Field(index=True)  # api_calls.id
    position: int  # 1 = JSearch's first result
    source_job_id: str
    job_id: int | None = Field(default=None, index=True)  # the job row it became / matched (None: too old)
    title: str
    company_name: str | None = None
    location_text: str | None = None
    outcome: str  # new | updated | unchanged | duplicate | already_seen | too_old
    created_at: datetime = Field(default_factory=utcnow)


class ApiCall(SQLModel, table=True):
    """Every request to a metered API (JSearch). Usage and quotas are counted from here.
    Written *before* the request is sent (status "sending"), so a crash still counts it."""

    __tablename__ = "api_calls"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    api: str = Field(default="jsearch", index=True)
    query_id: int | None = Field(default=None, index=True)
    scan_id: str | None = Field(default=None, index=True)
    purpose: str = "scan"  # scan | calibration
    params: dict = Field(default_factory=dict, sa_column=Column(JSON))  # never holds the key
    page: int = 1
    status: str = "sending"  # sending | ok | error
    http_status: int | None = None
    results: int = 0
    new_jobs: int = 0
    relevant_jobs: int = 0
    error: str | None = None
    variant: str | None = None  # the wording used, e.g. "titles · exp off" (Phase 2.6)


class FetchRun(SQLModel, table=True):
    """One source (or one company board) in one scan. Kept: it's the scan history."""

    __tablename__ = "fetch_runs"

    id: int | None = Field(default=None, primary_key=True)
    scan_id: str = Field(index=True)
    scan_date: str = Field(index=True)  # YYYY-MM-DD (UTC)
    trigger: str = "manual"
    source: str
    company: str | None = None
    status: str = "running"  # running | ok | failed
    fetched: int = 0
    new: int = 0
    updated: int = 0
    duplicates: int = 0
    already_seen: int = 0
    error: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class Scan(SQLModel, table=True):
    """One scan (all sources). Kept with its totals for the Overview."""

    __tablename__ = "scans"

    id: str = Field(primary_key=True)
    trigger: str = "manual"
    phase: str = "fetching"
    totals: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class JobLedger(SQLModel, table=True):
    """One tiny row per job ever seen. Never pruned: dedupe + history work after jobs are deleted."""

    __tablename__ = "job_ledger"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    source_job_id: str = Field(index=True)
    dedupe_key: str = Field(index=True)
    canonical_url: str | None = Field(default=None, index=True)
    job_id: int | None = Field(default=None, index=True)
    first_seen_date: str = Field(index=True)
    category: str | None = None
    workplace_type: str | None = None
    country: str | None = None
    relevance: float | None = None
    outcome: str = "active"  # active | excluded | not_relevant | expired | hidden | other | applied
    is_duplicate: bool = False  # another source's listing of a job already in the ledger
    updated_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    """Full data for jobs still in play. Pruned; see job_ledger for history."""

    __tablename__ = "jobs"

    id: int | None = Field(default=None, primary_key=True)
    seen_on: list = Field(default_factory=list, sa_column=Column(JSON))  # [{source, source_job_id, job_url}]
    dedupe_key: str = Field(index=True)
    canonical_url: str | None = None
    content_hash: str
    company_name: str | None = None
    api_call_id: int | None = Field(default=None, index=True)  # the request that found it
    title: str
    location_text: str | None = None
    description_text: str = Field(default="", sa_column=Column(Text))
    country_codes: list = Field(default_factory=list, sa_column=Column(JSON))
    remote_regions: list = Field(default_factory=list, sa_column=Column(JSON))
    workplace_type: str | None = None
    category: str | None = None
    seniority: str | None = None
    compensation_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    min_years_experience: float | None = None
    internship_duration: str | None = None
    start_date: str | None = None
    apply_deadline: str | None = None
    visa_sponsorship: str | None = None
    field_sources: dict = Field(default_factory=dict, sa_column=Column(JSON))
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    job_url: str | None = None
    apply_url: str | None = None
    source_published_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    status: str = Field(default="active", index=True)  # active | expired
    pipeline_status: str = Field(default="new", index=True)  # new | excluded | not_relevant | relevant | mapped | failed
    status_reason: str | None = None  # why excluded / not relevant
    status_changed_at: datetime = Field(default_factory=utcnow)
    relevance: float | None = None
    relevance_card_id: int | None = None
    role_score: float | None = None  # job title vs best of "Roles you want" (cosine); None = not scored
    role_match: str | None = None  # which of your roles the title matched best
    coverage: dict | None = Field(default=None, sa_column=Column(JSON))
    mapped_memory_version: str | None = None
    hidden: bool = False  # legacy (before decisions): moved to decision="discarded" on start-up
    hidden_at: datetime | None = None
    # Your call on the job: None (undecided) | selected (for the agent to apply) | discarded | applied.
    # Only discarded jobs are ever deleted (after Limits -> keep_discarded_days).
    decision: str | None = Field(default=None, index=True)
    # Your call on relevance: "relevant" (keep it, whatever the checks say) | "not_relevant" | None.
    relevance_override: str | None = None
    decided_at: datetime | None = None
    repost_of: str | None = None  # date an earlier listing of the same job was first seen
    embedding_status: str = "pending"
    raw_payload: dict | None = Field(default=None, sa_column=Column(JSON))
    # Source's own requirement lists, e.g. JSearch job_highlights {"Qualifications": [...], ...}.
    # Kept (unlike raw_payload) because requirements are built from it.
    highlights: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class JobRequirement(SQLModel, table=True):
    """One chunk of a job description (bullet / sentence). Deleted with its job."""

    __tablename__ = "job_requirements"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(index=True)
    section: str
    importance: str  # must | nice | unknown
    text: str = Field(sa_column=Column(Text))
    skills: list = Field(default_factory=list, sa_column=Column(JSON))
    position: int = 0
    embedding_status: str = "pending"
    # The middle layer: this chunk vs your memory cards.
    status: str | None = None  # met | partial | missing | unknown
    method: str | None = None  # exact_skill | vector | numeric | none
    best_card_id: int | None = None
    best_score: float | None = None
    evidence: list = Field(default_factory=list, sa_column=Column(JSON))  # [{card_id, score}]


@lru_cache
def get_engine():
    path = data_dir() / "app.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    # Keep the host snapshot fresh: any committed write to any table schedules a copy.
    @event.listens_for(engine, "after_cursor_execute")
    def _mark_write(conn, _cursor, statement, *_):
        if statement.lstrip().split(None, 1)[0].upper() in _WRITE_VERBS:
            conn.info["wrote"] = True

    @event.listens_for(engine, "commit")
    def _after_commit(conn):
        if conn.info.pop("wrote", False):
            snapshots.schedule(path)

    @event.listens_for(engine, "rollback")
    def _after_rollback(conn):
        conn.info.pop("wrote", None)

    return engine


_WRITE_VERBS = {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"}


def _add_missing_columns(engine) -> None:
    """create_all() never alters an existing table: add new *nullable* model columns to old DBs.
    (Renames, type changes and NOT NULL columns still need a deliberate migration.)"""
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for column in table.columns:
                if column.name not in have and column.nullable:
                    ddl = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'))


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())
    _add_missing_columns(get_engine())
    # Refresh the snapshot on every start, so it matches the live DB even after a restore.
    snapshots.schedule(data_dir() / "app.db")


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(get_engine()) as session:
        yield session


def new_session() -> Session:
    """For background tasks (each task gets its own session)."""
    return Session(get_engine())


def get_meta(session: Session, key: str) -> str | None:
    row = session.get(Meta, key)
    return row.value if row else None


def set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(Meta, key) or Meta(key=key, value=value)
    row.value = value
    session.add(row)


def get_profile_row(session: Session) -> ProfileRow:
    row = session.get(ProfileRow, 1)
    if row is None:
        row = ProfileRow(id=1, data={}, field_origins={})
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def db_check() -> str:
    with new_session() as s:
        s.exec(select(Meta).limit(1)).all()
    return f"SQLite at {data_dir() / 'app.db'}"
