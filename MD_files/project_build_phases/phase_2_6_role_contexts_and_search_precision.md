# Phase 2.6: Role contexts and search precision

> **Status:** BUILT 2026-11-19 (steps 1–6; 177 backend tests green). Next: step 7, the user reviews
> the role contexts and runs the query lab. See §Build notes at the end.
> Replaces the "memory slots" stub: one **role context** per role does that job more simply.
> Two parts: **A** better JSearch requests (fixes + a query lab the user runs), **B** role
> contexts (an AI-written, job-description-style context per role, embedded once and compared
> with every fetched job). Per-card embeddings are removed.
> Real JSearch requests are spent only by the user. This build needs none.

**Goal:** more jobs that are actually for you, per request spent, and the best ones on top.
**Measure:** *relevant jobs per request* (jobs that end up in Matches and stay there) and
*precision of Matches*.

## Decisions (2026-11-19)

| # | Question | Decision |
| --- | --- | --- |
| 1 | What represents "you" when judging a job? | **One role context per role**, written by the AI model in the form of a market job description for that role, built from your memory cards. Embedded once; compared with each fetched job's text. |
| 2 | Memory cards | **Kept as stored text** (the material role contexts are written from, and the proof for "skill X ← card Y"). **Their embeddings are removed** (no memory vectors, no requirement-chunk vectors). |
| 3 | What may a role context contain? | **A full market job description** for the role, including skills you don't have (more opportunities). Gaps are shown per job after ranking. |
| 4 | Where does market knowledge come from? | The model's knowledge **plus up to 3 real job descriptions for that role already fetched** (Matches / Selected / Applied). No extra requests. |
| 5 | How is it used in a scan? | **Title check stays** (it reliably drops Mechanical / Treasury jobs). The weak "job vs nearest card" score is replaced by **"job vs that role's context"**: used for the borderline rescue and to rank Matches. |
| 6 | Where in the UI? | **Memory becomes a dropdown: Cards / Role contexts.** On Role contexts you pick a role and see its context, how it was drafted (which cards and example jobs), edit, save. |
| 7 | When is it written? | **Automatically when a role is added** (Search criteria, or "Add title to my roles"), and saved. Editable any time; **Regenerate** on demand. Never rewritten automatically after you edit it. |
| 8 | Scope of 2.6 | **Role contexts + the no-request JSearch query fixes**, then the user runs the query lab. Labelled set / evaluation / discard reasons / one rank score: later (§Later). |

---

## 0. Evidence so far (10 requests, 2026-11-17/18)

| # | Query | date_posted | Returned | New | Relevant |
| --- | --- | --- | --- | --- | --- |
| 1 | Backend Engineer in India | month | 8 | 8 | 2 |
| 2 | AI Engineer in India | month | 10 | 9 | 2 |
| 3 | AI Engineer in India (page 2) | month | 0 | 0 | 0 |
| 4 | LLM Engineer in India | month | 3 | 0 | 0 |
| 5 | AI Engineer OR Artificial Intelligence (AI) Associate in Bengaluru | month | 0 | 0 | 0 |
| 6 | AI Engineer in Bengaluru | month | 1 | 1 | 0 |
| 7 | AI Engineer in India | **today** | 0 | 0 | 0 |
| 8 | LLM Engineer in India | **today** | 1 | 1 | 0 |
| 9 | Software Engineer in India | month | 10 | 8 | 0 |
| 10 | ML Engineer in India | month | 10 | 5 | 0 |

All sent `job_requirements=under_3_years_experience,no_experience` and `country=in`.
10 requests → 5 jobs in Matches (+3 you applied to). **About 0.5 relevant jobs per request.**

- **F1. The same "Fresher" pool comes back whatever the role** ("Mechanical Engineer -
  Fresher", "Junior Software Developer - Fresher", "Be(CS/IT) Freshers", "Application Support
  Engineer" for AI, ML *and* Software Engineer). Prime suspect: `job_requirements`.
- **F2. The experience filter is loose anyway:** in calls 9–10, 7 of 20 results ask for 2–5+
  years (dropped by our own check).
- **F3. Incremental recency starves repeats:** a search that ran yesterday sends
  `date_posted=today` → 0–1 results.
- **F4. Parentheses in a role break the query:** "(AI)" in an OR query → 0 results.
- **F5. Narrow places return little:** Bengaluru → 1 job; page 2 → 0.
- **F6. Duplicates across overlapping roles** waste slots.
- **F7. Our title gate works on what arrives**; the loss is mainly upstream.

---

## Part A: How JSearch searches, and better requests

### A1. How it works

| Fact | Confidence | Source |
| --- | --- | --- |
| JSearch sends our `query` to **Google for Jobs**; 10 results per page; 1 page = 1 request | provider | `api_references/jsearch.md` §1–3 |
| Filters (`date_posted`, `employment_types`, `job_requirements`, `work_from_home`) are Google Jobs' filter chips | likely | jsearch.md §3.1 |
| Google maps a query to an **occupation** and retrieves postings for it, not only keyword matches | reported (Google patent analysed by [Go Fish Digital](https://gofishdigital.com/blog/how-google-built-machine-learning-into-their-job-search-engine/), 2018) | — |
| `"exact phrase"`, `OR`, `AND`, `( )`, `*`, `after:` work in Google Jobs; `-word`, `site:`, `before:` don't | vendor blog ([SerpApi](https://serpapi.com/blog/google-jobs-search-query-operators.md)), unverified by us | — |

So a plain "AI Engineer in India" lands in a broad occupation, and with the entry-level chip
on, Google fills the 10 slots from the small entry-level pool (F1). Exact phrases and title
groups are our levers; exclusions are not.

### A2. Hypotheses (tested in the query lab)

| Id | Change | Expected |
| --- | --- | --- |
| H1 | Don't send `job_requirements` (check years after) | fewer generic fresher jobs, more on-role |
| H2 | Quote the title: `"AI Engineer" in India` | fewer off-field jobs |
| H3 | Title group: `("AI Engineer" OR "Machine Learning Engineer") in India` | H2's precision, fuller pages |
| H4 | Title group + one key skill | narrower, more on-profile |
| H5 | Recency floor (`week` instead of `today`) | no 0-result repeats |

### A3. Query lab (run by the user, after this build)

~12 requests: AI Engineer and Backend Engineer × 6 variants (V0 plain + filter = today's
baseline · V1 plain, no filter · V2 exact title · V3 title group · V4 title group, no
filter · V5 title group + skill), same day, `date_posted=month`. Read the results in
Scan Jobs → Requests and JSearch analytics → "By wording", then pick the default wording and
whether the experience filter is sent.

### A4. What is built in 2.6

1. **Recency floor:** `[scout.search.sources] min_date_posted = "week"`; incremental
   `date_posted` never goes narrower (fixes F3).
2. **Clean role text:** characters Google reads as operators (`( ) " [ ]`) are stripped from
   role names in queries (fixes F4).
3. **Search wording** (provider-neutral; the JSearch adapter writes Google's syntax):
   - per role, **search titles** (the role + market synonyms) and **keywords**, proposed by
     the model with the role context and editable on the Role contexts page;
   - **wording style**: `plain` ("AI Engineer in India", today's), `exact`
     (`"AI Engineer" in India`), `titles` (`("AI Engineer" OR "Machine Learning Engineer")
     in India`), `titles_keywords` (titles + the first keyword).
   - Default in Search criteria; override per scan in the Scan now picker.
   - Combined OR scans join the chosen roles' titles (max 8).
4. **Experience filter switch:** Admin → JSearch `send_experience_filter` (default on until
   the lab says otherwise) + per-scan override. The years check after the call always runs.
5. **Wording recorded per request** (`api_calls.variant`, e.g. `titles · exp off`), and
   JSearch analytics shows **relevant per request by wording**.

---

## Part B: Role contexts

### B1. What a role context is

A text that reads like a real job posting for that role in your market, written for your
level. It contains a short summary, responsibilities, requirements and nice-to-haves,
and it is a **full market description**, including skills you don't have. It's the
"ideal job" a search for that role should find. Separately (not embedded) it holds the
**search titles** and **keywords** used to build queries.

### B2. How it's written

- **Model task** `role_context` (`[llm.tasks.role_context]` in config.toml), structured
  output: `summary`, `responsibilities[]`, `requirements[]`, `nice_to_have[]`,
  `search_titles[]`, `keywords[]`.
- **Inputs** (all as untrusted data inside tags):
  - the role name;
  - your years of experience and locations (market and level);
  - your profile headline;
  - your enabled memory cards' text;
  - up to **3 fetched job descriptions** for the role, as examples of current wording.
    They are your Selected / Applied / Matches jobs whose title matched this role best,
    using the title plus the Qualifications and Responsibilities highlights.
- **Rules in the system prompt:**
  - write like an employer's posting in that market;
  - cover what such jobs commonly ask for;
  - use the candidate's material only to understand which kind of work in this role they
    pursue (e.g. LLM applications vs computer vision), never to copy project or company
    names;
  - no personal data.
- **Stored** in table `role_contexts`: the role, the parts, the embedded text, what it was
  built from (card ids, example job ids, memory version), edited or not, its embedding (one
  vector, kept in the row; no vector collection needed), and timestamps.
- **When:** on role add (background task); missing contexts for current roles are written
  on startup. **Regenerate** rewrites it (asks first if you edited it). If your memory
  changed since it was written, the page says so; nothing is rewritten automatically.

### B3. How it's used in a scan

```
JSearch result ─► ingest ─► criteria (years asked > yours, type, place, …) → Excluded
   ─► embed job text = title + Responsibilities + Qualifications (highlights), else the
      description (first 2,000 chars); re-embedded once for existing jobs
   ─► title score  = job title vs your roles (unchanged); picks the role
   ─► context score = job text vs THAT role's context (cosine)
   ─► relevant if title ≥ 0.72, or title ≥ 0.60 and context ≥ borderline_context_threshold (0.50)
      (no roles: everything passes; the gate needs roles)                → Not relevant
   ─► evidence: requirement chunks → named skills you have (exact, from card text) / years
      asked vs yours → met / missing / not judged; gap list = skills asked you don't have
   ─► Matches ranked by context score, then title score
```

- The borderline context threshold is set from the real distribution after contexts exist,
  measured on the stored jobs with OpenAI embeddings only (no JSearch).
- Matching settings that only served card vectors go: `relevance_threshold`, met / partial
  thresholds, `evidence_top_k`, `aggregation`, `match_method`, `query_context`.
  `borderline_profile_threshold` becomes `borderline_context_threshold`.
- The job panel shows "Role context match" and the skill gaps. A deeper, AI-written gap
  note per job is Phase 3.

### B4. Memory pages

- **Memory ▾ → Cards** (`/memory`): today's page minus the embedding dots and counts.
- **Memory ▾ → Role contexts** (`/memory/roles`):
  - role list on the left;
  - the selected role's context, with what it was drafted from (cards, example jobs, model,
    date, "edited by you");
  - edit the parts, search titles and keywords; Save (re-embeds); Regenerate;
  - **Test a job description**: paste a JD and see its match with each role context.
    This replaces "Test against a JD" on Cards.

---

## Build steps

| Step | What | Requests |
| --- | --- | --- |
| 1 | Query fixes: recency floor, clean role text, experience-filter switch | 0 |
| 2 | Role contexts: table, model task, generation on add / startup, edit, regenerate, API | 0 JSearch (model calls) |
| 3 | Scan uses contexts: new job text, context score, gate, ranking; card and chunk embeddings removed; evidence by exact skills + years | 0 |
| 4 | Search wording from role contexts (styles), picker override, variant per request, analytics by wording | 0 |
| 5 | Memory ▾ Cards / Role contexts pages, Test a JD | 0 |
| 6 | Measure the context-score distribution on stored jobs; set the borderline default | 0 JSearch |
| 7 | **User:** review contexts, then run the query lab (~12 requests) | ~12 |

## Acceptance

- Adding a role writes its context within a minute. It's viewable, editable and saved on
  Memory ▾ Role contexts, with what it was built from.
- Scans and re-checks use the role context score. No memory or requirement vectors remain.
  The job panel shows the context match and the skill gaps.
- Queries never contain `( )`, and repeats never send `today`. The picker shows the wording
  and the experience-filter switch. Each request records its wording, and analytics shows
  yield by wording.
- After the lab: ≥ 3 relevant jobs per request on AI Engineer (baseline 0–2), with the chosen
  wording set as the default.

## Later (not in 2.6)

- Labelled set from your actions + evaluation panel.
- Discard reasons.
- One rank score with visible weights.
- Thresholds suggested from data.
- Duplicate-aware planning.
- Phase 3: AI scoring per job with a written gap note.

---

## Build notes (2026-11-19)

- **Built as planned.** Backend:
  - `services/role_contexts.py`;
  - `role_contexts` table;
  - `api/records/memory.py` (role routes);
  - `job_search` (digest v2, `context_score`, gate);
  - `compass` (exact + years only, fit over judged requirements);
  - `memory` (no embedding, `after_change`, `cards_version`, drop unused collections once);
  - `search_plan` (wording, floor, experience switch, `variant`);
  - `sources/jsearch.build_query`;
  - analytics "By wording".

  Frontend:
  - Memory ▾ Cards / Role contexts (`pages/RoleContexts.tsx`);
  - Scan picker: Wording + "Send the experience filter";
  - Search criteria: wording;
  - Admin → JSearch: floor + switch, and Matching (title + context thresholds only);
  - job rows show "% context".
- **First run:** 6 contexts written (one model call + one embedding each); 32 jobs re-embedded
  with the new job text; no JSearch requests.
- **Measured (step 6):**
  - Context scores for jobs you applied to or kept: 0.53–0.67.
  - "Data Scientist, Launch Program": 0.65, but its title (0.54) is below the borderline, so
    it stays Not relevant. Add "Data Scientist" as a role if you want those.
  - Unrelated near-miss titles (Mechanical / Electronics / Build & Release / Data Services /
    Backend Operations, title 0.62–0.69): 0.41–0.46.
  - So `borderline_context_threshold` = 0.50. The old card-based score overlapped
    (0.20–0.63 for every tech job).
- Removed settings: `relevance_threshold`, `met_threshold`, `partial_threshold`,
  `evidence_top_k`, `aggregation`, `match_method`, `query_context`, `probe_top_k`,
  `probe_min_score`; `borderline_profile_threshold` → `borderline_context_threshold`.
- With no roles set, the gate passes everything (titles and contexts both need roles).

### Added 2026-11-19: requests explained in plain words

Asked after requests 11–12 (`"AI Engineer" in India` → 0 jobs; `AI Engineer in India` → 2
remote, off-topic jobs). Every request so far had the experience filter on, so the query lab's
"exp off" runs are the next test.

- **Scan now → What will be sent:** each parameter with what Google for Jobs does with it
  ("narrows" marked; the experience filter and very short windows in amber), what the same
  search (same role and place) returned before and what it sent differently, a note when the
  exact same request already ran, and **Then, on the jobs that come back** (our checks:
  duplicates, age, title check thresholds, years, job types, workplace, locations...).
- **Scan Jobs → Requests (expanded):** **Why these results** (few results, remote “Anywhere”
  filler, titles without the search's key words, generic “Fresher” postings, title-check
  failures, exclusions by reason, years asked despite the filter, how many reached Matches) and
  **Next time** suggestions, plus the other requests for the same search.
- Code: `sources/jsearch.explain_param` (JSearch-specific meanings), `services/request_explain.py`
  (plan annotation, history, findings), `GET /api/scout/search/calls/{id}/explain`; schemas
  `ParamNote`, `PastRequest`, `CallExplainOut`, `PlannedCall.explain/history`,
  `SearchPlanOut.after`. Tests: `test_request_explain.py` (4). Reads our records only.

### Added 2026-11-20: Scan now shows where every value comes from

- **Wording buttons removed from Scan now.** Each request has an editable **Query text** box,
  prefilled with what your roles, locations and default wording (Search criteria) generate;
  Reset returns to it. Typed text is sent as is (whitespace collapsed, ≤ 300 chars) for that scan
  only; the request's variant is `custom · exp on|off`.
- **Date posted** per scan: Automatic (default) or a fixed window.
- Every parameter shows **From:** (e.g. `country` ← Locations “India” → in; `date_posted` ← “last
  ran 8 hours ago, so today, raised to the floor week”; `job_requirements` ← years 1 → under 3
  years + no experience) and **Your settings not sent to JSearch** lists the rest with why.
- Code: `ScanSelection.query_texts` / `date_posted`; `PlannedCall.default_query` / `custom` /
  `sources`; `ParamNote.source`; `SearchPlanOut.not_sent`; `search_plan.date_window`,
  `param_sources`, `not_sent`. Tests: 2 more in `test_request_explain.py` (a scan sends the typed
  text and chosen date).

### Changed 2026-11-20: a simpler Scan now, locations with states

- Scan now shows only **Roles** (+ one OR request when several), **Location** (one of your saved
  locations; "+ Add a location…" = country dropdown + optional state/city, saved to Search
  criteria), **Date posted** (default past week) and the **Query** per request (default from roles
  + location + Search criteria wording; editable; "Default" resets). The parameter explanations
  stay on Scan Jobs → Requests (per past request).
- Locations are "State or city, Country" or "Country": `country` = the country's code; the whole
  text goes into the query. The post-filter checks the country (or city), not the state.
  `job_facts.place_options()` / `GET /api/scout/search/places`: 80 countries with known states
  and cities as suggestions.
- Budget: Requests per day > 0 now replaces pacing (`api_budget.quota`).

### Changed 2026-11-20 (later): location only informs, never excludes

- `criteria_reason` no longer checks Locations (`keep_unknown_location` is unused; removed from the
  page, like "How searches are worded"). On start `reapply_criteria_if_needed` (meta
  `criteria_version`) re-checks every job; `reapply_criteria` now also refreshes a stale reason.
- Each job row shows its location against the place searched by the request that found it
  (`JobCard.searched_place` / `place_check`): in the place (bold), elsewhere (amber, "not
  Karnataka"), area not stated, remote.
- Found while checking: Search criteria → Job types = Internship excluded all 42 stored
  undecided jobs (all full-time); 20 of them also ask for more than 1 year.

### Changed 2026-11-20 (evening): criteria only shape the scan; daily-limit switch

- `criteria_reason` returns None: job types, workplace, years, posted-within, excluded words /
  companies never remove a job (start-up re-check v4 freed all 42; 20 reached Matches). The title
  check is the only sorter (Matches / Not relevant); the Jobs page filters type / workplace. The
  Excluded tab shows only while old excluded jobs remain. Removed from Search criteria: Posted
  within, Exclude words in title, Never these companies. Only Internship adds "internship" to the
  default query (`search_plan.query_extra`).
- Budget: `pacing` removed; `daily_limit_on` switch (Admin → JSearch → Limit requests per day).
  On = at most `daily_limit` a day from today regardless of earlier spending; off = everything
  left. QuotaOut adds days_left, scan_budget / used / left, even_pace, expected_by_today,
  ahead_by; Admin shows them with "Use N a day".
- Scan now shows the exact request (all parameters) under each query box again.

### Changed 2026-11-20 (night): years move to the Jobs page

- Search criteria → years of experience and Admin → "Send your years of experience to JSearch"
  removed from the UI; `params_for` never sends `job_requirements` (fields kept, ignored).
- Jobs → Matches: "Experience asked" (Any, None, up to 1/2/3/5/8 years; remembered in the
  browser) = `GET /api/scout/search/jobs?max_years=`; jobs that don't state their years always
  stay. Rows show "N+ yrs asked". `JobCard.min_years_experience`.
- Live check: 28 matches; up to 1 year leaves 12 (all of them don't state years).
