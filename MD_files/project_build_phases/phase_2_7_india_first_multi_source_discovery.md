# Phase 2.7: More sources for jobs in India

> **Status:** 📝 PLAN, rewritten 2026-11-20 after the feasibility review and the user's scope:
> *"We are mainly targeting jobs in India. Remote is fine, but let's not get into international
> APIs: if an API or source offers both India and international, that's fine; international
> only is not okay."* Decisions D1–D5 below are pending. Nothing is built yet.
> Real requests to any source are made only by the user. Tests use fake responses.
> Previous version (2026-11-19, "jobs from anywhere"): replaced by this one.

**Goal:** more real, current jobs **in India (or remote and open to India)** for your roles,
**prioritising jobs the agent can apply to by itself**: an open application form (ATS) that
needs no login or account creation, on a posting that is still live.

> **Why (user, 2026-11-20):** "Eventually we need to automate making applications, so we can't
> be stuck on expired jobs or login / account-creation jobs, which JSearch mostly brings. We
> need to hit jobs which are forms the agent can fill in. When the agent tries to apply and
> can't, the user applies manually later, and the agent automatically applies to the rest."
> So the target flow (Phases 4–6) is: agent tries every selected job → applied, or "needs you"
> (with the reason and the link) → you apply to those by hand.

**Not in this phase:** changing the matching. The 2.6 pipeline (title check, role context
score, evidence) runs on whatever is collected, unchanged. Search criteria keep shaping the
search only; they never remove a job (decided 2026-11-20).

---

## 0a. Apply route: the first thing we know about a job

Every job gets an **apply route** when it's stored (all sources, JSearch included: its
`apply_options` links often point at an ATS):

| Route | Meaning | Agent can apply? |
| --- | --- | --- |
| `form:<ats>` | Public ATS form, no account: Greenhouse, Lever, Ashby (+ SmartRecruiters, Workable, Recruitee: **to verify**) | ✅ target |
| `account:<ats>` | ATS that makes you create an account first: Workday, Taleo, SuccessFactors, iCIMS (**to verify** per ATS) | ❌ → "needs you" |
| `direct` | Employer's own site, unknown form | maybe (try, else "needs you") |
| `aggregator:<name>` | Jooble, Kit Job, … (redirects; often ends on a login platform) | ❌ unless it resolves to a `form:` link |
| `platform:<name>` | LinkedIn, Naukri, Internshala, Indeed (login) | ❌ never automated |

- Shown on every job, with a **"Agent can apply" filter** on the Jobs page, and counted per
  source in the analytics (share of `form:` jobs = how useful a source is for automation).
- **Live check:** board sources only list open postings; before applying (later phases) the
  posting is re-checked and an expired one is marked, not applied to.

## 0. Scope rule (applies to every source)

| A source is… | In scope? |
| --- | --- |
| India-only, or India among other countries (we ask it for India) | ✅ |
| Remote jobs, when a job is open to India (worldwide, APAC, "India") | ✅ (only those jobs) |
| International only (no India jobs, or remote limited to other regions) | ❌ |
| Login-walled platforms (LinkedIn, Naukri, Indeed, Glassdoor, Internshala, Instahyre, foundit) | ❌ no scraping (terms, bans). They still reach us through JSearch (Google indexes many of their jobs). |

So every source either takes India as a parameter (search APIs) or its jobs pass the
**India scope check**: located in India, or remote and open to India. Jobs outside that scope
are counted in the per-source analytics, not stored.

---

## 1. Why more than JSearch (evidence)

- The first 32 stored jobs all came from JSearch (`country=in`); **21 were Jooble listings**.
  So Jooble holds much of the same India pool, with its own quota.
- No job had a direct employer or ATS link: JSearch mostly finds aggregator copies.
- JSearch: 200 requests a month, about 0.5 relevant jobs per request in the first 10.
- Phase 2 measurement (former sources): of 827 jobs from Remotive, Remote OK, Arbeitnow,
  Greenhouse, Lever and Ashby, **3 were located in India**. How many were remote and open to
  India wasn't measured; remote feeds are therefore last in line and measured before kept.

---

## 2. Sources, in build order

Order decided 2026-11-20: **form-first**. Company ATS boards give `form:` jobs directly and only
list open postings, so they come first; Jooble (an aggregator: mostly `aggregator:` routes) is
second.

| Stage | Source | Kind | India coverage | How | Cost / quota | Status of facts |
| --- | --- | --- | --- | --- | --- | --- |
| — | **JSearch** (existing) | search API | `country=in` + place in the query | as today | 200 / month free | known |
| B | **Jooble** | search API | India + other countries; asked with an India location | `POST https://jooble.org/api/<key>` with keywords + location (per their docs) | free key on request; quota **to verify** | **to verify** with the user's key + terms → `api_references/jooble.md` |
| B (research) | **Careerjet** | search API | India site (careerjet.co.in) among others | partner / affiliate API | **to research** | unverified |
| A | **Company ATS boards**: Greenhouse, Lever, Ashby, SmartRecruiters (Workable, Recruitee next) | board (all of one company's jobs; `form:` routes) | companies hiring in India; each job checked by the scope rule | one public GET per company (endpoints in `api_references/former_sources.md`) | free | known (Phase 2) |
| A (research) | India-common ATS / HR systems with public careers pages: Zoho Recruit, Keka, Darwinbox, Freshteam | board / page | India-first | **to research**: public JSON or only HTML? | free | unverified |
| C | **Remote feeds**: Remotive, Remote OK, Himalayas, Jobicy, We Work Remotely | feed | only jobs remote **and open to India** | GET / RSS; attribution as each requires | free | Remotive / Remote OK known; others to verify |
| D (only if A–C leave gaps) | **Careers-page reader** (schema.org `JobPosting` JSON-LD that sites publish for Google) | page | Indian company sites you add | you paste a careers URL; robots.txt respected; slow and polite | free | design only |
| ❌ | Arbeitnow (Europe), Adzuna (25 free calls then a card; snippets), US-only boards, scraping LinkedIn / Naukri / Indeed | — | — | — | — | out of scope |

---

## 3. Design

**Principle (user, 2026-11-20): every source works the way JSearch does now, and the user does
as little as possible.** One **Scan now** button collects from every enabled source. The scan
options are shared by all sources; a source gets extra options only when it truly needs them.
Everything we built for JSearch is reused per source, not reinvented:

| JSearch today | Every source in 2.7 |
| --- | --- |
| Scan now: roles, location, date posted, editable query, exact request shown | The **same** shared options drive every source; each source's exact request(s) shown under it |
| Dry run (`POST /plan`) before spending anything | One dry run for all sources: what each will call and what it costs |
| Request budget (monthly, per day switch, reserve, per scan) | The same budget settings **per quota'd source** |
| Every request logged before it's sent (`api_calls`) | Same log; `api_calls.api` = the source |
| Requests and what they found; Why these results | Same, for every source's requests |
| JSearch analytics | One analytics page with a per-source table (+ each source's own detail) |
| Search criteria shape the scan, never remove a job | Same; only the India scope + title pre-check for board / feed sources (§0) |
| Admin → JSearch section | Admin → **Sources**: one row per source (on/off, budget, last run, last error) + a section for a source's own settings |

```
Scan now / automatic scan
        │  roles, location (India place), date, query text
        ▼
┌──────────────────── collector ────────────────────┐
│ search sources (JSearch, Jooble): one request per │  ← query + India location as parameters
│   role × place, each within its own budget         │
│ board / feed sources: fetch, then the India scope  │  ← title matches a role (word match, no
│   check + title pre-check (cheap, before storing)  │    embeddings) AND India / remote-open-to-India
│ dedupe → store (jobs + job_ledger, seen_on)        │
└────────────────────────────────────────────────────┘
        ▼
existing 2.6 matching → Matches / Not relevant
```

- **Source contract.** One module per source in `backend/services/sources/`: `name`, `kind`
  (`search` | `board` | `feed` | `page`), `fetch(...) -> list[NormalizedJob]`, built on the
  existing `SourceHttp` + `NormalizedJob`; a registry lists them. Adding a source = one file +
  one registry line + its config section.
- **Budget per source.** `api_budget` today counts only `jsearch`; it becomes per source
  (`api_calls.api` already stores the source name). Each quota'd source has its own monthly /
  daily limits and the same "Limit requests per day" switch. Free sources: a politeness delay.
- **Pre-check for board / feed sources only** (they can't take a query and return everything):
  keep a job if its title matches one of your roles or their search titles (word match after
  the abbreviation expansion) **and** it passes the India scope check. Search sources need no
  pre-check: the query already narrows them. This is a scope rule, not a criteria filter.
- **Dedupe.** The existing company + title + location key, plus a normalised apply-URL match.
  One opening from several sources keeps them all in `seen_on`.
- **Scan now (one button for all).** Same layout as today: Roles, Location, Date posted, Query.
  Below them, **Sources**: every enabled source ticked by default (untick to skip one this
  time), each with a one-line summary of what it will do ("JSearch: 1 request · 18 left today",
  "Jooble: 1 request", "Companies: check 12 boards (free)", "Remote feeds: 3 feeds (free)").
  The shared query text is used by every search source; a source's own options (e.g. its own
  query text if its syntax differs, or which companies to check) sit in a collapsed "More"
  under that source. The exact request(s) of each source are shown as for JSearch today.
  Automatic scans use the same plan with every enabled source.
- **Analytics.** A per-source table: fetched, outside India scope, kept, new (not a duplicate),
  reached Matches, applied. That decides which sources stay.
- **Companies list (Stage B).** Table `employers`: name, `kind` (greenhouse | lever | ashby |
  smartrecruiters | …), board id, enabled, last checked, last error, jobs found / kept. Search
  Settings → Companies: paste a careers URL; the kind and board id are read from it. Claude can
  draft a starter list of companies hiring in India on these ATSs; each is enabled only after
  you check it.
- **Apply route per job (Stage B, data only):** `ats:<kind>` | `direct` | `aggregator:<name>` |
  `platform:<name>`, shown on the job; groundwork for applying in later phases.

---

## Decisions (2026-11-20)

| # | Question | Decision |
| --- | --- | --- |
| D1 | Order | **Form-first**: A0 shared source structure + apply route for every job (JSearch included); A company ATS boards + Companies list; B Jooble; C remote feeds (open-to-India only, kept if the analytics show India-open jobs); D careers-page reader only if needed. |
| D2 | Jooble key | ✅ The user requests a free key and adds `JOOBLE_API_KEY` to `.env`; Claude records terms / quota in `api_references/jooble.md` and builds against fake responses; the user runs the first live request. |
| D3 | Company list | ✅ Claude drafts a starter list (India-hiring companies on Greenhouse / Lever / Ashby / SmartRecruiters, board links); each is enabled only after the user checks it. |
| D4 | Remote jobs | ✅ Kept only when open to India (worldwide, APAC, India); others counted, not stored. |
| D5 | India-common ATSs (Zoho Recruit, Keka, Darwinbox, Freshteam), Careerjet, and which ATSs need an account | Research first (public JSON? form without login? terms?), recorded in `api_references/`, then decide per source. |

---

## Build steps

| Step | What | Real requests |
| --- | --- | --- |
| A0 | Source contract + registry; JSearch moved onto it unchanged; budget per source; per-source analytics; Scan now source ticks (one button for all); **apply route** for every job (JSearch's `apply_options` classified) + "Agent can apply" filter | 0 |
| A1 | `employers` table + Companies page (paste a careers link → ATS + board id); Greenhouse, Lever, Ashby, SmartRecruiters adapters; India scope + title pre-check | 0 (fake responses) |
| A2 | Starter company list (draft → your check); research which ATSs need accounts (D5) | your clicks |
| B1 | Jooble adapter + `api_references/jooble.md` — **parked 2026-11-22** (user): an aggregator gives few jobs the agent can apply to | — |
| A3 | Find companies automatically from stored jobs' apply links (built 2026-11-22) | 0 |
| A4 | Workable + Recruitee boards (built 2026-11-22); Rippling researched, **not built** (apply flow unconfirmed) | 0 (fake responses) |
| C1 | Remote feeds with the open-to-India check (built 2026-11-22: Himalayas, RemoteJobs.org, Remotive) | 0 (fake responses) |
| E | **Company finder** (seed list + careers pages + name guesses + Common Crawl index), Indian boards Keka / Darwinbox / Zoho Recruit, board read schedule, SmartRecruiters India filter, JSearch "new since last run" default, one row per scan in the request log (built 2026-11-22) | 0 (fake responses); finder runs are the user's |
| — | **You:** scan with the enabled sources, read the per-source table (incl. share of `form:` jobs) | your choice |

## Acceptance

- One scan can collect from every enabled source; the dry run shows which sources will be
  called and how many quota'd requests each will use; JSearch works exactly as before.
- Every stored job is in India or remote and open to India; the same opening appears once,
  with all its sources.
- Adding a source is one file + a registry line + its config section.
- The per-source table shows fetched / outside scope / kept / new / reached Matches / applied,
  and the share of jobs with a `form:` apply route.
- Every job shows its apply route; the Jobs page can filter to "Agent can apply".
- Matching (2.6) is unchanged and runs on jobs from every source.

## Later

- Job-alert emails from LinkedIn / Naukri / Internshala (needs mailbox access + one parser per
  sender).
- Fuzzy and description-based dedupe, if the analytics show missed duplicates.
- Phase 3: an agent that selects like you (LLM judge per job, shadow mode first). Phases 4–6:
  applying, `ats:*` routes first; never bypass CAPTCHAs / bot checks, never automate LinkedIn /
  Naukri / Indeed.

---

## Build notes

### A0 built 2026-11-20

- **Source contract + registry:** `sources/base.py` `SourceAdapter` (name, label, kind
  search|board|feed|page, quota, terms_url, env_keys, configured()); `sources.SOURCES` (JSearch
  only; `ADAPTERS` kept as an alias). JSearch's scan flow unchanged.
- **Budget per source:** `api_budget.quota / reserve_call / recent_calls / blocked_until` take
  `api` (default `jsearch`); JSearch-only parts (billing period and remaining quota from OpenWeb
  Ninja) apply to JSearch only.
- **Apply route:** `services/apply_route.py` (host rules: form = Greenhouse, Lever, Ashby +
  SmartRecruiters, Workable, Recruitee *to verify in A2*; account = Workday, Taleo,
  SuccessFactors, iCIMS, Oracle; platforms = LinkedIn, Naukri, Indeed, Glassdoor, Internshala,
  foundit, Instahyre, Wellfound, Shine, apna, hirist, Cutshort, iimjobs, TimesJobs; known
  aggregators; employer site = the source says direct or the company name is in the host; else
  aggregator). `NormalizedJob.apply_links`; JSearch fills it from `apply_options` +
  `job_apply_link`. Stored on `jobs.apply_route` / `apply_route_url`; best route kept; start-up
  re-derivation (`apply_routes_if_needed`, meta `apply_route_version`).
- **Jobs page:** "Apply via" filter (`GET /jobs?apply=form|direct|account|aggregator|platform`),
  a route badge on each row (green for "Agent can apply"), "How to apply" line in the job panel.
- **Scan now:** a Sources list (`SearchPlanOut.sources` / `PlanSource`): each source ticked by
  default with a one-line summary; `ScanSelection.sources` (None = all enabled; [] = nothing,
  refused).
- **Analytics:** JSearch analytics → "By source" (`by_source` / `SourceYield`: requests,
  returned, new, jobs, in Matches, applied, agent can apply).
- Tests: `test_sources_a0.py` (8); backend 197 green.
- Live labelling of the 81 stored jobs: 46 job board (Jooble 22, Shine…), 27 login platform
  (LinkedIn 10…), 8 employer site, **0 company forms**: JSearch alone gives the agent nothing to
  apply to, which is what A1 (company boards) is for.

### A1 + A2 built 2026-11-20

- **Companies:** `employers` table; Search Settings → **Companies** (paste a careers link → ATS +
  board id via `sources.parse_careers_url`; switch on/off; **Check** reads the board once and
  says found / in India / would keep, storing nothing; remove; "Add starter list").
  API `/api/scout/search/companies` (GET, POST, PATCH, DELETE, `/{id}/check`, `/starter`).
- **Adapters** (kind `board`, free): `sources/greenhouse.py` (+ EU boards), `lever.py`,
  `ashby.py`, `smartrecruiters.py` (details only for pre-checked jobs), base `sources/boards.py`;
  registered in `sources.SOURCES` / `BOARDS`. Reference: `api_references/ats_boards.md`.
- **Pre-check** (`services/employers.precheck`): India or remote open to India (unknown kept,
  via `job_facts.location_match(["IN"], …)`) AND the title contains every distinctive word of a
  role or one of its search titles (abbreviations expanded; back-end = backend). No roles = all.
- **Scan:** `employers.collect` after JSearch: every switched-on company, `delay_seconds` apart;
  each board read logged in `api_calls` (api = ATS) with `skipped_scope` / `skipped_title`;
  stored like any job (dedupe, title gate, role context); postings gone from their board →
  expired. Scan now: one **Companies** row ("check N companies · free"), can be unticked; a
  scan may be companies-only. Requests and what they found + "Why these results" cover board
  reads. Config `[scout.search.boards]`: enabled, delay_seconds, timeout_seconds,
  max_details_per_board.
- **A2:** starter list of **34 companies** (12 Greenhouse, 9 Lever, 8 Ashby, 5 SmartRecruiters)
  from web search, each board URL seen in results, none fetched; added switched off.
  Research (account needed? CAPTCHA? India-common ATSs) in `api_references/ats_boards.md`;
  `apply_route` rules updated (Greenhouse EU hosts). No adapter for Zoho Recruit / Keka /
  Darwinbox / Freshteam (HTML-only or unverified); Rippling ATS is the best next board candidate.
- Tests: `test_boards_a1.py` (9); the shared test setup now clears companies (a leftover company
  made later test scans try a real board once during development; fixed). Backend 205 green.

### Changed 2026-11-20 (user): the system manages the companies

*"We don't want to give the user the power to decide on job boards; let the system take care.
It should be a tick box like for JSearch, so the user knows where jobs are fetched from and can
decide during the scan."*

- Search Settings → Companies removed (the API stays, unused by the UI).
- The starter list is the system's company list: added **switched on** on start
  (`employers.sync_starter`, meta `starter_companies_version`); a board that answers "not found"
  is switched off by the system and stays off.
- Scan now → Sources: **one tick box per source** (JSearch, Greenhouse, Lever, Ashby,
  SmartRecruiters), each board showing "N companies · free" and the company names;
  `ScanSelection.sources` takes these names. The Scan button reads "Scan (1 request + 34 companies)".
- Tests: company boards are off in the test config (conftest) and switched on only by tests that
  fake every board. Backend 206 green.

### A3 + A4 + C1 built 2026-11-22

User (2026-11-22): leave Jooble out for now; build the rest; research Rippling and build it only
if the agent can apply without an account, otherwise report the caveats.

- **A3 — companies found automatically** (`employers.discover`, run in every scan after the
  searches and feeds, before the boards): every stored job's links (best apply link, apply /
  posting URL, `seen_on` URLs, JSearch `apply_options` while the raw record is kept) go through
  `sources.parse_careers_url`; a board we read that isn't in `employers` is added
  (`origin = "discovered"`, `found_via_job_id`, note "Found through ..."), at most
  `max_new_per_scan` (10) per scan. Nothing is fetched to find them. Its first board read in the
  same scan is the check: no job in India -> switched off at once; later, no India jobs for
  `drop_after_empty_scans` (3) scans in a row -> switched off. A switched-off found company is
  tried again after `retry_after_days` (30) if a job links to it again; a board that's gone
  (404) never. Scan totals `companies_found` / `companies_dropped`. Scan now's board rows say
  "N companies (M found by the app) · free". Config `[scout.search.boards]` discover,
  max_new_per_scan, drop_after_empty_scans, retry_after_days. DB `employers.found_via_job_id`,
  `empty_scans`.
- **A4 — Workable + Recruitee boards** (`sources/workable.py`, `recruitee.py`, kind board):
  Workable v1 widget `apply.workable.com/api/v1/widget/accounts/{sub}?details=true` (in
  Workable's help centre); Recruitee Careers Site API `{company}.recruitee.com/api/offers/`
  (documented). No starter companies on them: they fill up through A3. **Recruitee caveat:**
  from 10 Feb 2027 that API needs the company's own token (401 without it); then reads fail and
  Recruitee needs another route (careers page / XML feed). Research: `api_references/ats_boards.md`.
- **Rippling: not built.** A keyless jobs JSON exists (`api.rippling.com/platform/api/ats/v2/board/{slug}/jobs`)
  but is undocumented, needs a detail call per job, slugs are case-sensitive and often hidden
  behind custom careers domains, and whether its apply form needs an account / has a CAPTCHA
  could not be confirmed. Revisit when Phase 6 (applying) can test one form by hand.
- **C1 — remote feeds** (`sources/feeds.py` base, `himalayas.py`, `remotejobs.py`,
  `remotive.py`, kind feed; `services/remote_feeds.py`): one tick box each in Scan now under
  "Remote feeds · open to India". Himalayas and RemoteJobs.org: one request per role of the
  scan (`max_queries_per_feed` 5) with `country=IN` on their side; Remotive: one request for its
  software category, at most every 8 h (its terms). Each feed's own eligibility field decides
  "open to India" (Himalayas `locationRestrictions` empty or with IN; RemoteJobs.org
  `location_normalization`; Remotive `candidate_required_location` free text: worldwide /
  anywhere / Asia / APAC / India), then the title pre-check. Logged in `api_calls`; "Why these
  results" for feeds. A feed link to an ATS form makes a `form:<ats>` job **and** feeds A3.
  Skipped: Jobicy (India not a geo option; endpoint changing), We Work Remotely (terms forbid
  storing), Remote OK (location mostly empty), Working Nomads (no docs / terms). Reference:
  `api_references/remote_feeds.md`. Config `[scout.search.feeds]`.
- **Credit:** the job panel's "Seen on" shows the source's name linking to its job page (the
  feeds' terms ask for a visible credit + link back).
- Request log rows carry `source_kind` / `source_label` (search | board | feed); Scan now groups
  its Sources list (Job search / Company boards / Remote feeds); the Scan button reads
  "Scan (N requests + M companies + K feed reads)".
- Tests: `test_discovery_a3.py` (4), `test_feeds_c1.py` (6); feeds off in the test config.
  Backend 216 green. Feed and Workable / Recruitee response shapes come from docs and
  open-source code, **not verified live**: the user's first scan is the check. (Feeds verified by
  the user's scan of 2026-11-22 12:50: Himalayas 20 listed / 5 kept, RemoteJobs.org 50 / 9,
  Remotive 16 / 1.)

### E built 2026-11-22: finding companies, Indian boards, a leaner fetch

User (2026-11-22): boards only cover companies we know; we need companies all over India; find
them, fetch only relevant jobs, don't waste calls; legal and free; research first; build steps
1–4 (research, company finding, Indian systems, fetch efficiency); no deploy / push until tested
on localhost. Recommendations taken: finder runs in the background (and after each scan), ~300+
seed companies, Common Crawl included.

- **Research** (`api_references/indian_ats.md`, `common_crawl.md`): Keka, Darwinbox, Zoho Recruit
  have keyless public job lists that robots allows, but every application form has a CAPTCHA or
  OTP → built **for finding only** (apply route `account:<kind>`, "you apply" in Scan now).
  Freshteam is being retired (skipped); TurboHire no public pattern. Common Crawl's CDX index is
  free, its terms allow it (no personal data taken), heavily rate limited.
- **Company finder** (`services/company_finder.py`, table `company_leads`): leads from the seed
  list (`services/seed_companies.csv`: 407 Indian unicorns, startups, product companies and
  global companies with Indian engineering; compiled from Wikipedia / YC / public lists, domains
  partly from memory — a wrong one only means no board is found) and from the Common Crawl index
  (`services/crawl_index.py`: board addresses under each system's host, a few index pages per
  run, position kept in `meta`). Per lead, cheapest first: board already known → the company's
  careers page (robots.txt honoured; links, iframes and scripts searched for a board link) → its
  name tried on each system (greenhouse, lever, ashby, keka, darwinbox, workable,
  smartrecruiters, recruitee; ≥ 4-character ids only). The board is read once with the scan's
  pre-check: jobs in India → an `employers` row (origin discovered) that every scan reads; else
  re-checked after 30 days (no board: 90). Background thread; one request at a time with a delay;
  stores no jobs (the next scan does). Scan Jobs → **Company finder** card: status, counts,
  web-index progress, companies kept, **Find companies**. Starts after every scan
  (`run_after_scan`). Config `[scout.search.finder]`. API `GET /api/scout/search/finder`,
  `POST .../finder/run`.
- **Fetch efficiency:** boards with no job matching your roles are read weekly, not every scan
  (`employers.next_read_at`, `quiet_board_days` 7; all due again when your roles change; Scan now
  says "N more read weekly"); SmartRecruiters asks for `country=in` only; Lever's location filter
  is exact-match only (not used). Change detection (ETag / 304) researched but unverified →
  not used. JSearch: Scan now's Date posted defaults to **"New since this search last ran"**
  (the automatic-scan window), so a manual request doesn't re-fetch jobs already found.
- **Request log:** "Scans and what they found" = one row per scan (`GET .../scan-requests`), its
  requests grouped JSearch / each board system with its companies / feeds; "Recent scans"
  removed.
- Tests: `test_finder_e.py` (8) with trimmed real Keka / Darwinbox / Zoho responses
  (`tests/fixtures/indian_ats/`); finder off in the test config. Backend 224 green.
- **Not verified live:** the finder's careers-page reading and name guessing against real sites,
  and the Common Crawl paging (its server answered 504 during research). The user's first
  **Find companies** run is the check.
