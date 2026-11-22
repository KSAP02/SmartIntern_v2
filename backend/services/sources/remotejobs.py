"""RemoteJobs.org: GET https://remotejobs.org/api/v1/jobs?q=&country=IN&workArrangement=remote&limit=50
(public, no key; ~200 requests an hour per IP). Docs: remotejobs.org/developers/api.

Eligibility: `location_normalization` {scope ("worldwide"...), allowed_countries,
excluded_countries, regions}; the server already filters by `country=IN`, so a job is dropped
only when it explicitly excludes India or names countries without it. Terms: a visible
"Powered by RemoteJobs.org" link back (the job's link is its RemoteJobs.org page). Response
shape from the docs (unverified live): the list may be under "jobs" or "data"."""
from __future__ import annotations

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.feeds import FeedAdapter, category_of, open_text

API = "https://remotejobs.org/api/v1/jobs"


def _codes(value) -> set[str]:
    out = set()
    for x in value or []:
        code = x.get("code") or x.get("alpha2") if isinstance(x, dict) else x
        if isinstance(code, str):
            out.add(code.strip().upper())
    return out


class RemoteJobsFeed(FeedAdapter):
    name = "remotejobs"
    label = "RemoteJobs.org"
    terms_url = "https://remotejobs.org/developers/api"

    def fetch(self, http: SourceHttp, query: str | None) -> list[NormalizedJob]:
        http.label = "RemoteJobs.org"
        params = {"country": "IN", "workArrangement": "remote", "limit": 50, "sort": "newest"}
        if query:
            params["q"] = query
        data = http.get_json(API, params=params)
        rows = data if isinstance(data, list) else ((data or {}).get("jobs") or (data or {}).get("data") or [])
        out = []
        for j in rows:
            if not isinstance(j, dict) or not j.get("id") or not clean_str(j.get("title")):
                continue
            company = j.get("company")
            name = clean_str(company.get("name")) if isinstance(company, dict) else clean_str(company)
            page = clean_str(j.get("url"))
            apply = clean_str(j.get("apply_url"))
            types = j.get("employment_types") or [j.get("employment_type")]
            out.append(NormalizedJob(
                source=self.name, source_job_id=str(j["id"]), company_name=name or "Unknown",
                title=clean_str(j["title"]), description_html=j.get("description") or None,
                location_text=clean_str(j.get("location")) or "Remote", is_remote=True, workplace_type="remote",
                category=category_of(" ".join(str(t) for t in types if t)),
                job_url=page or apply, apply_url=apply or page,
                apply_links=[{"url": u, "direct": False} for u in dict.fromkeys(x for x in (apply, page) if x)],
                source_published_at=parse_datetime(j.get("posted_at")), raw=j,
            ))
        return out

    def open_to_india(self, job: NormalizedJob) -> bool:
        raw = job.raw or {}
        norm = raw.get("location_normalization") if isinstance(raw.get("location_normalization"), dict) else {}
        if "IN" in _codes(norm.get("excluded_countries")):
            return False
        allowed = _codes(norm.get("allowed_countries"))
        if allowed:
            return "IN" in allowed
        if str(norm.get("scope") or "").lower() == "worldwide":
            return True
        regions = " ".join(str(r) for r in norm.get("regions") or [])
        if regions:
            return open_text(regions)
        return True  # the server filtered on country=IN
