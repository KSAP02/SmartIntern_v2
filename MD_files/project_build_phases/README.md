# Project build phases

One file per phase. A phase is planned here **before** it is built, updated while
building, and marked ✅ when its acceptance test passes.

| Phase | File | Status |
| --- | --- | --- |
| 1 | [Candidate foundation](phase_1_candidate_foundation.md): resumes → profile → memory cards | ✅ done |
| 2 | [Job Search](phase_2_job_discovery_and_understanding.md): sources → rules + embeddings (no LLM) → evidence map → apply preset; Utility → Job Search ▾ (Overview / Jobs / Search Settings) | 🔍 built; acceptance passed (API, live data, 2026-11-17); your UI review pending |
| 2.5 | [JSearch-only, budget-planned search](phase_2_5_jsearch_budgeted_search.md): one source (JSearch, free tier 200 req/month), query plan from search criteria before any call, server-side filters, incremental scans, call budget + yield-based allocation | 🔍 built and used live; mark ✅ after a last UI look |
| 2.6 | [Role contexts and search precision](phase_2_6_role_contexts_and_search_precision.md): one AI-written, job-description-style context per role + simplified Scan now (roles / location / date / editable query + exact request), criteria only shape the scan, years filter on Jobs, daily-limit switch | 🔍 built; JSearch works well enough (user, 2026-11-20); mark ✅ after a last UI look |
| 2.7 | [More sources for jobs in India](phase_2_7_india_first_multi_source_discovery.md): form-first (jobs the agent can apply to), one Scan button for all sources, apply route per job, company ATS boards, Jooble, remote open-to-India feeds | 🔍 built 2026-11-22 (A0–A4, C1, E; Jooble parked, Rippling not built); pushed 2026-11-23 |
| 2.8 | [Multiple profiles](phase_2_8_multiple_profiles.md): several profiles (from a resume or a copy), one active; cards, role contexts and roles follow it; shared jobs re-scored on a switch | 🔍 built 2026-11-23; user tests on localhost |
| 3 | Scoring + Apply / Maybe / Skip | later |
| 4 | Application preparation (Prepare-only) | later |
| 5 | Daily agent + analytics | later |
| 6 | Controlled automation + tracking | later |
| 7 | Deploy (S3, Postgres, Milvus server, OAuth) | 🟡 app deployed 2026-11-20 (Vercel + Render); S3 / Postgres / Milvus server / OAuth still open |

## Phase 7 decisions so far

**Company finder stays local (user, 2026-11-23).** The finder runs only on the localhost app;
the deployed backend sets `COMPANY_FINDER=false` (env, Render) and never runs it: no automatic
runs, no Run now; scans there still read every company in the database (`employers`).
**One shared Postgres, chosen by `.env` (user, 2026-11-23; built the same day).**
`DATABASE_URL` set = Postgres, blank = SQLite, so the code on `main` behaves the same
everywhere and only `.env` decides. The local and the deployed backend point at the **same**
Postgres (Supabase, free plan: no compute-hour cap; Neon's 100 CU-hours/month would run out
with the 30-second timer and back-to-back finder runs). Who does what, also in `.env`:

| `.env` key | Local backend | Deployed (Render) |
| --- | --- | --- |
| `DATABASE_URL` | Supabase session pooler string | the same string |
| `AUTO_SCANS` | `false` | `true` (automatic scans run only here) |
| `COMPANY_FINDER` | `true` (finder runs only here) | `false` |

Built: `db.postgres_url` / `postgres_engine` / `sync_id_counter`, `services/db_copy.py`
(first copy), `AUTO_SCANS` in `scheduler._tick`, test guard. Verified 2026-11-23 on a throwaway
Postgres 17: backend tests 239 passed + 1 skipped (SQLite snapshot); the real local data copied
(25,806 rows, 18 tables) and every main page's API read it.
Not covered: resume files (storage seam → S3 / R2, later); **Milvus Lite stays** per machine
(user, 2026-11-23: vectors are only used to re-score; a job without a local vector keeps its
score).

Background: `MD_files/initial_draft_plan.md` (original game plan, Phase 1 detail),
`MD_files/smart_job_application_agent_blueprint.md` (reference spec),
`MD_files/project_notes/database.md` (current schema).
