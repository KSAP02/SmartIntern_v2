"""'Fill in using resume' + edit tracking for the profile (Records / Me). Pure functions, no I/O.

Origins (`field_origins`) are tracked per path:
- scalar fields:      "personal.address.city"
- lists:              "skills.languages", "skills.groups" (groups merge item by item)
- list-section items: "work_history[<item id>]"
Values are "user" (edited by hand) or "resume:<id>" (filled from that resume).
"""
from __future__ import annotations

import re
from typing import Any

from backend.schemas import FillChange, Profile, new_id

SECTIONS = ("work_history", "education", "projects", "certifications")
SECTION_LABELS = {
    "work_history": "Work history",
    "education": "Education",
    "projects": "Projects",
    "certifications": "Certifications",
}
NEVER_FROM_RESUME = ("preferences",)
GROUPS_PATH = "skills.groups"


# ── helpers ────────────────────────────────────────────────────────────────────


def is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def flatten(d: dict, prefix: str = "", include_preferences: bool = True) -> dict[str, Any]:
    """Leaf paths -> values, skipping list sections (those are tracked per item)."""
    out: dict[str, Any] = {}
    for key, val in d.items():
        if not prefix and (key in SECTIONS or (not include_preferences and key in NEVER_FROM_RESUME)):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.update(flatten(val, path, include_preferences))
        else:
            out[path] = val
    return out


def set_path(d: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def item_key(section: str, item: dict) -> tuple | None:
    fields = {
        "work_history": ("company", "title"),
        "education": ("institution", "degree"),
        "projects": ("name",),
        "certifications": ("name", "issuer"),
    }[section]
    key = tuple(_norm(item.get(f)) for f in fields)
    return key if any(key) else None


def item_summary(section: str, item: dict) -> str:
    g = item.get
    if section == "work_history":
        return " at ".join(x for x in (g("title"), g("company")) if x) or "Untitled role"
    if section == "education":
        return ", ".join(x for x in (g("degree"), g("institution")) if x) or "Untitled education"
    if section == "projects":
        return g("name") or "Untitled project"
    return " · ".join(x for x in (g("name"), g("issuer")) if x) or "Untitled certification"


def path_label(path: str) -> str:
    parts = [p for p in path.split(".") if p != "personal"]
    return " › ".join(p.replace("_", " ").capitalize() for p in parts)


def _strip_id(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "id"}


def _skill_group_changes(cur_d: dict, inc_d: dict, origins: dict[str, str], mode: str) -> list[FillChange]:
    """Skill groups are one change at path "skills.groups".

    empty_only: keep the current groups and only add skills that aren't there yet (into the
    group with the same name, or a new group). Never removes or moves anything, so it is
    offered even after hand edits (flagged, so the UI leaves it unchecked by default).
    replace: take the resume's grouping as is.
    """
    cur = cur_d["skills"]["groups"]
    inc = [g for g in inc_d["skills"]["groups"] if g["items"]]
    if not inc:
        return []
    if mode == "replace":
        ids = {_norm(g["name"]): g["id"] for g in cur if g.get("name")}
        merged = [{**g, "id": ids.get(_norm(g["name"]), g["id"]), "items": list(g["items"])} for g in inc]
        if [(_norm(g["name"]), g["items"]) for g in merged] == [(_norm(g["name"]), g["items"]) for g in cur]:
            return []
    else:
        merged = [{**g, "items": list(g["items"])} for g in cur]
        present = {_norm(s) for g in cur for s in g["items"]}
        for g in inc:
            new = []
            for s in g["items"]:
                if _norm(s) not in present:
                    present.add(_norm(s))
                    new.append(s)
            if not new:
                continue
            target = next((m for m in merged if _norm(m.get("name")) == _norm(g.get("name"))), None)
            if target is not None:
                target["items"] += new
            else:
                merged.append({**g, "items": new})
        if merged == cur:
            return []
    return [
        FillChange(
            path=GROUPS_PATH,
            section="skills",
            label="Skills › Groups",
            action="set",
            current=cur,
            incoming=merged,
            user_edited=origins.get(GROUPS_PATH) == "user",
        )
    ]


# ── fill from resume ───────────────────────────────────────────────────────────


def compute_changes(
    current: Profile, incoming: Profile, origins: dict[str, str], mode: str
) -> list[FillChange]:
    """What applying `incoming` (a parsed resume) to `current` would change."""
    changes: list[FillChange] = []
    cur_d, inc_d = current.model_dump(), incoming.model_dump()

    # Scalars and string lists (preferences are never filled from a resume).
    cur_flat = flatten(cur_d, include_preferences=False)
    for path, inc in flatten(inc_d, include_preferences=False).items():
        if path == GROUPS_PATH:
            continue  # merged item by item below
        cur = cur_flat.get(path)
        if is_empty(inc) or cur == inc:
            continue
        user_edited = origins.get(path) == "user"
        if mode == "empty_only" and (not is_empty(cur) or user_edited):
            continue
        changes.append(
            FillChange(
                path=path,
                section=path.split(".")[0],
                label=path_label(path),
                action="set",
                current=cur,
                incoming=inc,
                user_edited=user_edited,
            )
        )

    changes.extend(_skill_group_changes(cur_d, inc_d, origins, mode))

    # List sections: match entries instead of duplicating them.
    for section in SECTIONS:
        existing = cur_d[section]
        used: set[str] = set()
        for n, inc_item in enumerate(inc_d[section]):
            key = item_key(section, inc_item)
            if key is None:
                continue
            match = next(
                (e for e in existing if e["id"] not in used and item_key(section, e) == key), None
            )
            if match is None:
                changes.append(
                    FillChange(
                        path=f"{section}[+{n}]",
                        section=section,
                        label=f"{SECTION_LABELS[section]} › {item_summary(section, inc_item)}",
                        action="add",
                        current=None,
                        incoming=_strip_id(inc_item),
                        user_edited=False,
                    )
                )
                continue
            used.add(match["id"])
            path = f"{section}[{match['id']}]"
            user_edited = origins.get(path) == "user"
            if mode == "empty_only" and user_edited:
                continue
            merged = dict(match)
            for k, v in inc_item.items():
                if k == "id" or is_empty(v):
                    continue
                if mode == "replace" or is_empty(merged.get(k)) or (k == "is_current" and not merged.get(k)):
                    merged[k] = v
            if merged == match:
                continue
            changes.append(
                FillChange(
                    path=path,
                    section=section,
                    label=f"{SECTION_LABELS[section]} › {item_summary(section, match)}",
                    action="update",
                    current=_strip_id(match),
                    incoming=_strip_id(merged),
                    user_edited=user_edited,
                )
            )
    return changes


def apply_changes(
    current: Profile,
    changes: list[FillChange],
    exclude: set[str],
    origins: dict[str, str],
    resume_id: int,
) -> tuple[Profile, dict[str, str], int]:
    d = current.model_dump()
    origins = dict(origins)
    tag = f"resume:{resume_id}"
    applied = 0
    for ch in changes:
        if ch.path in exclude:
            continue
        if ch.action == "set":
            set_path(d, ch.path, ch.incoming)
            origins[ch.path] = tag
        elif ch.action == "update":
            item_id = ch.path[len(ch.section) + 1 : -1]
            for item in d[ch.section]:
                if item["id"] == item_id:
                    item.update(ch.incoming)  # type: ignore[arg-type]
            origins[ch.path] = tag
        else:  # add
            item = {**ch.incoming, "id": new_id()}  # type: ignore[dict-item]
            d[ch.section].append(item)
            origins[f"{ch.section}[{item['id']}]"] = tag
        applied += 1
    return Profile.model_validate(d), origins, applied


# ── hand edits ─────────────────────────────────────────────────────────────────


def mark_user_edits(old: Profile, new: Profile, origins: dict[str, str]) -> dict[str, str]:
    """Every path whose value changed between `old` and `new` becomes origin 'user'."""
    origins = dict(origins)
    old_d, new_d = old.model_dump(), new.model_dump()
    old_flat = flatten(old_d)
    for path, val in flatten(new_d).items():
        if old_flat.get(path) != val:
            origins[path] = "user"
    for section in SECTIONS:
        old_items = {i["id"]: i for i in old_d[section]}
        new_ids = set()
        for item in new_d[section]:
            new_ids.add(item["id"])
            if old_items.get(item["id"]) != item:
                origins[f"{section}[{item['id']}]"] = "user"
        for gone in set(old_items) - new_ids:
            origins.pop(f"{section}[{gone}]", None)
    return origins


# ── completeness ───────────────────────────────────────────────────────────────


def completeness(p: Profile) -> int:
    checks = [
        p.personal.full_name,
        p.personal.email,
        p.personal.phone,
        p.personal.address.city,
        p.personal.address.country,
        p.personal.links.linkedin or p.personal.links.github or p.personal.links.portfolio,
        p.headline.current_title or p.headline.summary,
        p.skills.all_items(),
        p.work_history or p.projects,
        p.education,
        p.preferences.roles_of_interest,
        p.preferences.employment_types,
        p.preferences.preferred_locations or p.preferences.remote_preference,
        p.preferences.work_authorization,
    ]
    return round(100 * sum(1 for c in checks if not is_empty(c)) / len(checks))
