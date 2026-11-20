"""Pydantic models shared by services and API routes: the profile, resumes, memory cards."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.config import EmbeddingConfig, LLMParams
from backend.job_schemas import LimitsSettings, MatchingSettings, ScheduleSettings, SourcesSettings


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Profile (Records / Me) ─────────────────────────────────────────────────────


class Address(BaseModel):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class Links(BaseModel):
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None
    other: list[str] = Field(default_factory=list)


class Personal(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: Address = Field(default_factory=Address)
    links: Links = Field(default_factory=Links)


class Headline(BaseModel):
    current_title: str | None = None
    summary: str | None = None
    years_experience: float | None = None


class SkillGroup(BaseModel):
    """A themed group of technical skills, e.g. "Backend & APIs". One group = one memory card."""

    id: str = Field(default_factory=new_id)
    name: str | None = None
    items: list[str] = Field(default_factory=list)


class Skills(BaseModel):
    groups: list[SkillGroup] = Field(default_factory=list)
    # Spoken / human languages (kept apart from technical skills).
    languages: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _from_flat_lists(cls, data):
        """Profiles saved before skill groups had flat `skills` + `tools` lists: keep them as two groups."""
        if isinstance(data, dict) and "groups" not in data and ("skills" in data or "tools" in data):
            data = dict(data)
            data["groups"] = [
                {"name": name, "items": items}
                for name, items in (("Skills", data.pop("skills", None)), ("Tools & technologies", data.pop("tools", None)))
                if items
            ]
        return data

    def all_items(self) -> list[str]:
        return [s for g in self.groups for s in g.items]


class WorkItem(BaseModel):
    id: str = Field(default_factory=new_id)
    company: str | None = None
    title: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None
    is_current: bool = False
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    id: str = Field(default_factory=new_id)
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None
    grade: str | None = None


class ProjectItem(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str | None = None
    description: str | None = None
    tech: list[str] = Field(default_factory=list)
    url: str | None = None


class CertificationItem(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str | None = None
    issuer: str | None = None
    date: str | None = None


class Preferences(BaseModel):
    """Set by the user only, never filled from a resume."""

    roles_of_interest: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: Literal["any", "remote", "hybrid", "onsite"] | None = None
    employment_types: list[str] = Field(default_factory=list)
    minimum_salary: float | None = None
    salary_currency: str | None = None
    notice_period: str | None = None
    work_authorization: str | None = None
    earliest_start_date: str | None = None


class Profile(BaseModel):
    personal: Personal = Field(default_factory=Personal)
    headline: Headline = Field(default_factory=Headline)
    skills: Skills = Field(default_factory=Skills)
    work_history: list[WorkItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)


class ProfileOut(BaseModel):
    profile: Profile
    # path -> "user" | "resume:<id>". Scalar paths like "personal.address.city";
    # lists like "skills.groups" / "skills.languages"; list items like "work_history[<item id>]".
    field_origins: dict[str, str]
    # resume id -> label, so the UI can render "from <label>" badges.
    resume_labels: dict[str, str]
    last_filled_from_resume_id: int | None
    confirmed_at: datetime | None
    updated_at: datetime | None
    completeness: int  # 0-100
    memory_stale: bool


FillMode = Literal["empty_only", "replace"]


class FillRequest(BaseModel):
    resume_id: int
    mode: FillMode = "empty_only"
    preview: bool = True
    exclude_fields: list[str] = Field(default_factory=list)


class FillChange(BaseModel):
    path: str  # stable id of this change; send it back in exclude_fields to skip it
    section: str  # top-level section, e.g. "personal", "work_history"
    label: str  # human label, e.g. "Address › City", "Work history › SWE at Acme"
    action: Literal["set", "add", "update"]
    current: object | None
    incoming: object | None
    user_edited: bool  # current value was edited by hand; UI should default it to unchecked


class FillPreview(BaseModel):
    resume_id: int
    resume_label: str
    mode: FillMode
    changes: list[FillChange]


class FillResult(BaseModel):
    applied: int
    view: ProfileOut  # the updated profile


# ── Resumes (Records / Vault) ──────────────────────────────────────────────────

ParseStatus = Literal["pending", "parsing", "parsed", "failed"]


class RegroupRequest(BaseModel):
    """Current (possibly unsaved) skill groups to re-sort by theme."""

    groups: list[SkillGroup]


class RegroupResult(BaseModel):
    """A proposal only; nothing is saved until the profile is saved."""

    groups: list[SkillGroup]


class ResumeOut(BaseModel):
    id: int
    label: str
    original_filename: str
    mime_type: str
    size_bytes: int
    parse_status: ParseStatus
    parse_error: str | None
    is_default: bool
    has_parsed_data: bool
    created_at: datetime
    updated_at: datetime


class ResumeDetail(ResumeOut):
    extracted_text: str | None
    parsed_data: Profile | None


class UploadError(BaseModel):
    filename: str
    detail: str


class UploadResult(BaseModel):
    items: list[ResumeOut]
    duplicates: list[int]  # ids of items that were already in the vault (same file)
    errors: list[UploadError]


class ResumePatch(BaseModel):
    label: str | None = None
    is_default: bool | None = None


# ── Memory cards (Records / Memory) ────────────────────────────────────────────

CardKind = Literal["summary", "experience", "project", "education", "skills", "certification", "custom"]


class CardOut(BaseModel):
    id: int
    kind: CardKind
    title: str
    text: str
    enabled: bool
    pinned: bool
    origin: Literal["generated", "user"]
    user_edited: bool
    source_ref: str | None
    position: int
    updated_at: datetime


class MemoryOut(BaseModel):
    cards: list[CardOut]
    built_at: datetime | None
    memory_stale: bool  # profile changed since the last build


class CardCreate(BaseModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)


class CardPatch(BaseModel):
    title: str | None = None
    text: str | None = None
    enabled: bool | None = None
    pinned: bool | None = None






# ── Insight / Desk and System / Switchboard ───────────────────────────────────


class ComponentStatus(BaseModel):
    ok: bool
    detail: str


class DeskOut(BaseModel):
    first_name: str | None
    completeness: int
    profile_confirmed: bool
    resumes: dict[str, int]  # total, parsed, parsing (incl. pending), failed
    cards: dict[str, int]  # total, enabled, embedded, failed
    memory_stale: bool
    status: dict[str, ComponentStatus]  # llm, embeddings, vectors, database, storage
    # found_today, relevant, fits_preset; last_scan_at / next_scan_at as ISO strings or None
    job_search: dict[str, int | str | None] = Field(default_factory=dict)


class StatusOut(BaseModel):
    app: str
    config_file: str
    config_loaded: bool
    llm: dict  # provider, model, reasoning_effort, temperature, max_output_tokens, tasks{}
    embedding: dict  # provider, model, dimensions, batch_size
    limits: dict  # max_upload_mb, allowed_types
    components: dict[str, ComponentStatus]  # llm, embeddings, vectors, database, storage


# ── Admin settings (System -> Admin settings = settings/config.toml) ──────────


class LLMTaskOverride(BaseModel):
    """[llm.tasks.<task>]: a value left empty inherits from [llm]."""

    temperature: float | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None


class ModelsSettings(BaseModel):
    llm: LLMParams = Field(default_factory=LLMParams)
    tasks: dict[str, LLMTaskOverride] = Field(default_factory=dict)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)


class AdminSettings(BaseModel):
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    sources: SourcesSettings = Field(default_factory=SourcesSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)


class AdminSettingsOut(BaseModel):
    settings: AdminSettings
    version: str  # changes whenever config.toml changes (send it back when saving)
    file: str
    file_error: str | None = None  # config.toml can't be read: last good values shown
    section_errors: dict[str, str] = Field(default_factory=dict)  # a section had invalid values: defaults shown
    env_overrides: dict[str, str] = Field(default_factory=dict)  # "llm.model" -> value from .env (env wins)


class AdminSettingsIn(BaseModel):
    settings: AdminSettings
    version: str  # the version the edits started from; 409 if config.toml changed meanwhile

