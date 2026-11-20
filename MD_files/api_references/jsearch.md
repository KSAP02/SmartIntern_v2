# JSearch API reference (job search via Google for Jobs)

> **Collected:** 2026-11-17 from OpenWeb Ninja's machine-readable spec (the human docs page,
> https://www.openwebninja.com/api/jsearch/docs, is rendered by JavaScript and couldn't be read
> automatically). **Status:** reference for `backend/services/sources/jsearch.py`.
> Re-check against the live docs before relying on a detail marked *unverified*.

JSearch (by OpenWeb Ninja, formerly "letscrape") returns real-time job postings from LinkedIn,
Indeed, Glassdoor, ZipRecruiter, Naukri, company career sites and other public job sites,
collected through **Google for Jobs**. It also has salary-estimate endpoints. It is an official
API, so we don't scrape any of those sites ourselves.

---

## 1. Three ways to call it (same data, different access)

| Access | Base URL | Auth | Search path | Pricing (as seen) | Used by us |
| --- | --- | --- | --- | --- | --- |
| **RapidAPI** | `https://jsearch.p.rapidapi.com` | headers `X-RapidAPI-Key: <key>` + `X-RapidAPI-Host: jsearch.p.rapidapi.com` | `GET /search` | Basic: **200 requests / month free**; pay-per-use option **$0.005 / request** (user-reported, 2026-11-17) | **Yes** (`JSEARCH_API_KEY`) |
| OpenWeb Ninja direct | not stated in what we could read (Developer Portal: https://app.openwebninja.com) | API key from the portal (header name not stated) | not stated | not stated | No |
| OpenWeb Ninja agent storefront | `https://agents.openwebninja.com/zcj/<storefront-id>` (the id differs per fetch; never hardcode it) | `Authorization: Bearer <agent token>` (register: `<base>/auth.md`); "No upstream API key is needed." | `GET /jsearch/search-v2` | $0.03 per 10 requests; free trial 50 requests (verified email); prepaid credits from $0.50 | No |

**RapidAPI details are from the RapidAPI listing and JSearch's long-standing public usage, not
from the spec below** (RapidAPI's pages are JavaScript-only). *Unverified until our first live
call:* that RapidAPI's `/search` returns `data` as a **list** of jobs (the storefront's
`search-v2` returns `data.jobs` + `data.cursor`). Our adapter must accept the shape RapidAPI
actually sends.

---

## 2. Endpoints

Storefront paths shown; RapidAPI uses the same names without the `/jsearch` prefix
(`/search`, `/job-details`, `/estimated-salary`, `/company-job-salary`). All `GET`.

| Endpoint | Purpose |
| --- | --- |
| `search` (`search-v2` on the storefront) | "Searches job postings across public sites via Google for Jobs." |
| `job-details` | "Returns full job details, including application options and links, employer reviews, and estimated salaries for similar jobs." |
| `estimated-salary` | "Get estimated salaries / pay for a jobs around a location by job title and location." |
| `company-job-salary` | "Get estimated job salaries/pay in a specific company by job title and optionally a location and experience level in years." |

---

## 3. Parameters

### 3.1 `search`

| Param | Type | Required | Default | Values / notes |
| --- | --- | --- | --- | --- |
| `query` | string | **yes** | | e.g. `developer jobs in chicago`. "Including job title and location is recommended." |
| `page` | integer | no | 1 | RapidAPI `/search` paging (storefront `search-v2` uses `cursor` instead) |
| `cursor` | string | no | | storefront only: `data.cursor` from the previous response; omit for page 1 |
| `num_pages` | integer | no | 1 | 1–20. **Each page (up to 10 results) costs one request**, so `num_pages` multiplies the cost |
| `country` | string | no | `us` | ISO 3166-1 alpha-2, e.g. `in` |
| `language` | string | no | | ISO 639; empty = the country's main language |
| `date_posted` | string | no | `all` | `all`, `today`, `3days`, `week`, `month` |
| `work_from_home` | boolean | no | false | remote jobs only (older name: `remote_jobs_only`) |
| `employment_types` | string | no | | comma list: `FULLTIME`, `CONTRACTOR`, `PARTTIME`, `INTERN` |
| `job_requirements` | string | no | | comma list: `under_3_years_experience`, `more_than_3_years_experience`, `no_experience`, `no_degree` |
| `radius` | number | no | | km from the location in `query`; "Google does not strictly enforce it." |
| `exclude_job_publishers` | string | no | | comma list of publisher names, e.g. `BeeBe,Dice` |
| `fields` | string | no | all | comma list of fields to return (projection) |

### 3.2 `job-details`

| Param | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `job_id` | string | **yes** | | e.g. `20N57zBfi3eT9BdpAAAAAA==`; up to 20 ids comma-separated, **each id counts as one request** (*unverified*) |
| `country` | string | no | `us` | ISO 3166-1 alpha-2 |
| `language` | string | no | | ISO 639 |
| `fields` | string | no | all | projection |
| `enrich` | boolean | no | | storefront: `enrich=true` adds the AI-derived fields marked † below (*unverified for RapidAPI*) |

### 3.3 `estimated-salary`

| Param | Type | Required | Default | Values |
| --- | --- | --- | --- | --- |
| `job_title` | string | **yes** | | e.g. `nodejs developer` |
| `location` | string | **yes** | | e.g. `new york` |
| `location_type` | enum | no | `ANY` | `ANY`, `CITY`, `STATE`, `COUNTRY` |
| `years_of_experience` | enum | no | `ALL` | `ALL`, `LESS_THAN_ONE`, `ONE_TO_THREE`, `FOUR_TO_SIX`, `SEVEN_TO_NINE`, `TEN_TO_FOURTEEN`, `ABOVE_FIFTEEN` |
| `fields` | string | no | all | projection |

### 3.4 `company-job-salary`

| Param | Type | Required | Default | Values |
| --- | --- | --- | --- | --- |
| `company` | string | **yes** | | e.g. `Amazon` |
| `job_title` | string | **yes** | | e.g. `software developer` |
| `location` | string | no | | free text |
| `location_type` | enum | no | `ANY` | as above |
| `years_of_experience` | enum | no | `ALL` | as above |

---

## 4. Responses

### 4.1 Envelope

| Endpoint | Top level |
| --- | --- |
| `search` (RapidAPI) | `status`, `request_id`, `parameters` (echo), `data`: **list of jobs** (*unverified, see §1*) |
| `search-v2` (storefront) | `status`, `request_id`, `parameters`, `data.jobs` (list), `data.cursor` (string or null = no more pages) |
| `job-details` | `status`, `request_id`, `parameters` (`job_id`, `country`, `language`), `data` (list) |
| `estimated-salary` | `status`, `request_id`, `parameters`, `data` (list) |
| `company-job-salary` | `status`, `request_id`, `data` (list; empty if no data) |

### 4.2 Job object

**Required:** `job_id`, `job_title`, `employer_name`, `job_publisher`, `job_apply_link`. Every
other field can be null or missing. † = AI-enriched field (job-details with `enrich=true`).

| Field | Type | Meaning |
| --- | --- | --- |
| `job_id` | string | Stable id; use for `job-details` |
| `job_title` | string | |
| `employer_name` | string | |
| `employer_logo` / `employer_website` | string | |
| `employer_reviews` | list | `score`, `max_score`, `num_stars`, `publisher`, `review_count`, `reviews_link`, `employer_name` (job-details) |
| `job_publisher` | string | Where it was posted, e.g. `LinkedIn`, `Naukri.com` |
| `job_employment_type` | string | e.g. `FULLTIME` (older single value) |
| `job_employment_types` | string[] | `FULLTIME`, `CONTRACTOR`, `PARTTIME`, `INTERN` |
| `job_apply_link` | string | Main apply / posting URL |
| `job_apply_is_direct` | boolean | Apply link is the employer's own site |
| `apply_options` | list | `{publisher, apply_link, is_direct}` per site |
| `job_google_link` | string | The Google for Jobs page |
| `job_description` | string | **Full description text** (not a snippet) |
| `job_highlights` | object | Keys usually `Qualifications`, `Responsibilities`, `Benefits`; values are string lists |
| `job_is_remote` | boolean | |
| `job_posted_at` | string | e.g. `3 days ago` |
| `job_posted_at_timestamp` | integer | Unix seconds |
| `job_posted_at_datetime_utc` | string | ISO 8601 |
| `job_location` | string | e.g. `San Francisco, CA` |
| `job_city` / `job_state` | string | |
| `job_country` | string | ISO 3166-1 alpha-2, e.g. `IN` |
| `job_latitude` / `job_longitude` | number | |
| `job_salary` / `job_salary_string` | string | Salary as published (free text) |
| `job_min_salary` / `job_max_salary` | number | |
| `job_salary_period` | string | `HOUR`, `DAY`, `WEEK`, `MONTH`, `YEAR` |
| `job_salary_currency` | string | *not listed in the spec*; our adapter reads it if present, otherwise salary is left unknown |
| `job_benefits` | string[] | Codes, e.g. `health_insurance`, `paid_time_off` |
| `job_benefits_strings` | string[] | |
| `job_onet_soc` / `job_onet_job_zone` | string | US occupation codes |
| † `job_function` | string | `backend`, `frontend`, `full-stack`, `mobile`, `devops`, `data-engineering`, `ml-ai`, `systems`, `qa`, `security`, `other` |
| † `seniority_level` | string | `entry`, `mid`, `senior`, `principal`, `lead`, `manager` |
| † `work_arrangement` | string | `onsite`, `remote`, `hybrid` |
| † `required_experience_years` | integer | |
| † `required_technologies` / `preferred_technologies` | string[] | |
| † `visa_sponsorship` | boolean | |
| † `education_required` | object | `field`, `level` |
| † `industry`, `start_date`, `contract_duration` | string | |
| † `soft_skills`, `methodologies`, `benefits_extended` | string[] | |
| † `ai_ml_involved`, `has_management_responsibilities`, `relocation_required`, `relocation_assistance` | boolean | |

### 4.3 Salary entry (`estimated-salary`, `company-job-salary`)

`location`, `job_title` (or `company` + `job_title`), `salary_period` (`HOUR`…`YEAR`),
`salary_currency` (ISO 4217), `confidence` (`CONFIDENT` / `NOT_CONFIDENT`), `min_salary`,
`max_salary`, `median_salary`, `min_base_salary`, `max_base_salary`, `median_base_salary`,
`min_additional_pay`, `max_additional_pay`, `median_additional_pay`, `salary_count`,
`publisher_name` (e.g. Glassdoor), `publisher_link`, `salaries_updated_at` (ISO 8601).

---

## 5. Errors, limits, terms

- **RapidAPI:** `401/403` = bad key or not subscribed to a plan; `429` = rate limit or monthly
  quota used up. Requests that fail are generally still counted by RapidAPI.
- **Storefront:** `401 bearer_required`, `403 plan_required` (body lists plans that cover the
  call), `410 free_plan_exhausted`. Rate limits: "wait the response retry_after or Retry-After
  before a safe retry."
- **Billing:** one request = one page of up to 10 results, so `num_pages=N` costs N, and
  `job-details` with several ids costs one per id (*unverified*).
- **Terms:** https://www.openwebninja.com/terms, privacy https://www.openwebninja.com/privacy;
  RapidAPI's own terms apply to RapidAPI subscriptions.

---

## 6. How SmartIntern uses it (`backend/services/sources/jsearch.py`)

- **Key:** `JSEARCH_API_KEY` in the root `.env` (the RapidAPI key). Blank = source skipped,
  shown as "API key missing" in Admin settings.
- **Query:** one `search` request per *Roles you want* × place in Locations, as
  `"<role> in <place>"` with `country=<iso>`, `page=1`, `num_pages=1` (10 results),
  `date_posted` from Schedule → *ignore postings older than* (≤1 day `today`, ≤3 `3days`,
  ≤7 `week`, ≤31 `month`, else `all`). No Locations → `api_country` (default IN).
- **Plan + budget (Phase 2.5):** what to send comes from `services/search_plan.py` (one search
  per role × place, filters mapped to params, incremental `date_posted`); whether it may be sent
  from `services/api_budget.py` (`[scout.search.sources]`: `monthly_limit` 200, `reserve` 10,
  `daily_limit_on` + `daily_limit` (pacing removed 2026-11-20), `max_per_scan` 8, smart page 2). Every request is logged in `api_calls` before it is
  sent; **no retries**; HTTP 429 pauses JSearch until the next UTC day.
- **Field mapping:** `job_id` → id; `job_title`; `employer_name`; `job_description` (full text
  → requirements + evidence map); `job_city, job_state, job_country` → location;
  `job_is_remote` → remote; `job_employment_types` → job type (`INTERN` → internship);
  `job_min/max_salary` + `job_salary_period` + `job_salary_currency` → pay (only when all are
  present); `job_publisher` → tag "via LinkedIn"; `job_apply_link` → posting link;
  `job_posted_at_datetime_utc` → date posted.
- **Used since Phase 2.5:** `job_highlights` (Qualifications / Responsibilities become the
  requirements), `job_requirements` (Experience level), `employment_types` (Job types),
  `work_from_home` (Remote only), `exclude_job_publishers`, `apply_options[].is_direct`.
- **Not used yet:** `job-details` with `enrich=true` (AI-extracted skills / seniority / visa:
  costs a request per job), salary endpoints.

---

## 7. OpenWeb Ninja direct API and the usage endpoint (added 2026-11-18)

The user's key is an **OpenWeb Ninja** key (`ak_...`), so the app calls OpenWeb Ninja directly
by default (`[scout.search.sources] provider = "openwebninja"`; `"rapidapi"` still works):

| What | Request | Status |
| --- | --- | --- |
| Job search | `GET https://api.openwebninja.com/jsearch/search?query=...`, header `x-api-key: <key>` | Path follows OpenWeb Ninja's `https://api.openwebninja.com/<api_id>/<endpoint>` pattern; **unverified** until calibration call 1 |
| Usage | `GET https://api.openwebninja.com/usage?api_id=<api_id>`, header `x-api-key: <key>` | From the user (OpenWeb Ninja docs, "Check API Usage Programmatically"): "returns your plan, billing period, and remaining quota for a specific API. Pass `?api_id=` with the API's slug ... The slug is what appears in the API's URL (`https://api.openwebninja.com/<api_id>`)." |

**Finding (2026-11-18):** `GET /usage?api_id=jsearch` → HTTP 404 with JSON body
`{"status":"ERROR","error":{"message":"No active subscription for this API","code":404}}`.
So the host, path and slug are right; 404 here means **the account isn't subscribed to
JSearch**. Errors come as `{"status":"ERROR","request_id":...,"error":{"message","code"}}`;
the client now shows `error.message`.

**Real `/usage` answer once subscribed (2026-11-18, Basic free plan):**

```json
{"status": "OK", "request_id": "...", "data": {"api_id": "jsearch",
  "plan": {"id": "...", "key": "basic", "nickname": "Basic", "is_free": true},
  "status": "active", "term": "month",
  "period_start": "2026-11-17T19:59:00.000Z", "period_end": "2026-12-17T19:59:00.000Z",
  "quotas": [{"name": "Requests", "limit": 200, "used": 0, "remaining": 200,
              "reset_at": "2026-12-17T19:59:00.000Z"}]}}
```

The billing period runs from the **subscription day** (17th to 17th), not the calendar
month; the app's budget uses `period_start` / `period_end` when known. The `/usage` call
itself did not change `used`. The response shape is undocumented here, so
`services/jsearch_usage.py` stores it raw and picks plan / period / limit / used / remaining
by field name; the analytics page also lists every returned field.


---

## 8. How the search behaves (findings, added 2026-11-19)

From our 10 live requests and two outside sources. Details and the test plan:
`project_build_phases/phase_2_6_role_contexts_and_search_precision.md` (Part A).

- **Occupation matching (reported):** Google for Jobs maps a query to an occupation with a
  learned title→occupation model and retrieves postings for that occupation, so results can
  match none of the query's words. Source: Google patent US20180107983 as analysed by
  [Go Fish Digital](https://gofishdigital.com/blog/how-google-built-machine-learning-into-their-job-search-engine/)
  (2018); current behaviour not confirmed.
- **Query operators (vendor-reported, unverified by us):**
  - work: `"exact phrase"` (may match in the description), `OR`, `AND`, `( )`, `*`,
    `after:YYYY-MM-DD`;
  - don't work: `-word`, `site:`, `before:`.

  Source: [SerpApi blog](https://serpapi.com/blog/google-jobs-search-query-operators.md).
  So role names must not carry `( )` unescaped: "Artificial Intelligence (AI) Associate" in an
  OR query returned 0 results.
- **Ours, observed:** with `job_requirements=under_3_years_experience,no_experience` and
  `country=in`, different roles return largely the same generic "Fresher" postings. The
  filter is loose: many results still ask for 3–5+ years. `date_posted=today` on a repeat
  search returned 0–1 jobs. A city (Bengaluru) returned 1 job.
- **Ours, observed 2026-11-19 (requests 11–12, all 12 requests so far had the experience
  filter on):** `"AI Engineer" in India` + week + experience filter → **0** results;
  `AI Engineer in India` + week + experience filter → **2**, both remote “Anywhere” postings
  from unrelated fields (Chemistry Researcher, Treasury Manager). The same plain text with
  `month` returned 10 (2 relevant) on 17 Nov. Reading: when few postings pass every filter,
  Google pads the page with remote listings from any occupation. Untested so far: the
  experience filter **off** (the prime suspect). Scan now and Scan Jobs → Requests now explain
  each parameter, the same search's history, and why a request returned what it did
  (`services/request_explain.py`, `GET /api/scout/search/calls/{id}/explain`).
