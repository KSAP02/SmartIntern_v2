# Company job boards (ATS) — Phase 2.7 A1 / A2 / A4

Public, unauthenticated job-board APIs read by `backend/services/sources/{greenhouse,lever,ashby,smartrecruiters}.py`.
One company = one board; a board lists **only open postings**. Free, no key, no quota. Polite:
one company at a time with `[scout.search.boards] delay_seconds` between them.

| ATS | List endpoint | Detail | Board id from a link | Notes |
| --- | --- | --- | --- | --- |
| **Greenhouse** | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | — (content included) | `boards.greenhouse.io/<token>`, `job-boards.greenhouse.io/<token>/jobs/<id>` | `content` is entity-escaped HTML. Hosted form: `job-boards.greenhouse.io/<token>/jobs/<id>`. **EU boards** (e.g. Groww: `job-boards.eu.greenhouse.io/groww`) stored as `eu:<token>`, read from `boards-api.eu.greenhouse.io` (**host to verify** with Companies → Check). |
| **Lever** | `GET https://api.lever.co/v0/postings/{site}?mode=json&skip=&limit=100` | — | `jobs.lever.co/<site>/...` | `applyUrl` = hosted form; `workplaceType`; `categories.commitment`; `createdAt` in ms; optional `country`. EU boards (`api.eu.lever.co`) not read yet. |
| **Ashby** | `GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | — | `jobs.ashbyhq.com/<board>/...` | Skip `isListed: false`; `isRemote` is true for remote **and** hybrid → use `workplaceType`; `employmentType` FullTime / Intern / …; `applyUrl`. |
| **SmartRecruiters** | `GET https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=100&offset=` | `GET .../postings/{postingId}` → `jobAd.sections` (+ `applyUrl`) | `jobs.smartrecruiters.com/<id>/...`, `careers.smartrecruiters.com/<id>` | The list has no description: details only for jobs that passed the pre-check (`max_details_per_board`). `location.country` is lower-case ISO ("in"). Ids are case-sensitive (`LinkedIn3`). |

Mapping: `source_job_id = "<board>:<id>"`; every board job gets its hosted form as an apply link, so
its apply route is `form:<ats>` (or `direct` when the company serves the form on its own domain).

## Can a candidate apply without an account? (A2 research, 2026-11-20, web search only)

| ATS | Without an account? | CAPTCHA / checks | Source |
| --- | --- | --- | --- |
| Greenhouse | Yes (one public form) | Invisible reCAPTCHA; a low score may ask for an emailed code or a visible captcha (sensitivity set per board) | support.greenhouse.io/hc/en-us/articles/115005448066 ; .../18529082909979 |
| Lever | Yes (hosted form) | Not documented | github.com/lever/postings-api |
| Ashby | Yes (likely) | Spam protection levels (Strict … none) | docs.ashbyhq.com/job-board-application-spam-protection |
| SmartRecruiters | Depends on the employer (guest or account; one-time passcode) | — | smartrecruiters.com/resources/glossary/1-click-apply |
| Workable | Yes (likely) | — | help.workable.com/hc/en-us/articles/115015713847 |
| Recruitee | Yes | Invisible CAPTCHA on by default for risky submissions | support.recruitee.com/en/articles/6929909 |
| Workday | Usually no (Candidate Home account) | — | kb.wisconsin.edu/workday/152462 |
| Taleo | Depends (register by default; "Apply as Guest" option) | — | docs.oracle.com (Taleo 22C, apply as guest) |
| SAP SuccessFactors | No | — | SAP KBA 2835999 |
| iCIMS | No ("a login is always required") | — | community.icims.com candidate guide |
| Oracle Recruiting Cloud | No password, but a 6-digit email / SMS code (unless auto-confirm) | Optional hCaptcha | docs.oracle.com talent-management faimh |

**Rule for the agent (Phases 4–6):** never bypass a CAPTCHA, emailed code or login; such a job
becomes "needs you". In `services/apply_route.py`: form = Greenhouse, Lever, Ashby,
SmartRecruiters (depends), Workable, Recruitee; account = Workday, Taleo, SuccessFactors, iCIMS,
Oracle.

## India-common systems (A2 research; not built)

| System | Public listing | Careers URL | Notes |
| --- | --- | --- | --- |
| Zoho Recruit | HTML careers page; an XML feed exists but is requested by the employer for job boards; RSS of saved searches | `<company>.zohorecruit.com/jobs/Careers` (own domains possible) | no public JSON found; account / terms unknown |
| Keka Hire | HTML careers page (+ embed widget) | `<company>.keka.com/careers`, jobs `/careers/jobdetails/<id>` | public JSON unknown |
| Darwinbox | candidate portal with sign-up | pattern unconfirmed | account likely |
| Freshteam | being shut down (renewals stopped ~March 2026) | `<company>.freshteam.com/jobs` | skip |
| Rippling ATS | `ats.rippling.com/<company>/jobs/<id>`; a `ats.rippling.com/api/v2/board/<company>/jobs` URL was seen | — | possible public JSON board: a candidate for a later adapter (unverified) |

Decision: none of these get an adapter now (HTML-only or unverified). Rippling is the most
promising next board; Zoho / Keka would need the careers-page reader (2.7 stage D).

## Workable, Recruitee (built, A4) and Rippling (not built) — research 2026-11-22 (docs, help centres, open-source code; no API called)

| ATS | List endpoint | Board id from a link | Apply without account? | Notes |
| --- | --- | --- | --- | --- |
| **Workable** | `GET https://apply.workable.com/api/v1/widget/accounts/{sub}?details=true` (one response; `jobs[]`: title, shortcode, employment_type, telecommuting, url, application_url, published_on, created_at, city/state/country, `locations[]`, description) | `apply.workable.com/<sub>/j/<code>/`, old `<sub>.workable.com`; the share link `apply.workable.com/j/<code>` has no account | Likely (guest form) | Bot defences incl. CAPTCHA for suspicious traffic; Workable tags AI / auto-filled applications. Undocumented v3 (`POST .../api/v3/accounts/{sub}/jobs`) rate-limits hard: not used. help.workable.com/hc/en-us/articles/115012771647 |
| **Recruitee** | `GET https://{company}.recruitee.com/api/offers/` (documented; `offers[]`: id, slug, title, description, requirements, status, published_at, careers_url, careers_apply_url, remote / hybrid / on_site, `locations[]`, employment_type_code) | subdomain of `<company>.recruitee.com` | Yes (guest form `/o/<slug>/c/new`) | **From 10 Feb 2027 the API needs `X-Careers-Sites-Token` (made by the company) -> 401 without it.** Invisible CAPTCHA on by default for risky submissions. docs.recruitee.com/reference/offers , /reference/authentication-1 |
| **Rippling** | `GET https://api.rippling.com/platform/api/ats/v2/board/{slug}/jobs?groupJobsByLocation=true&page=0&pageSize=1000` (undocumented; no description / date: detail `.../v1/board/{slug}/jobs/{id}` per job) | `ats.rippling.com/<slug>/jobs/<uuid>` (slug case-sensitive; often behind a custom careers domain) | **Unconfirmed** | Not built: undocumented API, apply flow (account / CAPTCHA) not confirmed. Sources: dev.to/adderleydata (Rippling job board API measured), github.com/gleanery-works/ats-job-apis |
