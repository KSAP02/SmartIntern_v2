"""Remotive: GET https://remotive.com/api/remote-jobs?category=software-dev (public, no key).
Docs: github.com/remotive-com/remote-jobs-api.

No location filter on their side: `candidate_required_location` is free text ("Worldwide",
"USA Only", "Europe", "India", ...), checked here. Terms: about 4 reads a day (more than 2 a
minute gets blocked), jobs are shown 24 h late, credit Remotive and link to its job page (`url`),
don't pass jobs on to other job boards. So: one request per scan for the whole software
category, at most once every `min_hours_between_reads`."""
from __future__ import annotations

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.feeds import FeedAdapter, category_of, open_text

API = "https://remotive.com/api/remote-jobs"


class RemotiveFeed(FeedAdapter):
    name = "remotive"
    label = "Remotive"
    terms_url = "https://github.com/remotive-com/remote-jobs-api"
    searchable = False
    min_hours_between_reads = 8.0

    def fetch(self, http: SourceHttp, query: str | None) -> list[NormalizedJob]:
        http.label = "Remotive"
        data = http.get_json(API, params={"category": "software-dev"})
        out = []
        for j in (data or {}).get("jobs") or []:
            if not isinstance(j, dict) or not j.get("id") or not clean_str(j.get("title")):
                continue
            where = clean_str(j.get("candidate_required_location"))
            page = clean_str(j.get("url"))
            out.append(NormalizedJob(
                source=self.name, source_job_id=str(j["id"]), company_name=clean_str(j.get("company_name")) or "Unknown",
                title=clean_str(j["title"]), description_html=j.get("description") or None,
                location_text=f"Remote ({where or 'Worldwide'})", is_remote=True, workplace_type="remote",
                category=category_of(j.get("job_type")), job_url=page, apply_url=page,
                apply_links=[{"url": page, "direct": False}] if page else [],
                source_published_at=parse_datetime(j.get("publication_date")), raw=j,
            ))
        return out

    def open_to_india(self, job: NormalizedJob) -> bool:
        return open_text((job.raw or {}).get("candidate_required_location"))
