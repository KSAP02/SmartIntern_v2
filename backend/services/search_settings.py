"""Job Search settings.

- criteria, preset: saved in the DB (`app_settings`) from Job Search -> Search Settings;
  `[scout.search.<section>]` in settings/config.toml holds their defaults. Since Phase 2.8 the
  criteria's `roles` / `auto_roles` are the active profile's: each profile keeps its own copy
  (`profile.roles`), kept in step on save and swapped in on a switch (`profiles.activate`).
  Precedence: saved setting > config.toml > code default (the pydantic model).
- sources, schedule, limits, matching: live in config.toml only (System -> Admin settings
  writes the file; hand edits apply within seconds).
"""
from __future__ import annotations

from pydantic import BaseModel
from sqlmodel import Session

import json
import logging

from sqlmodel import select

from backend import vectors
from backend.config import ConfigWriteError, get_tuning, write_tuning
from backend.db import AppSetting, get_meta, new_session, set_meta, utcnow
from backend.job_schemas import (
    ADMIN_SECTIONS,
    ApplyPreset,
    LimitsSettings,
    MatchingSettings,
    ScheduleSettings,
    SearchCriteria,
    SearchSettings,
    SettingsPatch,
    SourcesSettings,
)

SECTIONS: dict[str, type[BaseModel]] = {
    "criteria": SearchCriteria,
    "preset": ApplyPreset,
    "sources": SourcesSettings,
    "schedule": ScheduleSettings,
    "limits": LimitsSettings,
    "matching": MatchingSettings,
}


def _toml(section: str) -> dict:
    return dict(((get_tuning().scout or {}).get("search") or {}).get(section) or {})


def default(section: str) -> BaseModel:
    return SECTIONS[section](**_toml(section))


log = logging.getLogger(__name__)


def get(session: Session, section: str) -> BaseModel:
    base = _toml(section)
    if section not in ADMIN_SECTIONS:
        row = session.get(AppSetting, section)
        if row and row.value:
            if "experience" in row.value and "experience_years" not in row.value:
                base.pop("experience_years", None)  # saved before 2026-11-19: convert the old choice
            base.update(row.value)
    try:
        return SECTIONS[section](**base)
    except Exception:  # noqa: BLE001 - a stale saved value must never break the app
        return default(section)


def _save_roles(session: Session, roles: list[str], auto_roles: list[str]) -> None:
    """Keep the active profile's copy of its roles in step (Phase 2.8)."""
    from backend.db import get_profile_row

    row = get_profile_row(session)
    row.roles, row.auto_roles = list(roles), list(auto_roles)
    session.add(row)


def swap_in_roles(session: Session, roles: list[str], auto_roles: list[str]) -> None:
    """A profile switch: its roles become the search criteria's (not committed)."""
    crit = get(session, "criteria").model_copy(update={"roles": list(roles), "auto_roles": list(auto_roles)})
    _save(session, "criteria", crit)


def get_all(session: Session) -> SearchSettings:
    return SearchSettings(**{name: get(session, name) for name in SECTIONS})


def load(section: str):
    """For background work without a request session."""
    with new_session() as s:
        return get(s, section)


def _save(session: Session, section: str, value: BaseModel) -> None:
    row = session.get(AppSetting, section) or AppSetting(key=section)
    row.value = value.model_dump(mode="json")
    row.updated_at = utcnow()
    session.add(row)


def patch(session: Session, body: SettingsPatch) -> tuple[SearchSettings, set[str]]:
    """Replace the given sections. Returns (all settings, names of sections that changed)."""
    changed: set[str] = set()
    for name in ("criteria", "preset"):
        new = getattr(body, name)
        if new is None:
            continue
        if new.model_dump() != get(session, name).model_dump():
            changed.add(name)
        _save(session, name, new)
        if name == "criteria":
            _save_roles(session, new.roles, new.auto_roles)
    session.commit()
    return get_all(session), changed


def reset(session: Session, section: str) -> SearchSettings:
    row = session.get(AppSetting, section)
    if row:
        session.delete(row)
    if section == "criteria":
        d = default(section)
        _save_roles(session, d.roles, d.auto_roles)
    session.commit()
    return get_all(session)


def move_db_settings_to_toml() -> None:
    """One-off (startup): sources / schedule / limits / matching used to be saved in the DB and
    source on/off in `job_sources.enabled`. Write any such values into config.toml, then drop
    them from the DB, so config.toml is their only home. Skipped (kept in DB) if the file
    can't be written."""
    with new_session() as s:
        rows = [r for r in s.exec(select(AppSetting)).all() if r.key in ADMIN_SECTIONS]
        moved_sources = get_meta(s, "source_toggles_in_toml") == "1"
        changes: dict[tuple[str, ...], object] = {}
        for row in rows:
            current = _toml(row.key)
            for k, v in (row.value or {}).items():
                if k in SECTIONS[row.key].model_fields and current.get(k) != v and v is not None:
                    changes[("scout", "search", row.key, k)] = v
        if not rows and moved_sources:
            return
        try:
            if changes:
                write_tuning(changes)
        except ConfigWriteError as e:
            log.warning("settings stay in the DB for now: %s", e)
            return
        for row in rows:
            s.delete(row)
        set_meta(s, "source_toggles_in_toml", "1")
        s.commit()
        if changes:
            log.info("moved %d saved setting(s) into config.toml: %s", len(changes),
                     json.dumps(sorted(".".join(k[2:]) for k in changes)))


def currency_rates() -> dict[str, float]:
    """Value of 1 unit of each currency in USD ([scout.search.currency])."""
    rates = {"USD": 1.0}
    rates.update({k.upper(): float(v) for k, v in ((get_tuning().scout or {}).get("search") or {}).get("currency", {}).items()})
    return rates


def apply_metric() -> str:
    """Point the vector seam at the saved metric. Returns it."""
    m = load("matching").metric
    vectors.set_metric(m)
    return m
