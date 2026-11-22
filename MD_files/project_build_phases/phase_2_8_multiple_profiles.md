# Phase 2.8: Multiple profiles (one active at a time)

**State:** 🔍 built 2026-11-23 (approved the same day); the user tests on localhost. See
"Build notes" at the end.

## What the user asked (2026-11-23)

"a user can have multiple profiles based on multiple resumes if they want to in the My Profile
page, and the memory cards and the role contexts will change based on the profile they selected
as active."

Decisions (user, 2026-11-23):
- **Roles follow the profile.** Each profile has its own "Roles you want" (and automatic-scan
  roles) and its own role contexts. Locations, job types, workplace, date window, the JSearch
  budget, company boards and feeds stay shared.
- **One shared job pool for now.** Switching profile re-scores the jobs already found
  (Matches / Not relevant, evidence map) against the active profile; Selected / Applied /
  Discarded marks stay. Whether jobs should split by profile is decided later.
- **A new profile starts from a resume or as a copy** of the current one, then is edited.

## How it works for the user

- **My Profile** gets a profile bar at the top: the active profile's name, a dropdown to
  switch, **New profile** (from a resume in the Vault, or copy the current one), **Rename**,
  **Delete** (not the last one, not the active one). The page below is the same form as now,
  editing the active profile.
- Each profile names its resume (the one it was made from; changeable). **Fill in using
  resume** defaults to it.
- **Switching** makes the chosen profile active everywhere:
  - Memory ▾ Cards shows that profile's cards (built from it the first time).
  - Memory ▾ Role contexts shows its roles' contexts (written the first time a role is used by
    that profile: one LLM call per role, as today).
  - Search Settings → Search criteria shows its roles; Scan now offers its roles.
  - Jobs are re-scored in the background (no JSearch / board requests; a few seconds; a
    "Re-scoring jobs for <profile>…" note on Jobs while it runs).
- The sidebar / Desk shows the active profile's name so it's clear which one is in use.
- Today's profile becomes the first profile, named after its resume (or "My profile"); nothing
  is lost.

## How it is built

### Data (`backend/db.py`, `MD_files/database.md`)

| Change | Detail |
| --- | --- |
| `profile` table → one row per profile | `id` (1 = today's profile), new columns `name`, `resume_id` (its resume, nullable), `roles` (JSON list), `auto_roles` (JSON list), `created_at`. Existing columns unchanged. |
| Active profile | meta key `active_profile_id` (default 1). `get_profile_row(session)` returns the active one, so existing callers keep working. |
| `memory_cards.profile_id` | Nullable column, backfilled to 1. Every card read / rebuild filters by the active profile. |
| `role_contexts.profile_id` | Backfilled to 1. The unique index on `role_key` becomes unique on (`profile_id`, `role_key`): **a deliberate one-time migration** (SQLite can't change a unique constraint in place: copy the table, recreate it, copy back; guarded by a meta key). Two profiles can then each have their own "Backend Engineer" context. |
| Roles | `search_criteria.roles` / `auto_roles` move into the profile row (copied once into profile 1). `search_settings.get(session, "criteria")` overlays them from the active profile, and saving criteria writes them back to it, so the ~25 places that read `criteria.roles` don't change. |

Jobs, job requirements, scans, requests, employers: unchanged (shared pool).

### Backend

- `services/profiles.py` (new): `list`, `active`, `create(from_resume | copy_of)`, `rename`,
  `delete`, `activate(id)`.
- `activate` = set `active_profile_id`, then in the background (under `pipeline_lock`):
  build the profile's memory cards if it has none → ensure role contexts for its roles →
  `job_search.rescore_relevance(roles_changed=True)` → `compass.remap_all()` (evidence map vs
  its cards). Boards' read schedule resets on its own (`boards_roles_key` changes with roles).
- `memory.py`, `role_contexts.py`, `compass.py`: filter by the active profile.
- API (room `records/profile`): `GET /profiles`, `POST /profiles` (`{name, resume_id?,
  copy_of?}`), `PATCH /profiles/{id}` (name, resume), `DELETE /profiles/{id}`,
  `POST /profiles/{id}/activate` (202; status in `GET /profiles`). Existing `/profile`
  endpoints keep meaning "the active profile".
- A scan and a switch never run at the same time (`pipeline_lock`).

### Frontend

- `Profile.tsx`: profile bar (switch, New profile dialog: from a resume / copy, rename,
  delete).
- Active profile name in the sidebar header / Desk.
- Memory, Role contexts, Search criteria, Scan now: no layout change; they reload after a
  switch.

### Tests (offline)

- Migration: one existing profile + cards + role contexts + criteria roles → profile 1 owns
  them all, unchanged behaviour.
- Two profiles: same role name gets two contexts; switching changes cards, roles, role
  contexts and `criteria.roles`; jobs re-scored, decisions kept.
- Create from a resume / copy; can't delete the last or active profile.

## Costs and limits

- Switching costs nothing external, except **writing role contexts the first time** a profile
  uses a role (OpenAI, one call per role, as when adding a role today).
- One active profile at a time; scans use the active profile's roles.
- Jobs aren't split by profile (later decision); a job's "applied" etc. is shared.

## Build steps

| Step | What | Check |
| --- | --- | --- |
| 1 | Data + migration + `profiles.py` + API, cards / role contexts / roles scoped to the active profile | pytest |
| 2 | Switch flow (background re-score + remap) | pytest |
| 3 | My Profile profile bar, active name shown, pages reload on switch | typecheck + build, click through on localhost |
| 4 | Docs: `database.md`, CLAUDE.md, this doc | — |
| — | **User:** create a second profile from another resume, switch, check Memory / Role contexts / Jobs | localhost; no push until the user says |

## Build notes (2026-11-23)

- **Roles: swapped, not overlaid.** The active profile's roles stay in the search criteria
  (`app_settings`), as before, so nothing that reads `criteria.roles` changed. Each profile keeps
  a copy (`profile.roles` / `auto_roles`): saved on every criteria save, and on a switch the old
  profile's are saved and the new one's swapped in (`search_settings.swap_in_roles`).
- **Migration:** on start, cards and role contexts without a profile → 1; the unique index on
  `role_contexts.role_key` is replaced by one on (`profile_id`, `role_key`) (a unique *index*,
  so no table copy was needed). Verified on the user's DB: 17 cards and 6 role contexts kept
  under profile 1. Profiles get their roles from the criteria once, and their resume from the
  last fill.
- Cards and role contexts saved without a profile get the active one (`before_insert` hook in
  `db.py`), so every existing code path stays correct.
- `services/profiles.py`: create (from a parsed resume: every field filled via the existing fill
  logic; or a copy), rename / built-on resume, delete (not the active one or the last; deletes
  its cards and role contexts), activate. The switch follow-up runs in a thread: build the
  profile's cards the first time → write missing role contexts → re-score jobs
  (`rescore_relevance(roles_changed=True)` + evidence re-map, under `pipeline_lock`). Each step
  stops if you switched again. Restart mid-switch → finished on start.
- API (room `records/profile`): `GET/POST /profiles`, `PATCH/DELETE /profiles/{id}`,
  `POST /profiles/{id}/activate` (202). `GET /records/profile` gains `profile_id`,
  `profile_name`, `resume_id`.
- UI: My Profile → profile pills (click to switch; warns about unsaved edits), **New profile**
  (from a resume / copy, optional name, "Switch to it now"), **Manage** (rename, built-on
  resume, delete), a status line (built on / cards / roles, or the switch progress). Sidebar
  shows the active profile's name. Fill in using resume defaults to the profile's resume.
- Tests: `test_profiles_28.py` (3: migration, switch with cards / role contexts / roles / jobs,
  create-copy-rename-delete rules). Backend 227 green.
- Not tried live: creating and switching on the user's data (a switch writes role contexts
  with real model calls) — the user's first switch is the check.
