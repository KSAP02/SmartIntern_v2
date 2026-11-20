# API references

Notes on external APIs the app calls, kept so we don't have to re-research them. Each file says
when it was collected, from which pages, and marks anything not confirmed by a live call.

| API | File | Used by |
| --- | --- | --- |
| JSearch (Google for Jobs via RapidAPI / OpenWeb Ninja) | [jsearch.md](jsearch.md) | `backend/services/sources/jsearch.py` |

Other job sources are documented in the docstring at the top of their adapter in
`backend/services/sources/` (Remotive, Arbeitnow, Remote OK, Greenhouse, Lever, Ashby, Adzuna).
