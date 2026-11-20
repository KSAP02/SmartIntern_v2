# Phase 2.5: JSearch-only, budget-planned job search

> **Status:** BUILT except step 1 (calibration needs the JSearch key), 2026-11-17. All §14
> decisions accepted as proposed. 139 backend tests green; build notes in §17.
> Builds on Phase 2 (pipeline, relevance gate, evidence map stay as they are).
> API facts: `MD_files/api_references/jsearch.md`. Free tier only; pay-as-you-go is a later
> switch (§16).

---

## 1. Why

- Phase 2's free feeds are US/Europe job boards: of 827 jobs gathered, **3 were in India**,
  none for your roles. JSearch (Google for Jobs: LinkedIn, Naukri, Indeed, company career
  sites) covers India and returns **full descriptions**.
- JSearch's free tier is **200 requests a month**, and **one request = one page of up to 10
  jobs**. That is at most **2,000 postings a month, ~66 a day**, before duplicates.
- So every call has to count. **Before** a call we must know exactly what we're asking for
  and why; **after** it we measure what it was worth, and use that to plan the next calls.

## 2. Goal and exit criteria

**Goal:** JSearch becomes the only job source. Every scan runs a **query plan** worked out
from your search criteria *before* any call: which requests, with which parameters, at what
cost. A budget system in the backend guarantees the free tier is never exceeded and spends it
where it finds the most new, relevant jobs.

Exit criteria:
1. Only JSearch is called; the other six sources and Adzuna are removed from scanning (§5).
2. **Query plan:** Search criteria are turned into a list of JSearch requests (role × place,
   with filters the API can apply itself). You can see the plan and its cost before a scan
   and run a **dry run** (no calls).
3. **Server-side filtering:** job type, remote-only, experience level and recency are sent as
   JSearch parameters, so fewer of the 10 results per call are wasted.
4. **Incremental:** each query asks only for postings since it last ran (`date_posted`).
5. **Budget:** hard monthly cap (200), daily pacing, a reserve, per-scan cap; never exceeded,
   even with Scan now clicks, auto-scans and restarts mixed together. Every call is logged.
6. **Yield-aware:** per query we record results / new / relevant; low-yield queries back off,
   high-yield ones may get a second page when there is spare budget.
7. Calibration (≤ 10 live calls) confirms the response shape and the unverified items in the
   API reference, and the reference is updated.
8. Quota and yield visible in the UI (Overview meter, Search plan card, call history).
9. Tests offline with recorded responses; no test ever calls JSearch.

## 3. JSearch facts this design relies on

From `api_references/jsearch.md` (verified ✓ / to confirm in calibration ?):

| Fact | Status | Design consequence |
| --- | --- | --- |
| 1 request = 1 page = up to 10 jobs; `num_pages=N` costs N | ✓ spec | Default `num_pages=1`; a 2nd page only when page 1 was worth it |
| `query` free text, "title + location recommended"; `country` ISO code | ✓ | Query unit = role × place |
| `date_posted`: all, today, 3days, week, month | ✓ | Incremental scans (§7.3) |
| `employment_types`: FULLTIME, CONTRACTOR, PARTTIME, INTERN | ✓ | From Search criteria job types |
| `work_from_home=true` remote only | ✓ | Only when Workplace = Remote only |
| `job_requirements`: no_experience, under_3_years_experience, more_than_3_years_experience, no_degree | ✓ | New "Experience level" criterion (§6) |
| `exclude_job_publishers` | ✓ | Skip low-quality publishers you name |
| Full `job_description`, `job_highlights.Qualifications` | ✓ | Better requirements than our own chunking |
| RapidAPI `/search` returns `data` as a list (vs storefront `data.jobs`) | ? | Adapter accepts both until confirmed |
| `job_salary_currency` present | ? | Pay unknown if absent (never guessed) |
| `OR` in `query` merges roles ("Backend Engineer OR AI Engineer") | ? | Could halve calls (§7.5); test first |
| Failed requests still count at RapidAPI | ? (assume yes) | No retries; count before calling |

## 4. Design principles

1. **Plan before calling.** A scan first builds its plan (deterministic, explainable),
   checks it against the budget, then calls. No call is ever "just to see".
2. **Push filters to the server.** Anything JSearch can filter, it filters; our rules
   only handle what it can't (hybrid vs on-site, excluded words, companies).
3. **Ask only for what's new.** `date_posted` follows each query's last run.
4. **Budget is a first-class resource.** Counted before the call, logged after, never
   exceeded; pacing spreads it over the month.
5. **Measure yield, then adapt.** Calls that keep returning nothing new get rarer; calls
   that keep finding relevant jobs get more.
6. **Free tier only** for now; nothing assumes paid capacity.

## 5. One source: JSearch

**[confirm]** Remove from scanning: Remotive, Arbeitnow, Remote OK, Greenhouse, Lever,
Ashby (company boards) and Adzuna. Proposed handling:

| Item | Proposal |
| --- | --- |
| Adapter code | Deleted (the docstrings' API notes move to `api_references/`), with their tests and fixtures |
| Search Settings → **Companies** section + `companies` table | Removed: JSearch already includes company career sites via Google for Jobs. To focus on an employer, use "Only these companies" in the apply preset |
| Jobs already gathered from those sources | Stay until normally pruned; ledger history kept |
| `[scout.search.sources.enabled]` | Removed (one source); JSearch on/off moves to the JSearch section (§10) |
| `job_sources` table | Kept as JSearch's health row (last success / error) |

## 6. Search criteria → JSearch request (the mapping)

| Search criteria (yours) | Sent to JSearch | If it can't be sent |
| --- | --- | --- |
| **Roles you want** | part of `query`: `"<role> in <place>"` | none: required (no roles = no scan) |
| **Locations** (country / city) | `country=<iso>` + place in `query`; country-level by default, a city only if you list a city | none |
| No Locations | `api_country` (default IN) | none |
| **Job types** | `employment_types` (internship→INTERN, full-time→FULLTIME, part-time→PARTTIME, contract/freelance→CONTRACTOR) | none |
| **Workplace** = Remote only | `work_from_home=true` | Hybrid / On-site: filtered by our rules after the call |
| **Experience level** *(new criterion)*: No experience / Under 3 yrs / Any | `job_requirements=no_experience,under_3_years_experience` (or omitted) | none |
| **Posted within** + query's last run | `date_posted` (smallest bucket covering both) | none |
| Exclude words in title | (calibration: does `-word` work in `query`?) | otherwise our rules |
| Never these companies | none | our rules |
| *(Admin)* Excluded publishers | `exclude_job_publishers` | none |

Everything else (relevance gate, evidence map, apply preset) runs on our side as in Phase 2.

## 7. Query planner and budget

### 7.1 The query set

From the criteria: **one query per role × place.** With your 5 roles and India that is
**5 queries**. Each query is stored (`search_queries`, §9) with its parameters, a stable key
and its yield history, so the plan is the same from scan to scan unless the criteria change.

### 7.2 Budget (backend-enforced)

| Knob (Admin → JSearch) | Default | Meaning |
| --- | --- | --- |
| `monthly_limit` | 200 | Free tier; hard stop |
| `reserve` | 10 | Kept back for calibration / manual tests; not used by scans |
| `pacing` | on | Today's allowance = (limit − reserve − used this month) / days left, rounded up |
| `max_per_scan` | 8 | One scan never spends more than this |
| `pages_policy` | "smart" | 1 page; a 2nd page only per §7.4 |

Guarantees:
- **Count before calling:** the call is recorded (status "sending") *before* the HTTP
  request, inside the pipeline lock, so two scans or a crash can't overspend.
- **No retries.** A 429 ends JSearch for the day; a 401/403 stops it until the key is fixed.
- **Manual Scan now** spends from today's allowance; if it's used up, the scan still runs
  the pipeline on stored jobs and says "JSearch: today's share used; next calls tomorrow".
  **[confirm]** Optionally allow "borrow from tomorrow" with an explicit confirm.

Example for your setup (5 queries, 30-day month, reserve 10 → 190 for scans):

| Use | Requests / month | Jobs returned (max) |
| --- | --- | --- |
| Daily auto-scan, 5 queries × 1 page | 150 | 1,500 |
| Spare for page 2 / manual scans | 40 | 400 |
| Reserve | 10 | n/a |

### 7.3 Incremental `date_posted`

Per query: since its last successful run → `today` (≤ 1 day), `3days` (≤ 3), `week` (≤ 7),
`month` (≤ 31), first run → `month` (or *Posted within* if smaller). Jobs we've seen before
are still returned sometimes; the ledger dedupes them for free.

### 7.4 Which queries get spent today (allocation)

Each scan ranks the queries and spends top-down until the allowance (or `max_per_scan`) runs
out:

1. **Due queries first:** never run, or last run ≥ its interval (default daily).
2. **Score** = staleness × yield, where yield = relevant new jobs per request over the last
   5 runs (a new query starts at a neutral prior).
3. **Back-off:** a query with 0 new jobs in 3 runs in a row moves to every 3 days, then
   weekly; any new hit resets it to daily.
4. **Page 2:** only if page 1 returned 10 results **and** ≥ 5 were new **and** there is
   spare beyond today's due queries.
5. Short allowance → rotation, so every query runs within a few days.

### 7.5 Fewer calls per role (calibration first)

If `"Backend Engineer OR AI Engineer in India"` returns a sensible mix, related roles can
share one query (5 → 2–3 calls per scan). **[confirm]** after calibration (§11) shows the
numbers.

## 8. Getting the most from each response

- **Requirements:** use `job_highlights.Qualifications` (and Responsibilities) as the
  requirement list when present, instead of chunking the description; must/nice from the
  wording as today.
- **Facts from fields, not guesses:** `job_employment_types`, `job_is_remote`,
  `job_country/city`, `job_min/max_salary` + period (+ currency if present),
  `job_posted_at_datetime_utc`.
- **Links:** prefer a direct apply option (`apply_options[].is_direct`), keep
  `job_publisher` ("via LinkedIn"), keep the Google for Jobs link as a fallback.
- **Duplicates:** the same job on several publishers is usually merged by Google; our dedupe
  key (company + title + place) catches the rest. Calibration measures the rate.
- **No `job-details` calls** (1 request per job) in this phase; the search response already
  has the full description.
- Raw response kept for a few days (as now) to re-parse without re-calling.

## 9. Data model

| Table | New / changed | Columns (main) | Why |
| --- | --- | --- | --- |
| `search_queries` | new | `id`, `key` (hash of role+place+params), `role`, `place`, `country`, `params` JSON, `enabled`, `interval_days`, `last_run_at`, `runs`, `results`, `new_jobs`, `relevant_jobs`, `zero_streak`, `created_at` | The plan and each query's yield; survives restarts |
| `api_calls` | new | `id`, `at`, `query_id`, `params` JSON, `page`, `status` (sending / ok / error), `http_status`, `results`, `new_jobs`, `relevant_jobs`, `error`, `scan_id` | Every call logged; month / day usage is counted from here (replaces `meta.jsearch_usage`) |
| `companies` | removed **[confirm]** | | §5 |
| `job_sources` | kept | JSearch health only | |
| `jobs`, `job_ledger`, requirements | unchanged | | Pipeline as Phase 2 |

## 10. UI

- **Search Settings → Search plan** (new card under Search criteria): the requests the next
  scan would make, e.g. `AI Engineer in India · INTERN, FULLTIME · under 3 yrs · last 3 days`,
  each with its yield, next due time and an on/off switch. Shows "next scan: 5 requests ·
  today 6 left · month 174 / 190". Buttons: **Dry run** (builds the plan, calls nothing).
- **Search criteria:** new **Experience level**; hints mark which options are sent to
  JSearch and which are filtered afterwards.
- **Overview:** quota meter (month used / limit, today's allowance, reset date) and a
  per-query yield table; scan history shows requests spent per scan.
- **Admin settings → JSearch** (replaces Sources & APIs): on/off, key status, monthly limit,
  reserve, pacing, max per scan, pages policy, excluded publishers, call log (last 50).

## 11. Calibration (first live calls, ≤ 10, from the reserve)

| # | Call | Learn |
| --- | --- | --- |
| 1 | `AI Engineer in India`, country=in, date_posted=month | Response shape (`data` list vs `data.jobs`), field names, currency, India coverage |
| 2 | Same + `employment_types=INTERN` | Does the filter work for India; how many internships |
| 3 | Same + `job_requirements=under_3_years_experience` | Effect of the experience filter |
| 4 | `Backend Engineer OR AI Engineer in India` | Can roles share a query (§7.5) |
| 5 | Call 1 again with `page=2` | Overlap between pages |
| 6 | `AI Engineer in Bengaluru` | City vs country query |
| 7 | `AI Engineer -senior in India` | Does `-word` exclude |
| 8–10 | Spare | Re-check anything surprising |

Results go into `api_references/jsearch.md` (removing "unverified" marks) and into the
defaults here.

## 12. Build order (each step: tests green + Docker up + checked in the browser)

| # | Build | Check |
| --- | --- | --- |
| 1 | Calibration script (manual, uses the reserve) + update the API reference | Unknowns in §3 settled |
| 2 | Remove other sources, Companies section/table; JSearch adapter accepts both response shapes | Scan calls only JSearch; old jobs still listed |
| 3 | `api_calls` log + budget guard (count-before-call, cap, reserve, pacing, max per scan, no retries) | Simulated month never exceeds 200; concurrent scans safe |
| 4 | Query planner: criteria → `search_queries` + param mapping (§6) + Experience level | Plan matches criteria exactly; unit tests per mapping row |
| 5 | Incremental `date_posted`, allocation + back-off + page-2 rule (§7.3–7.4) | Simulated 30 days with recorded responses: spend ≤ budget, every query runs |
| 6 | Use `job_highlights` for requirements; apply_options / publisher | Evidence map on real JSearch jobs |
| 7 | UI: Search plan card + dry run, Overview quota meter + yield table, Admin → JSearch | Numbers match the call log |
| 8 | Acceptance (§13); docs (`database.md`, `CLAUDE.md`, this file → ✅) | |

## 13. Acceptance test

| # | Do | Expect |
| --- | --- | --- |
| 1 | Search criteria: 5 roles, India, Internship + Full-time, Under 3 yrs | Search plan shows 5 requests with those parameters |
| 2 | Dry run | Plan + cost shown; call log unchanged |
| 3 | Scan now | Exactly the planned requests; each logged; new jobs from JSearch only |
| 4 | Scan now again (same day) | Spends at most the rest of today's allowance; says so |
| 5 | Open a job | Full description, requirements from Qualifications, evidence map |
| 6 | Overview | Quota meter = call log counts; yield per query |
| 7 | Set monthly limit to 3 in Admin, scan | Stops at 3 with a clear message |
| 8 | Restart Docker | Usage, plan and yields persist |
| 9 | `pytest` | Green offline; no test calls JSearch |

## 14. Decisions **[confirm]**

| # | Question | Proposed |
| --- | --- | --- |
| 1 | Remove all other sources (feeds, company boards, Adzuna) from scanning and delete their code? | Yes |
| 2 | Remove the Companies section and table (JSearch covers career sites)? | Yes |
| 3 | Add **Experience level** to Search criteria (sent as `job_requirements`)? | Yes, default "Under 3 yrs" for an internship search |
| 4 | Reserve 10 requests a month for calibration / testing? | Yes |
| 5 | Allow "borrow from tomorrow" on a manual scan (with a confirm)? | No for now |
| 6 | Merge related roles into one query if calibration shows `OR` works? | Decide after calibration |
| 7 | Spend up to 10 live calls on calibration (step 1)? | Yes |

## 15. Risks

- **Google for Jobs coverage for India entry-level roles** may be thinner than hoped;
  calibration shows it before we build the rest.
- **API shape drift** (RapidAPI vs OpenWeb Ninja versions): adapter accepts both; response
  recorded during calibration becomes the test fixture.
- **Quota surprises** (failed calls counted, page counting): count-before-call and no
  retries keep us under the cap even in the worst case.
- **Duplicates across publishers** reduce new jobs per call: measured, and dedupe handles
  them at no extra cost.

## 16. Later

- **Pay-as-you-go** ($0.005 / request = $1 per 200): raise `monthly_limit`; the same budget
  system then caps spending (e.g. 400 = at most $2 a month). Needs a card on RapidAPI.
- `job-details?enrich=true` for top jobs only (AI-extracted skills / seniority / visa).
- Salary endpoints for "expected pay" hints in Phase 3/4.
- **Memory slots** (planned next): each slot brings its own roles, so the planner makes
  queries per slot and the budget is shared across slots by yield.

## 17. Build notes (2026-11-17)

Built: steps 2–7. Waiting: step 1 (calibration) and the acceptance test, which need
`JSEARCH_API_KEY`.

| Piece | Where |
| --- | --- |
| JSearch client (HTTP + field mapping, both response shapes, no retries, direct apply link, highlights) | `backend/services/sources/jsearch.py` |
| Query planner (criteria → searches → params, incremental `date_posted`, due / back-off, scoring, dry run) | `backend/services/search_plan.py` |
| Request budget (count-before-call, monthly cap, reserve, pacing, per-scan cap, 429 pause) | `backend/services/api_budget.py` |
| Scan loop (page 1 for planned searches, then smart page 2 with what's left; relevance credited per request) | `job_search.fetch_jsearch` |
| Requirements from `job_highlights` | `job_text.chunks_from_highlights`, `compass._chunks_for` |
| Calibration tool | `python -m backend.services.jsearch_calibration [--run]` |
| API | `GET /api/scout/search/plan` (dry run), `PATCH /api/scout/search/queries/{id}`, `GET /api/scout/search/calls` |
| UI | Search Settings → Experience level + **Search plan**; Admin settings → **JSearch**; Overview → quota meter |

Removed: Remotive, Arbeitnow, Remote OK, Greenhouse, Lever, Ashby, Adzuna (notes kept in
`api_references/former_sources.md`), the Companies section / API, per-source switches.
Jobs already gathered from them stay until pruned.

Deviations from the plan: none in behaviour. `fetch_runs.company` now holds "N requests"
(the column is reused rather than adding one). Usage is a calendar month in UTC; if RapidAPI
resets on your subscription date instead, the reserve absorbs the difference.

### Added 2026-11-18: OpenWeb Ninja provider + JSearch analytics

- `provider` setting (`openwebninja` default, `rapidapi`): URL + key header per provider.
- `services/jsearch_usage.py`: OpenWeb Ninja `/usage` (plan, period, remaining), refreshed on
  demand (≤ once a minute) and before a scan if older than 6 h; when "remaining" is known the
  budget never plans past it. First live call returned 404 (see `api_references/jsearch.md` §7).
- Sidebar wing "Admin": Admin settings, **JSearch analytics** (`/jsearch`): provider's plan
  view, the app's budget, KPI tiles (requests, jobs returned, new, relevant, per request),
  per-day chart (requests / new / relevant, 7 / 30 / 90 days, table view), searches table,
  recent requests. API: `GET /api/system/jsearch`, `POST /api/system/jsearch/usage`.

### Added 2026-11-18: user decisions, keep-until-decided, "Add title to my roles"

- Every job a request returns is visible: Jobs page tabs **Matches** (undecided relevant;
  fits / other), **Selected**, **Applied**, **Discarded**, **Not relevant**, **Excluded**
  (with the reason).
- `jobs.decision`: selected (the agent's apply list, used from Phase 4) / discarded /
  applied; per job, in bulk, and "Select these & discard the rest" (confirmed).
- **Retention changed:** nothing is deleted unless discarded (after `keep_discarded_days`,
  default 3; the ledger keeps it out). `expire_after_days` (45, by posting age) is a label.
  Fixes the "expired after 7 days unseen" problem, since JSearch asks only for new postings.
- **Add title to my roles** (job row in Not relevant / Excluded, and the job panel): the
  user, not the system, decides which title variants count; the role is added to Search
  criteria, gathered jobs are re-checked, the plan gets a search for it.

### Added 2026-11-18: choose roles per scan, combined OR searches

- Sidebar "Overview" → **Scan Jobs**. **Scan now** opens a picker (roles as checkboxes,
  "Combine into one request (OR)", live dry-run cost). Manual scans are capped by what's left
  today (daily / monthly / provider), not by requests per scan; over budget → refused (400)
  with the reason.
- Automatic scans: Search criteria → **Roles in automatic scans** (`auto_roles`, [] = all) and
  **How automatic scans search** (`auto_mode`): rotate (one role per request, taking turns),
  each (every included role, one request each), combined (one OR request per place).
- A combined search is its own `search_queries` row (`roles` = its role list), so its yield
  is tracked separately and can be compared with single-role searches. At most 8 roles per OR.
- The per-search on/off toggles were removed (the role choice decides now).
- `OR` support in JSearch is unverified; the user's first combined scan will show it.

### Added 2026-11-18: stricter-but-fairer relevance, your override, per-request results

- User report: relevant jobs landed in Not relevant. Real case: "Entry-Level Machine Learning
  Engineer (LLM & AI Agent Specialist)" scored 0.52 (long title blurred) while "Mechanical
  Engineer – Fresher" scored 0.569 against "ML Engineer" (the short form "ML" confuses the
  model). Fix: compare each **part** of the title, drop level / place noise, expand
  abbreviations (roles only expanded). Evaluated on the 17 real jobs: relevant 0.78–1.0,
  unrelated ≤ 0.67 → `role_threshold` 0.72; borderline rescue 0.60 + profile 0.50.
- **Move to matches / Not relevant** per job (`relevance_override`), beats the title check and
  the search criteria; "Let the checks decide" undoes it.
- **Scan Jobs → Requests and what they found**: each request expands to the jobs it returned
  (JSearch's order), what happened to each this time (new / already had / duplicate / too
  old), its title match and where it is now (Matches / Not relevant / Selected...). Table
  `api_call_jobs`.
- Future (agent phase): an LLM reads Matches and Not relevant with the user's context and
  proposes moves, which the user confirms.


**Bug fixed 2026-11-18:** a manual Scan now with 1 role sent 2 requests (call 3 = page 2 of
"AI Engineer in India", 0 results): the smart page-2 rule used the day's allowance instead of
the picker's request count. Manual scans now send exactly the planned requests (test
`test_manual_scan_never_adds_a_page_2`). Cost the user 1 request.

### Added 2026-11-19: Scan now filters, exact request, experience in years

- **Scan now picker** now also shows Locations, Your years of experience, Job types and
  Workplace, prefilled from Search criteria. Changes apply to that scan only
  (`ScanSelection.locations / job_types / workplace / experience_years`;
  `search_plan.for_this_scan`). An "Also save these to my Search criteria" tick saves them
  first. A place your saved Locations don't cover gets a note: its jobs would be Excluded
  by the location rule. A place that can't be resolved gets a note too ("Can't place
  Banglore").
- **The exact request** is shown: under "What will be sent" in the picker (every parameter of
  `GET /jsearch/search`; the key header is never shown) and in each expanded request under
  Scan Jobs → Requests (`components/jobs/RequestParams.tsx`).
- **Experience is a number now**: `criteria.experience_years` (int, empty = any) replaces the
  old `experience` choice (any / no_experience / under_3_years → None / 0 / 2, converted on
  read, including old saved rows). JSearch gets `job_requirements` 0 → `no_experience`,
  1–2 → `under_3_years_experience,no_experience`, 3+ or empty → nothing (JSearch has no
  finer bucket). After the call, jobs asking for more years than this are Excluded.
  UI: a − / + stepper with a text box (`YearsStepper.tsx`).
- **Criteria are provider-neutral; each API adapter translates them.** Years of experience
  (a number) and job types are our only criteria. The translation into JSearch's values
  (`job_requirements`, one of 4 options; `employment_types`) lives in the JSearch adapter
  (`sources/jsearch.py`: `job_requirements()`, `employment_types()`), not in the planner.
  A future API gets its own translation in its own adapter.
