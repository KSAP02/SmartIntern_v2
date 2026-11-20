# Project build phases

One file per phase. A phase is planned here **before** it is built, updated while
building, and marked ✅ when its acceptance test passes.

| Phase | File | Status |
| --- | --- | --- |
| 1 | [Candidate foundation](phase_1_candidate_foundation.md): resumes → profile → memory cards | ✅ done |
| 2 | [Job Search](phase_2_job_discovery_and_understanding.md): sources → rules + embeddings (no LLM) → evidence map → apply preset; Utility → Job Search ▾ (Overview / Jobs / Search Settings) | 🔍 built; acceptance passed (API, live data, 2026-11-17); your UI review pending |
| 2.5 | [JSearch-only, budget-planned search](phase_2_5_jsearch_budgeted_search.md): one source (JSearch, free tier 200 req/month), query plan from search criteria before any call, server-side filters, incremental scans, call budget + yield-based allocation | 🔍 built and used live; next: discuss refining JSearch queries for more role-specific results |
| 2.6 | [Role contexts and search precision](phase_2_6_role_contexts_and_search_precision.md): one AI-written, job-description-style context per role (embedded once, compared with each job; card embeddings removed) + JSearch query fixes (wording styles, recency floor, experience-filter switch, yield by wording) | 🔍 built 2026-11-19; next: your review of role contexts, then the query lab (~12 requests, run by you) |
| 2.7 | [One collector layer for jobs from anywhere](phase_2_7_india_first_multi_source_discovery.md): one source contract (search APIs, company ATS boards, open feeds, a JSON-LD careers-page scraper), one basic filter (role / type / place / recency / years), dedupe, per-source analytics; matching stays in 2.6 | 📝 plan rewritten 2026-11-19; decisions D1–D5 pending |
| 3 | Scoring + Apply / Maybe / Skip | later |
| 4 | Application preparation (Prepare-only) | later |
| 5 | Daily agent + analytics | later |
| 6 | Controlled automation + tracking | later |
| 7 | Deploy (S3, Postgres, Milvus server, OAuth) | later |

Background: `MD_files/initial_draft_plan.md` (original game plan, Phase 1 detail),
`MD_files/smart_job_application_agent_blueprint.md` (reference spec),
`MD_files/database.md` (current schema).
