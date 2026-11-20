"""System -> Admin settings: the tuning in settings/config.toml, read and written in place.

Covers models ([llm], [llm.tasks.*], [embedding]) and Job Search's sources, schedule, limits
and matching ([scout.search.*]). config.toml is the only store: saving writes only the keys
that changed (comments kept), and a hand edit of the file shows up here on the next read.
What a change sets in motion (re-embedding, re-mapping) runs in `settings_effects.sync_config`.
"""
from __future__ import annotations

import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError

from backend.config import (
    EmbeddingConfig,
    LLMParams,
    env_overrides,
    get_settings,
    tuning_error,
    tuning_raw,
    tuning_stamp,
    write_tuning,
)
from backend.job_schemas import LimitsSettings, MatchingSettings, ScheduleSettings, SourcesSettings
from backend.schemas import AdminSettings, AdminSettingsOut, LLMTaskOverride, ModelsSettings

SEARCH = ("scout", "search")
_SEARCH_SECTIONS: dict[str, type[BaseModel]] = {
    "matching": MatchingSettings,
    "sources": SourcesSettings,
    "schedule": ScheduleSettings,
    "limits": LimitsSettings,
}


class StaleVersion(Exception):
    """config.toml changed since the client loaded it."""


class InvalidSetting(ValueError):
    pass


def _table(raw: dict, *keys: str) -> dict:
    for k in keys:
        raw = raw.get(k) if isinstance(raw.get(k), dict) else {}
    return dict(raw)


def _section(errors: dict[str, str], name: str, model: type[BaseModel], data: dict) -> Any:
    try:
        return model(**data)
    except ValidationError as e:
        errors[name] = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())[:300]
        return model()


def read() -> tuple[AdminSettings, dict[str, str]]:
    """Current values from config.toml (code defaults for keys the file leaves out)."""
    raw, errors = tuning_raw(), {}
    llm = _table(raw, "llm")
    tasks = llm.pop("tasks", {}) if isinstance(llm.get("tasks"), dict) else {}
    models = ModelsSettings(
        llm=_section(errors, "models", LLMParams, llm),
        tasks={name: _section(errors, "models", LLMTaskOverride, {k: v for k, v in (t or {}).items()
                                                                  if k in LLMTaskOverride.model_fields})
               for name, t in tasks.items()},
        embedding=_section(errors, "models", EmbeddingConfig, _table(raw, "embedding")),
    )
    sections = {n: _section(errors, n, m, _table(raw, *SEARCH, n)) for n, m in _SEARCH_SECTIONS.items()}
    return AdminSettings(models=models, **sections), errors


def get() -> AdminSettingsOut:
    settings, errors = read()
    return AdminSettingsOut(
        settings=settings, version=tuning_stamp(), file=str(get_settings().config_file),
        file_error=tuning_error(), section_errors=errors, env_overrides=env_overrides(),
    )


def _paths(s: AdminSettings) -> dict[tuple[str, ...], Any]:
    """Every value as a config.toml key path. None = key absent (inherit / unset)."""
    out: dict[tuple[str, ...], Any] = {}
    for k, v in s.models.llm.model_dump().items():
        out[("llm", k)] = v
    for task, o in s.models.tasks.items():
        for k, v in o.model_dump().items():
            out[("llm", "tasks", task, k)] = v
    for k, v in s.models.embedding.model_dump().items():
        out[("embedding", k)] = v
    for name in _SEARCH_SECTIONS:
        for k, v in getattr(s, name).model_dump().items():
            if isinstance(v, dict):
                for sub, sv in v.items():
                    out[(*SEARCH, name, k, sub)] = sv
            else:
                out[(*SEARCH, name, k)] = v
    return out


def changes(old: AdminSettings, new: AdminSettings) -> dict[tuple[str, ...], Any]:
    o, n = _paths(old), _paths(new)
    return {k: n.get(k) for k in o.keys() | n.keys() if o.get(k) != n.get(k)}


def _validate(s: AdminSettings) -> None:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s.schedule.time):
        raise InvalidSetting("Schedule time must be HH:MM (24-hour), e.g. 07:00.")
    try:
        ZoneInfo(s.schedule.timezone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise InvalidSetting(f"Unknown time zone '{s.schedule.timezone}'. Use an IANA name like Asia/Kolkata.") from e
    m = s.matching
    for name in ("role_threshold", "borderline_role_threshold", "borderline_context_threshold"):
        if not 0 <= getattr(m, name) <= 1:
            raise InvalidSetting(f"Matching {name.replace('_', ' ')} must be between 0 and 1.")
    if m.borderline_role_threshold > m.role_threshold:
        raise InvalidSetting("The borderline title threshold must not be above the role threshold.")
    if not s.models.llm.model.strip() or not s.models.embedding.model.strip():
        raise InvalidSetting("Model names can't be empty.")
    if s.models.embedding.dimensions < 1 or s.models.embedding.batch_size < 1:
        raise InvalidSetting("Embedding dimensions and batch size must be positive.")
    j = s.sources
    if min(j.monthly_limit, j.reserve, j.max_per_scan, j.daily_limit) < 0:
        raise InvalidSetting("JSearch limits can't be negative.")
    if j.daily_limit_on and j.daily_limit < 1:
        raise InvalidSetting("Requests per day must be at least 1 while the daily limit is on.")
    if j.daily_limit > j.monthly_limit:
        raise InvalidSetting("Requests per day can't be more than requests per month.")
    if j.reserve > j.monthly_limit:
        raise InvalidSetting("The JSearch reserve can't be larger than the monthly limit.")
    if len(j.api_country.strip()) != 2:
        raise InvalidSetting("Search API country must be a 2-letter ISO code, e.g. IN.")


def save(new: AdminSettings, version: str) -> tuple[AdminSettingsOut, set[str]]:
    """Write the keys that changed. Returns (fresh state, names of the areas that changed)."""
    if version != tuning_stamp():
        raise StaleVersion("config.toml was changed elsewhere since you opened this page. Reload to see the new values.")
    _validate(new)
    old, _ = read()
    diff = changes(old, new)
    if diff:
        write_tuning(diff)
    areas = {("models" if k[0] in ("llm", "embedding") else k[2]) for k in diff}
    return get(), areas


def set_autoscan(enabled: bool) -> ScheduleSettings:
    """The Overview's Auto-scan switch: one key in config.toml."""
    write_tuning({(*SEARCH, "schedule", "autoscan"): enabled})
    return read()[0].schedule
