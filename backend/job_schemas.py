"""Pydantic models for Job Search (Phase 2): the API contract, settings sections, adapter output.

Same layer as `schemas.py` (imported by services and API, imports only pydantic).
Plan: MD_files/project_build_phases/phase_2_job_discovery_and_understanding.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Category = Literal["internship", "full_time", "part_time", "contract", "freelance"]
Workplace = Literal["remote", "hybrid", "onsite"]
Compensation = Literal["paid", "stipend", "unpaid"]
Seniority = Literal["intern", "entry", "mid", "senior", "lead"]
SalaryPeriod = Literal["year", "month", "week", "day", "hour"]
FactSource = Literal["source", "rules", "ai"]

# Before 2026-11-19 experience was a choice; it is now the most years a job may ask for.
LEGACY_EXPERIENCE = {"any": None, "no_experience": 0, "under_3_years": 2}


def _years(v):
    """Years of experience: empty / "any" / negative -> None (any experience is fine)."""
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "any")):
        return None
    n = int(float(v))
    return None if n < 0 else min(n, 50)


# ── Adapter output ─────────────────────────────────────────────────────────────


class NormalizedJob(BaseModel):
    """What every source adapter returns. Unknown values stay None; never guessed."""

    source: str  # adapter name, e.g. "remotive"
    source_job_id: str  # unique within the source
    company_name: str | None = None
    title: str
    description_html: str | None = None  # raw HTML if the source gives HTML
    description_text: str | None = None  # plain text if the source gives text
    location_text: str | None = None
    is_remote: bool | None = None
    workplace_type: Workplace | None = None  # only if the source states it
    category: Category | None = None  # only if the source states the job type
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None  # ISO 4217, e.g. "USD", "INR"
    salary_period: SalaryPeriod | None = None
    tags: list[str] = Field(default_factory=list)
    job_url: str | None = None  # the posting page
    apply_url: str | None = None  # where to apply, if different
    source_published_at: datetime | None = None
    raw: dict | None = None  # original record (kept only for a few days)
    # The source's own requirement lists, e.g. {"Qualifications": [...], "Responsibilities": [...]}.
    highlights: dict[str, list[str]] | None = None


# ── Settings sections (criteria + preset: DB with config.toml defaults; the rest: config.toml) ─
# "All" is always the empty list / None.


class SearchCriteria(BaseModel):
    """Before gathering: what to collect at all. Unknown values are always kept."""

    roles: list[str] = Field(default_factory=list)  # "Roles you want"; [] = judge by whole profile
    # Automatic scans: which roles (names from `roles`; [] = all) and how they are searched:
    # rotate = one role per request, taking turns; each = every included role, one request each;
    # combined = all included roles in ONE request ("A OR B OR C in <place>").
    auto_roles: list[str] = Field(default_factory=list)
    auto_mode: Literal["rotate", "each", "combined"] = "rotate"
    job_types: list[Category] = Field(default_factory=list)
    workplace: list[Workplace] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)  # countries or cities; [] = anywhere
    # With locations set: keep jobs whose location can't be read? Off = only places you named
    # (and remote jobs open to them). Feeds often give bare town names we can't place.
    keep_unknown_location: bool = False
    # Your years of experience: jobs asking for more are dropped; 0-2 also ask JSearch for
    # entry-level postings (job_requirements). None = any experience is fine.
    experience_years: int | None = None
    posted_within_days: int | None = None
    # How a search is worded (the JSearch adapter writes the syntax): plain = "AI Engineer in
    # India"; exact = the title in quotes; titles = the role's search titles (Memory -> Role
    # contexts) as one OR group; titles_keywords = that plus the role's first keyword.
    query_wording: Literal["plain", "exact", "titles", "titles_keywords"] = "plain"
    exclude_title_words: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy_experience(cls, data):
        if isinstance(data, dict) and "experience" in data:
            data = dict(data)
            old = data.pop("experience")
            if "experience_years" not in data:
                data["experience_years"] = LEGACY_EXPERIENCE.get(old)
        return data

    @field_validator("experience_years", mode="before")
    @classmethod
    def _clean_years(cls, v):
        return _years(v)


class ApplyPreset(BaseModel):
    """Before applying: sorts gathered jobs into "Fits your preset" / "Other relevant"."""

    pay: list[Compensation] = Field(default_factory=list)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "INR"
    salary_period: SalaryPeriod = "year"
    min_fit: int | None = None  # % of must-haves met (partial counts half)
    seniority: list[Seniority] = Field(default_factory=list)
    max_years_experience: float | None = None
    needs_visa_sponsorship: bool = False
    max_internship_months: int | None = None
    only_companies: list[str] = Field(default_factory=list)
    include_unknown: bool = True


class SourcesSettings(BaseModel):
    """JSearch, the only job source (config.toml [scout.search.sources]; Admin settings -> JSearch).
    One request = one page of up to 10 jobs."""

    enabled: bool = True
    # Where the JSEARCH_API_KEY comes from: OpenWeb Ninja directly (x-api-key) or RapidAPI.
    provider: Literal["openwebninja", "rapidapi"] = "openwebninja"
    monthly_limit: int = 200  # hard cap per billing period (free plan: 200)
    # Limit requests per day: on = scans spend at most daily_limit a day (UTC), from today,
    # whatever was spent before; off = scans may use everything left this period (minus reserve).
    daily_limit_on: bool = True
    daily_limit: int = 6
    reserve: int = 10  # kept back from scans for tests (Admin -> JSearch -> Test with 1 request)
    max_per_scan: int = 1  # requests one scan may spend (1 request = up to 10 jobs)
    pages_policy: Literal["single", "smart"] = "smart"  # smart: a 2nd page only when page 1 paid off
    page2_min_new: int = 5  # smart: page 1 must bring at least this many new jobs
    backoff_after_empty: int = 3  # runs with nothing new before a search is run less often
    timeout_seconds: float = 30
    api_country: str = "IN"  # searched when Search criteria has no Locations (ISO code)
    excluded_publishers: list[str] = Field(default_factory=list)  # sent as exclude_job_publishers
    # A repeat search asks only for jobs posted since it last ran, but never narrower than this
    # (a 'today' window returned 0-1 jobs). today | 3days | week | month | all
    min_date_posted: Literal["today", "3days", "week", "month", "all"] = "week"
    # Send your years of experience to JSearch as job_requirements (it is checked after the
    # call either way). Off = JSearch doesn't filter by experience (query lab H1).
    send_experience_filter: bool = True


class ScheduleSettings(BaseModel):
    autoscan: bool = False
    time: str = "07:00"  # HH:MM in `timezone`
    every_hours: Literal[12, 24] = 24
    timezone: str = "Asia/Kolkata"  # IANA name
    recency_days: int = 30  # ignore postings older than this at ingestion


class LimitsSettings(BaseModel):
    """Retention. Jobs are kept until YOU discard them (or the agent applies); nothing else is
    deleted automatically."""

    keep_discarded_days: int = 3  # discarded jobs are deleted after this (the ledger keeps them out)
    expire_after_days: int = 45  # posted (or found) longer ago -> marked "expired" (label only)
    raw_payload_days: int = 7  # the source's original record is dropped after this
    repost_window_days: int = 60


class MatchingSettings(BaseModel):
    """Since Phase 2.6: job title vs your roles decides; the job's text vs that role's context
    (Memory -> Role contexts) rescues borderline titles and ranks Matches. Memory cards are no
    longer embedded (evidence = exact skills + years)."""

    metric: Literal["COSINE", "IP", "L2"] = "COSINE"
    role_threshold: float = 0.72  # job title (best part, abbreviations expanded) vs your roles
    # Borderline rescue: a title at least this close still counts when the job text also matches
    # that role's context at least borderline_context_threshold. 0 = off.
    borderline_role_threshold: float = 0.60
    borderline_context_threshold: float = 0.50  # measured: kept 0.53-0.67, unrelated near-misses 0.41-0.46


class SearchSettings(BaseModel):
    criteria: SearchCriteria = Field(default_factory=SearchCriteria)
    preset: ApplyPreset = Field(default_factory=ApplyPreset)
    sources: SourcesSettings = Field(default_factory=SourcesSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)


# Saved in the DB from Job Search -> Search Settings (config.toml holds their defaults).
# sources / schedule / limits / matching live in config.toml itself (System -> Admin settings).
SettingsSection = Literal["criteria", "preset"]
ADMIN_SECTIONS = ("sources", "schedule", "limits", "matching")


class SettingsPatch(BaseModel):
    """criteria and/or preset; each given section is replaced as a whole."""

    criteria: SearchCriteria | None = None
    preset: ApplyPreset | None = None


class SettingsReset(BaseModel):
    section: SettingsSection


class AutoscanToggle(BaseModel):
    enabled: bool


# ── Source health, search plan, API calls ──────────────────────────────────────────────────────


class SourceOut(BaseModel):
    name: str
    label: str
    kind: Literal["feed", "ats"]
    enabled: bool
    terms_url: str | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    active_jobs: int
    configured: bool = True  # False = needs keys in .env (see setup_hint)
    setup_hint: str | None = None


class QuotaOut(BaseModel):
    """JSearch request budget right now (counted from api_calls)."""

    month_used: int
    monthly_limit: int
    reserve: int
    today_used: int
    today_allowance: int  # what scans may still spend today
    scan_allowance: int  # what the next scan may spend (today_allowance capped by max_per_scan)
    daily_limit: int = 0  # the per-day cap (when daily_limit_on)
    daily_limit_on: bool = True
    max_per_scan: int = 0
    resets_on: str  # YYYY-MM-DD (first day of next month, UTC)
    # How the period is going (scan requests; the reserve isn't counted):
    days_left: int = 0  # days left in the billing period, today included
    scan_budget: int = 0  # monthly_limit - reserve
    scan_used: int = 0  # scan requests this period
    scan_left: int = 0  # scan_budget - scan_used (never past the hard limit)
    even_pace: int = 0  # scan_left (+ today's) spread evenly over days_left: a fair per-day number now
    expected_by_today: int = 0  # what an even pace from the period start would have used by end of today
    ahead_by: int = 0  # scan_used - expected_by_today: > 0 spent faster than even, < 0 slower
    blocked_until: datetime | None = None  # after an HTTP 429 from JSearch
    provider_remaining: int | None = None  # OpenWeb Ninja's remaining quota (minus our calls since), if known


class ProviderUsageOut(BaseModel):
    """OpenWeb Ninja /usage, as last fetched. Fields are picked by name; `raw` has everything."""

    fetched_at: str | None = None
    error: str | None = None
    plan: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    limit: int | None = None
    used: int | None = None
    remaining: int | None = None
    raw: list[tuple[str, str | int | float | bool | None]] = Field(default_factory=list)


class ParamNote(BaseModel):
    """One sent parameter in plain words: what JSearch / Google for Jobs does with it."""

    key: str  # query | country | date_posted | job_requirements | ...
    value: str
    meaning: str
    narrows: bool = False  # it removes postings from what Google would otherwise return
    warn: bool = False  # often the reason for few or off-target results
    source: str = ""  # where the value came from (your settings), e.g. "Locations: India -> in"


class PastRequest(BaseModel):
    """An earlier request for the same search (same role and place), and how it went."""

    id: int
    at: datetime
    query: str
    results: int
    relevant: int
    variant: str | None = None
    differs: list[str] = Field(default_factory=list)  # what it sent differently, e.g. "date_posted: month"


class PlannedCall(BaseModel):
    query_id: int
    query: str  # "AI Engineer in India"
    page: int
    params: dict  # what will be sent (no key)
    reason: str  # "never run" | "due (last run 2 days ago)" | ...
    default_query: str = ""  # the text your settings generate (custom = you typed another)
    custom: bool = False
    sources: dict[str, str] = Field(default_factory=dict)  # parameter -> where its value came from
    explain: list[ParamNote] = Field(default_factory=list)  # each parameter in plain words
    history: list[PastRequest] = Field(default_factory=list)  # the same search before (newest first)


class CountryOption(BaseModel):
    """A country for the location picker, with the states / cities we know there (suggestions)."""

    code: str  # ISO, e.g. IN (sent to JSearch as country=in)
    name: str  # India
    places: list[str]  # Karnataka, Maharashtra, ..., Bengaluru, Pune, ...


class CallExplainOut(BaseModel):
    """Why one past request returned what it did."""

    params: list[ParamNote]
    findings: list[str]  # what the returned jobs show, e.g. "2 of 2 were remote 'Anywhere' listings"
    suggestions: list[str]  # what to change next time
    history: list[PastRequest]  # other requests for the same search


class QueryOut(BaseModel):
    id: int
    role: str
    place: str
    country: str
    query: str
    roles: list[str] = Field(default_factory=list)  # combined search: its roles
    active: bool
    enabled: bool
    interval_days: int
    last_run_at: datetime | None
    next_due_at: datetime | None
    runs: int
    results: int
    new_jobs: int
    relevant_jobs: int
    yield_per_request: float | None  # relevant new jobs per request, recent runs
    zero_streak: int


class ScanSelection(BaseModel):
    """Scan now with your choice: which roles, and one combined (OR) request per place or one
    request per role. Empty roles = not allowed (choose at least one)."""

    roles: list[str] = Field(min_length=1, max_length=20)
    combine: bool = False
    # This scan only (None = your Search criteria). Prefilled in the picker from Search criteria.
    locations: list[str] | None = Field(default=None, max_length=10)
    job_types: list[Category] | None = None
    workplace: list[Workplace] | None = None
    # Sent explicitly (even empty = any) -> replaces your criteria's experience for this scan.
    experience_years: int | None = None
    wording: Literal["plain", "exact", "titles", "titles_keywords"] | None = None
    send_experience: bool | None = None  # None = Admin settings -> JSearch
    # date_posted for this scan (None = automatic: since this search last ran, at least the floor).
    date_posted: Literal["today", "3days", "week", "month", "all"] | None = None
    # Query text you typed, per search (query_id -> text); missing / empty = the generated text.
    query_texts: dict[int, str] | None = Field(default=None, max_length=20)

    @field_validator("experience_years", mode="before")
    @classmethod
    def _clean_years(cls, v):
        return _years(v)


class SearchPlanOut(BaseModel):
    """What the next scan would send to JSearch (nothing is called to build this)."""

    configured: bool
    enabled: bool
    kind: str = "auto"  # auto (the automatic-scan plan) | manual (your Scan now choice)
    mode: str = "rotate"  # rotate | each | combined | separate
    allowance: int = 0  # requests this scan may spend (auto: per-scan cap; manual: what's left today)
    fits_budget: bool = True  # manual: False when the choice needs more requests than allowed now
    calls: list[PlannedCall]
    queries: list[QueryOut]
    quota: QuotaOut
    notes: list[str]  # e.g. "No roles set", "Key missing", "2 searches wait for tomorrow's budget"
    variant: str | None = None  # the wording of these requests, e.g. "titles · exp off"
    after: list[str] = Field(default_factory=list)  # what we check on the returned jobs, in plain words
    not_sent: list[str] = Field(default_factory=list)  # your settings that aren't sent to JSearch, and why


class QueryPatch(BaseModel):
    enabled: bool


class CallJobOut(BaseModel):
    """One job a request returned, with what became of it."""

    position: int
    title: str
    company_name: str | None
    location_text: str | None
    outcome: str  # new | updated | unchanged | duplicate (seen on another listing) | already_seen | too_old
    job_id: int | None
    # The job now (None if it no longer exists, e.g. discarded and deleted).
    pipeline_status: str | None = None  # excluded | not_relevant | relevant | mapped | ...
    status_reason: str | None = None
    decision: str | None = None
    role_score: float | None = None
    role_match: str | None = None


class ApiCallOut(BaseModel):
    id: int
    at: datetime
    query: str | None
    purpose: str
    page: int
    params: dict
    status: str
    http_status: int | None
    results: int
    new_jobs: int
    relevant_jobs: int
    error: str | None
    variant: str | None = None


class UsageDay(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    requests: int
    errors: int
    results: int
    new_jobs: int
    relevant_jobs: int


class JSearchTestOut(BaseModel):
    """Admin -> JSearch -> Test with 1 request."""

    ok: bool
    error: str | None = None
    query: str | None = None
    params: dict = Field(default_factory=dict)
    results: int = 0
    new_jobs: int = 0
    relevant_jobs: int = 0
    shape: str | None = None  # "data[list]" (OpenWeb Ninja / RapidAPI) or "data.jobs"
    countries: dict = Field(default_factory=dict)
    publishers: dict = Field(default_factory=dict)
    types: dict = Field(default_factory=dict)
    has_currency: int = 0  # jobs with job_salary_currency
    has_highlights: int = 0  # jobs with job_highlights
    titles: list = Field(default_factory=list)
    fields_seen: list[str] = Field(default_factory=list)
    saved_as: str | None = None


class WordingYield(BaseModel):
    """What one way of wording requests bought (e.g. "titles · exp off")."""

    variant: str
    requests: int
    results: int
    new_jobs: int
    relevant_jobs: int
    relevant_per_request: float | None


class JSearchAnalyticsOut(BaseModel):
    """Admin -> JSearch analytics: budget, provider's view, and what the requests bought."""

    configured: bool
    provider: str
    quota: QuotaOut
    usage: ProviderUsageOut
    per_day: list[UsageDay]  # last `days` days, oldest first, zero days included
    totals: dict[str, int]  # requests, ok, errors, scan, calibration, results, new_jobs, relevant_jobs
    per_request: dict[str, float | None]  # results, new_jobs, relevant_jobs per request
    queries: list[QueryOut]
    recent: list[ApiCallOut]
    by_wording: list[WordingYield] = Field(default_factory=list)  # Phase 2.6 query lab


class FetchRunOut(BaseModel):
    source: str
    company: str | None
    status: Literal["running", "ok", "failed"]
    fetched: int
    new: int
    updated: int
    duplicates: int
    already_seen: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class ScanOut(BaseModel):
    scan_id: str
    trigger: Literal["manual", "auto"]
    phase: Literal["fetching", "processing", "mapping", "pruning", "done", "failed"]
    started_at: datetime
    finished_at: datetime | None
    totals: dict[str, int]  # fetched, new, updated, duplicates, already_seen, excluded, not_relevant, relevant, mapped
    runs: list[FetchRunOut]
    error: str | None


# ── Overview (dashboard) ───────────────────────────────────────────────────────


class DayCount(BaseModel):
    date: str  # YYYY-MM-DD (date found)
    source: str
    found: int  # fetched that day
    new: int  # first seen that day


class OverviewOut(BaseModel):
    running: ScanOut | None
    last_scan: ScanOut | None
    autoscan: bool
    next_scan_at: datetime | None
    per_day: list[DayCount]  # last 30 days
    funnel: dict[str, int]  # seen, excluded, not_relevant, relevant, mapped, fits_preset
    breakdown: dict[str, dict[str, int]]  # category / workplace / country -> value -> count (relevant jobs)
    sources: list[SourceOut]
    quota: QuotaOut | None = None
    memory_ready: bool  # False if a role has no ready role context yet (Memory -> Role contexts)


# ── Jobs ───────────────────────────────────────────────────────────────────────


class Coverage(BaseModel):
    must_total: int
    must_met: int
    must_partial: int
    must_missing: int
    nice_total: int
    nice_met: int
    fit: int | None  # 0–100: (met + 0.5 * partial) / must_total; None if no requirements found


class SeenOn(BaseModel):
    source: str
    job_url: str | None


class JobCard(BaseModel):
    id: int
    title: str
    company_name: str | None
    location_text: str | None
    category: Category | None
    workplace_type: Workplace | None
    country_codes: list[str]
    remote_regions: list[str]
    compensation_type: Compensation | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None
    seniority: Seniority | None
    min_years_experience: float | None = None  # years the posting asks for (None: not stated)
    first_seen_at: datetime
    source_published_at: datetime | None
    seen_on: list[SeenOn]
    relevance: float | None  # 0–1: job text vs the role context of role_match (Phase 2.6)
    role_score: float | None = None  # title vs your best-matching role (cosine)
    role_match: str | None = None  # that role
    coverage: Coverage | None
    pipeline_status: str  # new | excluded | not_relevant | relevant | mapped | failed
    status_reason: str | None = None  # why excluded / not relevant
    decision: Literal["selected", "discarded", "applied"] | None = None
    decided_at: datetime | None = None
    relevance_override: Literal["relevant", "not_relevant"] | None = None  # your call, beats the checks
    # The place searched by the request that found it, and whether the job is there (never excludes).
    searched_place: str | None = None
    place_check: Literal["match", "elsewhere", "remote", "unknown"] | None = None
    expired: bool = False  # posted (or found) longer ago than Limits -> expire_after_days
    fits_preset: bool
    preset_misses: list[str]  # human reasons, e.g. "Unpaid", "Asks 5+ years"
    job_url: str | None
    apply_url: str | None


JobsView = Literal["matches", "selected", "applied", "discarded", "not_relevant", "excluded"]


class JobsOut(BaseModel):
    view: str
    fits: list[JobCard]  # view "matches": undecided relevant jobs that fit the apply preset
    other: list[JobCard]  # view "matches": undecided relevant jobs outside the preset
    items: list[JobCard]  # every other view
    counts: dict[str, int]  # fits, other, selected, applied, discarded, not_relevant, excluded


class CardRef(BaseModel):
    card_id: int
    title: str
    score: float


class RequirementOut(BaseModel):
    id: int
    section: str  # requirements | responsibilities | nice_to_have | about | other
    importance: Literal["must", "nice", "unknown"]
    text: str
    skills: list[str]
    status: Literal["met", "partial", "missing", "unknown"] | None
    method: str | None
    best: CardRef | None
    evidence: list[CardRef]


class JobDetail(JobCard):
    description_text: str
    snippet_only: bool = False  # the source gives only a short excerpt (thin evidence map)
    field_sources: dict[str, FactSource]
    internship_duration: str | None
    visa_sponsorship: Literal["yes", "no"] | None
    start_date: str | None
    apply_deadline: str | None
    tags: list[str]
    requirements: list[RequirementOut]
    missing_skills: list[str]  # vocabulary skills the job asks for that your profile lacks
    matched_skills: list[str]


class JobPatch(BaseModel):
    decision: Literal["selected", "discarded", "applied"] | None  # None = back to undecided


class JobsDecide(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    decision: Literal["selected", "discarded", "applied"] | None


class RelevanceOverride(BaseModel):
    override: Literal["relevant", "not_relevant"] | None  # None = let the checks decide again


class RoleAdd(BaseModel):
    role: str = Field(min_length=2, max_length=120)


# ── Role contexts (Phase 2.6) ─────────────────────────────────────────────────────────────────


class RoleRef(BaseModel):
    id: int | None
    label: str


class RoleContextOut(BaseModel):
    """One role's job-description-style context (Memory -> Role contexts)."""

    id: int | None  # None = not written yet (status missing)
    role: str
    status: str  # missing | pending | ready | failed
    error: str | None = None
    summary: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    search_titles: list[str] = Field(default_factory=list)  # used to word searches, not embedded
    keywords: list[str] = Field(default_factory=list)
    text: str = ""  # exactly what is embedded
    edited: bool = False
    generated_at: datetime | None = None
    updated_at: datetime | None = None
    model: str | None = None
    cards: list[RoleRef] = Field(default_factory=list)  # memory cards it was drafted from
    example_jobs: list[RoleRef] = Field(default_factory=list)  # fetched postings used as examples
    memory_changed: bool = False  # your cards changed since it was written
    in_roles: bool = True  # False = a role you removed (kept for re-adding)


class RoleContextPatch(BaseModel):
    summary: str | None = None
    responsibilities: list[str] | None = None
    requirements: list[str] | None = None
    nice_to_have: list[str] | None = None
    search_titles: list[str] | None = None
    keywords: list[str] | None = None


class RoleTest(BaseModel):
    text: str = Field(min_length=20, max_length=20000)


class RoleMatch(BaseModel):
    role: str
    context_id: int | None
    score: float
