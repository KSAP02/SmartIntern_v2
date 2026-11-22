# Common Crawl URL index (Phase 2.7 E: board addresses for the company finder)

Collected 2026-11-22 from https://pywb.readthedocs.io/en/latest/manual/cdxserver_api.html,
https://commoncrawl.org/faq and https://commoncrawl.org/terms-of-use; `collinfo.json` checked live
(3 small queries returned 504: the server is slow; plan for retries).

- **Crawls:** `GET https://index.commoncrawl.org/collinfo.json` → array, newest first:
  `{id: "CC-MAIN-2026-43", "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-43-index", ...}`.
- **Query:** `GET {cdx-api}?url=<pattern>&output=json` (NDJSON, one capture per line, field `url`).
  `jobs.lever.co/*` = prefix; `*.recruitee.com` = every subdomain. `filter==status:200` keeps
  successful captures. No server-side DISTINCT (`collapse` isn't supported): slugs are taken on
  our side (`sources.parse_careers_url`).
- **Paging:** `showNumPages=true` → `{"pages": N, "pageSize": P}`; then `page=0..N-1`. A page past
  the end → 400.
- **Politeness:** "heavily rate limited"; sleep between calls, one request at a time, no threads
  or proxies; 503 = slow down; a blocked IP waits about a day. No numeric pace published: we use
  `crawl_delay_seconds` (5 s) and stop the run on an error, continuing next run.
- **Terms:** limited non-exclusive licence; comply with laws; crawled content may carry its
  owners' terms; no harvesting of personal information. We only take company board ids (not
  personal data); each board is then read through its own public API under its own terms.
- **Patterns used:** boards.greenhouse.io/*, job-boards.greenhouse.io/*, jobs.lever.co/*,
  jobs.ashbyhq.com/*, apply.workable.com/*, jobs.smartrecruiters.com/*, *.recruitee.com,
  *.keka.com, *.darwinbox.in, *.zohorecruit.in, *.zohorecruit.com.
- **Scale (unverified):** published projects report ~1–2 thousand Greenhouse / Lever / Ashby
  boards from one crawl; many are dead or outside India, which the finder's board read filters.
- **Alternative (not used):** the Parquet URL index on data.commoncrawl.org (anonymous HTTPS,
  ~300 GB per crawl) — cleaner for "all URLs under a host" with DuckDB, but a heavy batch job.

## Board filters and change detection (same research)

- Lever `api.lever.co/v0/postings/{site}`: `location`, `commitment`, `team`, `department`,
  `level` — exact match on Lever's own strings (not usable for "India"); we filter on our side.
- SmartRecruiters `api.smartrecruiters.com/v1/companies/{id}/postings`: `country=in` (used),
  `q`, `city`, `region`, `locationType`, `releasedAfter`, `limit` ≤ 100.
- Greenhouse, Ashby, Workable, Recruitee: no location / keyword filters.
- All four probed boards send weak ETags; whether `If-None-Match` returns 304 is untested, so
  change detection is not used yet (`employers.etag` / `last_modified` are reserved for it).
  Ashby caches 60 s.
