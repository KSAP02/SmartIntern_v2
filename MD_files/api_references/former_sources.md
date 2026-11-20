# Former job sources (removed in Phase 2.5)

> Removed on 2026-11-17 when JSearch became the only source (Phase 2.5, decision 1). Kept
> here so they can be re-added without re-research. The adapter code was never
> committed (the repo had no commits), so it has to be rewritten from this table (Phase 2.7). Measured in Phase 2: of 827 jobs from the sources
> below, 3 were in India.

| Source | Endpoint | Auth | Shape / paging | Terms and limits | Notes |
| --- | --- | --- | --- | --- | --- |
| **Remotive** (remote feed) | `GET https://remotive.com/api/remote-jobs` (`limit`) | none | one response, no paging | Link back to the Remotive URL and name Remotive; don't resubmit jobs to other job sites; **~4 requests a day** (> 2 a minute gets blocked); jobs delayed 24 h | Salary is free text |
| **Arbeitnow** (Europe-heavy board) | `GET https://www.arbeitnow.com/api/job-board-api` (`?page=`) | none | paginated, `links.next`; updated hourly | Free public API, "please do not abuse", linking back appreciated | Locations are often bare German / Swiss / French town names |
| **Remote OK** (remote feed) | `GET https://remoteok.com/api` | none | one response (~100 jobs); element 0 is a legal notice | Link back to the Remote OK job URL (followed) and name Remote OK, or access is suspended; don't use their logo | Text is **double-encoded UTF-8** ("partnerâ\x80\x99s"): repair with latin-1 → utf-8 per byte run; salary values outside 1k–1M are noise |
| **Greenhouse** (one employer per board) | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | none | one response, `meta.total` | Public data; no documented rate limit | `content` is entity-escaped HTML (unescape once); pay only on the single-job endpoint |
| **Lever** (one employer per board) | `GET https://api.lever.co/v0/postings/{site}?mode=json` (`skip`, `limit`) | none | JSON list, paginated | Only the apply POST is rate-limited (2/s) | EU boards on `api.eu.lever.co` |
| **Ashby** (one employer per board) | `GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | none | one response | Public; no documented rate limit | Skip `isListed: false`; `isRemote` is true for remote **and** hybrid, so read `workplaceType` |
| **Adzuna** (search API) | `GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id&app_key&what&where&content-type=application/json` | `app_id` + `app_key` | `results` list | Free key = **25 test calls**, then a card on file is needed; label each shown ad "Adzuna" linked to the Adzuna site | Description is a **~100–200 char snippet** (thin evidence map); drop `salary_is_predicted` salaries |

Board identifiers that worked in testing: Greenhouse `anthropic`, Lever `spotify`, Ashby `openai`.
