# SmartIntern: Game Plan (v2)

> Replaces the first brainstorm draft. Aligned with
> `MD_files/smart_job_application_agent_blueprint.md` (the "blueprint"), adjusted to the
> decisions below. **Phase 1 is detailed; later phases are sketched** and get detailed when
> we reach them. Items marked **[confirm]** need a yes from you before we build them;
> **[verify]** = check against current official docs while building.

> **Phase docs have moved to `MD_files/project_build_phases/`** (Phase 1 record, Phase 2
> plan and onwards). This file stays as the original game plan; §2 below is superseded by
> those files.

> **Status (2026-11-16): Phase 1 built.** Backend + frontend run in Docker; 17 backend
> tests pass; verified live with gpt-6-luna and OpenAI embeddings. Remaining: you run the
> §1.8 acceptance test with your real resume. Implementation notes vs this plan: the
> vector-store URI setting is `VECTOR_DB_URI` (not `MILVUS_URI`), and config is read with
> `tomllib` + Pydantic models instead of pydantic-settings' TOML source (same precedence).

---

## 0. Decisions

| Topic | Decision | Status |
| --- | --- | --- |
| Users | **Single user**, personalised experience (your name, your data everywhere). No login in Phase 1; **OAuth added later** (Phase 7) | Decided |
| Resumes | **Unlimited resumes** stored; each parsed independently; one marked *default* | Decided |
| Backend | Python + FastAPI (existing scaffold) | Decided |
| Frontend | Node + TypeScript, modern/minimal, multi-page | Decided |
| Vector DB | **Milvus Lite** (`pymilvus`, a local file, same API as Milvus server / Zilliz Cloud) | Decided |
| Embeddings | **OpenAI** embeddings API, key in `.env` | Decided |
| LLM (resume → profile extraction) | OpenAI **`gpt-6-luna`** via the Responses API, structured output (JSON schema), through `backend/model.py`; set in `settings/config.toml` | Decided |
| Relational DB | **SQLite** (one file) for Phase 1; Postgres when we deploy/multi-user | Decided |
| File storage | `backend/storage.py` seam: local disk now, S3-compatible when deployed | Decided (from first draft) |
| Frontend framework | **Vite + React + TypeScript + Tailwind + React Router**; `server.ts` keeps serving + proxying | Decided |
| Background work | FastAPI `BackgroundTasks` in Phase 1; in-process scheduler later; Celery/Redis only if needed | Proposed |
| Tuning config | `settings/config.toml`: models, temperature, reasoning effort, limits, weights, per-task overrides; secrets stay in `.env` | Decided (draft file created) |

### Where we deliberately differ from the blueprint

| Blueprint | This plan | Why |
| --- | --- | --- |
| Phase 1 = job discovery | Phase 1 = **candidate side** (resume → profile → context) | Matching needs a solid context first; it's what you asked for |
| PostgreSQL + Alembic | SQLite, simple `create_all` | Single user, minimal; move to Postgres at deploy |
| pgvector | Milvus Lite | Your choice; moves to Milvus server/Zilliz by changing a URI |
| Next.js | Vite + React SPA | Keeps the existing `server.ts` proxy seam; no SSR needed |
| Celery + Redis + Beat | BackgroundTasks → APScheduler | No extra services until the simple version runs out of room |
| Multi-user, auth | Single user, no auth until OAuth in Phase 7 | Personal service first |

Everything else from the blueprint is kept as the target design: clear REST resource paths
(grouped by wing, see 1.5, instead of `/v1`), the profile schema, "never invent facts", untrusted-input handling, source
adapters, the `NormalizedJob` schema, application modes (Prepare only by default), the
status/event model, and analytics derived from stored events.

---

## 1. Phase 1: Candidate foundation (detailed)

### 1.1 Goal and exit criteria

A real multi-page web app, running in Docker, where you can:

1. **Upload as many resumes as you like** (PDF/DOCX). Each file is stored, its text
   extracted, and an LLM turns it into structured data saved *with that resume*.
2. On the **Me** page (profile), click **Fill in using resume**, pick one of your resumes,
   review what will change, and apply. Then edit anything (personal details, address,
   links, work history, education, projects, skills, preferences).
3. See the **Memory** page (context) built from the profile as **editable cards**: edit, toggle,
   pin, add, delete. Every card is embedded with OpenAI and stored in Milvus Lite;
   editing a card re-embeds it.
4. **Test the context**: paste any job description and see which cards match best, with
   similarity scores. This proves embeddings and Milvus work end to end.
5. See the **Desk** (dashboard) with Phase 1 numbers and system status.
6. Restart Docker and **everything is still there**.

**Done when:** `docker compose up --build` is healthy, the setup check is green, and the
flow upload → profile → context → test-JD works in the browser with a real resume.

### 1.2 User flow

```
Upload resume(s) ──▶ store file ──▶ extract text ──▶ LLM → structured data (JSON schema),
                                                         saved on that resume record
                                                              │
   Profile page ── [Fill in using resume ▾ pick resume] ──▶ preview changes ──▶ apply
                                  │  (then edit freely)
                                  │  "Build context" (automatic the first time the profile is filled)
                                  ▼
             Context cards (SQLite = source of truth) ──▶ embed (OpenAI) ──▶ Milvus Lite
                                  │
                         "Test against a JD" ──▶ embed JD ──▶ vector search ──▶ ranked cards
```

Parsing runs as a background task. The upload returns `202` at once with
`parse_status=pending`, and the UI polls until `parsed` / `failed`. Parsing takes 5–30 s
and should never block a request (blueprint §10).

### 1.3 Profile rules (from the blueprint §6)

- Extraction uses a **strict JSON schema**. Anything not in the resume stays `null`/empty.
  **Nothing is inferred.**
- **Preferences are never taken from the resume.** You set them (roles, locations,
  remote, employment types incl. *internship*, min salary, notice period, work authorization).
- **Uploading never changes the profile by itself.** The profile changes only when you click
  **Fill in using resume** on the Profile page:
  1. Pick a resume (dropdown, defaults to your *default* resume; only parsed ones selectable).
  2. Choose a mode: **Fill empty fields only** (default) or **Replace everything**.
  3. A preview lists each field that would change (current → from resume), with checkboxes
     to leave some out.
  4. Apply. Filled fields are marked `resume:<resume id>` (shown as the resume's label). A field you edited by hand is
     marked `user`; *Fill empty only* never touches it, and *Replace everything* asks first.
  5. List sections (work history, education, projects) merge by matching entries (same
     company + title, same institution + degree) instead of duplicating them.
- Each field shows a small badge, **from "<resume label>"** or **edited**, plus a
  **Confirm profile** action (sets `confirmed_at`).
- Resume text is **untrusted input**: the extraction prompt treats it as data only, and
  instructions inside a resume are ignored.

**Profile schema (Phase 1):**

```text
personal:   full_name, email, phone, address{line1, line2, city, state, postal_code, country},
            links{linkedin, github, portfolio, other[]}
headline:   current_title, summary, years_experience
skills:     skills[], tools[], languages[]
work_history[]: company, title, location, start, end, is_current, bullets[]
education[]:    institution, degree, field, start, end, grade
projects[]:     name, description, tech[], url
certifications[]: name, issuer, date
preferences (user-only): roles_of_interest[], preferred_locations[], remote_preference,
            employment_types[], minimum_salary, salary_currency, notice_period,
            work_authorization, earliest_start_date
```

### 1.4 Context rules

- Built **deterministically** from the profile, not by the LLM, so it's predictable:
  one card per work-history entry, per project, per education entry, one per skill group,
  one for the summary/headline. Phase 1 needs no extra LLM call here.
- Card fields: `kind` (experience, project, education, skills, summary, custom), `title`,
  `text`, `enabled`, `pinned`, `origin` (generated / user), `user_edited` (a generated card
  you changed), `embedding_status` (pending / embedded / failed), `updated_at`.
- **SQLite is the source of truth; Milvus holds vectors keyed by card id.** Editing a card
  → re-embed → upsert in Milvus. Deleting a card → delete its vector. Search filters to
  `enabled == true`.
- "Rebuild from profile" regenerates untouched *generated* cards and **keeps your custom and
  edited cards**. When the profile changed since the last build, Memory shows a
  "Profile changed, rebuild?" hint (no silent rebuilds).
- Failed embeddings (e.g. network error) keep the card and show *failed* with a **Retry**.
- Context personas (e.g. "ML Intern" vs "Backend SWE") wait until a later phase. Phase 1 has
  one context.

### 1.5 Backend design

**New/changed modules** (keeping the CLAUDE.md seams):

```
backend/
├── main.py            wiring only: app, include routers, error handlers, startup
├── config.py          reads .env (secrets/infra) + settings/config.toml (tuning)
├── model.py           + get_embedder() / embed(texts) next to get_client()  (one model seam)
├── storage.py         NEW seam: save/open/delete; LocalStorage now, S3Storage later
├── db.py              NEW: SQLite engine/session, table creation on startup
├── vectors.py         NEW seam: Milvus Lite client, ensure collection, upsert/delete/search
├── schemas.py         NEW: Pydantic models (Profile, ContextCard, Resume, API I/O)
├── services/
│   ├── resume_text.py     PDF (PyMuPDF) / DOCX (python-docx) → text; scanned-PDF detection
│   ├── profile_extract.py LLM structured extraction + merge rule
│   └── context_build.py   profile → cards; embed + sync to Milvus
├── api/               one package per wing, one router per room
│   ├── records/       vault.py, me.py, memory.py
│   ├── insight/       desk.py
│   └── system/        status.py
└── agents/            unused in Phase 1
```

Import direction: `config` ← `model`/`storage`/`db`/`vectors` ← `services` ← `api` ←
`main`. (CLAUDE.md §7 gets updated when we build this.)

**Naming theme: "your intern's office", with wings and rooms.** SmartIntern is an intern
working for you. Its office has **wings**, one per kind of work (storing information about
you, finding jobs, doing agent work, applying and filling forms, reporting), and each wing has
**rooms** (areas). The wing replaces `/v1` as the first path segment, so a path says what kind
of work it does:

```
/api/<wing>/<room>/...        e.g. /api/records/vault, /api/apply/forms
backend/api/<wing>/<room>.py  e.g. backend/api/records/vault.py
page URL: /<room>             e.g. /vault  (short; sidebar groups rooms under wing headings)
```

| Wing (API prefix) | Use case | Rooms (phase) |
| --- | --- | --- |
| **`/api/records`** | **Storing information** about you: everything the intern knows | **Vault** (resume library, 1) · **Me** (profile + preferences, 1) · **Memory** (embedded context cards, 1) · **Answers** (answer bank for form questions, 4) |
| **`/api/scout`** | **Finding jobs**: discovery and matching | **Radar** (sources + jobs found, 2) · **Compass** (match scores, explanations, gaps, 3) |
| **`/api/intern`** | **Agentic work**: the agent itself, its runs and tasks | **Shifts** (run history, run now, 5) · **Tasks** (per-run steps and errors, 5) |
| **`/api/apply`** | **Applications and form filling** | **Drafts** (review queue: tailored resume, cover letter, answers, 4) · **Forms** (form-fill sessions: fields detected, values used, unknowns, 6) · **Outbox** (applications tracker + events, 4) |
| **`/api/insight`** | **Reporting** | **Desk** (dashboard, 1) · **Pulse** (analytics, 5) |
| **`/api/system`** | Settings and health | **Switchboard** (status + settings, 1) |

New features get a room in the right wing; a new wing is added only for a genuinely new
kind of work. No version prefix: the frontend and MCP server ship with the backend from this
repo. Add `/v2`-style versioning only if an outside client ever depends on the API.

**Phase 1 endpoints** (the browser calls `/api/...`; the frontend proxy strips `/api`, so
backend routes are `/records/vault`, and so on):

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/records/vault` | Upload one or more resumes (multipart), returns `202` + each resume with `parse_status` |
| GET | `/api/records/vault` / `/api/records/vault/{id}` | List / detail (status, extracted text, parsed data) |
| GET | `/api/records/vault/{id}/file` | Download/preview the original |
| PATCH | `/api/records/vault/{id}` | Rename/label, set as default |
| POST | `/api/records/vault/{id}/reparse` | Re-run extraction on that resume (doesn't touch Me) |
| DELETE | `/api/records/vault/{id}` | Delete file + row (profile keeps values already filled) |
| GET / PUT | `/api/records/profile` | Read / save the whole profile (marks edited fields) |
| POST | `/api/records/profile/fill` | **Fill in using resume**: `{resume_id, mode: empty_only \| replace, preview: bool, exclude_fields[]}`; `preview=true` returns the field diff, `false` applies it |
| POST | `/api/records/profile/confirm` | Set `confirmed_at` |
| GET / POST | `/api/records/memory` | List cards / add a custom card |
| PATCH / DELETE | `/api/records/memory/{id}` | Edit (→ re-embed) / remove (→ delete vector) |
| POST | `/api/records/memory/rebuild` | Regenerate generated cards from Me |
| POST | `/api/records/memory/probe` | **Test against a JD**: `{text, k}` → top cards with scores |
| GET | `/api/insight/desk` | Counts, profile completeness, status |
| GET | `/api/system/status` | Detailed status: LLM, embeddings, Milvus, database, storage (for Switchboard) |
| GET | `/api/health` | Unchanged scaffold liveness check (backend `/health`, used by the Docker healthcheck) |

**SQLite tables (Phase 1):**

- `resumes` (unlimited rows): id, label (defaults to filename, renamable, e.g. "ML resume"),
  original_filename, mime_type, size_bytes, sha256, storage_key,
  parse_status (pending/parsing/parsed/failed), parse_error, extracted_text,
  **parsed_data** (JSON, that resume's extracted profile), is_default, created_at
- `profile`: single row (single user): `data` (JSON, validated by the Pydantic `Profile`),
  `field_origins` (JSON: field → `user` or `resume:<id>`), `last_filled_from_resume_id`,
  `confirmed_at`, updated_at
- `memory_cards`: id, kind, title, text, enabled, pinned, origin, user_edited, source_ref,
  embedding_status, embedding_error, embedded_at, position, updated_at

**Milvus Lite collection `memory_cards`** (name from `config.toml`): `id` (PK = card id), `vector`
(dimension of the embedding model), `kind`, `enabled`. Changing the embedding model means
re-embedding everything, so the collection records the model name and the app rebuilds it on a mismatch.

**Files on disk** (one Docker **named volume** `appdata` mounted at `/app/data`):
`data/app.db` (SQLite), `data/uploads/<sha256>.<ext>` (resumes), `data/milvus.db`
(Milvus Lite). A named volume rather than a Windows bind mount, because SQLite and
Milvus Lite file locking is unreliable over Docker Desktop's Windows file sharing. **[confirm]**

**Upload validation:** PDF/DOCX only (checks both extension and magic bytes), max size from
`config.toml` `[records.vault]` (default 10 MB), sha256 dedupe (same file uploaded again → same resume record).

**Robustness rules:**
- **Scanned PDFs:** no OCR in Phase 1. If extracted text is below
  `min_text_chars`, the resume is marked *failed* with "looks scanned, upload a text-based PDF".
- **Restart mid-parse:** on startup, resumes stuck in `pending`/`parsing` are re-queued, so a
  container restart never leaves a resume spinning forever.
- **One Milvus client** per process, guarded by a lock (background tasks run in threads).
- **Extraction call:** OpenAI Responses API with structured output parsed straight into the
  Pydantic `Profile` schema (`client.responses.parse(..., text_format=...)`) **[verify]**;
  the resume text goes in as clearly delimited data, never as instructions.
- **Proxy:** `server.ts` also forwards `content-disposition` so "open original" works;
  uploads (max 10 MB) are buffered, which is fine at this size.

**Configuration: two files, two jobs.**

- **`settings/config.toml`** (committed, no secrets) holds every tunable *behaviour*: `[llm]`
  provider/model/temperature/reasoning_effort/max_output_tokens/timeouts, with
  `[llm.tasks.<task>]` per-task overrides (Phase 1 uses `resume_extract`), `[embedding]`
  model/dimensions/batch size, `[vectors]` metric/collections, `[records.vault]` upload
  limits, `[records.profile]` fill default, `[records.memory]` card size and probe top-k. Later
  phases add `[scout.*]`, `[intern.*]`, `[apply]` (already sketched, commented out).
- **`.env`** (gitignored) holds secrets + infrastructure only: `LLM_API_KEY`,
  `EMBEDDING_API_KEY` (blank → reuse `LLM_API_KEY`), `LLM_BASE_URL`, `DATA_DIR=/app/data`,
  `STORAGE_BACKEND=local`, `VECTOR_DB_URI=` (blank → `DATA_DIR/milvus.db`; not `MILVUS_URI`, which pymilvus reads itself), ports.
- **Precedence:** env var > `config.toml` > code default, so an experiment can override a
  knob without editing the file. `backend/config.py` reads both with pydantic-settings'
  `TomlConfigSettingsSource` (verified; stdlib `tomllib`, no new dependency), ordered
  env → .env → TOML in `settings_customise_sources`.
- Model calls ask for settings **by task name**: `model.chat(task="resume_extract", ...)`
  looks up `[llm.tasks.resume_extract]`, falls back to `[llm]`, and sends only parameters
  the model supports (e.g. no `temperature` to models that reject it) **[verify per model]**.
- Docker: `./settings` is mounted read-only at `/app/settings`. Edit the file, then run
  `docker compose restart backend` (no rebuild).
- `LLM_PROVIDER` / `LLM_MODEL` move from `.env` to `config.toml` in Step 2. The env names
  keep working as overrides.

**New backend dependencies** **[confirm]**: `openai`, `pymilvus` + `milvus-lite`, `pymupdf`, `python-docx`, `python-multipart` (FastAPI
uploads), `sqlmodel` (or plain `sqlalchemy`), `pytest` (dev only).

**Milvus Lite facts (checked):**
- Current **milvus-lite 3.x** is a pure-Python rewrite (built on faiss-cpu + pyarrow),
  supporting **Python 3.10–3.13**. Windows is now nominally supported but only lightly tested,
  so **Docker stays the standard way to run the backend**.
- **The backend image must be pinned:** `python:3-slim` is now **Python 3.15**, which
  milvus-lite doesn't support. Step 2 pins the backend image to **`python:3.13-slim`**
  (a compatibility pin, allowed by CLAUDE.md §4).
- 3.x `.db` files are not compatible with older 2.x files. Irrelevant for us (fresh start).
- One process owns the `.db` file. Uvicorn with 1 worker is fine.
- `pymilvus` + `milvus-lite` exact package/extra names: confirm at install time **[verify]**.

### 1.6 Frontend design

**Stack [confirm]:** Vite + React + TypeScript + Tailwind CSS + React Router +
`lucide-react` icons. No component library or state library in Phase 1; a few small in-house
components instead. `server.ts` stays as the production server: it serves the built app, falls back to
`index.html` for client routes, and proxies `/api/*`. In development, Vite's dev server proxies `/api`
to the backend.

```
frontend/
├── src/server.ts            prod server (unchanged role) + SPA fallback
├── web/                     the React app (Vite root)
│   ├── index.html, main.tsx, App.tsx (layout + sidebar + routes)
│   ├── pages/  Desk, Vault, Me, Memory, Switchboard (one file per area name)
│   ├── components/  Button, Card, Input, Badge, Toggle, Dropzone, Toast, EmptyState, Spinner
│   └── lib/  api.ts (typed fetch wrapper), types.ts (mirrors backend schemas)
```

**Look & feel:** calm and minimal. Left sidebar (logo, rooms grouped under wing headings: *Records*, *Insight*, *System* in
Phase 1, status dot at the bottom), content max-width ~1100 px, neutral greys + **one accent colour**, soft 12–16 px
radius cards, generous spacing, Inter/system font, real **dark mode** (follows the OS, plus a
toggle). Motion is subtle (150 ms transitions, skeleton loaders, toasts). Empty states
always say what to do next.

**Pages:**

| Page | What's on it |
| --- | --- |
| **Desk** (`/`), the dashboard | Personal greeting ("Good morning, <first name>") + profile completeness ring; tiles: resumes, context cards (embedded / total), profile confirmed?; system status (LLM, embeddings, Milvus, storage); quick actions (Upload resume, Edit profile, Test a JD); greyed "Jobs found today / Applications" tiles labelled *Phase 2+*, so the dashboard grows with each phase |
| **Vault** (`/vault`), resumes | Drag-and-drop zone (multiple files at once); your resume library as cards: label (renamable), filename, upload date, live status chip (pending → parsing → parsed / failed + reason), ★ default; actions: rename, set default, re-parse, delete; side panel with extracted text, parsed fields and "open original" |
| **Me** (`/me`), the profile | Header with your name and a prominent **Fill in using resume** button → dialog: pick resume, pick mode, field-by-field preview with checkboxes, Apply. Sectioned form: Personal, Address, Links, Headline, Skills (chip input), Work history (add/reorder/remove entries, bullet editor), Education, Projects, Certifications, **Preferences** (user-only). Per-field badges *from "ML resume"* / *edited*; sticky Save bar showing unsaved changes; **Confirm profile** button |
| **Memory** (`/memory`), the context | Cards grouped by kind; inline edit (textarea autosaves on blur → re-embed), toggle include, pin, delete, "+ Add card"; embedding status dot per card; "Rebuild from profile". Right panel **Test against a JD**: paste text → top-k cards with similarity bars; matching cards highlight in the list |
| **Switchboard** (`/switchboard`), settings | The old setup check (health detail), current model names, upload limit, data location; later: sources, schedule, autonomy mode |

### 1.7 Build order (we build and check step by step)

| Step | Work | Check |
| --- | --- | --- |
| 1 | Frontend shell: Vite + React + Tailwind + router, sidebar layout, 5 placeholder pages (Desk, Vault, Me, Memory, Switchboard), Docker build updated, SPA fallback | All pages navigable at :3000; health still green |
| 2 | Backend foundations: pin backend image to `python:3.13-slim`; `config.py` reads `settings/config.toml` + `.env` (precedence rules), settings mount, `db.py`, `storage.py`, `appdata` volume, `/api/system/status` | Switchboard shows db + storage OK and the active model settings; changing `config.toml` + restart takes effect; data survives restart |
| 3 | Resume upload + text extraction + Resume page (multi-upload, library, default, status polling) | Upload several PDFs/DOCX, see each one's extracted text |
| 4 | LLM extraction → `parsed_data` per resume; `/api/records/profile` GET/PUT; `/api/records/profile/fill` (preview + apply, both modes) | Fill from resume A, edit a field, fill from resume B (empty only) → your edit kept |
| 5 | Profile page (full form, **Fill in using resume** dialog with preview, badges, save, confirm) | Fill, edit and save in the browser |
| 6 | `model.embed()` + `vectors.py` (Milvus Lite) + context build/sync | Cards created and embedded; vectors in Milvus |
| 7 | Context page (cards CRUD) + Test-a-JD search | Paste JD → ranked cards |
| 8 | Dashboard summary + polish (empty states, toasts, dark mode) + a few pytest tests (text extraction, merge rule, context build) with a **fake** sample resume | Full exit criteria in 1.1 |

Each step keeps the setup check green, as the CLAUDE.md working rules require.

### 1.8 Phase 1 acceptance test (run locally in Docker)

**Prerequisites:** Docker Desktop running; `settings/config.toml` has `[llm] model` set;
`.env` has `LLM_API_KEY` (an OpenAI key with billing enabled; Phase 1 usage costs cents).

```bash
docker compose up --build        # then open http://localhost:3000
```

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Open **Switchboard** | LLM, embeddings, Milvus, database, storage all ✅ |
| 2 | **Vault**: drop 2 resumes (one PDF, one DOCX) | Both appear; status goes pending → parsing → parsed; extracted text and parsed fields visible |
| 3 | Rename one, mark the other ★ default | Persists after a page refresh |
| 4 | Upload a non-PDF/DOCX file, or one that's too large | Clear error, nothing stored |
| 5 | **Me** → *Fill in using resume* → pick resume A → preview → Apply | Fields filled with *from "A"* badges; nothing invented |
| 6 | Edit your phone number by hand, Save | Badge becomes *edited* |
| 7 | *Fill in using resume* → resume B → *empty fields only* | Your phone edit is kept; only blanks are filled; no duplicate jobs or degrees |
| 8 | Fill in **Preferences**, click **Confirm profile** | Saved; dashboard completeness goes up |
| 9 | **Memory** | Cards for each job, project, degree, skill group and the summary; all show *embedded* |
| 10 | Edit a card, add a custom card, disable one | Edited/new cards re-embed; disabled card excluded from search |
| 11 | **Test against a JD**: paste a real job description | Ranked cards with similarity scores; the most relevant experience is on top |
| 12 | *Rebuild from profile* | Generated cards refreshed; your custom/edited cards kept |
| 13 | **Desk** | Greeting with your name; correct counts; status green |
| 14 | `docker compose down` then `docker compose up` | All resumes, profile, cards and search results still there |
| 15 | Delete a resume | File and row gone; profile values already filled stay |

Plus the automated tests: `docker compose run --rm backend pytest` (uses a fake resume and
no network or OpenAI calls).

---

## 2. Later phases (brief, detailed when we get there)

**Phase 2: Job discovery** (blueprint Phase 1)
Source adapter interface + `NormalizedJob`; start with Remote OK, Arbeitnow, Greenhouse
(blueprint's first task), then Himalayas, Remotive, Jobicy, WWR RSS, Lever, Ashby. Company
registry for India-focused employers' ATS boards. Dedupe, provenance, `first_seen/last_seen`,
source run logs, "Run now" button, **Jobs** page (list, filters, original links). JD
embeddings in a second Milvus collection. Respect each provider's terms/limits **[verify]**.

**Phase 3: Matching**
Hard filters (only those you mark mandatory) → vector similarity (JD vs context cards) →
LLM scoring of the top N with component scores (skills, experience, role, location,
qualifications), matched/missing skills, explanation, `score_version`. Jobs feed ranked;
job detail with match breakdown; dashboard gets the discovery funnel + skills gap.

**Phase 4: Application preparation (Prepare-only mode)**
Answer bank on Profile; tailored resume (reorders/re-emphasizes **existing** facts only,
shows a diff); optional cover letter; screening answers with unknowns flagged for you;
**Review queue**; **Applications tracker** (status + events model from blueprint §9); use
the official apply link.

**Phase 5: Daily agent + analytics**
In-process scheduler for the daily run; run history + source health; idempotent tasks;
**Analytics** page fully driven by stored events (with sample sizes and date ranges); daily
digest.

**Phase 6: Controlled automation + tracking**
Approve-then-submit through Playwright only where permitted; hard stop on
login/CAPTCHA/MFA; idempotency keys; `submission_unknown` when not confirmed; audit
log. Gmail (OAuth, least privilege) for response tracking. Probably a separate Compose
service for the browser.

**Phase 7: Deploy**
`S3Storage` backend; Postgres (+ migrations); Milvus Lite → Milvus server/Zilliz Cloud
(URI change); **OAuth login** (e.g. Google) protecting the single user's data; secrets
management; data export/delete; context personas. Tables already avoid assumptions that would
make adding a `user_id` later painful.

---

## 3. Ideas kept on the shelf (from first draft)

Context personas · skill-gap coach · interview prep pack · daily digest · referral flags ·
repost/duplicate detection · freshness boost for internships · company blocklist and
per-company cooldown · dry-run mode.

---

## 4. What I need from you before Step 1

1. ~~OpenAI chat model~~ decided: `gpt-6-luna`; `LLM_API_KEY` is set in `.env` ✅
2. OK to add the **backend deps** listed in 1.5 and the **frontend stack** in 1.6?
3. OK with **SQLite** and a Docker **named volume** for data in Phase 1?
4. OK that **Docker is the standard way to run the backend** (backend image pinned to Python 3.13 for Milvus Lite)?
