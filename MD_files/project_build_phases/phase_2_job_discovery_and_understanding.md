# Phase 2: Job Search (discovery → embeddings → evidence map → preferences)

> **Status:** BUILT (2026-11-17). Acceptance test §11 passed 1–11 against live sources
> (API level); 127 backend tests green. Remaining before ✅: your review of the pages in the
> browser. Build notes + relevance evaluation: §14. **[confirm]** = needs your yes;
> **[verify]** = check against current provider docs while building. Blueprint refs: §3–5, §7, §12.
>
> v3 changes: **no LLM on job descriptions by default** (rules + embeddings only, §4);
> **embeddings first, preferences after** as an instant filter view (§4, §5); a
> **Search Settings** (Job Search ▾ in the sidebar) for everything about the search (§7); auto-scan toggle on
> Job Search (§7). v2 kept: lean storage + ledger, dedupe across sources, comparison
> evaluation.

---

## 1. Scope and goal

**Phase 2 = job search and viewing, up to the vector mapping.** Gather jobs, work out
their facts with rules, embed them, keep the ones related to your profile, break each into
requirements, map every requirement to evidence in your memory cards, and let your
preferences filter the view.

**Not in Phase 2:** scoring and Apply / Maybe / Skip (Phase 3), applying and the
**Applications** page (later).

```
 FREE ─────────────────────────────────┐  CHEAP (embeddings) ─────────────────┐  INSTANT ─────────┐
 ① Discover ─▶ ② Dedupe ─▶ ③ Facts by   │ ④ Relevance gate ─▶ ⑤ Requirements ─▶│ ⑦ Preferences    │ ─▶ Jobs list
   sources      (ledger)     rules     │   job digest vs       chunks embedded  │   filter view    │    + evidence
                             (no LLM)  │   memory cards        ⑥ Map to cards   │   (reversible)   │      map
───────────────────────────────────────┘──────────────────────────────────────┘──────────────────┘
 ⑧ Prune keeps the jobs table small.   Optional ⑨ LLM enrich: off by default; at most N top jobs/day.
```

### Expected outcomes (exit criteria)

1. **Scan now** and an **Auto-scan** toggle (daily) pull jobs from the sources enabled in
   Search Settings. Each job is stored once, with its source(s), original link and date found.
2. Job facts (internship / full-time…, remote / hybrid / on-site, country, pay, salary,
   experience, seniority) come from the **source fields + rules**, marked *from source* /
   *from rules*. Unknown stays unknown. **No LLM call per job.**
3. Only jobs **related to your profile** (embedding similarity to your memory cards) go
   further; the rest are skipped with a reason and pruned.
4. Each relevant job shows an **evidence map**: requirement → your best cards, similarity,
   **met / partial / missing / unknown**, plus coverage ("must-haves met 6/8").
5. Options are split by **when** they act, each in one place only: **Search criteria**
   decide what is gathered; the **Apply preset** sorts gathered
   jobs into "Fits your preset" vs "Other relevant". Both default to *All*, show a few core
   options first and hide the rest under "More options".
6. **Job Search → Search Settings** controls criteria, apply preset, sources/APIs, companies, schedule, limits, retention and the
   matching method; no file editing or restart needed.
7. The `jobs` table stays small (ledger + pruning); history per date survives.
8. Matching method/metric/thresholds tested on real JDs; I recommend the best with numbers.
9. Persists across restarts; tests offline with recorded fixtures.

---

## 2. Sources

Adapters returning one `NormalizedJob` shape. Read-only, documented public endpoints only;
attribution + original link stored; fetch limits respected **[verify]**. All switchable in
**Search Settings → Sources & APIs**.

| Source | Type | Coverage | Default |
| --- | --- | --- | --- |
| **Remotive** | public API | remote, global | on |
| **Arbeitnow** | public API | Europe-heavy, remote + on-site | on |
| **Remote OK** | public feed | remote, global | on |
| **Greenhouse / Lever / Ashby** | employer boards | direct employer jobs, incl. India | on, for companies in **Search Settings → Companies** |
| Himalayas, Jobicy | public APIs | remote | added later in the phase |
| We Work Remotely | RSS | remote | later (needs `feedparser`) |
| LinkedIn / Indeed / Naukri | no permitted API | n/a | not supported |

---

## 3. Data model and storage lifecycle

SQLite = source of truth, Milvus = vectors only, UTC timestamps.

### Deduplication

| Case | Example | Detected by | Result |
| --- | --- | --- | --- |
| Same source, again | Tomorrow's Remotive scan returns the same posting | `(source, source_job_id)` in the ledger | No new row; `last_seen_at` updated; reprocessed only if its text changed |
| Same job, other source | Company's Greenhouse board + Remote OK | `canonical_url` or `dedupe_key` (company + title + location) in the ledger | No second row; source added to `seen_on` |
| Already applied / pruned | Job comes back after we deleted it | Same keys, **ledger** (never deleted) | Ignored; ledger `outcome` says why |
| Repost | Same role, new ID | `dedupe_key` / `canonical_url` | Ignored; if older than `repost_window_days` → treated as new but flagged "you applied to a similar role on <date>" |

### Lifecycle

```
 scan ─▶ job_ledger (tiny, forever) ─▶ jobs (full, temporary) ─┬─▶ pruned after N days (not relevant,
                                                               │   expired, hidden, filtered out)
                                                               └─▶ applied (later phase): minimal copy
                                                                   to `applications`, deleted from jobs
```

### 3.1 `job_sources`
`id, name (unique), kind (feed|ats), enabled, terms_url, last_success_at, last_error_at, last_error`

### 3.2 `companies` (ATS registry)
`id, name, normalized_name (indexed), ats_type, board_identifier, careers_url, country_focus, enabled, last_checked_at`

### 3.3 `fetch_runs` (kept: the scan history)
`id, scan_id, scan_date, trigger (manual|auto), source, company_id?, started_at,
finished_at, status, fetched, new, updated, duplicates, already_seen, error`

### 3.4 `job_ledger` (one tiny row per job ever seen, kept)

| Column | Meaning |
| --- | --- |
| `source`, `source_job_id` | Unique together |
| `dedupe_key`, `canonical_url` | Cross-source identity (indexed) |
| `job_id` | → `jobs.id` while the full job exists; null after pruning |
| `first_seen_date` | Date found (indexed) |
| `category`, `workplace_type`, `country`, `relevance` | Copied for analytics after pruning |
| `outcome` | `active` / `not_relevant` / `excluded` (search criteria) / `expired` / `hidden` / `other` / `applied` |
| `updated_at` | |

### 3.5 `jobs` (full data while in play)

| Column | Meaning |
| --- | --- |
| `id` | Also the vector id in Milvus `jobs` |
| `seen_on` | `[{source, source_job_id, job_url}]` |
| `dedupe_key`, `canonical_url`, `content_hash` | Identity / change detection |
| `company_name`, `company_id?`, `title`, `location_text` | As given |
| `description_text` | Plain text (HTML converted; never rendered as HTML) |
| `country_codes`, `remote_regions` | e.g. `["IN"]`, `["US","EU"]`; `[]` = unknown |
| `workplace_type` | `remote` / `hybrid` / `onsite` / null |
| `category` | `internship` / `full_time` / `part_time` / `contract` / `freelance` / null |
| `seniority` | `intern` / `entry` / `mid` / `senior` / `lead` / null |
| `compensation_type` | `paid` / `stipend` / `unpaid` / null |
| `salary_min`, `salary_max`, `salary_currency`, `salary_period` | Only if stated |
| `min_years_experience`, `internship_duration`, `start_date`, `apply_deadline`, `visa_sponsorship` | Only if stated |
| `field_sources` | `{"category": "source" | "rules" | "ai"}` |
| `tags`, `job_url`, `apply_url` | |
| `source_published_at`, `first_seen_at`, `last_seen_at` | |
| `status` | `active` / `stale` / `closed` |
| `pipeline_status` | `new` → `not_relevant` / `relevant` → `mapped`; `failed` |
| `relevance` | Best similarity of the job digest to your memory cards |
| `relevance_card_id` | The card that matched best ("related to: AI / LLM") |
| `hidden` | You hid it |
| `embedding_status`, `raw_payload` (dropped after N days), `created_at`, `updated_at` | |

### 3.6 `job_requirements` (deleted with the job)
`id (= vector id), job_id, section (requirements|responsibilities|nice_to_have|about|other),
importance (must|nice|unknown), text (one chunk: a bullet or sentence), skills (JSON:
vocabulary terms found in it), years?, position, embedding_status`

### 3.7 `requirement_matches`: the middle layer (deleted with the job)
`id, requirement_id (unique), job_id, status (met|partial|missing|unknown), method
(exact_skill|vector|numeric|none), best_card_id, best_score, evidence JSON, memory_version,
computed_at`

### 3.8 `search_preferences` (one row, §6) and `app_settings` (key/value, §7)

### 3.9 Milvus Lite collections (same embedding model → comparable scores)

| Collection | Vector of | Used for |
| --- | --- | --- |
| `memory_cards` (exists) | each card | evidence search |
| `jobs` (new) | job digest (title + location + first ~1,500 chars) | relevance gate; Phase 3 recall |
| `job_requirements` (new) | each requirement chunk | requirement ↔ card mapping |

---

## 4. Pipeline (one scan): no LLM by default

**① Discover (free):** enabled sources/companies; timeout, retries with backoff,
`Retry-After`; generic User-Agent `SmartIntern/0.1`; one failing source never stops the others.

**② Dedupe (free):** against the ledger as in §3; only new or changed jobs continue.

**③ Facts by rules (free)**, then the **search criteria** (Search Settings) (job types,
workplace, locations, posted within, excluded words/companies; §7) drop clear
mismatches *before* any embedding. Jobs whose fact is unknown are always kept at this
stage. Source fields first (many feeds give job type, remote flag,
salary, tags); otherwise rules over title, location and description:

| Fact | Rule examples |
| --- | --- |
| Category | title/description has "intern", "internship" → internship; "contract", "part-time", "freelance" |
| Workplace | source remote flag; "remote", "work from home", "WFH", "hybrid", "on-site", "in office" |
| Country / remote region | location text vs a small country + city list; "Remote (US only)" → `remote_regions = [US]` |
| Pay / salary | source salary fields; patterns like "₹25,000/month", "$90k–110k", "12 LPA", "stipend", "unpaid" |
| Experience / seniority | "3+ years", "0–2 years"; title words "Senior", "Lead", "Junior", "Graduate" |
| Visa | "visa sponsorship available" / "no sponsorship" (else unknown) |

Rules only set a value when the text is clear; otherwise null (unknown). Facts are marked
*from source* or *from rules*.

**④ Relevance gate (embeddings, always on):** embed the job digest → compare with your
enabled memory cards → `relevance` = best similarity (method per §5). Below
`relevance_threshold` → `not_relevant` (reason shown, pruned later).
**Changed while building (see §14):** with **Roles you want** set (Search criteria), the job
*title* is compared with your roles instead (`role_score ≥ role_threshold`, default 0.58);
the whole-profile check is the fallback when no roles are set.

**⑤ Requirements without an LLM (embeddings):** split the description into chunks (bullets
and sentences), tagged by the heading they sit under ("Requirements", "Qualifications",
"Must have" → `must`; "Nice to have", "Preferred", "Bonus" → `nice`; "Responsibilities" /
"What you'll do"; anything else → `unknown`). Skills are spotted in each chunk with a
**skills vocabulary** (your skill items + a bundled tech list + aliases, e.g.
`postgres → postgresql`), so we can also see skills a job asks for that you don't have.
Each chunk is embedded.

**⑥ Map, the middle layer (no LLM):** per chunk: vocabulary skills found in your profile
→ `met` via exact match; otherwise vector evidence over your cards → `met` / `partial` /
`missing` by threshold; "N+ years" vs your `years_experience` → numeric. Per job: a
**coverage summary** (must-haves met / partial / missing, nice-to-haves met, missing
skills). Evidence, **not a score**. Re-mapped automatically when memory changes.

**⑦ Apply preset (instant sorting):** your preferences (§6) split the gathered, relevant
jobs into **"Fits your preset"** and **"Other relevant jobs"** when you look at the list;
later the agent applies only to the first group. Changing the preset never re-processes
anything.

**⑧ Prune:** deletes from `jobs` (+ chunks, matches, vectors) per the retention settings:
`not_relevant`, expired, hidden, and jobs that stayed in "Other relevant" (not fitting your preset) for N days.
The ledger keeps the outcome.

~~**⑨ Optional LLM enrich**~~ **Dropped (2026-11-17):** never built; the unused
`llm_enrich_per_day` setting was removed. Original idea: if rules leave key facts unknown on the
**most relevant** jobs, an LLM can fill them, at most N jobs a day (default
0). Step 7 measures whether rules are good enough; Phase 3 uses the LLM only on a short
shortlist anyway.

---

## 5. Comparing vectors: methods, metrics and how we choose

Milvus offers **COSINE**, **IP** and **L2** for our vectors. OpenAI embeddings are
unit-length, so IP = cosine and L2² = 2 − 2·cosine: **all three give the same ranking**,
just on different scales. They're configurable anyway (a change rebuilds collections
automatically), and the test confirms it. The UI always shows 0–1 similarity.

What actually changes results (all in **Search Settings → Matching**, all tested):

| Setting | Options | Affects |
| --- | --- | --- |
| Metric | COSINE · IP · L2 | Scale only (expected) |
| Match method | hybrid (vocabulary exact match, then vector) · vector · exact | Precision on named skills vs paraphrase recall |
| Aggregation | best card (max) · mean of top-k | One strong card vs broad support |
| Relevance threshold | number | How many jobs pass the profile gate |
| Met / partial thresholds | numbers | Where met / partial / missing split |
| Query context | chunk alone · chunk + job title | Disambiguation |
| Evidence top-k | e.g. 3 | Cards shown as evidence |
| Embedding model | 3-small · 3-large (≈6× cost) | Quality vs cost |

**Evaluation (build step 7):** ~20 real jobs; we label relevance (yes/no) and each
requirement (met / partial / missing), ~15 minutes. A script in
`experiments/compass_eval/` runs every combination, reports accuracy/precision/recall and
score separation, and I recommend one setting; you approve; it becomes the default.

---

## 6. Options: two places, split by *when* they act

Too many choices in one place overwhelms. So every option lives in **exactly one** place,
chosen by when it acts. Each place shows **a few core options first** and keeps the rest
under **More options** (collapsed). Every option defaults to **All**.

```
   SEARCH CRITERIA                         your profile                 APPLY PRESET
   "what to gather"              ─▶   relevance gate + evidence   ─▶   "what to apply to"
   broad, set once, before a scan       (automatic)                    sorts gathered jobs, before applying
```

### 6.1 Search criteria: Search Settings, first section (before gathering)

Broad on purpose: wrong-niche jobs never enter, so everything gathered is already "your
kind of job". Jobs whose value is unknown are **always kept** here (never dropped for
missing data).

| | Option | Choices |
| --- | --- | --- |
| Core | **Job types** | All · Internship · Full-time · Part-time · Contract · Freelance |
| Core | **Workplace** | All · Remote / WFH · Hybrid · On-site |
| Core | **Locations** | All (anywhere) · countries · cities; remote jobs restricted to other regions are dropped |
| More | Posted within | All · 24 h · 3 days · 7 days · 30 days |
| More | Exclude words in title | e.g. "Principal", "Staff" |
| More | Never these companies | e.g. a past employer |

### 6.2 Apply preset: Search Settings, second section (before applying)

Works only on jobs already gathered and relevant. It doesn't remove anything; it sorts the
list into **"Fits your preset (N)"** and **"Other relevant jobs (M)"**. The future agent will
apply only to "Fits your preset". One switch, **Include jobs with unknown details** (default
on), covers all options.

| | Option | Choices |
| --- | --- | --- |
| Core | **Pay** | All · Paid · Stipend · Unpaid |
| Core | **Salary range** | All · min–max + currency + per year / month / hour |
| Core | **Minimum fit** | All · must-haves met ≥ N% (from the evidence map) |
| More | Seniority | All · Intern · Entry · Mid · Senior · Lead |
| More | Experience asked | All · up to N years |
| More | Visa sponsorship | All · I need sponsorship |
| More | Internship duration | All · up to N months |
| More | Start date | All · from / until |
| More | Only these companies | All · list |

A summary line sits on top of each place, e.g. *Gathering: Internship, Full-time ·
Remote, India · everything else All* and *Preset: Paid · ≥ 60 % must-haves · everything
else All*.

**Moved out of My Profile:** the old preferences block (roles, locations, remote,
employment types, minimum salary) is split into the two places above. Work authorization,
notice period and earliest start date stay on My Profile, because application forms need
them. ~~Roles aren't an option any more~~ **Reversed while building (§14):** the profile
gate alone could not decide the role niche on real postings, so Search criteria got
**Roles you want** (Search Settings only, not synced to My Profile).

---

## 7. UI: sidebar, pages, settings

Everything about job search sits under one expandable **Job Search** entry (a layered
dropdown in the sidebar). System stays as it is (Switchboard = status).

```
Insight     Desk
Records     Vault · My Profile · Memory
Utility     Job Search  ▾                        ← Phase 2 (click to expand / collapse)
              Overview          /job-search
              Jobs              /job-search/jobs
              Search Settings   /job-search/settings
            Applications                         ← later phase (hidden until built)
System      Switchboard
```

The group opens automatically when you're on any Job Search page and remembers if you
collapsed it. On phones it's the same list inside the slide-out menu.

### Job Search → Overview `/job-search` (the job search dashboard)

**Auto-scan toggle** (on/off, "next scan 07:00"), **Scan now** with live progress, jobs
pulled per date per source (chart), funnel (found → excluded by criteria → relevant →
mapped → fits your preset), breakdown by category / workplace / country, source health.

### Job Search → Jobs `/job-search/jobs`

Two groups: **Fits your preset** and **Other relevant jobs** (§6.2). Chips per job
(category, workplace, country, pay, found-on, relevance, coverage), quick filters, search.
**Job detail** panel: facts with *from source* / *from rules* badges, plain-text
description, **Requirements ↔ your evidence**, original/apply links, Hide.

### Job Search → Search Settings `/job-search/settings`

**All** job search settings, the search criteria and the apply preset included, on one
page in sections. Core options first, *More options* collapsed. Saved in the **database**
(`app_settings`, `search_preferences`), so changes apply on the next scan with no restart;
`config.toml` only holds the defaults. Precedence: env (secrets/infra) > **saved setting**
> `config.toml` > code. (`CLAUDE.md` §7 gets this rule when built.)

| Section | Settings (defaults) |
| --- | --- |
| **Search criteria** (before gathering) | §6.1: job types, workplace, locations; more options collapsed |
| **Apply preset** (before applying) | §6.2: pay, salary range, minimum fit; more options collapsed |
| **Sources & APIs** | per source on/off, health, terms link; request timeout (20 s), retries (3), max jobs per source per scan (500) |
| **Companies** | registry: add / edit / disable (name, ATS type, board name, careers URL) |
| **Schedule** | auto-scan time (07:00), frequency (daily / every 12 h), recency window for new jobs (30 days) |
| **Limits & retention** | keep not-relevant 3 days, expired 14, hidden 3, "other relevant" 14; raw payload 7 days; repost window 60 days; LLM enrich per day (0) |
| **Matching** | §5 table (metric, method, aggregation, thresholds, query context, top-k) |

Each section has its own **Save**, plus **Reset to defaults**.

Desk gets a small "Job search" tile (found today, relevant, last/next scan).

## 8. API

Wing **`scout`**: rooms **`search`** (jobs, scans, search settings) and **`compass`**
(evidence map). The API follows the page layers: `/scout/search/settings/...` ↔
Job Search → Search Settings.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/scout/search/overview` | Dashboard numbers |
| GET | `/api/scout/search/jobs` | List, grouped *fits preset* / *other* |
| GET / PATCH | `/api/scout/search/jobs/{id}` | Detail / hide |
| POST | `/api/scout/search/scan` | Scan now (background) |
| GET | `/api/scout/search/scans` | Scan history |
| PUT | `/api/scout/search/autoscan` | Toggle auto-scan |
| GET / PATCH | `/api/scout/search/settings` | All search settings, by section (criteria, preset, schedule, limits, matching) |
| POST | `/api/scout/search/settings/reset` | Reset a section to defaults |
| GET / PATCH | `/api/scout/search/settings/sources` (`/{name}`) | Sources on/off |
| GET / POST / PATCH / DELETE | `/api/scout/search/settings/companies` (`/{id}`) | Company registry |
| GET | `/api/scout/compass/{job_id}` | Evidence map for one job |
| POST | `/api/scout/compass/remap` | Re-map all relevant jobs |

## 9. Cost, safety, privacy

- **Per scan: zero LLM calls by default.** Embeddings only: one per new job + one per
  requirement chunk of relevant jobs, roughly a cent per thousand jobs **[verify]** current
  price. The ledger prevents re-embedding jobs already seen.
- JDs are untrusted data; shown as plain text only; never sent anywhere but the embeddings API.
- Attribution + original link always shown; per-source limits respected; no scraping.
- Nothing about you is sent to job sources.

## 10. Build order (each step ends green: tests + Docker up + checked in the browser)

| # | Build | Check |
| --- | --- | --- |
| 1 | Tables; adapter base + Remotive; scan; ledger dedupe; recorded-fixture tests | Second scan creates no duplicates |
| 2 | Other feeds + Greenhouse/Lever/Ashby; cross-source dedupe; stale; pruning | One row per real job; pruned jobs not re-imported |
| 3 | Sidebar *Utility* → **Job Search ▾** (Overview, Jobs, Search Settings); **Search Settings** v1 (`app_settings`: Sources & APIs, Companies, Schedule, Limits); Overview with Scan now; Jobs list/detail | Change a setting in the UI → next scan uses it |
| 4 | Facts by rules (+ tests on tricky postings); digest embedding + **relevance gate** | Unrelated jobs skipped with a reason; facts correct on samples |
| 5 | Requirement chunking + skills vocabulary + chunk embeddings | Sensible chunks + must/nice on samples |
| 6 | **Middle layer**: mapping + coverage + compass endpoints + evidence panel; re-map on memory change | Evidence map on real jobs |
| 7 | **Evaluation**: label ~20 jobs; test all Matching settings; report; set defaults | You approve the recommended setting |
| 8 | **Search criteria** (applied at step ③) + **Apply preset** sections in Search Settings (Fits / Other groups); move fields off My Profile; **Auto-scan** toggle + in-process scheduler; Desk tile | Criteria cut gathering; preset sorts instantly; overnight scan appears |
| 9 | Acceptance test (§11); update `database.md`, `CLAUDE.md`, this file → ✅ | |

## 11. Acceptance test

| # | Do | Expect |
| --- | --- | --- |
| 1 | Search Settings: enable sources, add 3 companies | Saved; health "never run" |
| 2 | Job Search → **Scan now** | Live progress; jobs *found today*; a failing source doesn't stop others; **no LLM calls** |
| 3 | Scan again | No duplicates; two-source job shows both in "seen on" |
| 4 | Overview | Pulls per source per date; funnel adds up |
| 5 | Jobs (no preferences) | Only profile-related jobs; unrelated ones skipped with reason |
| 6 | Open a job | Facts with source/rules badges; requirements with must/nice; evidence map + coverage |
| 7a | Search Settings → Search criteria: Internship + Remote → Scan | Only internships/remote (plus unknowns) are gathered |
| 7b | Search Settings → Apply preset: Paid + ≥ 60 % must-haves | Jobs split into "Fits your preset" / "Other relevant" instantly; back to All puts everything in Fits |
| 8 | Disable a skill card / rebuild memory | Affected jobs re-map |
| 9 | Toggle **Auto-scan** on; set time a few minutes ahead in Search Settings | Scan runs by itself; shows as *auto* in history |
| 10 | Hide a job; prune with hidden = 0 | Gone; history unchanged; not re-imported |
| 11 | Restart Docker; `pytest` | All still there; tests green offline |

## 12. Decisions before step 1 **[confirm]**

Everything about sources, companies, schedule, limits and matching is now a **setting
with a default**, changeable in the app any time, so those aren't decisions anymore.
Only these remain (reply "yes" to all, or per number):

| # | Question | Proposed |
| --- | --- | --- |
| 1 | OK to add **`beautifulsoup4`** (job-page HTML → plain text)? | Yes |
| 2 | ~~Sidebar~~ **decided:** Utility → Job Search ▾ → Overview / Jobs / Search Settings | ✅ |
| 3 | ~~Settings storage~~ **decided:** saved in the DB, `config.toml` = defaults | ✅ |
| 4 | ~~Preferences~~ **decided:** moved into Search Settings (search criteria + apply preset); form facts stay on My Profile | ✅ |
| 5 | No LLM in Phase 2 by default (rules + embeddings; optional enrich stays at 0/day)? | Yes |

## 13. Later phases (context)

- **Phase 3, scoring:** score from the evidence map + relevance + preference "Prefer"
  boosts → LLM judge only on a short shortlist → **Apply / Maybe / Skip**; skills-gap view.
- **Applications (Utility → Applications):** prepare → approve → apply → track; applied
  jobs move to the lean `applications` table.

---

## 14. Build notes and evaluation (2026-11-17)

**Live run.** First scan pulled 1,701 postings from all six sources (Remotive 17,
Arbeitnow 500, Remote OK 97, Greenhouse/Anthropic 500, Lever/Spotify 87, Ashby/OpenAI 500):
899 too old, 8 cross-listings merged, 794 new. Second scan: 0 new, 795 unchanged (dedupe ✓).
Cost: embeddings only (`text-embedding-3-small`), about $0.01 for the first scan.

**Relevance gate: profile similarity failed, title-vs-roles works.** With real OpenAI
embeddings every job digest scored 0.20–0.63 against the profile; 690/794 passed 0.35, and an
accountant, a sales manager and a clinical data manager were "related". You labelled 16
jobs across the score range and kept only *Backend Engineer, AI Systems*; UX designer (0.526)
and CEO (0.524) out-scored engineering roles, so **no threshold could separate them**.
Comparing the **title** with your roles separated them cleanly (your "yes" 0.78, best "no"
0.60). With your roles (Backend / AI / LLM / Software / ML Engineer) the boundary sits at
**0.58**: developer and AI-engineer titles 0.585–1.0 kept; service desk, sales engineer,
architect titles 0.51–0.576 dropped. "AI / LLM Engineer" as one phrase embedded poorly, so
it is stored as two roles. Seniority (VP / Head of Engineering pass the title check) is the
apply preset's job.

**Fixed after the live run**
- Company boilerplate counted as requirements: an inline label ("Minimum education: …")
  switched the chunker into *requirements* for every following line, so Anthropic's
  Logistics block (visa, hybrid policy, EEO) became ~10 must-haves in 120+ jobs. Inline
  labels now apply to their own line (they open a section only when ending in ":"),
  "Logistics" is a legal/process heading, and more boilerplate patterns are recognised
  (apply-even-if, Fair Chance, compensation-range text, Arbeitnow footers).
- Stored requirements are re-chunked when the chunker's output changes (were reused forever).
- Race: a remap working from a stale job list undid a criteria exclusion saved meanwhile.
  Scans, remaps and settings effects now share one re-entrant `pipeline_lock`.
- Remote OK serves double-encoded UTF-8 ("partnerâs"): repaired per byte run
  (`fix_mojibake`), genuine accents untouched.
- Overview crashed (single-column select unpacked as a tuple).
- `init_db` adds new nullable columns to existing tables (`role_score`, `role_match`).

### Admin settings (2026-11-17, your request)

Sources & APIs, Schedule, Limits & retention and Matching moved out of Search Settings into a
new sidebar page **System → Admin settings** (`/admin`), together with **Models** (LLM +
per-task overrides + embeddings). That page *is* `settings/config.toml`: one **Save & apply**
bar writes only the changed keys (comments and line endings kept, via `tomlkit`), and edits
made in the file show on the page within seconds. Per-source on/off moved into the file too.
Search Settings keeps Search criteria, Apply preset and Companies. "LLM enrichments per day"
was removed (never built). Values previously saved in the DB were moved into the file once,
on start-up.


### India coverage (2026-11-17)

Of 827 gathered jobs only 3 were in India (sources are US/EU-centric), and ~10 on-site jobs in
small German/French/Swiss towns slipped past Locations = India because their location couldn't
be read ("unknown is kept"). Fixes: Search criteria → **Keep jobs with an unknown location**
(off by default once Locations is set), ~150 more European cities/regions and local-language
country names ("Schweiz", "Frankrijk"); and a new source, **Adzuna** (job search API with an
India site): one search per *Roles you want* per country in Locations (`adzuna_country`
fallback, default IN). Adzuna returns only a description snippet (thin evidence map, flagged
on the job), drops predicted salaries, and needs `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` in `.env`
(skipped and shown as "API key missing" until set).

**JSearch added (2026-11-17).** Adzuna's free signup allows only 25 test calls before a card
is required, so **JSearch** (RapidAPI; Google for Jobs: LinkedIn, Naukri, Indeed, company sites)
was added as the main India source: one request per role per place, **full descriptions**
(real evidence maps), monthly cap `jsearch_monthly_limit` (default 200 = the free plan), paced daily (left / days left, ~6 a day) with role rotation, counted in
`meta.jsearch_usage`, no retries (they'd spend quota). Key: `JSEARCH_API_KEY` in `.env`.
`adzuna_country` became `api_country` (shared by both search APIs).
