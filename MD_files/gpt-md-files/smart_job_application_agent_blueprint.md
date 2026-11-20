# Smart Job Application Agent --- Engineering Blueprint

**Purpose:** Build a daily job-discovery and application-assistance
agent that uses a candidate's uploaded resume and preferences to find
relevant jobs, rank them, prepare applications, track outcomes, and
provide job-search insights.

**Initial cost constraint:** Prefer free public job feeds and public ATS
job-listing endpoints. Free job discovery does not imply free
application submission. Verify each provider's current documentation,
terms, attribution, refresh limits, and redistribution rules before
production use.

**Status:** Engineering specification and MVP blueprint. Provider
endpoints and policies can change.

## 1. Product goals

The system should: 1. Accept a resume (PDF/DOCX initially) and candidate
preferences. 2. Extract a structured candidate profile. 3. Discover jobs
from free public APIs, RSS feeds, and public employer ATS boards. 4.
Normalize listings into one internal schema. 5. Deduplicate jobs and
identify stale listings. 6. Match and rank jobs against the candidate
profile. 7. Explain each match and identify skills gaps. 8. Prepare
tailored resumes, cover letters, and screening-answer drafts. 9. Submit
applications only through a permitted official integration or
user-authorized browser workflow. 10. Track application events and email
responses. 11. Run daily and provide analytics.

### MVP non-goals

-   Bypassing CAPTCHAs, MFA, access controls, rate limits, or anti-bot
    systems.
-   Scraping sites where automated access is prohibited.
-   Claiming an application was submitted without verified confirmation.
-   Inventing candidate experience, qualifications, or answers.
-   Guaranteeing comprehensive coverage of LinkedIn, Indeed, Naukri, or
    other restricted platforms.

## 2. Recommended stack

  -----------------------------------------------------------------------
  Layer                   Technology              Notes
  ----------------------- ----------------------- -----------------------
  Frontend                Next.js + TypeScript +  Candidate profile, job
                          Tailwind                feed, approvals,
                                                  analytics

  API backend             Python + FastAPI        REST API and
                                                  orchestration

  Database                PostgreSQL              Source of truth

  Semantic search         pgvector                Optional initially

  Background jobs         Celery + Redis          Ingestion, parsing,
                                                  matching

  Scheduler               Celery Beat or managed  Daily runs
                          scheduler               

  Browser automation      Playwright              Only where permitted

  Resume parsing          PyMuPDF, python-docx;   PDF/DOCX extraction
                          optionally Docling      

  AI                      Pluggable LLM provider  Structured extraction,
                                                  matching explanations,
                                                  drafting

  Object storage          S3-compatible storage   Original/generated
                          or local dev storage    files

  Email                   Gmail API or authorized Detect application
                          IMAP                    emails

  Deployment              Docker Compose          Move to managed
                          initially               services later
  -----------------------------------------------------------------------

Keep LLM, embedding, storage, and browser providers behind interfaces so
local/open-source alternatives can be used.

## 3. Free job sources

All sources must be implemented as independent adapters that return a
shared `NormalizedJob` shape.

### 3.1 Public remote-job APIs and feeds

These are useful for remote/international listings; they do not
guarantee strong India-local coverage.

  -----------------------------------------------------------------------------------------------------
  Source            Example endpoint                                Auth              Notes
  ----------------- ----------------------------------------------- ----------------- -----------------
  Himalayas         `https://himalayas.app/jobs/api?limit=20`       Public endpoint;  Remote jobs;
                                                                    verify current    verify current
                                                                    key/limit options query/filter
                                                                                      parameters

  Remote OK         `https://remoteok.com/api`                      Public feed       Response may
                                                                                      begin with
                                                                                      metadata/terms
                                                                                      object; filter
                                                                                      non-job entries.
                                                                                      Attribute and
                                                                                      link back as
                                                                                      required

  Arbeitnow         `https://www.arbeitnow.com/api/job-board-api`   Public feed       Stronger European
                                                                                      coverage than
                                                                                      India coverage

  Remotive          `https://remotive.com/api/remote-jobs`          Public API        Remote jobs;
                                                                                      follow refresh,
                                                                                      attribution, and
                                                                                      redistribution
                                                                                      restrictions

  Jobicy            `https://jobicy.com/api/v2/remote-jobs`         Public feed       Remote jobs;
                                                                                      verify filters
                                                                                      and usage terms

  We Work Remotely  `https://weworkremotely.com/remote-jobs.rss`    RSS               Parse with Python
                                                                                      `feedparser`
  -----------------------------------------------------------------------------------------------------

Official documentation: - Himalayas:
https://himalayas.app/docs/remote-jobs-api - Remote OK:
https://remoteok.com/faq - Arbeitnow:
https://www.arbeitnow.com/blog/job-board-api - Remotive:
https://remotive.com/remote-jobs/api - Jobicy:
https://jobicy.com/jobs-rss-feed - We Work Remotely:
https://weworkremotely.com/remote-jobs.rss

Implementation requirements: - Confirm endpoint, filters, response
fields, limits, and terms against current documentation. - Configure
request intervals, timeouts, retries, and per-source rate limits. -
Store attribution and original listing URL for every job. - Store
`first_seen_at`, `last_seen_at`, and `source_published_at` separately. -
Respect terms for caching, display, attribution, and redistribution. -
Do not fetch more frequently than the provider permits. Remotive
documents a limited refresh frequency; check its current limit. - Handle
pagination only where documented. - Do not assume these feeds can be
commercially republished or used to build a competing job aggregator.

### 3.2 Public employer ATS job-board endpoints

These are useful for direct employer listings. Public read access does
**not** mean unrestricted application-submission access.

**Greenhouse**

``` http
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}?questions=true
```

Docs: https://docs.greenhouse.io/job-board

**Lever**

``` http
GET https://api.lever.co/v0/postings/{company}?mode=json
GET https://api.lever.co/v0/postings/{company}/{posting_id}
```

Docs: https://github.com/Lever/postings-api

**Ashby**

``` http
GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}
```

Docs: https://developers.ashbyhq.com/docs/public-job-posting-api

Submission caveat: - Greenhouse application submission typically
requires employer-authorized credentials. - Lever programmatic
application endpoints have API-key/integration requirements. - Ashby
application submission requires appropriate candidate-write
permission. - Do not ask candidates for employer API keys they do not
own or attempt to obtain private credentials. - If no permitted
submission API exists, provide the official apply URL or use a
user-authorized browser workflow where terms permit.

### 3.3 India-specific coverage

Free public feeds skew toward remote/international jobs. For India
roles: - Maintain a curated registry of target employers and their
official career URLs. - Identify each employer's ATS and public board
identifier. - Ingest through documented public APIs/feeds only. - For
sites without a documented permitted feed/API, link to the employer's
career page instead of assuming scraping is allowed. - Do not promise
complete coverage of LinkedIn, Indeed, Naukri, Instahyre, or Cutshort.
Candidate-side data/application APIs may be restricted or partner-only.

Company registry fields:

  Field                Description
  -------------------- ------------------------------------------------
  `company_id`         Internal ID
  `company_name`       Employer name
  `careers_url`        Official career page
  `ats_type`           `greenhouse`, `lever`, `ashby`, `rss`, `other`
  `board_identifier`   ATS board token/name
  `country_focus`      Optional region
  `enabled`            Whether ingestion is active
  `terms_url`          Applicable policy
  `last_checked_at`    Last successful fetch

## 4. Source adapter design

Each adapter should: 1. Fetch with a timeout and descriptive User-Agent.
2. Validate HTTP status and content type. 3. Parse source-specific
records. 4. Map to `NormalizedJob`. 5. Preserve raw payload only where
permitted and with retention limits. 6. Return structured errors without
stopping other source workers.

Example interface:

``` python
from typing import Protocol, Iterable

class JobSourceAdapter(Protocol):
    source_name: str

    async def fetch_jobs(self, query: dict) -> Iterable[dict]:
        ...

    def normalize(self, raw_job: dict) -> dict:
        ...
```

Example request helper:

``` python
import httpx

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)

async def get_json(url: str, params: dict | None = None) -> dict | list:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.get(
            url,
            params=params,
            headers={"User-Agent": "JobDiscoveryAgent/0.1 (contact: YOUR_CONTACT_EMAIL)"},
        )
        response.raise_for_status()
        return response.json()
```

Replace `YOUR_CONTACT_EMAIL` before deployment. Add retries with
exponential backoff for transient errors (429, 5xx, network timeouts),
honoring `Retry-After`. Do not retry permanent 4xx errors indefinitely.

Suggested modules:

``` text
app/integrations/job_sources/
  base.py
  himalayas.py
  remote_ok.py
  arbeitnow.py
  remotive.py
  jobicy.py
  weworkremotely_rss.py
  greenhouse.py
  lever.py
  ashby.py
```

Configuration example:

``` env
HIMALAYAS_ENABLED=true
REMOTEOK_ENABLED=true
ARBEITNOW_ENABLED=true
REMOTIVE_ENABLED=true
JOBICY_ENABLED=true
WEWORKREMOTELY_ENABLED=true

JOB_SOURCE_TIMEOUT_SECONDS=20
JOB_SOURCE_MAX_RETRIES=3
JOB_SOURCE_USER_AGENT=JobDiscoveryAgent/0.1
```

Keep secrets out of source control. Public endpoints may not require
secrets; if a provider later requires a key, store it in a secret
manager or environment variable.

## 5. Canonical normalized job schema

All sources map to this internal model:

``` json
{
  "source": "greenhouse",
  "source_job_id": "12345",
  "company_name": "Example Company",
  "title": "Backend Engineer",
  "description_text": "Plain text job description",
  "description_html": null,
  "location_text": "Bengaluru, India",
  "country_code": "IN",
  "is_remote": false,
  "workplace_type": "hybrid",
  "employment_type": "full_time",
  "seniority": null,
  "salary_min": null,
  "salary_max": null,
  "salary_currency": null,
  "salary_period": null,
  "tags": ["Python", "PostgreSQL"],
  "source_published_at": null,
  "source_updated_at": null,
  "first_seen_at": "ISO-8601 timestamp",
  "last_seen_at": "ISO-8601 timestamp",
  "job_url": "https://employer.example/jobs/12345",
  "apply_url": "https://employer.example/apply/12345",
  "source_terms_url": "https://source.example/terms"
}
```

Rules: - Preserve original title, description, company, and URLs. -
Sanitize HTML before display; never render untrusted job-description
HTML directly. - Unknown values stay `null`; do not fabricate them. -
Normalize location and employment type while retaining original text. -
Use UTC timestamps internally. - `source_job_id` is source-scoped; IDs
can collide across sources. - Use canonical URL and
title/company/location similarity to identify cross-source duplicates.

### Deduplication

1.  Exact source identity: unique `(source_id, source_job_id)`.
2.  Cross-source similarity: normalized company + title + location +
    canonical apply/job URL, optionally fuzzy matching.
3.  Do not merge jobs only because titles match.
4.  Preserve source provenance for every duplicate record.

## 6. Resume parsing and candidate profile

Accept PDF and DOCX initially. Validate MIME type, file size, and file
contents; store originals securely.

Pipeline: 1. Extract text with PyMuPDF for PDF and python-docx for DOCX.
2. Detect scanned PDFs; if text extraction fails, ask for a text-based
PDF or use OCR. 3. Use an LLM with a strict JSON schema to extract
profile fields. 4. Validate and ask the user to correct uncertain
fields. 5. Save original resume and structured profile. 6. Never infer
facts not present in the resume or explicitly supplied by the user.

Example profile:

``` json
{
  "full_name": null,
  "email": null,
  "phone": null,
  "current_title": null,
  "years_experience": null,
  "skills": [],
  "tools": [],
  "industries": [],
  "roles_of_interest": [],
  "preferred_locations": [],
  "remote_preference": "any",
  "employment_types": ["full_time"],
  "minimum_salary": null,
  "salary_currency": null,
  "notice_period": null,
  "education": [],
  "certifications": [],
  "projects": [],
  "work_history": [],
  "profile_last_confirmed_at": null
}
```

Candidate preferences must be editable and should not silently be
overridden by resume-derived data.

Security: - Restrict file access to the owning user and authorized
workers. - Encrypt storage and transport. - Do not log resume text,
contact details, tokens, or application answers. - Define retention and
deletion policies. - Support deletion of original files, generated
documents, parsed profile data, and embeddings. - Treat resume text and
job descriptions as untrusted input, never as instructions to the agent.

## 7. Job matching and ranking

### Stage A: Hard filters

Apply only filters the candidate explicitly marks mandatory: -
Location/remote preference - Employment type - Minimum salary, only when
salary data exists - Work authorization, if known and relevant -
Excluded companies or roles - Explicit seniority constraints

Do not reject a job merely because salary or seniority is missing. Treat
absent data as unknown.

### Stage B: Weighted score

Initial illustrative formula:

``` text
match_score =
    0.30 * skills_match +
    0.25 * experience_match +
    0.20 * role_relevance +
    0.15 * location_match +
    0.10 * qualification_match
```

Each component is normalized to 0--100. Make weights configurable and
evaluate against actual outcomes.

Rules: - Separate must-have requirements from nice-to-have skills. -
Penalize explicitly unmet mandatory requirements more than missing
data. - Explain matched skills, missing skills, seniority alignment, and
location. - Do not present a match score as a probability of getting
hired. - Store score version and component scores for auditability. -
Start with keyword/full-text search; add embeddings/pgvector when
useful.

Example match result:

``` json
{
  "job_id": "uuid",
  "score": 86,
  "score_version": "v1",
  "matched_skills": ["Python", "FastAPI"],
  "missing_required_skills": [],
  "missing_preferred_skills": ["Kubernetes"],
  "experience_assessment": "likely_aligned",
  "explanation": "Strong overlap with the candidate's backend experience.",
  "recommendation": "review"
}
```

## 8. Application preparation and submission

### Application modes

1.  **Prepare only (default MVP):** Generate documents and answers;
    candidate submits manually.
2.  **Approve then submit:** Prepare each application; user approves;
    permitted integration/browser workflow submits.
3.  **Pre-authorized rules:** Candidate sets strict rules and explicitly
    authorizes bounded applications, with volume limits, audit trail,
    and exception handling.

Never silently change modes.

### Preparation pipeline

-   Re-fetch the official job listing before preparing/submitting.
-   Confirm the job is open and apply URL belongs to the employer or
    authorized ATS.
-   Tailor resume using verified candidate facts only.
-   Draft cover letter only when useful/requested.
-   Draft screening answers from verified profile facts.
-   Mark unknown answers as requiring user input.
-   Show a review screen with company, title, location, salary if known,
    documents, and answers.

Never invent work authorization, visa status, experience, salary
history, demographic information, or other sensitive answers.

### Submission order

1.  Official application API with credentials/permissions legitimately
    issued to the integration.
2.  User-authorized browser automation where site terms permit it.
3.  Open official apply URL for manual completion.

Public listing APIs are not unrestricted candidate submission APIs.
Greenhouse, Lever, and Ashby have separate application authorization
requirements.

### Browser safeguards

-   Use site-specific Playwright workflows where permitted.
-   Detect login, CAPTCHA, MFA, and anti-bot challenges; stop and
    request user action.
-   Do not bypass access controls or bot protections.
-   Validate application and authorization before submit.
-   Capture confirmation/reference only where permitted.
-   If result is uncertain, set `submission_unknown`, not `submitted`.
-   Check for an existing application and use idempotency keys before
    retrying.
-   Audit every approval and submission attempt.

## 9. Application tracking and email

Suggested statuses:

``` text
discovered
matched
saved
preparing
awaiting_approval
approved
submitting
submitted
submission_failed
submission_unknown
assessment
interview
rejected
offer
withdrawn
closed
```

Track events separately from current status: - `application_prepared` -
`user_approved` - `submission_started` - `submission_confirmed` -
`submission_failed` - `confirmation_email_received` -
`interview_invitation_received` - `rejection_received` -
`offer_received` - `status_manually_updated`

Gmail API: https://developers.google.com/gmail/api

Email integration requirements: - Use OAuth and least-privilege scopes;
user must explicitly connect mailbox. - Search only relevant
recruiting/application messages. - Classify with confidence scores. -
Low-confidence messages go to review; do not automatically change
status. - Store message IDs and minimal metadata where possible. - Avoid
storing full email bodies unless necessary and authorized. - Email
signals are not definitive proof of portal status; store event source
and confidence.

## 10. Daily scheduling and background workflow

Use Celery + Redis + Celery Beat, or an equivalent managed scheduler and
queue.

``` text
1. Load active candidate preferences
2. Fetch enabled job sources
3. Normalize source records
4. Upsert and deduplicate jobs
5. Mark stale/closed listings only when source evidence supports it
6. Apply candidate hard filters
7. Calculate match scores
8. Save matches and explanations
9. Prepare documents if enabled
10. Queue approvals or authorized submissions
11. Update analytics
12. Send daily digest
```

Do not run this entire workflow in one HTTP request.

Reliability: - Every task must be retryable and idempotent. - Use
bounded retries and exponential backoff. - Honor provider
`Retry-After`. - Apply per-source rate limits. - Isolate source
failures. - Track run IDs, task IDs, counts, duration, and errors. -
Prevent overlapping runs for the same user/source with distributed
locks. - Recheck job availability before preparing/submitting. - Absence
from a feed is not definitive evidence that a job is closed unless
source behavior supports that conclusion.

Example task stubs:

``` python
@celery_app.task
def run_daily_discovery(user_id: str):
    # enqueue ingestion tasks, then normalization/matching
    ...

@celery_app.task
def ingest_source(user_id: str, source_name: str):
    ...

@celery_app.task
def match_new_jobs(user_id: str, run_id: str):
    ...

@celery_app.task
def prepare_application(user_id: str, job_id: str):
    ...
```

These are architectural stubs, not complete implementations.

## 11. Backend API contract proposal

Use versioned REST routes. Authenticate every user-specific endpoint and
enforce ownership checks.

### Candidate

``` http
POST   /api/v1/candidate/resume
GET    /api/v1/candidate/profile
PATCH  /api/v1/candidate/profile
PATCH  /api/v1/candidate/preferences
```

### Jobs

``` http
POST   /api/v1/jobs/search
GET    /api/v1/jobs
GET    /api/v1/jobs/{job_id}
GET    /api/v1/jobs/recommended
POST   /api/v1/jobs/{job_id}/save
```

### Matching

``` http
POST   /api/v1/matching/run
GET    /api/v1/matching/results
GET    /api/v1/matching/results/{job_id}
```

### Applications

``` http
POST   /api/v1/applications/prepare
GET    /api/v1/applications
GET    /api/v1/applications/{application_id}
POST   /api/v1/applications/{application_id}/approve
POST   /api/v1/applications/{application_id}/submit
POST   /api/v1/applications/{application_id}/withdraw
PATCH  /api/v1/applications/{application_id}/status
```

The submit endpoint must verify authorization mode, application state,
duplicate checks, and submission method. It must not allow one user to
submit another user's application.

### Agent and analytics

``` http
POST   /api/v1/agent/runs
GET    /api/v1/agent/runs
GET    /api/v1/agent/runs/{run_id}
GET    /api/v1/analytics/overview
GET    /api/v1/analytics/conversion
GET    /api/v1/analytics/source-performance
GET    /api/v1/analytics/skills-gap
```

Use consistent error objects, pagination, request IDs, and
`202 Accepted` for long-running tasks. Expose run/task status.

## 12. Database schema proposal

Use UUID primary keys and UTC timestamps. Use Alembic migrations and
indexes for common filters.

### `users`

-   `id`
-   `email` (unique)
-   `created_at`
-   `updated_at`

### `candidate_profiles`

-   `id`
-   `user_id` (FK, unique)
-   `profile_json` (validated structured profile)
-   `profile_confirmed_at`
-   `created_at`
-   `updated_at`

### `candidate_preferences`

-   `id`
-   `user_id`
-   `preferred_roles` (JSONB)
-   `preferred_locations` (JSONB)
-   `remote_preference`
-   `employment_types` (JSONB)
-   `minimum_salary`
-   `salary_currency`
-   `excluded_companies` (JSONB)
-   `daily_application_limit`
-   `automation_mode`
-   `created_at`
-   `updated_at`

### `resumes`

-   `id`
-   `user_id`
-   `storage_key`
-   `original_filename`
-   `mime_type`
-   `file_hash`
-   `parsed_text` (restricted access; consider encryption)
-   `parse_status`
-   `created_at`
-   `deleted_at`

### `job_sources`

-   `id`
-   `name` (unique)
-   `source_type`
-   `enabled`
-   `config_json`
-   `terms_url`
-   `last_success_at`
-   `last_error_at`

### `companies`

-   `id`
-   `name`
-   `normalized_name`
-   `careers_url`
-   `ats_type`
-   `board_identifier`
-   `enabled`

### `jobs`

-   `id`
-   `source_id` (FK)
-   `source_job_id`
-   `company_id` (nullable FK)
-   `company_name`
-   `title`
-   `description_text`
-   `location_text`
-   `country_code`
-   `is_remote`
-   `workplace_type`
-   `employment_type`
-   `salary_min`
-   `salary_max`
-   `salary_currency`
-   `tags` (JSONB)
-   `job_url`
-   `apply_url`
-   `source_published_at`
-   `first_seen_at`
-   `last_seen_at`
-   `last_verified_at`
-   `status`
-   `raw_payload` (JSONB, retention-limited)
-   unique `(source_id, source_job_id)`

### `job_matches`

-   `id`
-   `user_id`
-   `job_id`
-   `score`
-   `score_version`
-   `component_scores` (JSONB)
-   `matched_skills` (JSONB)
-   `missing_skills` (JSONB)
-   `explanation`
-   `created_at`
-   Unique `(user_id, job_id, score_version)` or an equivalent versioned
    upsert policy.

### `applications`

-   `id`
-   `user_id`
-   `job_id`
-   `status`
-   `submission_method`
-   `idempotency_key`
-   `approved_at`
-   `submitted_at`
-   `external_confirmation_id`
-   `last_status_source`
-   `created_at`
-   `updated_at`
-   Unique `(user_id, job_id)` unless product requirements explicitly
    support multiple attempts.

### `application_documents`

-   `id`
-   `application_id`
-   `document_type`
-   `storage_key`
-   `content_hash`
-   `created_at`

### `application_events`

-   `id`
-   `application_id`
-   `event_type`
-   `event_source`
-   `confidence`
-   `metadata` (JSONB)
-   `created_at`

### `agent_runs`

-   `id`
-   `user_id`
-   `status`
-   `started_at`
-   `completed_at`
-   `stats` (JSONB)
-   `error_summary`

### `source_fetch_runs`

-   `id`
-   `source_id`
-   `agent_run_id`
-   `status`
-   `started_at`
-   `completed_at`
-   `jobs_fetched`
-   `jobs_created`
-   `jobs_updated`
-   `error_summary`

Suggested indexes: - `(jobs.status, jobs.last_verified_at)` -
`(jobs.company_id)` - `(jobs.country_code, jobs.is_remote)` -
`(job_matches.user_id, job_matches.score DESC)` -
`(applications.user_id, applications.status)` -
`(application_events.application_id, created_at DESC)`

Do not store large binary files in PostgreSQL.

## 13. Analytics and insights

Derive metrics from persisted application events, not from LLM
guesses: - Jobs discovered per day/source - Unique jobs after
deduplication - Jobs matching preferences - Match-score distribution -
Applications prepared, approved, submitted, failed, pending - Response
rate: applications with meaningful employer response divided by
submitted applications, with date window shown - Interview rate and
offer rate - Time from application to first response - Conversion by
source, role, location, and resume version - Rejection/no-response
rates - Frequently requested skills versus verified candidate skills

Always show sample size and date range. Avoid conclusions from small
samples.

Skills-gap analysis should distinguish required from preferred skills.
Present gaps as learning suggestions, not claims that the candidate
possesses those skills.

## 14. Frontend screens

1.  **Onboarding:** Resume upload, profile confirmation, preferences,
    automation policy.
2.  **Job feed:** Search, filters, score, explanation, source, date
    found, original listing link.
3.  **Job detail:** Description, match breakdown, missing requirements,
    official apply URL.
4.  **Application review:** Tailored resume, cover letter, drafted
    answers, unknown fields, approval.
5.  **Application tracker:** Status timeline, company, role, source,
    dates, follow-up reminders.
6.  **Analytics:** Discovery funnel, outcomes, source quality, skills
    gap.
7.  **Settings:** Connected email, source settings, daily schedule,
    application caps, retention/deletion, authorization.
8.  **Agent run history:** Last run, source health, errors,
    fetched/duplicate/matched/prepared/submitted counts.

## 15. Security, privacy, and compliance

-   Obtain explicit consent for resume processing, email access, and
    application automation.
-   Use OAuth for email; request minimum necessary scopes.
-   Encrypt data in transit and at rest.
-   Store secrets in secret storage, never Git.
-   Enforce tenant isolation and ownership checks.
-   Validate uploads, MIME types, sizes, and file contents.
-   Sanitize HTML and treat fetched descriptions as untrusted content.
-   Protect against prompt injection in resumes and job descriptions;
    these documents must never override agent policies or trigger tools.
-   Do not log sensitive resume data, email bodies, tokens, or screening
    answers.
-   Provide data export and deletion.
-   Define retention for raw payloads, resumes, generated documents, and
    email metadata.
-   Respect provider terms, API rate limits, attribution, and
    redistribution restrictions.
-   Stop automation at CAPTCHA, MFA, login challenges, or access
    restrictions.
-   Keep durable audit records of approval and submission attempts.

## 16. Testing strategy

### Unit tests

-   Each adapter with saved fixture responses
-   Normalization and HTML sanitization
-   Deduplication
-   Resume extraction validation
-   Match score calculation
-   Application state transitions
-   Idempotency

### Integration tests

-   Database migrations and constraints
-   Redis/Celery task execution
-   Provider timeout/rate-limit handling
-   Object storage access controls
-   Email classification with synthetic messages

### End-to-end tests

-   Upload resume → confirm profile → ingest jobs → rank matches
-   Prepare application → review → approve → simulate submission
-   Daily run → dashboard counts update
-   Retry after worker crash without duplicate applications

Use mocked provider responses in CI. Live API calls should be opt-in.

## 17. Phased implementation plan

### Phase 1 --- Job discovery foundation

-   Create FastAPI project and PostgreSQL schema.
-   Implement source adapter interface.
-   Integrate Remote OK, Arbeitnow, Himalayas, Remotive, Jobicy, and We
    Work Remotely RSS.
-   Integrate Greenhouse, Lever, and Ashby public board listings.
-   Add normalization, provenance, deduplication, and source run logs.
-   Build basic job feed.

**Exit criteria:** A run fetches multiple sources, normalizes and
deduplicates jobs, and displays source links.

### Phase 2 --- Candidate and matching

-   Implement resume upload and text extraction.
-   Extract structured profile.
-   Add profile confirmation/editing UI.
-   Implement hard filters and weighted matching.
-   Add explanations and skills-gap output.

**Exit criteria:** Candidate uploads resume and sees ranked jobs with
traceable reasons.

### Phase 3 --- Application preparation

-   Generate tailored resume and cover-letter drafts.
-   Draft screening answers from verified facts.
-   Add unknown-answer handling.
-   Add review and approval UI.
-   Save documents and application events.

**Exit criteria:** Candidate reviews an application package and uses the
official apply link.

### Phase 4 --- Controlled automation and tracking

-   Add permitted ATS submission integrations only where legitimate
    credentials/permissions exist.
-   Add Playwright workflows only for permitted sites.
-   Add CAPTCHA/MFA stop-and-handoff.
-   Add idempotency, result verification, and audit logs.
-   Add Gmail integration with explicit OAuth consent.

**Exit criteria:** Every submission is authorized and classified as
confirmed, failed, or unknown.

### Phase 5 --- Daily agent and analytics

-   Add per-user schedules.
-   Add retries, monitoring, alerts, and source health.
-   Add daily digest.
-   Add conversion/source-performance analytics.
-   Add export/deletion controls.

**Exit criteria:** Daily runs are reliable, observable, and do not
duplicate applications.

## 18. Suggested repository layout

``` text
job-agent/
  backend/
    app/
      main.py
      api/v1/
        candidate.py
        jobs.py
        matching.py
        applications.py
        analytics.py
        agent.py
      core/
        config.py
        security.py
        logging.py
      db/
        session.py
        models/
        migrations/
      schemas/
      services/
        resume_parser.py
        candidate_profile.py
        job_normalizer.py
        deduplication.py
        matching.py
        document_generator.py
        application_manager.py
        email_classifier.py
        analytics.py
      integrations/
        job_sources/
          base.py
          himalayas.py
          remote_ok.py
          arbeitnow.py
          remotive.py
          jobicy.py
          weworkremotely_rss.py
          greenhouse.py
          lever.py
          ashby.py
        email/
          gmail.py
      workers/
        celery_app.py
        ingestion_tasks.py
        matching_tasks.py
        application_tasks.py
        scheduled_tasks.py
      tests/
    Dockerfile
    pyproject.toml
  frontend/
    app/
    components/
    lib/
    package.json
  infra/
    docker-compose.yml
  docs/
    PROVIDER_TERMS.md
    ARCHITECTURE.md
  .env.example
  README.md
```

## 19. Definition of done for the first usable MVP

-   User can register and upload PDF/DOCX resume.
-   System extracts profile and asks user to confirm it.
-   User can set roles, locations, remote preference, employment type,
    and daily limits.
-   At least three free sources work through independent adapters.
-   Jobs are normalized, deduplicated, and stored.
-   User sees ranked matches with explanations and original links.
-   User can save jobs and prepare an application package.
-   No application is submitted without explicit authorization.
-   Agent runs on a schedule and records run history.
-   User sees application statuses and basic analytics.
-   Provider errors, rate limits, and stale listings are handled safely.

## 20. Instructions for the coding assistant

Implement incrementally. Do not generate the entire product in one pass.

1.  Inspect the existing repository and preserve its framework and
    conventions.
2.  Propose a concise implementation plan and identify assumptions
    before editing files.
3.  Build Phase 1 first. Do not start browser application automation
    before ingestion and tracking are reliable.
4.  For each provider, verify current endpoint, response format, terms,
    attribution, and rate limits from official documentation.
5.  Add typed schemas, migrations, adapter tests, and fixture data.
6.  Keep provider-specific logic inside adapters.
7.  Do not invent API capabilities, credentials, response fields, or
    successful submission outcomes.
8.  Use mocked fixtures in CI; live provider calls must be opt-in.
9.  Keep secrets out of source control and provide `.env.example`.
10. After each phase, report completed work, changed files, test
    results, known limitations, and next recommended task.

**First coding task:** Scaffold the backend, database models/migrations,
source adapter interface, and three initial adapters (Remote OK,
Arbeitnow, Greenhouse). Add fixture-based tests and a CLI/admin endpoint
to trigger ingestion. Then add remaining sources one at a time.
