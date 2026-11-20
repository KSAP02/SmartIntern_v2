# India-First Job Discovery: JSearch Debugging and API Strategy

## Goal

Build an India-first job discovery system while keeping the architecture ready for international opportunities later. The immediate priority is to improve India coverage, diagnose JSearch's results, and avoid duplicates.

## 1. Why JSearch may not return the expected roles

A missing result does **not** prove that the job does not exist. Possible causes:

1. **Search failure:** JSearch does not retrieve a job that exists.
2. **Matching/filtering failure:** JSearch retrieves it, but your application filters it out.
3. **Coverage gap:** JSearch does not index that employer, job board, or listing.

A key parameter to check is `country`. It is separate from the free-form `query` and may default to `us`. For India searches, explicitly set `country=in`; mentioning India or Bengaluru only in the query may not be sufficient.

Documentation: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch

### Example request shape

```http
GET /search
  ?query=Python Backend Developer in Bengaluru
  &country=in
  &language=en
  &date_posted=week
  &num_pages=2
```

This is illustrative. Confirm exact parameter names and allowed values in the current API documentation.

### Parameters to inspect

| Parameter | Purpose |
|---|---|
| `query` | Role and search terms |
| `country` | Country dataset; explicitly use `in` for India |
| `location` | Geographic search context, if supported |
| `date_posted` | Recency filter |
| `work_from_home` | Remote-work filter |
| `employment_types` | Full-time, contract, internship, etc. |
| `job_requirements` | Experience or degree filters |

Start with only the role query and `country=in`. Add optional filters one at a time. Too many constraints can exclude suitable listings. Check current pagination and request-credit limits against your plan.

## 2. Test JSearch systematically

Run these tests and save the **raw API response** before applying your own filters.

| Test | Query | Country | Purpose |
|---|---|---|---|
| A | `software developer` | `in` | Broad India baseline |
| B | `Python developer` | `in` | Role-specific coverage |
| C | `FastAPI developer` | `in` | Specific technology coverage |
| D | `Python backend engineer in Bengaluru` | `in` | Role plus location |

For each test, check:
1. Did the API return results?
2. Are the titles relevant?
3. Are the locations correct?
4. Does the raw response contain relevant jobs that your application later rejects?
5. Do later pages contain additional relevant listings?

### Interpreting results

- **A returns jobs, but B/C do not:** likely a keyword, title-variation, or source-coverage issue.
- **Raw results are relevant, but final results are not:** likely a bug or overly strict application-side filtering.
- **B/C return irrelevant jobs:** the aggregator's search relevance may be imprecise; retrieve broadly and rank independently.
- **A role appears on an employer's career page but not in JSearch:** likely an aggregator coverage gap.

Do not assume the API is at fault until you compare its raw response with the output after your own processing.

## 3. Search using multiple role variations

Do not rely on one exact title or one long query. Employers describe similar jobs differently.

For a Python backend profile:

```python
queries = [
    "Python Developer",
    "Python Backend Developer",
    "Backend Engineer Python",
    "FastAPI Developer",
    "Django Developer",
    "Python API Engineer",
    "Software Engineer Python",
]
```

Search important Indian locations separately where appropriate:

```python
locations = [
    "Bengaluru",
    "Bangalore",
    "Hyderabad",
    "Pune",
    "Chennai",
    "Mumbai",
    "Delhi NCR",
    "Remote India",
]
```

Avoid requiring every resume skill in one query. A query requiring Python, FastAPI, Django, AWS, and PostgreSQL simultaneously may miss a suitable job that mentions only Python and FastAPI.

Recommended process:
1. Extract target roles, title synonyms, skills, seniority, and location preferences from the resume.
2. Generate a small set of focused role queries.
3. Search broadly enough to avoid missing jobs.
4. Normalize and deduplicate results.
5. Apply your own relevance ranking after retrieval.

You do not need to run every query-location combination against every provider daily. Prioritize strong combinations, rotate broader searches, and monitor which queries produce useful results.

## 4. India-first API and source priorities

Keep JSearch while evaluating it. Add sources in stages.

### Priority 1: Job aggregators

**Jooble**
- Supports India-focused job searches.
- Its API documentation describes a free allowance of 100 requests per day per country API key; verify current terms and obtain the appropriate India key.
- Example request body:

```json
{
  "keywords": "Python Backend Developer",
  "location": "Bangalore",
  "page": 1
}
```

Documentation: https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation

**Adzuna**
- Country-based job search API.
- Requires an application ID and key.
- Confirm India is enabled for your account and verify current quotas.

Documentation: https://developer.adzuna.com/

### Priority 2: Direct employer career-board APIs

These are not global job search engines. You need an employer registry containing target companies and their ATS board identifiers.

| ATS provider | Use |
|---|---|
| Greenhouse | Discover Indian employers using Greenhouse and ingest their public job boards |
| Lever | Discover employer posting-board identifiers and ingest public postings |
| SmartRecruiters | Use public company posting endpoints |
| Ashby | Discover employer board names and ingest public postings |

Documentation:
- Greenhouse Job Board API: https://developers.greenhouse.io/job-board.html
- Lever Postings API: https://github.com/Lever/postings-api
- SmartRecruiters Posting API: https://developers.smartrecruiters.com/reference/v1listpostings
- Ashby Public Job Posting API: https://developers.ashbyhq.com/docs/public-job-posting-api

**Important:** Public job-listing endpoints do not imply unrestricted application-submission APIs. Use the employer's official application link or an explicitly authorized application integration. Do not bypass CAPTCHAs, MFA, access controls, or anti-bot protections.

### Priority 3: International and remote feeds for later

When expanding beyond India, evaluate:
- Himalayas: https://himalayas.app/docs/remote-jobs-api
- Remote OK: https://remoteok.com/faq
- Jobicy: https://jobicy.com/jobs-rss-feed
- Remotive: https://remotive.com/remote-jobs/api
- Arbeitnow: https://www.arbeitnow.com/blog/job-board-api

Check each provider's current refresh frequency, attribution requirements, application-link rules, rate limits, and redistribution restrictions. Do not assume a public feed can be republished or passed into another job board.

## 5. Rank jobs independently of the API

Treat aggregator results as candidate jobs, not final recommendations. Build your own relevance score.

| Factor | Starting weight |
|---|---:|
| Role/title similarity | 30% |
| Required skills match | 30% |
| Experience and seniority fit | 20% |
| Location and work arrangement | 10% |
| Other preferences | 10% |

These are starting weights, not universal rules. Tune them using jobs manually labelled relevant or irrelevant.

Distinguish required skills, preferred skills, related skills, and missing skills. A missing preferred skill should not automatically reject an otherwise suitable job.

## 6. Deduplication and freshness

The same opening may appear through JSearch, Jooble, Adzuna, and an employer ATS board. Maintain one canonical job record and a separate association between that job and each source.

Suggested canonical fields:
- Canonical job ID
- Employer
- Normalized title
- Location and work arrangement
- Description
- Original application URL
- Source name and source job ID
- First seen timestamp
- Last seen timestamp
- Last verified timestamp
- Posted timestamp, if available
- Status (active, stale, closed, unknown)

Suggested deduplication order:
1. Exact application URL.
2. Exact ATS/source job ID where meaningful.
3. Normalized employer + title + location.
4. Fuzzy employer/title/location comparison.
5. Optional description similarity for ambiguous cases.

Do not merge jobs solely because their titles match. One employer may have multiple openings for the same role in different cities or teams.

Track `first_seen_at`, `last_seen_at`, and `last_verified_at` to distinguish genuinely new jobs from repeated listings.

## 7. Recommended implementation order

1. **Debug JSearch:** confirm `country=in`, inspect raw responses, test pagination, and review post-processing filters.
2. **Integrate Jooble:** test India-specific queries and compare unique relevant results.
3. **Integrate Adzuna:** verify India access and compare coverage.
4. **Create an employer registry:** start with 50–100 target companies and record their ATS platform and board identifier.
5. **Add ATS adapters:** Greenhouse, Lever, SmartRecruiters, and Ashby.
6. **Implement normalization and cross-source deduplication.**
7. **Implement independent relevance scoring.**
8. **Add international remote feeds later**, respecting each source's terms and attribution rules.

### Measure quality, not raw result count

Track:
- Unique jobs discovered per source.
- Duplicate rate.
- Relevant-job rate (manually sampled).
- Freshness and proportion of still-open jobs.
- Number of new jobs per day.
- Application conversion rate.

A source returning 500 mostly irrelevant or duplicated jobs may be less valuable than one returning 30 unique, relevant, active jobs.

## 8. What is needed to diagnose the current JSearch setup

Collect one concrete example:
- Exact role being searched.
- JSearch request parameters, with API keys removed.
- One irrelevant result, or an example of a job visible on an employer's site that JSearch did not return.
- Whether the job appears in the raw API response before your own filters.

This will help isolate query format, parameters, provider coverage, pagination, or application-side filtering.
