# API references

Notes on external APIs the app calls, kept so we don't have to re-research them. Each file says
when it was collected, from which pages, and marks anything not confirmed by a live call.

| API | File | Used by |
| --- | --- | --- |
| JSearch (Google for Jobs via RapidAPI / OpenWeb Ninja) | [jsearch.md](jsearch.md) | `backend/services/sources/jsearch.py` |
| Company boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee; Rippling not built) | [ats_boards.md](ats_boards.md) | `backend/services/sources/*.py` |
| Remote feeds (Himalayas, RemoteJobs.org, Remotive) | [remote_feeds.md](remote_feeds.md) | `backend/services/remote_feeds.py` |
| Indian hiring systems (Keka, Darwinbox, Zoho Recruit; Freshteam skipped) | [indian_ats.md](indian_ats.md) | `sources/keka.py`, `darwinbox.py`, `zohorecruit.py` |
| Common Crawl URL index + board filters | [common_crawl.md](common_crawl.md) | `backend/services/crawl_index.py` |

Other job sources are documented in the docstring at the top of their adapter in
`backend/services/sources/` (Remotive, Arbeitnow, Remote OK, Greenhouse, Lever, Ashby, Adzuna).
