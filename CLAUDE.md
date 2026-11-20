# CLAUDE.md

Guidance for Claude Code when working in this repository.

Started from a blank-canvas template: Python backend, Node.js + TypeScript frontend, a few
seams that keep the project easy to change, everything in Docker. §1 describes this project.

---

## 1. This project

### Status by phase (updated 2026-11-20)

| Phase | State | Doc |
| --- | --- | --- |
| 1 Candidate foundation (Vault → My Profile → Memory → Desk / Switchboard) | ✅ done, verified with the user's real resume | `phase_1_candidate_foundation.md` |
| 2 Job Search (rules + embeddings, no LLM; title-vs-roles relevance gate; requirement ↔ memory evidence map; apply preset; Admin settings = config.toml) | 🔍 built; **user's UI review pending** before ✅ | `phase_2_job_discovery_and_understanding.md` (§14) |
| 2.5 JSearch-only, budget-planned search (query plan, request budget, scan picker, combined OR, decisions, per-request results, JSearch analytics) | 🔍 built, used live (22 requests by 2026-11-20) | `phase_2_5_jsearch_budgeted_search.md` (§17 + "Added" notes) |
| 2.6 Role contexts + search precision, then **simplified on 2026-11-20** (see "Changed 2026-11-20" notes in the doc): criteria only shape the scan, Scan now = roles / location / date / editable query + the exact request, years = Jobs-page filter, location highlighted not filtered, daily-limit switch | 🔍 built; **user says JSearch now works well enough** (2026-11-20) → mark 2 / 2.5 / 2.6 ✅ after a last UI look | `phase_2_6_role_contexts_and_search_precision.md` |
| 2.7 More sources for **jobs in India** (or remote and open to India; no international-only sources): A source refactor + Jooble, B company ATS boards + Companies list, C remote feeds (open-to-India only), D careers-page reader if needed | 📝 plan rewritten 2026-11-20: India scope, **form-first** (jobs the agent can apply to), one Scan button for all sources; D1–D4 decided, D5 research; next: build A0 | `phase_2_7_india_first_multi_source_discovery.md` |
| 3–7 Scoring / prepare applications / daily agent / automation / deploy | later | `README.md` in the phase folder |

Backend tests: 189 green (`docker compose run --rm --no-deps backend pytest backend/tests -q`).
Frontend: `cd frontend && npm run typecheck && npm run build`. Stack: `docker compose up --build -d`.
Nothing has been committed to git yet (all files untracked); commit only when the user asks.

### ▶ Next session: start here

1. **Phase 2.7 (India scope, form-first)**: decisions D1–D4 made 2026-11-20 (2.7 doc). Goal:
   jobs the future agent **can apply to by itself** (public ATS form, no login / account
   creation, posting still live); what it can't apply to becomes "needs you" for manual apply
   (Phases 4–6). Build order: **A0** shared source structure (registry, JSearch moved onto it
   unchanged, budget per source — `api_budget` counts only "jsearch" today —, per-source
   analytics, Scan now source ticks) + **apply route for every job** (`form:<ats>` /
   `account:<ats>` / `direct` / `aggregator:` / `platform:`; JSearch `apply_options` classified;
   "Agent can apply" filter); **A1** Companies list + Greenhouse / Lever / Ashby /
   SmartRecruiters boards (India scope + title pre-check); **A2** Claude drafts a starter
   company list, user approves each; research which ATSs need accounts (D5); **B1** Jooble (user
   is requesting `JOOBLE_API_KEY`); **C1** remote feeds, open-to-India only. Scope rule: a
   source must cover India; remote only when open to India; international-only sources out.
   **Design rule: copy the JSearch way for every source**: one Scan now button hits all
   enabled sources with the same shared options (roles, location, date, query); source-specific
   options only where needed (collapsed); same dry run / budget / request log / "why these
   results" / analytics per source (2.7 doc §3).
2. Mark Phases 2, 2.5 and 2.6 ✅ once the user has had a last look at Scan now, Jobs and Admin.
3. Later (2.6 "Later"): labelled set + evaluation panel, discard reasons, one rank score;
   Phase 3 = AI scoring with a written gap note per job.

### Current state (facts to rely on)

- **JSearch via OpenWeb Ninja** (`provider = "openwebninja"`: `api.openwebninja.com/jsearch/search`,
  header `x-api-key`; key `JSEARCH_API_KEY` in `.env`). Plan **Basic (free): 200 requests per
  billing period, 17th → 17th**; usage at OpenWeb Ninja `/usage?api_id=jsearch` (Admin → JSearch
  analytics → Check usage). **22 of 200 used by 2026-11-20.** Admin → JSearch: per month 200,
  reserve 10, per scan 1, **Limit requests per day = off** (user's choice; `daily_limit` 10 kept
  for when it's back on). On = at most `daily_limit` a day from today whatever was spent before;
  off = everything left. Admin shows used / left / days left / even pace / ahead or behind.
- Search criteria (user's, 2026-11-20): roles Backend Engineer, AI Engineer, LLM Engineer,
  Software Engineer, ML Engineer (each has a ready role context); locations "Bengaluru",
  "Hyderabad, India"; job types Full-time (sent as employment_types=FULLTIME; only-Internship
  would add "internship" to the query); auto-scan off. No experience filter is sent.
- Jobs (2026-11-20): 48 in Matches, 25 Not relevant, 3 applied, 5 discarded, 0 excluded.
- Data: only JSearch jobs (the pre-JSearch data was purged 2026-11-18; backup
  `/app/data/backups/app-before-purge-20261117-210231.db` in the appdata volume).
- Never read or print `.env`; check `GET /api/scout/search/settings/sources` → `configured`.
  After any `.env` change: `docker compose up -d --force-recreate backend` (plain `up -d` /
  `restart` keep the old values).

### What exists (reference)

- **Scan Jobs** (`/job-search`): **Scan now** = Roles (ticks; "one request for all chosen roles
  (OR)" when several), **Location** (one saved location per scan; "+ Add a location…" = country
  dropdown + optional state/city with suggestions, saved to Search criteria;
  `GET /api/scout/search/places`), **Date posted** (default past week), an editable **Query** per
  request (default "<role> [internship] in <place>"; "Default" resets) and **the exact request**
  under it (every parameter). `POST /api/scout/search/plan` (dry run) / `.../scan` take
  `{roles, combine, locations, date_posted, query_texts}`; a manual scan sends exactly what is
  shown. **Requests and what they found**: each request expands to its jobs (JSearch's order,
  outcome, where each job is now; `GET .../calls/{id}/jobs`), **Why these results** / **Next
  time** and each parameter in plain words (`GET .../calls/{id}/explain`,
  `services/request_explain.py`). Quota meter, funnel, per-day chart.
- **Search criteria only shape the scan; they never remove a job** (`criteria_reason` returns
  None; `job_search.CRITERIA_VERSION` re-checks jobs on start when that changes). Country =
  the location's country code; a state or city goes into the query text.
- **Automatic scans**: Search criteria → `auto_roles` ([] = all) + `auto_mode` rotate | each |
  combined; date window automatic (since the search last ran, floor `min_date_posted`).
- **Jobs** (`/job-search/jobs`): tabs Matches / Selected / Applied / Discarded / Not relevant
  (+ Excluded only while old excluded jobs remain); filters: search, job type, workplace, and
  on Matches **Experience asked** (`?max_years=`; jobs that don't state years stay; remembered
  in the browser). Rows show years asked and the **location against the place searched**
  (`job_facts.place_check`: in it = bold, elsewhere = amber "(not Karnataka)", area not stated,
  remote). Select / Discard / Mark applied / Undo, bulk, "Select these & discard the rest";
  **Move to matches** / **Not relevant** (`jobs.relevance_override`); **Add title to my roles**.
  Only discarded jobs are deleted (after `keep_discarded_days`); "expired" is a label.
- **Relevance v2**: title split into parts, level / place words dropped, role abbreviations
  expanded (ML, AI, LLM, SDE...); `role_threshold` 0.72 (measured on 17 real titles: relevant
  0.78–1.0, unrelated ≤ 0.67) + borderline rescue (title ≥ 0.60 and **role-context** match
  ≥ 0.50). Bump `job_search.TITLE_SCORING_VERSION` when changing `score_roles` (jobs are
  re-scored on start).
- **Role contexts (Phase 2.6)**: `role_contexts` table + `services/role_contexts.py` (task
  `role_context`): one market-style job description per role, written on role add (and on
  start for roles without one) from the enabled memory cards + up to 3 fetched postings of
  that role; editable (Memory ▾ Role contexts `/memory/roles`; API `/api/records/memory/roles`:
  list, ensure, PATCH, regenerate, test); never auto-rewritten after an edit; "memory
  changed" flag. Its vector lives in the row. `jobs.relevance` = job digest (title +
  Responsibilities / Qualifications; `DIGEST_VERSION` re-embeds on start) vs the context of
  `role_match`; Matches ranked by it. Measured 2026-11-19: kept jobs 0.53–0.67, unrelated
  near-miss titles 0.41–0.46. **Memory cards are not embedded any more**; evidence = exact
  skills (proving card by text) + years; gaps = skills asked you don't have.
- **Query building**: `search_plan.query_text` → `sources/jsearch.build_query` (strips
  `( ) " [ ]`); `query_wording` still exists in the schema (plain) but has no UI; the user edits
  the query per scan instead. `api_calls.variant` records the wording (`custom` when typed).
- **Search Settings**: Search criteria (roles, automatic-scan roles + mode, job types,
  workplace, locations with the country / state picker), Search plan (dry run of the next
  automatic scan, yields), Apply preset.
- **Admin** wing: Admin settings (= `settings/config.toml`: Models, Matching, JSearch budget +
  provider + **Run test (1 request)**, Schedule, Limits & retention), **JSearch analytics**
  (provider usage, app budget, per-day requests, yields, call log), Switchboard.
- Later (agent phase): an LLM reviews Matches vs Not relevant against the user's context and
  proposes moves; the agent applies only to `decision = "selected"` jobs and sets `applied`.

**Phase docs live in `MD_files/project_build_phases/`** (one file per phase, index in its
README): plan a phase there with the user before building it, update it while building,
mark it ✅ when its acceptance test passes. Original game plan: `MD_files/initial_draft_plan.md`
(Phase 1 detail). Reference spec: `MD_files/smart_job_application_agent_blueprint.md`;
follow it except where the game plan deliberately differs (table in plan §0).
Keep this section updated as decisions are made.

- **What it is:** SmartIntern, an agentic app that finds internships/jobs and applies to
  them for the user, based on their resume and profile. **Single user**, personalised
  experience; no login until OAuth is added later (Phase 7). Deploy planned later.
- **Resumes vs profile:** the user can store **unlimited resumes**; each is parsed into its
  own `parsed_data`. Uploading never changes the profile. The profile is filled only via
  the Profile page's **Fill in using resume** button (pick resume → preview → apply;
  "empty fields only" by default; hand-edited fields are never silently overwritten).
- **Core flow:** upload resume → parse into editable "context" → embed context → pull job
  descriptions (JDs) daily from JSearch (planned, budgeted queries) → score/match → (tailor)
  → apply → track progress.
- **Pages:** Desk `/` (dashboard), Vault `/vault` (resumes), My Profile `/profile` (profile +
  Fill in using resume), Memory ▾ Cards `/memory` (context cards, stored text) / Role contexts `/memory/roles` (one
  JD-style context per role, edit, regenerate, Test a job description); Utility →
  Job Search ▾: Scan Jobs `/job-search` (scan picker, requests and what they found, quota
  meter, funnel), Jobs
  `/job-search/jobs` (Fits / Other relevant, job panel with evidence map), Search Settings
  `/job-search/settings` (Search criteria, **Search plan** dry run, Apply preset); System:
  Admin wing: Admin settings `/admin` (= config.toml), JSearch analytics `/jsearch` (budget,
  provider usage, per-day requests and yield, searches, call log), Switchboard `/switchboard`
  (status). Later:
  Drafts, Outbox, Shifts, Pulse.
- **Job source: JSearch only** (since Phase 2.5; RapidAPI free tier, 200 requests/month,
  1 request = up to 10 jobs). What a scan sends = `services/search_plan.py`; whether it may =
  `services/api_budget.py`; HTTP = `services/sources/jsearch.py`. Former sources (Remotive,
  Arbeitnow, Remote OK, Greenhouse, Lever, Ashby, Adzuna) are documented in
  `MD_files/api_references/former_sources.md`.
- **Decisions made so far:**
  - Backend: FastAPI (Python), SQLite via SQLModel (single file in the `appdata` Docker
    volume; Postgres at deploy). Background work: FastAPI `BackgroundTasks`.
  - Frontend: Vite + React + TypeScript + Tailwind v4 + React Router + lucide-react,
    served by `frontend/src/server.ts` (SPA fallback + `/api` proxy).
  - **Look: minimal, not generic.** Warm "paper & ink" neutrals + one accent (clay), serif
    page titles, hairline borders, no gradients / drop shadows / hover lifts, sidebar shows
    only rooms that exist. The palette is defined once in `frontend/web/index.css` `@theme`
    (components use `zinc-*` = neutrals and `violet-*` = accent; their values are redefined
    there), so a colour change is a one-file edit. Light + dark mode.
  - File storage (resumes/PDFs/DOCX): go through a storage seam (`backend/storage.py`)
    — local disk/Docker volume in dev, S3-compatible object storage when deployed. DB
    stores metadata + storage key, never the file bytes.
  - **Vector DB: Milvus Lite** (`pymilvus`, local file). Behind a `backend/vectors.py`
    seam so it can move to Milvus server / Zilliz Cloud by URI. milvus-lite 3.x supports
    Python 3.10–3.13 only, so the backend image is pinned to `python:3.13-slim`
    (`python:3-slim` is 3.15). Docker is the standard way to run the backend.
  - **Embeddings: OpenAI** embeddings API, built in `backend/model.py` (same seam as the
    chat client). The user supplies the key in `.env`.
  - **Tuning lives in `settings/config.toml`** (models, temperature, reasoning effort,
    limits, weights, per-task overrides); secrets stay in `.env`. Read by `backend/config.py`.
    **System → Admin settings** (`/admin`, API `/api/system/admin`) edits it in place:
    Models, Matching, JSearch (on/off, request budget, pages policy, back-off, country,
    excluded publishers, call log), Schedule, Limits & retention. config.toml is the *only* store for those (not the DB): a save writes just the
    changed keys via `config.write_tuning` (`tomlkit`, comments and CRLF kept), and hand
    edits are picked up within ~30 s (re-read on file change; `settings_effects.sync_config`
    re-embeds / re-maps when models or matching changed). Search criteria + apply preset stay
    in the DB (`app_settings`, Search Settings page) with config.toml as their defaults.
  - **LLM: OpenAI `gpt-6-luna`** via the Responses API (structured outputs supported;
    `reasoning.effort` none|low|medium|high|xhigh|max; temperature support not documented,
    so only send it if accepted). Set in `settings/config.toml`.
  - **Skills are themed groups** (`profile.skills.groups`: name + items, plus spoken
    `languages`). Resume parsing groups them; My Profile → **Group by theme** (LLM task
    `skill_groups`) re-sorts them as an unsaved proposal; post-processing guarantees no skill
    is invented or lost. Memory makes **one card per group**. Old flat `skills`/`tools`
    profiles load as two groups.
  - **DB snapshot for notebooks:** the live `app.db` stays in the `appdata` volume (SQLite
    WAL + Milvus Lite are unreliable on a Windows bind mount). `backend/snapshots.py` keeps a
    read-only copy at `data_warehouse/snapshots/app.db` (SQLite backup API, debounced
    `[snapshot] debounce_seconds` after any committed write, and on startup; off when
    `SNAPSHOT_DIR` is blank). Milvus vectors are not snapshotted.
  - Deploy target: open.
- **Path naming ("your intern's office": wings and rooms).** API paths are
  `/api/<wing>/<room>/...`; backend routers live at `backend/api/<wing>/<room>.py`; page
  URLs are just `/<room>`. The wing names the kind of work and replaces a `/v1` prefix
  (no version prefix: single client, same repo). `/health` stays as the liveness probe.
  - `records`: storing information about the user: **vault** (resumes), **profile** (My Profile; renamed from "me"),
    **memory** (context cards), **answers** (form answer bank)
  - `scout`: finding jobs: **search** (Job Search: scans, jobs, settings, plan, calls),
    **compass** (requirement ↔ memory matching); "radar" was the original name for search
  - `intern`: agentic work: **shifts** (runs), **tasks**
  - `apply`: applications and form filling: **drafts** (review queue), **forms**
    (form-fill sessions), **outbox** (tracker)
  - `insight`: reporting: **desk** (dashboard), **pulse** (analytics)
  - `system` (sidebar label "Admin"): **switchboard** (status; `/api/system/status`), **admin**
    (Admin settings = config.toml; `/api/system/admin`), **jsearch** (analytics + provider
    usage; `/api/system/jsearch`, `POST /api/system/jsearch/usage`)
  New features get a room in the right wing; add a wing only for a new kind of work.
- **Things Claude should know:**
  - The app handles sensitive personal data (name, phone, address, work history). Never log
    it, never commit it, keep sample data fake.
  - "Context" = the editable, structured representation of the user's resume/profile that
    gets embedded and compared against JDs.
  - "JD" = job description.
  - External API notes (endpoints, fields, quotas, terms) live in `MD_files/api_references/`
    (e.g. `jsearch.md`); check there before re-researching an API.
  - Gotchas found while building: pymilvus reads an env var named `MILVUS_URI` itself and
    rejects file paths, so ours is `VECTOR_DB_URI`. `init_db()` adds new *nullable* columns
    to existing tables; anything else needs a deliberate migration. Scans, remaps and
    settings effects share `job_search.pipeline_lock`; anything new that rewrites job state
    must take it too. Milvus Lite allows ONE process: maintenance that touches vectors must run with the
    backend stopped (`docker compose stop backend`, then `docker compose run --rm --no-deps -e
    PYTHONPATH=/app backend python ...`), or inside the app. Every JSearch request goes through `api_budget.reserve_call` *before*
    it is sent (never call JSearch directly, never retry). Tests never call JSearch and never
    touch the real config.toml (conftest sets `CONFIG_FILE` to a temp copy). Editing files
    from Python on Windows: Git Bash heredocs turn `\\n` into real newlines; put scripts in a
    scratch file instead. A Milvus Lite collection reopens
    "released" after a restart and must be loaded (handled in `vectors.py`). SQLModel needs
    timezone-aware datetimes (`db.utcnow()`).

---

## 2. Working rules for Claude

- **Keep the setup check green.** After changing the backend, frontend, Dockerfiles or
  `docker-compose.yml`, `docker compose up --build` must still come up healthy and
  `GET /api/health` (through the frontend) must still return `"status": "ok"`.
- **Ask before adding** a dependency, a Compose service, a framework or a database.
  When one is added, add it to the manifest (`requirements.txt`, `package.json`) and
  the Dockerfile in the same change; remove it when it stops being used.
- **Never read, print or commit `.env` values.** When a new setting is needed, add the
  key to `.env.example` (with a safe default or blank) in the same change.
- **Keep `MD_files/database.md` current.** Any change to tables/columns in `backend/db.py`,
  to the JSON shapes in `backend/schemas.py` (`Profile`), to `meta` keys, or to where data
  is stored updates that file in the same change (schema, meaning, why the table exists).
- **Don't commit or push unless asked.**
- **Never make real JSearch / OpenWeb Ninja requests to test or verify anything** (no Scan now,
  no "Run test (1 request)", no calibration CLI, no `/usage` call, no curl). Each request costs
  the user's 200/month quota; the user runs live tests themselves. Verify with offline pytest
  (fake responses), the dry-run plan (`GET /api/scout/search/plan`) and the app's analytics
  (`GET /api/system/jsearch`), which never call the API. Then tell the user what to click.
- **Respect the seams** in §5 and §6 and the import direction in §7. If a change seems
  to need breaking one, stop and say so instead.
- **Prefer the simple version.** No multi-agent framework, vector DB, queue or frontend
  framework until the simple version has actually run out of room.

---

## 3. Directory layout

```
<project-root>/
├── CLAUDE.md                 # This file. Must be at the root to be loaded.
├── .claude/                  # Claude Code config: settings.json, hooks, skills
├── backend/                  # API layer, the single source of truth for logic
│   ├── main.py               # Entrypoint, wiring only: app, routes, error handlers
│   ├── config.py             # The ONLY module that reads env vars and settings/config.toml
│   ├── model.py              # The ONLY place model clients are built/called (§5)
│   ├── storage.py            # File storage seam (local now, S3 at deploy)
│   ├── vectors.py            # Vector store seam (Milvus Lite)
│   ├── db.py                 # SQLite engine, session, tables
│   ├── snapshots.py          # Host copy of app.db (data_warehouse/snapshots) after each write
│   ├── schemas.py            # Pydantic models shared by services + API (the API contract)
│   ├── services/             # Logic: vault, me, profile_fill, profile_extract, memory, ...
│   ├── api/<wing>/<room>.py  # Thin routers, e.g. api/records/vault.py
│   ├── agents/               # Agent / orchestration logic (from Phase 2+)
│   ├── tests/                # pytest; offline (model + Milvus stubbed, except test_vectors)
│   └── Dockerfile            # pinned python:3.13-slim (milvus-lite)
├── frontend/                 # Node.js + TypeScript; framework inside is open
│   ├── src/server.ts         # Serves dist/web (SPA fallback) and proxies /api/* to the backend
│   ├── web/                  # React app: pages/, components/, lib/ (api.ts, types.ts)
│   ├── vite.config.ts
│   ├── package.json
│   ├── tsconfig.json         # server; tsconfig.web.json = web app
│   └── Dockerfile
├── mcp-server/               # Optional thin pathway INTO the backend (§6)
│   ├── src/config.py         # Layer 0: how to reach the backend, nothing else
│   ├── src/tools.py          # Layer 1: each tool = one backend HTTP call
│   ├── src/server.py         # Layer 2: FastMCP instance + transport
│   ├── requirements.txt
│   └── .env / .env.example
├── settings/
│   └── config.toml           # Tuning knobs: models, temperature, reasoning effort, limits,
│                             # thresholds, weights. Committed; no secrets (§5, §7)
├── data_warehouse/           # Datasets, seed data, exports (contents gitignored)
├── experiments/              # Notebooks, prototypes, throwaway scripts
├── MD_files/                 # Idea docs, design notes, generated artifacts
│                             # database.md = tables, schemas, why each exists (keep current)
├── docker-compose.yml        # backend + frontend; add services only once they're real
├── requirements.txt          # Backend Python deps
├── .env / .env.example       # Root config for backend + frontend
├── .gitignore / .dockerignore
└── README.md
```

Empty folders keep a `.gitkeep`. Delete what the project genuinely doesn't need (no
agent tool-calling? delete `mcp-server/`) instead of leaving hollow placeholders.

---

## 4. Stack: fixed languages, open frameworks

| Layer | Default | Swap freely for |
| --- | --- | --- |
| Backend | **Python**, FastAPI + Uvicorn | The framework only. Python is fixed. |
| Frontend | **Node.js + TypeScript**, plain `node:http` server + static page | Vite/React, Next.js, etc. Node + TS is fixed. |
| Agent/LLM | `backend/agents/` calling `backend/model.py` | Any orchestration approach (the §5 rule still applies) |
| MCP server | `fastmcp` (standalone package), only if an agent needs to call in | — |
| Database | None until there's real state to persist | SQLite/DuckDB to start, Postgres if it grows |
| Packaging | `docker-compose.yml`: `backend` + `frontend` | Add services as they become real |

No versions are pinned. Docker images track `python:3-slim` and `node:lts-alpine`, and
packages resolve to latest stable at install time. Pin only when reproducibility
actually needs it.

---

## 5. The one rule that matters most: model/provider choice is config, not code

The project may call a hosted API, a local model, or several. Whatever it is, **build
model clients in exactly one module (`backend/model.py`)** and have everything else call
`get_client()`, never a provider SDK directly.

```
LLM_PROVIDER=<anthropic | openai | ollama | ...>
LLM_MODEL=<provider's model id>
LLM_API_KEY=<key, or blank for a local/keyless endpoint>
LLM_BASE_URL=<optional: any OpenAI-compatible endpoint>
```

- **In this project:** provider, model, temperature, reasoning effort and token limits live
  in `settings/config.toml` (`[llm]` defaults + `[llm.tasks.<task>]` per-task overrides,
  `[embedding]`). Only the **keys** (and a base URL if needed) stay in `.env`. Call sites
  ask for a task's settings by name (e.g. `resume_extract`), never hard-code a model.
- Swapping models or providers is a config edit (`config.toml`, or an env override), not a
  code change.
- The provider SDK is **not** in `requirements.txt` by default. Add the one you choose.
  Until then `/health` reports exactly what's missing.
- A missing key or package raises `ModelConfigError` with a message naming the fix;
  `main.py` turns it into a `503` with that message, never an opaque `500`.
- A framework (LangChain, LangGraph, an agent SDK, or plain SDK calls) is a separate
  choice. The rule is only: one seam, no model names scattered across call sites.
- Inside Docker, `localhost` is the container. To reach a model server on the host
  (e.g. Ollama), set `LLM_BASE_URL=http://host.docker.internal:11434/v1`.

---

## 6. The MCP server is a pathway, not a second backend

```
agent (MCP client) ──MCP──▶ mcp-server/src/tools.py ──HTTP──▶ backend API ──▶ db / model
```

- **Every tool is a thin wrapper:** take the arguments, call the backend's HTTP API,
  return the result. No business logic, database access or model calls in the MCP
  server. If REST and MCP need the same behavior, it lives once in `backend/`.
- Type hints and docstrings on each tool are the schema the agent sees. Write them for
  that reader.
- **Its own `.env` and `src/config.py`**, separate from the root. Only how to reach the
  backend and how to serve MCP. No `LLM_*` keys.
- **Errors are translated, not leaked:** tools raise `ToolError` with the backend's
  `detail`, or a "backend unreachable at …, start it with …" message.
- **Use `fastmcp`**, imported as `from fastmcp import FastMCP`. Not
  `mcp.server.fastmcp`, which is the low-level SDK's path and has changed between
  versions. `host`/`port` go to `mcp.run()`, not the constructor; `stdio` takes neither.
- Not in Docker Compose by default: an MCP client usually launches it over `stdio`.

---

## 7. Conventions

- **`backend/main.py` is wiring only.** Logic lives in `model.py`, `agents/` or wherever
  it naturally belongs.
- **Import direction is a rule.** In `backend/`: `config` ← `db` / `model` / `storage` /
  `vectors` / `schemas` ← `services` ← `api` ← `main` (services never import api);
  `config` ← `tools` ← `server` in `mcp-server/src/`. `tools.py` exports plain functions
  plus a `TOOLS` list, and only `server.py` touches the FastMCP object
  (`mcp.add_tool(fn)`). If two modules want each other, the shared thing belongs lower.
- **The browser only talks to the frontend server.** `frontend/src/server.ts` proxies
  `/api/*` to `BACKEND_URL` (`/api/health` → `/health`). No CORS, and the same code works
  locally (`http://localhost:8000`) and in Compose (`http://backend:8000`, set in
  `docker-compose.yml`). **Exception, deployed split (2026-11-20):** frontend on Vercel
  (`frontend/vercel.json`, static `dist/web`, build var `VITE_API_BASE_URL` = backend URL)
  calls the backend on Render directly; the backend allows those origins via `CORS_ORIGINS`
  (blank = no CORS). The Dockerfile binds `${PORT:-8000}` for Render.
- **Two `.env` files, two owners.** Root `.env` = backend + frontend. `mcp-server/.env` =
  MCP only. Both gitignored, both with a committed `.example`. Compose loads the root
  `.env` if it exists (`required: false`), so `docker compose up` works without one.
- **`.env` vs `settings/config.toml`.** `.env` = secrets + infrastructure (API keys, ports,
  URLs, paths); gitignored. `config.toml` = tunable behaviour (models, temperature,
  reasoning effort, limits, thresholds, weights); committed, never holds secrets.
  Precedence: env var > `config.toml` > code default. Only `backend/config.py` reads
  either. New tunable → add it to `config.toml` in the same change, following the file's
  style: a `# comment` on its own line directly above each key (never trailing after the
  value), a blank line between keys, and `# ====` banners between sections.
  The `settings/` folder is mounted **read-write** (Admin settings writes the file); edits
  apply without a restart. Tests use a temp copy (`CONFIG_FILE`), never the real file.
- **No inline comments in `.env` files.** Compose's `env_file` keeps a trailing `# ...`
  as part of the value. Comments go on their own line.
- **Optional subsystems are imported inside the function that needs them**, so the app
  still boots when one isn't installed or configured yet.
- **`frontend/tsconfig.json` lists `"types": ["node"]`.** Recent TypeScript versions no
  longer pick up `@types/node` automatically, and `tsc` fails on `node:*` imports
  without it.
- Keep manifests flat and honest: add a dependency when you use it, remove it when you
  stop.

---

## 8. Deliberately left open

Decide these when the project's shape is clear, and record the decision in §1:

- Agent orchestration approach
- Backend framework (FastAPI by default)
- Database (none until needed)
- Frontend framework (a static page is a legitimate UI)
- Version pins (none until reproducibility needs them)
- Testing, CI, linting (add when the project warrants it)

---

## 9. Commands

```bash
# Docker (default)
cp .env.example .env
docker compose up --build            # http://localhost:3000 (Switchboard shows status)
docker compose down                  # data stays in the 'appdata' volume
docker compose down -v               # ...and this DELETES all app data
docker compose restart backend       # not needed for config.toml edits any more (auto re-read)
docker compose run --rm --no-deps backend pytest backend/tests -q   # backend tests (offline)

# Local, without Docker
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash  (macOS/Linux: .venv/bin/activate)
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000   # Milvus Lite: Linux/macOS; Docker preferred
cd frontend && npm install && npm run dev        # Vite on :5173, proxies /api -> :8000

# MCP server (only if used; needs the backend up)
pip install -r mcp-server/requirements.txt
cd mcp-server && python src/server.py
```

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
```
