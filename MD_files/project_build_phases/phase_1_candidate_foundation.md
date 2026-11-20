# Phase 1: Candidate foundation ✅ completed

> **Status:** done (2026-11-17). Built, tested (23 backend tests) and verified live in
> Docker with `gpt-6-luna` + OpenAI embeddings and the user's real resume.
> Original detailed plan: `MD_files/initial_draft_plan.md` §1. Data reference:
> `MD_files/database.md`.

---

## 1. Goal

Everything on the **candidate side** that matching needs later: resumes in, a clean
structured profile, and an editable, embedded "context" (memory cards) that can be
compared with any job description.

## 2. What was built

| Page | URL | What it does |
| --- | --- | --- |
| Desk | `/` | Dashboard: greeting, profile completeness, resume/card counts, system status, next step |
| Vault | `/vault` | Unlimited resumes (PDF/DOCX): upload, dedupe, parse in background, rename, default, re-parse, delete, preview parsed data |
| My Profile | `/profile` | The one profile. **Fill in using resume** (pick → preview diff → apply; *empty fields only* by default), hand-edit tracking (`edited` / `from <resume>` badges), themed **skill groups** with drag-and-drop, confirm |
| Memory | `/memory` | Context cards built from the profile: edit, disable, pin, add custom, delete, rebuild; every card embedded; **Test against a JD** |
| Switchboard | `/switchboard` | Status of LLM, embeddings, vectors, database, storage + active tuning |

### Flow

```
upload ─▶ text extraction (local) ─▶ LLM extract (gpt-6-luna, strict schema) ─▶ resumes.parsed_data
                                                        │
                       My Profile ◀─ "Fill in using resume" (preview → apply, origins tracked)
                                                        │  deterministic, no LLM
                                                        ▼
                                  memory_cards (SQLite) ─▶ embeddings ─▶ Milvus Lite (vectors)
                                                        │
                                       Test against a JD: embed JD → nearest cards
```

### API (`/api/<wing>/<room>`)

| Room | Endpoints |
| --- | --- |
| `records/vault` | `POST` upload · `GET` list · `GET /{id}` · `GET /{id}/file` · `PATCH /{id}` · `POST /{id}/reparse` · `DELETE /{id}` |
| `records/profile` | `GET` · `PUT` · `POST /fill` (preview/apply) · `POST /confirm` · `POST /skills/regroup` |
| `records/memory` | `GET` · `POST` (custom card) · `PATCH/DELETE /{id}` · `POST /rebuild` · `POST /embed` · `POST /probe` |
| `insight/desk` | `GET` |
| `system/status` | `GET` (no network calls) |
| `/health` | liveness, through the proxy at `/api/health` |

### Storage

- **SQLite** `app.db` (tables `resumes`, `profile`, `memory_cards`, `meta`) in the `appdata`
  volume; read-only snapshot for notebooks at `data_warehouse/snapshots/app.db`.
- **Files**: resume files via the `storage.py` seam (local now, S3 later).
- **Milvus Lite** collection `memory_cards`: `{id, vector(1536)}`, COSINE.

### Where OpenAI is called

| Call | When | Model |
| --- | --- | --- |
| Resume extraction (incl. skill grouping) | upload / re-parse | `gpt-6-luna` (`resume_extract`) |
| Group by theme | button on My Profile, only shown when skills look unsorted | `gpt-6-luna` (`skill_groups`) |
| Embed cards | first fill, rebuild, card add/edit, startup catch-up | `text-embedding-3-small` |
| Embed a pasted JD | Test against a JD | `text-embedding-3-small` |

## 3. Changes made during the phase (vs the original plan)

- **Skills are themed groups** (`skills.groups[{id, name, items}]` + spoken `languages`)
  instead of flat `skills` / `tools` lists. Parsing groups them in the same LLM call; one
  memory card per group (replaced the arbitrary "15 skills per card" chunks). Old
  profiles load as two groups. Post-processing guarantees no skill is invented or lost.
- **Skill editor**: drag skills between groups, multi-select + "Move to", new group by drop.
- **"Me" renamed to "My Profile"**: page `/profile`, API `records/profile`, config
  `[records.profile]`, service `services/profile.py`.
- **UI redesign**: minimal "paper & ink" palette with one clay accent, serif titles,
  no gradients/shadows.
- **DB snapshot** for notebooks (`backend/snapshots.py`).
- Gotchas fixed: `VECTOR_DB_URI` (pymilvus hijacks `MILVUS_URI`), Milvus collection must be
  loaded after restart, SQLModel needs timezone-aware datetimes.

## 4. Exit criteria: met

- [x] `docker compose up --build` healthy; `/api/health` ok through the frontend
- [x] Upload → parse → fill profile → cards embedded → Test against a JD works with a real resume
- [x] Hand edits survive later fills; custom/edited cards survive rebuilds
- [x] Data persists across `docker compose down` / `up`
- [x] Test data removed from the live database (scan: 0 hits)

## 5. Carried into later phases

- Search preferences move to Job Search → Preferences in Phase 2. They're optional and
  default to *All*; the profile alone decides relevance.
- Write a **Summary** on My Profile (the resume has none; the Summary card is title-only).
- Not visually verified yet: Switchboard page and the modals.
