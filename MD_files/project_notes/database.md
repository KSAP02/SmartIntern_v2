# SmartIntern database reference

What is stored where, the schema of every table, and why each table exists.

**Keep this file in sync with the code.** The schema is defined only in `backend/db.py`
(SQLModel classes; `init_db()` runs `create_all` at startup, then adds any new *nullable*
columns missing from existing tables (`_add_missing_columns`); renames, type changes and NOT
NULL columns still need a deliberate migration). JSON column
shapes come from `backend/schemas.py`. Any change to either goes here in the same change.

_Last updated: 2026-11-23 (Postgres by `DATABASE_URL` with SQLite fallback; Supabase setup in §1)._

---

## 1. Where data lives

| Store | What it holds | Docker (standard) | Local run (no Docker) |
| --- | --- | --- | --- |
| **Postgres** (when `DATABASE_URL` is set, 2026-11-23) | All structured data: the same tables, same ids. Meant to be shared by the local and the deployed backend (Supabase) | the server in `DATABASE_URL` | same |
| **SQLite** `app.db` (fallback: `DATABASE_URL` blank) | All structured data: the tables below | `/app/data/app.db` in the `appdata` volume | `data_warehouse/appdata/app.db` |
| **Milvus Lite** `milvus.db` | Vectors only (no text): job digests (since Phase 2.6; memory-card and requirement-chunk collections were dropped) | `/app/data/milvus.db` in the `appdata` volume | `data_warehouse/appdata/milvus.db` |
| **File storage** | The uploaded resume files (PDF / DOCX) | `/app/data/resumes/<sha256>.<ext>` in the volume | `data_warehouse/appdata/resumes/` |
| **Snapshot** | Read-only copy of `app.db` for notebooks | `data_warehouse/snapshots/app.db` on the host | off unless `SNAPSHOT_DIR` is set |

- Paths come from `DATA_DIR` (Compose sets `/app/data`), `VECTOR_DB_URI` (blank = `milvus.db` in
  `DATA_DIR`) and `SNAPSHOT_DIR`.
- `docker compose down` keeps the volume. `docker compose down -v` **deletes all app data**.
- The DB runs in WAL mode, so `app.db-wal` / `app.db-shm` sit next to the live file. The
  snapshot is a single self-contained file (journal mode DELETE).
- `data_warehouse/` is gitignored: real personal data never reaches git.
- **Postgres (2026-11-23).** `db.postgres_url()` reads `DATABASE_URL` (`postgres://`,
  `postgresql://` → psycopg driver); blank or `sqlite` = the SQLite file. Session time zone UTC,
  no prepared statements (poolers work). On Postgres: no snapshot, no WAL, `_migrate_profiles`
  only fills `profile_id`. A row saved with an id we choose (profile 1) must be followed by
  `db.sync_id_counter(session, table)` (Postgres sequences don't move by themselves). Text
  can't hold the NUL character (the copy strips it). **First copy:** `python -m
  backend.services.db_copy` (SQLite → the Postgres in `DATABASE_URL`, same ids, sequences reset;
  `--replace` wipes the target first). Tests always use SQLite (conftest), unless run on purpose
  with `ALLOW_TEST_POSTGRES=1` against a throwaway database (its tables are dropped).
- **Milvus Lite stays per machine** (user, 2026-11-23): with a shared Postgres each backend has
  its own vectors. A job embedded on the other machine has no vector here, so re-scoring
  (`rescore_relevance`) skips it and it keeps its score.

### Reading it from a notebook

```python
import sqlite3, pandas as pd
con = sqlite3.connect("file:../data_warehouse/snapshots/app.db?mode=ro", uri=True)
pd.read_sql("select * from memory_cards", con)
con.close()   # on Windows an open handle blocks the next refresh
```

The snapshot refreshes about 2 s (`[snapshot] debounce_seconds`) after any committed write
to any table, and on every backend start. Edits to the copy are overwritten. Vectors are
not in it; open `milvus.db` with `pymilvus.MilvusClient(path)` if needed.

**On Postgres** there is no snapshot: read the database itself (read-only use only), e.g.
`pd.read_sql("select * from employers", sqlalchemy.create_engine(url))` with the
`DATABASE_URL` string, or Supabase → **Table Editor** / **SQL Editor**.

### Setting up Postgres (Supabase, chosen 2026-11-23)

**Why Supabase:** free plan with no compute-hour cap and a 500 MB database (ours: ~18 MB as
SQLite on 2026-11-23). Neon's free plan scales to zero after 5 min idle and gives 100
compute-hours a month; the 30-second timer and back-to-back finder runs keep a database awake,
so those hours would run out. Supabase's catch: a free project **pauses after about a week
without database activity** (restore it in the dashboard) and has **no automatic backups**.

**Which backend does what** (all in `.env`; the code on `main` is the same everywhere):

| `.env` key | Local backend | Deployed backend (Render) |
| --- | --- | --- |
| `DATABASE_URL` | the Supabase session pooler string | the same string |
| `AUTO_SCANS` | `false` | `true` (automatic scans start only here) |
| `COMPANY_FINDER` | `true` (the finder runs only here) | `false` |

**Steps (once):**
1. supabase.com → sign up → **New project**: name `smartintern`; a database password of
   letters and digits only (`@ # / :` break the connection string); region **Southeast Asia
   (Singapore)** (closest to India; pick Singapore for the Render backend too).
2. In the project: **Connect** (top bar) → **Session pooler** → copy the URI
   `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres`
   and put the password in. Not "Direct connection": it is IPv6 only, which Docker on Windows
   and Render don't have.
3. `.env`: `DATABASE_URL=<that URI>` (never commit it).
4. Copy the local data in (backend stopped, so the finder isn't writing):
   ```
   docker compose stop backend
   docker compose run --rm --no-deps backend python -m backend.services.db_copy
   docker compose up -d --force-recreate backend
   ```
   It prints each table with its row count, then "Done: N rows in M tables". It refuses a
   database that already has rows; `--replace` wipes it first.
5. Check: Admin → Switchboard → database = "Postgres at aws-0-…pooler.supabase.com:5432/postgres";
   Supabase → Table Editor lists the tables.
6. At deploy: Render's environment gets the same `DATABASE_URL`, `AUTO_SCANS=true`,
   `COMPANY_FINDER=false`.

**After the switch:** the local SQLite file stops changing (keep it as a backup; blank
`DATABASE_URL` goes back to it, without what was added to Postgres meanwhile); local pages are a
little slower (each query goes to Singapore); resume files are not in the database (file
storage moves online later); Milvus Lite stays per machine.

---

## 2. How the tables relate

```
resumes (many)  ──"Fill in using resume"──▶  profile (exactly one row)
                                                  │  deterministic build, no LLM
                                                  ▼
                                           memory_cards (many, stored text)
                                                  │  AI model, one call per role (Phase 2.6)
                                                  ▼
               criteria.roles ──role_key──▶  role_contexts (one per role; its vector in the row)
                                                  │  cosine
                                                  ▼
                                           jobs.relevance (job digest vs its role's context)

meta (key/value): settings the app must remember, e.g. which embedding model built the vectors
```

No foreign keys are declared (`PRAGMA foreign_keys=ON` is set, but no column references
another table). Links are by convention:

- `profile.last_filled_from_resume_id` → `resumes.id`
- `profile.field_origins` values like `"resume:3"` → `resumes.id = 3`
- `memory_cards.source_ref` → an item inside `profile.data` (e.g. `work_history:<item id>`)
- `role_contexts.role_key` = a role in Search criteria → Roles you want (lowercased); `built_from.card_ids` → `memory_cards.id`, `built_from.job_ids` → `jobs.id`
- `jobs.role_match` → the role whose context `jobs.relevance` was measured against

Deleting a resume therefore never changes the profile, by design.

---

## 3. Tables

### 3.1 `resumes`: the resume library (Vault page)

**Why it exists:** the user can keep any number of resumes (different roles or versions).
Each is parsed once into its own structured `parsed_data`. Uploading never changes the
profile: a resume is only a *source* the user can pull from on the My Profile page.

| Column | Type | Null | Default | Meaning |
| --- | --- | --- | --- | --- |
| `id` | INTEGER PK | no | auto | Resume id |
| `label` | TEXT | no | filename stem | Display name, editable |
| `original_filename` | TEXT | no | | Name of the uploaded file |
| `mime_type` | TEXT | no | | `application/pdf` or the DOCX type |
| `size_bytes` | INTEGER | no | | File size |
| `sha256` | TEXT | no | | Hash of the file. **Unique + indexed**: re-uploading the same file returns the existing row instead of a duplicate |
| `storage_key` | TEXT | no | | Where the file is in file storage (`resumes/<sha256>.<ext>`). The bytes are never stored in the DB |
| `parse_status` | TEXT | no | `pending` | `pending` → `parsing` → `parsed` or `failed`. Rows stuck in pending/parsing after a restart are queued again |
| `parse_error` | TEXT | yes | | Message shown when parsing failed (e.g. scanned PDF with too little text) |
| `extracted_text` | TEXT | yes | | Raw text pulled from the PDF/DOCX |
| `parsed_data` | JSON | yes | | Structured resume, shape = `Profile` (see §4), produced by LLM task `resume_extract` |
| `is_default` | BOOLEAN | no | false | Exactly one resume is the default. The first upload becomes default; deleting the default promotes the newest |
| `created_at` | DATETIME | no | now (UTC) | |
| `updated_at` | DATETIME | no | now (UTC) | |

Written by `backend/services/vault.py`.

### 3.2 `profile`: your profiles (My Profile page, `/profile`)

**Why it exists:** the single source of truth about the user (single-user app). It is
what Memory cards are built from and, later, what forms are filled from. It is filled
from a resume only via **Fill in using resume** (preview → apply), and hand edits are
tracked so they are never silently overwritten.

**Since Phase 2.8: one row per profile, one active** (meta `active_profile_id`, default 1;
`get_profile_row` returns the active one and creates profile 1 when there is none). Each profile
owns its memory cards, role contexts and roles; jobs and every other setting are shared.
The profile from before 2.8 is `id = 1`.

| Column | Type | Null | Default | Meaning |
| --- | --- | --- | --- | --- |
| `id` | INTEGER PK | no | | 1 = the first profile |
| `name` | TEXT | yes | | Shown in the switcher ("My profile" when empty) |
| `resume_id` | INTEGER | yes | | The resume it is built on (Fill in using resume starts from it); backfilled from `last_filled_from_resume_id` |
| `roles`, `auto_roles` | JSON list | yes | | Its "Roles you want" / automatic-scan roles. The active profile's live copy is in `app_settings` (criteria); it is saved here on every criteria save and on a switch, and the new profile's are swapped into the criteria (`profiles.activate`). None = not set yet (takes the criteria's on start) |
| `created_at` | DATETIME | yes | | |
| `data` | JSON | no | `{}` | The profile, shape = `Profile` (see §4) |
| `field_origins` | JSON | no | `{}` | Where each field's value came from. Key = path, value = `"user"` (edited by hand) or `"resume:<id>"` (filled from that resume). Paths: scalars `personal.address.city`; lists `skills.languages`, `skills.groups`; list items `work_history[<item id>]` |
| `last_filled_from_resume_id` | INTEGER | yes | | Resume used in the last fill |
| `confirmed_at` | DATETIME | yes | | When the user pressed confirm on the profile (Desk shows whether it's confirmed) |
| `updated_at` | DATETIME | yes | | Last time `data` changed |
| `memory_built_at` | DATETIME | yes | | Last time memory cards were rebuilt. If `updated_at > memory_built_at`, Memory is **stale** and the UI offers a rebuild |

Written by `backend/services/profile.py` (logic in `profile_fill.py`), API room
`/api/records/profile`, tuning in `[records.profile]`.

### 3.3 `memory_cards`: the "context" (Memory page)

**Phase 2.8:** `profile_id` (INTEGER, indexed): the profile the card belongs to; only the active
profile's cards are listed, used for evidence and written into role contexts. A card saved without
one gets the active profile (a `before_insert` hook in `db.py`); cards from before 2.8 → 1.

**Why it exists:** a profile is one big nested document; each card is one readable,
editable piece of it (one job, one project, one skill group...). **Since Phase 2.6 cards are
stored text only (not embedded).** They are (1) the material each role context is written
from and (2) the proof behind exact skill matches in the evidence map
(`job_requirements.best_card_id`). Job relevance is judged against role contexts (§3.6).

| Column | Type | Null | Default | Meaning |
| --- | --- | --- | --- | --- |
| `id` | INTEGER PK | no | auto | Card id |
| `kind` | TEXT | no | | `summary`, `experience`, `project`, `education`, `skills`, `certification`, `custom` |
| `title` | TEXT | no | | Card heading |
| `text` | TEXT | no | | Card body (max `records.memory.max_card_chars`) |
| `enabled` | BOOLEAN | no | true | Disabled cards are left out of role contexts and skill proof |
| `pinned` | BOOLEAN | no | false | Pinned by the user |
| `origin` | TEXT | no | `generated` | `generated` (built from the profile) or `user` (custom card) |
| `user_edited` | BOOLEAN | no | false | A generated card the user edited. Rebuilds keep it instead of regenerating it |
| `source_ref` | TEXT | yes | | Which part of the profile it came from: `headline`, `work_history:<id>`, `projects:<id>`, `education:<id>`, `skills:<group id>`, `skills:languages`, `certifications` |
| `embedding_status` | TEXT | no | `pending` | **Unused since Phase 2.6** (set to `none` once; cards aren't embedded). Kept: the column is NOT NULL |
| `embedding_error` | TEXT | yes | | Unused since Phase 2.6 |
| `embedded_at` | DATETIME | yes | | Unused since Phase 2.6 |
| `position` | INTEGER | no | 0 | Display order: generated cards first, then custom/edited ones |
| `created_at` | DATETIME | no | now (UTC) | |
| `updated_at` | DATETIME | no | now (UTC) | |

How cards are made (`backend/services/memory.py`):
1. **Build** (no LLM): one `summary` card, one card per work item / project / education
   item, one per skill group, one for languages, one for all certifications.
2. **Rebuild** after a profile change: regenerates untouched generated cards, deletes
   ones whose source is gone, keeps custom and user-edited cards.
3. **After any change** (`memory.after_change`): job evidence is re-checked; role contexts
   compare `memory.cards_version` with the version they were written from and show
   "memory changed" (rewritten only on Regenerate).

### 3.4 `meta`: small key/value store

**Why it exists:** a place for app-level facts that aren't user data and don't need their
own table.

| Column | Type | Null | Meaning |
| --- | --- | --- | --- |
| `key` | TEXT PK | no | Setting name |
| `value` | TEXT | no | Setting value |

Keys in use:

| Key | Value | Used for |
| --- | --- | --- |
| `active_profile_id` | profile id | The profile in use (Phase 2.8): cards, role contexts and roles follow it |
| `profile_switch_state` | JSON `{running, profile_id, step, error, finished_at}` | The background work after a switch (build cards, write role contexts, re-score jobs); My Profile shows it |
| `embedding_signature` | embedding model + dimensions + metric | On startup, if it differs from `settings/config.toml`, job vectors are dropped and re-embedded (vectors from different models can't be compared); role contexts re-embed themselves when used (`role_contexts.embedding_signature`) |
| `job_digest_version` | `job_search.DIGEST_VERSION` | The job text that is embedded changed (Phase 2.6: title + Responsibilities / Qualifications): stored job vectors are rebuilt on start |
| `criteria_version` | `job_search.CRITERIA_VERSION` | What Search criteria exclude changed: every job is re-checked on start (2026-11-20: v2 location no longer excludes, v3 stale reasons refreshed, v4 criteria never exclude) |
| `apply_route_version` | `job_search.APPLY_ROUTE_VERSION` | The apply-route rules (`services/apply_route.py`) changed: every job's route is re-derived on start (Phase 2.7 A0) |
| `seed_companies_version` | hash of `services/seed_companies.csv` | The company finder's seed list changed: missing seed companies are added to `company_leads` on start (Phase 2.7 E) |
| `company_finder_state` | JSON `{running, trigger, run_id, started_at, finished_at, message, error, last_run}` | Admin settings → Company finder (Phase 2.7 E; on Scan Jobs until 2026-11-23). `finished_at` + `error` pace the automatic runs (`auto_tick`) |
| `crawl_index_state` | JSON `{collection, size, hosts: {surt_prefix: {blocks: [[file, offset, length]], next, done}}, done_collections, recent, recent_date, leads, last_error}` | Where the finder is in the Common Crawl index files, so each run continues (Phase 2.7 E; index files instead of the CDX server since 2026-11-23; an old-format state is restarted) |
| `yc_list_date` | `YYYY-MM-DD` | When the YC list of companies in India was last read (read at most weekly; 2026-11-23) |
| `boards_roles_key` | hash of your roles' title words | Your roles changed: every quiet board (`employers.next_read_at`) is due again (Phase 2.7 E) |
| `starter_companies_version` | hash of the starter list (`services/starter_companies.py`) | The system-managed company list changed: missing starter companies are added (switched on) on start; companies the system switched off stay off |
| `phase26_dropped_collections` | ISO datetime | The unused `memory_cards` / `job_requirements` Milvus collections were dropped (once) |
| `config_applied` | JSON `{matching, embedding}` | What the job pipeline was last re-scored / embedded with. `settings_effects.sync_config` compares it with config.toml (on save, every 30 s, on start) and re-maps or re-embeds when they differ, so hand edits and edits made while the app was down take effect too |
| `jsearch_provider_usage` | JSON `{checked_at, fetched_at, data, error}` | OpenWeb Ninja's `/usage` answer (raw), shown on Admin → JSearch analytics; its "remaining" caps the request budget (minus our calls since) for 7 days |
| `jsearch_blocked_until` | JSON ISO datetime | After an HTTP 429 from JSearch: no requests until then (next UTC day). JSearch usage itself is counted from `api_calls` |
| `source_toggles_in_toml` | `"1"` | The one-off move of saved sources / schedule / limits / matching (and `job_sources.enabled`) from the DB into config.toml has run |

### 3.5 Job Search tables (Phase 2, Utility → Job Search)

Written by `backend/services/job_search.py` (scan, dedupe, criteria, relevance, prune),
`compass.py` (requirements + evidence) and `search_settings.py`. API wing `scout`
(`/api/scout/search`, `/api/scout/compass`). **No LLM**: facts come from the source + rules,
matching from embeddings.

```
search_queries ─ plan ─▶ api_calls (every JSearch request) ─▶ jobs.api_call_id
job_sources (health) ─ scan ─▶ fetch_runs (per scan)  scans (per scan, totals)   app_settings (criteria, preset)
                 │
                 ▼
          job_ledger (1 tiny row per listing ever seen, never pruned) ──job_id──▶ jobs (full, pruned)
                                                                                   │
                                                              job_requirements (chunks + evidence, deleted with the job)
```

| Table | Why it exists | Key columns |
| --- | --- | --- |
| `app_settings` | Search Settings saved from the UI; `config.toml [scout.search.*]` holds the defaults (saved value wins) | `key` (section: **criteria, preset** only; sources / schedule / limits / matching live in config.toml, edited from Admin settings), `value` JSON (shape = `backend/job_schemas.py`), `updated_at` |
| `job_sources` | Health of the source (only `jsearch` since Phase 2.5) | `name` PK, `enabled` (**unused**: on/off is `[scout.search.sources] enabled` in config.toml; kept because the column is NOT NULL), `last_success_at`, `last_error_at`, `last_error` |
| `search_queries` | **The JSearch plan**: one row per *Roles you want* × place, plus one per **combined OR search** you ran (role set × place), with its yield, so the planner spends the request budget where it pays off (Phase 2.5) | `key` (hash of role + place + country; `or:`-prefixed for combined), `role` ("A OR B" for combined), `roles` JSON (combined: its roles; [] = single), `place`, `country`, `active` (in the current criteria), `enabled` (you can pause one), `interval_days` (1, back-off 3 / 7), `last_run_at`, `last_success_at`, `runs`, `results`, `new_jobs`, `relevant_jobs`, `zero_streak`, `recent` JSON (last 5 runs `[requests, new, relevant]`) |
| `api_calls` | **Every JSearch request**; the quota is counted from here. Written with status `sending` *before* the request goes out, so a crash can't hide a spent request | `at`, `api`, `query_id`, `scan_id`, `purpose` (scan / calibration), `params` JSON (never the key; `params.query` = the exact text sent), `page`, `status` (sending / ok / error), `http_status`, `results`, `new_jobs`, `relevant_jobs`, `error`, **`variant`** (Phase 2.6: the wording, e.g. `titles · exp off`; null before 2.6 = plain, read from params) |
| `api_call_jobs` | **What each JSearch request returned**, job by job, in JSearch's order, and what happened to each; shown on Scan Jobs → Requests (Phase 2.5) | `call_id` (api_calls.id), `position` (1 = first result), `source_job_id`, `job_id` (the job it became / matched; null if too old), `title`, `company_name`, `location_text`, `outcome` (new / updated / unchanged / duplicate / already_seen / too_old), `created_at`. Kept after a job is discarded. Requests made before the table existed were back-filled from `jobs.api_call_id` (new jobs only) |
| `companies` | **Removed in Phase 2.5** (JSearch covers company career sites). The table may still exist in older DB files; nothing reads it | |
| `scans` | One row per scan: phase + totals, for the Overview | `id`, `trigger` (manual/auto), `phase`, `totals` JSON, `error`, `started_at`, `finished_at` |
| `fetch_runs` | One row per source per scan: the per-day history | `scan_id`, `scan_date`, `source`, `company` (since Phase 2.5: "N requests"), `status`, `fetched`, `new`, `updated`, `duplicates`, `already_seen`, `error` (or why no request was spent) |
| `job_ledger` | **Dedupe memory.** Every listing ever seen, kept after the full job is pruned or applied to, so it's never re-imported or re-processed; also per-date analytics | `source` + `source_job_id`, `dedupe_key` (company+title+location), `canonical_url`, `job_id` (null once pruned), `first_seen_date`, `outcome` (active / excluded / not_relevant / expired / hidden / other / applied), `is_duplicate`, `category`, `workplace_type`, `country`, `relevance` |
| `jobs` | Full data for jobs still in play (pruned per Limits & retention) | identity: `seen_on` JSON (every source listing it), `dedupe_key`, `canonical_url`, `content_hash`; posting: `title`, `company_name`, `location_text`, `description_text` (plain text), `job_url`, `apply_url`, `source_published_at`; facts (null = unknown): `category`, `workplace_type`, `country_codes`, `remote_regions`, `compensation_type`, `salary_*`, `seniority`, `min_years_experience`, `internship_duration`, `visa_sponsorship`, `field_sources` JSON (`source` / `rules`); pipeline: `pipeline_status` (new → excluded / not_relevant / relevant → mapped; failed), `status_reason`, `status` (active / expired), `relevance` (since Phase 2.6: job digest vs the role context of `role_match`, cosine; null when that role has no context) + `relevance_card_id` (unused since 2.6, always null), `role_score` + `role_match` (job title vs your best-matching "Roles you want", cosine; null when no roles are set; this decides relevance when roles are set), `coverage` JSON, `mapped_memory_version`, `hidden`, `repost_of`, `raw_payload` (dropped after N days), `api_call_id` (the JSearch request that found it; credits relevance back to its search), `highlights` JSON (JSearch `job_highlights`: Qualifications / Responsibilities lists, used as the requirements; kept), **`relevance_override`** (your call: `relevant` = keep in Matches whatever the title check / criteria say, `not_relevant`, null = checks decide), **`decision`** (null = undecided | `selected` = for the agent to apply | `discarded` | `applied`) + `decided_at`. `hidden` / `hidden_at` are legacy (moved to `decision = "discarded"` on start-up). **Retention:** only discarded jobs are deleted (after `limits.keep_discarded_days`); `status = expired` is a label by posting age (`limits.expire_after_days`), nothing is deleted for age or for being excluded / not relevant; **`apply_route`** (Phase 2.7: `form:<ats>` = public ATS form, no account, the agent's target / `direct` / `account:<ats>` / `aggregator:<name>` / `platform:<name>`; the best of all its apply links, by host) + **`apply_route_url`** (that link) |
| `job_requirements` | The "job memory" **and** the middle layer: one row per chunk of the description with its evidence | `job_id`, `section`, `importance` (must / nice / unknown), `text`, `skills` JSON, `status` (met / partial / missing / unknown = not judged), `method` (exact_skill / numeric / none; `vector` only on rows from before Phase 2.6), `best_card_id` (the card naming the skill), `best_score`, `evidence` JSON (empty since 2.6), `embedding_status` (unused since 2.6) |

`requirement_matches` from the plan was folded into `job_requirements` (always 1:1).
`coverage` = `{must_total, must_met, must_partial, must_missing, nice_total, nice_met, fit}`,
fit = (met + ½·partial) / judged must-haves (met + partial + missing; "unknown" doesn't count).
The apply preset is evaluated when jobs are listed; nothing about it is stored.

**Relevance gate (④, Phase 2.6).** A job is relevant when `role_score ≥ matching.role_threshold`
(0.72), or when `role_score ≥ borderline_role_threshold` (0.60) and `relevance` (job vs that
role's context) `≥ borderline_context_threshold`. No roles set: everything passes. Your
`relevance_override` beats both. Matches are ranked by `relevance`, then `role_score`.

### 3.6 `role_contexts`: one job-description-style context per role (Phase 2.6)

**Why it exists:** comparing a job posting with resume-shaped cards gave weak, flat scores.
Each role in *Roles you want* gets a context written by the AI model (task `role_context`)
**in the form of a market job description** for that role, at your level and in your market,
leaning towards the work your cards show. A posting is compared with that posting-like text.
Written when the role is added (and on start for roles without one); editable on Memory ▾
Role contexts; never rewritten automatically after you edit it.

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `role` | TEXT | The role as written |
| `profile_id` | INTEGER, indexed | Phase 2.8: the profile it belongs to (before 2.8 → 1; unset → the active one) |
| `role_key` | TEXT, indexed | Lowercased, spaces collapsed (matches `jobs.role_match`); **unique per profile** (`uq_role_contexts_profile_role` on `profile_id, role_key`; the old unique index on `role_key` alone is replaced once on start) |
| `status` | TEXT | `pending` / `ready` / `failed` |
| `error` | TEXT | Why writing failed |
| `summary` | TEXT | 2–3 sentences |
| `responsibilities`, `requirements`, `nice_to_have` | JSON lists | The posting's parts (a full market description: may include skills you don't have) |
| `search_titles` | JSON list | Market titles for this role (role first); word queries with the `titles` wording. Not embedded |
| `keywords` | JSON list | Distinctive skills; the first is added with `titles_keywords`. Not embedded |
| `built_from` | JSON | `card_ids`, `job_ids` (up to 3 fetched postings used as examples), `memory_version`, `model` |
| `edited` | BOOLEAN | You changed it after it was written |
| `embedding` | JSON list | The vector of `role + summary + parts` (`role_contexts.context_text`) |
| `embedding_signature` | TEXT | Embedding model + dims it was made with (re-embedded when it changes) |
| `generated_at`, `updated_at` | DATETIME | |

Contexts of roles you remove are kept (re-adding the role reuses it).

---

## 4. Shape of the JSON columns (`profile.data`, `resumes.parsed_data`)

Both use the `Profile` model in `backend/schemas.py`. Items in lists carry a stable `id`
(used by `field_origins` and `memory_cards.source_ref`). Example values are fake.

```text
Profile
├── personal: full_name, email, phone,
│             address { city, state, postal_code, country },
│             links { linkedin, github, portfolio, other[] }
├── headline: current_title, summary, years_experience
├── skills: groups[ { id, name, items[] } ], languages[]
├── work_history[ { id, company, title, location, start, end, is_current, bullets[] } ]
├── education[ { id, institution, degree, field, start, end, grade } ]
├── projects[ { id, name, description, tech[], url } ]
├── certifications[ { id, name, issuer, date } ]
└── preferences: roles_of_interest[], preferred_locations[],
                 remote_preference (any|remote|hybrid|onsite), employment_types[],
                 minimum_salary, salary_currency, notice_period,
                 work_authorization, earliest_start_date
```

In `parsed_data`, `preferences` is always empty: preferences are never taken from a
resume (the user sets them on the My Profile page). Old profiles with flat `skills` / `tools` lists load as two groups.

---

## 5. Milvus Lite collections

Not SQLite tables, listed here for completeness. Each holds `{id INT64 PK, vector FLOAT_VECTOR(1536)}`
(`text-embedding-3-small`), metric from Search Settings → Matching (COSINE by default; the seam
converts every metric to a 0–1 similarity).

| Collection | id = | Vector of |
| --- | --- | --- |
| `jobs` | `jobs.id` | job digest (since Phase 2.6): title + JSearch Responsibilities / Qualifications, else the description; up to 2,000 chars |

`memory_cards` and `job_requirements` collections existed until Phase 2.6 and are dropped once
on start (`meta.phase26_dropped_collections`). Role-context vectors live in
`role_contexts.embedding` (a handful of rows; no collection needed).

`meta.embedding_signature` = model + dimensions + metric. If it changes, job vectors are
rebuilt and re-embedded.

Settings: `[embedding]` and `[vectors]` in `settings/config.toml`. Code: `backend/vectors.py`.

---

## 6. Planned (not built yet)

From the game plan; add the real schema here when each phase is built.

| Phase | Likely tables | Room |
| --- | --- | --- |
| 3 | match scores | scout / compass |
| 4 | drafts (tailored resumes, cover letters) | apply / drafts |
| 5 | shifts (agent runs) | intern / shifts |
| 6 | answers (form answer bank), form sessions | records / answers, apply / forms |
| 6+ | applications tracker | apply / outbox |

### Phase 2.7 A0 notes (2026-11-20)

- `api_calls.api` = the source's registry name (`jsearch` so far); the request budget
  (`api_budget`) counts each metered source separately; a 429 pause is per source
  (`jsearch_blocked_until`, `<name>_blocked_until` in `meta`).
- `jobs.apply_route` / `apply_route_url`: set when a job is stored, upgraded when a better link is
  seen later (another source or a repeat); re-derived on start when the rules change.

### Phase 2.7 A1 (2026-11-20): `employers` + company-board requests

**`employers`** — a company whose public job board is read on every scan (Search Settings →
Companies). Why: company boards give live postings with a form the agent can fill (Phase 2.7
form-first).

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `name` | TEXT | shown name |
| `kind` | TEXT | `greenhouse` / `lever` / `ashby` / `smartrecruiters` / `workable` / `recruitee` (= the source name) |
| `board` | TEXT | board id in that ATS (`postman`; Greenhouse EU = `eu:<token>`); unique with `kind` (enforced in code) |
| `careers_url` | TEXT | the link you pasted |
| `enabled` | BOOLEAN | read on scans; set by the system (starter companies on; a board answering "not found" is switched off) |
| `origin` | TEXT | `you` / `starter` (drafted by Claude, `services/starter_companies.py`) / `discovered` (found in a stored job's apply link, Phase 2.7 A3) |
| `note` | TEXT | e.g. India cities seen |
| `added_at`, `last_checked_at` | DATETIME | |
| `last_error` | TEXT | last read failure (e.g. HTTP 404) |
| `last_found`, `last_in_scope`, `last_kept` | INTEGER | postings on the board / in India or remote-India / matching your roles, at the last check or scan |
| `found_via_job_id` | INTEGER (nullable, A3) | discovered companies: the job whose link pointed to the board (no FK; the job may be deleted later) |
| `empty_scans` | INTEGER (nullable, A3) | discovered companies: scans in a row whose board had no job in India; NULL = not read yet. First read empty, or `drop_after_empty_scans` in a row -> `enabled = false` with a `note` |

- **`api_calls`** for company boards: `api` = the ATS name, `params` = `{query: "<Company> ·
  <ATS> board", board, company}`, `results` = postings the board listed, `new_jobs`; new nullable
  **`skipped_scope`** (outside India / not remote-India) and **`skipped_title`** (title matching
  none of your roles). Not counted in any request budget.
- Jobs from a board: `seen_on[].source` = the ATS, `source_job_id` = `<board>:<posting id>`; no
  age limit on ingest (a board lists only open postings); a stored job its board no longer lists
  is marked `status = "expired"`; age-based expiry skips board jobs.

### Phase 2.7 C1 (2026-11-22): remote feeds

No new table. Feed requests are `api_calls` rows with `api` = `himalayas` / `remotejobs` /
`remotive`, `params` = `{query: "<role> · <Feed> (remote, open to India)", feed, q?}`,
`results` = jobs the feed returned, `skipped_scope` = not open to India, `skipped_title` = title
matching none of your roles. Jobs from a feed: `seen_on[].source` = the feed, `source_job_id` =
the feed's id (Himalayas: its job page URL), `job_url` = the feed's own job page (its terms ask
for that link back). Feed jobs age out like JSearch jobs (not closed by absence). Remotive's
"at most every 8 h" is counted from its last `ok` row in `api_calls`.

### Phase 2.7 E (2026-11-22): company finder, Indian boards, read schedule

**`company_leads`** — **why it exists:** companies the finder may check, kept with the verdict so
none is checked twice for nothing. Written by `services/company_finder.py` and
`services/crawl_index.py`; shown on Admin settings → Company finder (run by hand).

| Column | Type | Null | Meaning |
| --- | --- | --- | --- |
| `id` | INTEGER PK | no | |
| `name` | TEXT | no | Company name (crawl leads: from the board id) |
| `domain` | TEXT | yes | Website, e.g. razorpay.com (seed leads) |
| `careers_url` | TEXT | yes | Careers page if known |
| `origin` | TEXT, indexed | no | `seed` (seed list) \| `yc` (YC open-data list, companies based in India; 2026-11-23) \| `crawl` (Common Crawl index) |
| `category` | TEXT | yes | Seed list: unicorn \| startup \| product \| global; YC leads: startup. Sets who is checked first (`company_finder.rank`) |
| `kind`, `board` | TEXT, indexed | yes | The board once known (crawl leads arrive with it) |
| `how` | TEXT | yes | How the board was found: careers_page \| guessed (name tried on each system) \| crawl |
| `status` | TEXT, indexed | no | pending \| kept \| no_india_jobs \| no_board \| error |
| `total_jobs`, `india_jobs`, `matching_jobs` | INTEGER | yes | The board when checked: postings, in India (or open to India), title matching your roles |
| `employer_id` | INTEGER | yes | The `employers` row it became (kept) |
| `note` | TEXT | yes | Plain-words verdict |
| `attempts` | INTEGER | no | Checks so far |
| `added_at`, `checked_at` | DATETIME | no / yes | |
| `next_check_at` | DATETIME, indexed | yes | Not due before (no India jobs: +30 days; no board: +90); None = due |
| `run_id` | INTEGER, indexed | yes | The `finder_runs` row that last checked it (2026-11-23) |

**`finder_runs`** (2026-11-23) — **why it exists:** the company finder runs by itself, one run
after another while companies are waiting (`company_finder.auto_tick`, from the 30 s timer in
`scheduler.py`); each run is recorded so Admin → **Company finder** (`/company-finder`, API
`GET /api/scout/search/finder/dashboard`) can show what every run did. Counts are saved every 10
companies, so a restart keeps them (`status = interrupted`). An idle look that found nothing to
do leaves no row.

| Column | Type | Null | Meaning |
| --- | --- | --- | --- |
| `id` | INTEGER PK | no | Run number |
| `trigger` | TEXT | no | auto \| manual (Run now) |
| `status` | TEXT, indexed | no | running \| done \| failed \| interrupted |
| `started_at`, `finished_at` | DATETIME | no / yes | |
| `message`, `error` | TEXT | yes | Progress / last words; the error of a failed run |
| `new_leads` | JSON | no | Companies added to the waiting list: `{"seed", "yc", "crawl"}` |
| `crawl` | JSON | no | `{collections: [crawls read], blocks, error?}` |
| `planned` | INTEGER | no | Companies the run set out to check |
| `counts` | JSON | no | `{checked, kept, no_india_jobs, no_board, error}` |
| `by_kind`, `by_origin` | JSON | no | Per hiring system / per origin: `{checked, kept, india_jobs, matching_jobs}` (`none` = no board found) |
| `india_jobs`, `matching_jobs` | INTEGER | no | On the boards it kept: jobs in India (or open to India), titles matching your roles |
| `kept` | JSON | no | The companies it kept: `[{name, kind, origin, how, total_jobs, india_jobs, matching_jobs}]` |

A kept lead becomes an `employers` row with `origin = "discovered"` (note "Found by the company
finder through ..."), so the A3 rules apply to it (switched off when its India jobs go away).

**`employers`** gains `next_read_at` (a board with no job matching your roles at its last read is
read again only from then: `quiet_board_days`, 7; None = every scan; all reset when your roles
change) and `etag` / `last_modified` (reserved for change detection; unused while 304 support is
unverified).

New board kinds in `employers.kind` / `api_calls.api`: `keka`, `darwinbox`, `zohorecruit`
(board id for Zoho Recruit = subdomain + "." + data-centre TLD, e.g. `moneyforward.in`). Their jobs'
apply route is `account:<kind>` (CAPTCHA / OTP: needs you). Scan totals gain `boards_quiet`.
