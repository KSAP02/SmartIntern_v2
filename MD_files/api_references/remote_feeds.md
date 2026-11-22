# Remote-job feeds — Phase 2.7 C1

Free feeds of remote jobs from many companies. Kept only when **open to candidates in India**
(worldwide / anywhere / Asia / APAC / India) and the title matches a role. Researched
2026-11-22 from docs, terms pages and open-source code; **no feed was called** (shapes unverified
live). Code: `backend/services/sources/{feeds,himalayas,remotejobs,remotive}.py`,
`backend/services/remote_feeds.py`.

| Feed | Request | "Where may the candidate live" | Terms (short) | Status |
| --- | --- | --- | --- | --- |
| **Himalayas** | `GET https://himalayas.app/jobs/api/search?q=<role>&country=IN&sort=recent` (no key; a free key raises limits to 60/min, 10k/day) | `locationRestrictions` [{alpha2, name, slug}]; empty = worldwide | Visible credit + link to himalayas.app; data refreshes daily; don't pass jobs on to other job boards / Google Jobs / LinkedIn; apply via `applicationLink` | built |
| **RemoteJobs.org** | `GET https://remotejobs.org/api/v1/jobs?q=<role>&country=IN&workArrangement=remote&limit=50` (no key; ~200/h per IP) | `location_normalization` {status, scope, allowed_countries, excluded_countries, regions, timezones} | "Powered by RemoteJobs.org" link back | built |
| **Remotive** | `GET https://remotive.com/api/remote-jobs?category=software-dev` (no key, no geo filter, no paging) | `candidate_required_location` free text ("Worldwide", "USA Only", ...) | ~4 calls a day (>2/min blocked) -> read at most every 8 h; jobs 24 h late; credit + link to the Remotive page; don't pass jobs on to other boards | built |
| Jobicy | `GET https://jobicy.com/api/jobs` (old `/api/v2/remote-jobs`); `geo=` slugs (apac, anywhere, ...) | `jobGeo` | >=1 s between requests, <=1 sync/h; free tier links to Jobicy pages | skipped: India not a geo option, endpoint changing |
| Remote OK | `GET https://remoteok.com/api` (newest ~100) | `location` free text, mostly empty | followed link back required | skipped: can't tell who may apply |
| We Work Remotely | RSS; JSON API needs a partner token | `region` ("Anywhere in the World", "APAC Only") | **storing WWR data prohibited** | skipped |
| Working Nomads | `GET https://www.workingnomads.com/api/exposed_jobs/` | `location` regions | no docs / terms | skipped |

Sources: himalayas.app/docs/remote-jobs-api , himalayas.app/terms#api , remotejobs.org/developers/api ,
github.com/remotive-com/remote-jobs-api , jobicy.com/jobs-rss-feed , remoteok.com/legal ,
weworkremotely.com/api-terms-and-guidelines .

**Credit:** a feed job's `job_url` is the feed's own job page, and the job panel's "Seen on"
shows the feed's name linking to it.
