# Project build phases

One file per phase. A phase is planned here **before** it is built, updated while
building, and marked ✅ when its acceptance test passes.

| Phase | File | Status |
| --- | --- | --- |
| 1 | [Candidate foundation](phase_1_candidate_foundation.md): resumes → profile → memory cards | ✅ done |
| 2 | [Job Search](phase_2_job_discovery_and_understanding.md): sources → rules + embeddings (no LLM) → evidence map → apply preset; Utility → Job Search ▾ (Overview / Jobs / Search Settings) | 🔍 built; acceptance passed (API, live data, 2026-11-17); your UI review pending |
| 2.5 | [JSearch-only, budget-planned search](phase_2_5_jsearch_budgeted_search.md): one source (JSearch, free tier 200 req/month), query plan from search criteria before any call, server-side filters, incremental scans, call budget + yield-based allocation | 🔍 built and used live; mark ✅ after a last UI look |
| 2.6 | [Role contexts and search precision](phase_2_6_role_contexts_and_search_precision.md): one AI-written, job-description-style context per role + simplified Scan now (roles / location / date / editable query + exact request), criteria only shape the scan, years filter on Jobs, daily-limit switch | 🔍 built; JSearch works well enough (user, 2026-11-20); mark ✅ after a last UI look |
| 2.7 | [More sources for jobs in India](phase_2_7_india_first_multi_source_discovery.md): form-first (jobs the agent can apply to), one Scan button for all sources, apply route per job, company ATS boards, Jooble, remote open-to-India feeds | 🚧 A0 + A1 + A2 built 2026-11-20 (sources + apply route; company boards + Companies list; starter list + ATS research); next: B1 Jooble |
| 3 | Scoring + Apply / Maybe / Skip | later |
| 4 | Application preparation (Prepare-only) | later |
| 5 | Daily agent + analytics | later |
| 6 | Controlled automation + tracking | later |
| 7 | Deploy (S3, Postgres, Milvus server, OAuth) | 🟡 app deployed 2026-11-20 (Vercel + Render); S3 / Postgres / Milvus server / OAuth still open |

Background: `MD_files/initial_draft_plan.md` (original game plan, Phase 1 detail),
`MD_files/smart_job_application_agent_blueprint.md` (reference spec),
`MD_files/database.md` (current schema).
