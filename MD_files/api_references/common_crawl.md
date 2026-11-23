# Common Crawl URL index (Phase 2.7 E: board addresses for the company finder)

## What we use since 2026-11-23: the index files (cluster.idx + cdx blocks)

The CDX query server below answered **every** query with HTTP 504 after ~10 s on 2026-11-23
(even a one-URL lookup, on two crawls), so `crawl_index.py` reads the index **files** instead,
from `https://data.commoncrawl.org/cc-index/collections/<crawl>/indexes/` (Amazon S3, anonymous
HTTPS, byte ranges supported; checked live):
- `cluster.idx` (~104 MB for CC-MAIN-2026-43): sorted by SURT key, one line per block of 3,000
  index rows: `<surt key> <timestamp>\t<cdx-000NN.gz>\t<offset>\t<length>\t<block no>`.
  Binary-searched with 16 KB range requests (~10 per prefix), then read forward 256 KB at a time.
- `cdx-000NN.gz` at `offset`/`length`: one gzip member (~200–300 KB) = 3,000 rows
  `<surt key> <timestamp> {"url": ..., "status": ..., ...}`.
- SURT prefixes: `co,lever,jobs)/`, `io,greenhouse,boards)/`, `io,greenhouse,job-boards)/`,
  `com,ashbyhq,jobs)/`, `com,workable,apply)/`, `com,smartrecruiters,jobs)/`, `com,recruitee,`,
  `com,keka,`, `in,darwinbox,`, `in,zohorecruit,`, `com,zohorecruit,`. The block **before** the first
  matching line is read too (its tail can hold the first rows).
- **Measured (CC-MAIN-2026-43):** ~50 blocks, ~12 MB, ~1 min with 0.5 s pauses → **12,353**
  company boards (Greenhouse ~3,900 across both hosts, Workable ~3,800, Ashby ~1,000, Recruitee
  ~800, SmartRecruiters ~640, Lever ~270, Zoho Recruit ~210, Keka ~180, Darwinbox ~15).
- `collinfo.json` (still on index.commoncrawl.org, a static file) worked throughout.

## The CDX query server (first design, 2026-11-22; not used any more)

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
