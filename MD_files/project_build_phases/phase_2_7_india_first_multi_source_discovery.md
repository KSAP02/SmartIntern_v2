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
| B1 | Jooble adapter + `api_references/jooble.md` | 0 in build; you run the first live one |
| C1 | Remote feeds with the open-to-India check | 0 (fake responses) |
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
