"""Ashby job boards: GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
(public, no key, one response). Skip `isListed: false`. `isRemote` is true for remote AND
hybrid, so `workplaceType` decides. The hosted form (applyUrl) needs no account."""
from __future__ import annotations

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter, first_text

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"
EMPLOYMENT = {"fulltime": "full_time", "parttime": "part_time", "intern": "internship", "contract": "contract",
              "temporary": "contract"}
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


class AshbyBoard(BoardAdapter):
    name = "ashby"
    label = "Ashby"
    terms_url = "https://developers.ashbyhq.com/docs/public-job-posting-api"
    hosts = ("jobs.ashbyhq.com",)

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"Ashby ({board})"
        data = http.get_json(API.format(board=board), params={"includeCompensation": "true"})
        out = []
        for j in (data or {}).get("jobs") or []:
            if not isinstance(j, dict) or not j.get("id") or not clean_str(j.get("title")) or j.get("isListed") is False:
                continue
            addr = ((j.get("address") or {}).get("postalAddress") or {})
            places = [clean_str(j.get("location")),
                      *[clean_str((x or {}).get("location")) for x in j.get("secondaryLocations") or [] if isinstance(x, dict)],
                      clean_str(addr.get("addressCountry"))]
            location = ", ".join(dict.fromkeys(x for x in places if x)) or None
            apply = first_text(j.get("applyUrl"), j.get("jobUrl"))
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{j['id']}", company_name=company,
                title=clean_str(j["title"]), description_html=clean_str(j.get("descriptionHtml")),
                description_text=None if j.get("descriptionHtml") else clean_str(j.get("descriptionPlain")),
                location_text=location,
                workplace_type=WORKPLACE.get(str(j.get("workplaceType") or "").lower().replace("-", "")),
                category=EMPLOYMENT.get(str(j.get("employmentType") or "").lower()),
                job_url=clean_str(j.get("jobUrl")) or apply, apply_url=apply,
                apply_links=[{"url": apply, "direct": True}] if apply else [],
                source_published_at=parse_datetime(j.get("publishedAt")),
                raw=j,
            ))
        return out
