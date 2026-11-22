"""Himalayas remote jobs: GET https://himalayas.app/jobs/api/search?q=&country=IN&sort=recent
(public, no key; a free key only raises limits). Docs: himalayas.app/docs/remote-jobs-api.

`locationRestrictions` = [{alpha2, name, slug}] countries the candidate may live in; empty =
worldwide. `applicationLink` = where to apply (often the employer's own page / ATS). Terms:
credit Himalayas with a link to its job page (`guid`); data refreshes daily; don't pass jobs on
to other job boards. Response shape from the published OpenAPI spec (unverified live)."""
from __future__ import annotations

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.feeds import FeedAdapter, category_of

API = "https://himalayas.app/jobs/api/search"


def _countries(raw: dict) -> list[dict]:
    return [x for x in raw.get("locationRestrictions") or [] if isinstance(x, dict)]


class HimalayasFeed(FeedAdapter):
    name = "himalayas"
    label = "Himalayas"
    terms_url = "https://himalayas.app/terms#api"

    def fetch(self, http: SourceHttp, query: str | None) -> list[NormalizedJob]:
        http.label = "Himalayas"
        params = {"country": "IN", "sort": "recent"}
        if query:
            params["q"] = query
        data = http.get_json(API, params=params)
        rows = (data or {}).get("jobs") if isinstance(data, dict) else data
        out = []
        for j in rows or []:
            if not isinstance(j, dict) or not clean_str(j.get("title")):
                continue
            page = clean_str(j.get("guid")) or clean_str(j.get("url"))
            jid = page or f"{j.get('companySlug')}:{j.get('title')}"
            names = [clean_str(x.get("name")) for x in _countries(j)]
            where = ", ".join(x for x in names if x) or "Worldwide"
            apply = clean_str(j.get("applicationLink"))
            out.append(NormalizedJob(
                source=self.name, source_job_id=str(jid), company_name=clean_str(j.get("companyName")) or "Unknown",
                title=clean_str(j["title"]), description_html=j.get("description") or None,
                description_text=None if j.get("description") else clean_str(j.get("excerpt")),
                location_text=f"Remote ({where})", is_remote=True, workplace_type="remote",
                category=category_of(j.get("employmentType")),
                job_url=page or apply, apply_url=apply or page,
                apply_links=[{"url": apply, "direct": False}] if apply else [],
                source_published_at=parse_datetime(j.get("pubDate")), raw=j,
            ))
        return out

    def open_to_india(self, job: NormalizedJob) -> bool:
        codes = {str(x.get("alpha2") or "").upper() for x in _countries(job.raw or {})}
        return not codes or "IN" in codes
