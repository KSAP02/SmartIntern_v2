"""SmartRecruiters job boards (public Posting API, no key):
- list:   GET https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=100&offset=
- detail: GET https://api.smartrecruiters.com/v1/companies/{id}/postings/{postingId}
  (the description: jobAd.sections; only fetched for jobs that passed the pre-check).
`location.country` is a lower-case ISO code ("in"). Public posting page:
https://jobs.smartrecruiters.com/{id}/{postingId}. Whether its form needs an account: to verify (A2)."""
from __future__ import annotations

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter, first_text

API = "https://api.smartrecruiters.com/v1/companies/{board}/postings"
PAGE = 100
MAX_PAGES = 10
EMPLOYMENT = {"intern": "internship", "full": "full_time", "part": "part_time", "contract": "contract",
              "temporary": "contract", "freelance": "freelance"}
SECTIONS = ("jobDescription", "qualifications", "additionalInformation")


class SmartRecruitersBoard(BoardAdapter):
    name = "smartrecruiters"
    label = "SmartRecruiters"
    terms_url = "https://developers.smartrecruiters.com/docs/posting-api"
    hosts = ("jobs.smartrecruiters.com", "careers.smartrecruiters.com", "api.smartrecruiters.com")

    def board_url(self, board: str) -> str:
        return f"https://careers.smartrecruiters.com/{board}"

    def parse(self, url: str) -> str | None:
        board = super().parse(url)
        if board == "v1":  # api.smartrecruiters.com/v1/companies/<id>/postings
            from urllib.parse import urlparse

            parts = [p for p in urlparse(url if "://" in url else "https://" + url).path.split("/") if p]
            return parts[2] if len(parts) >= 3 and parts[1] == "companies" else None
        return board

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"SmartRecruiters ({board})"
        # Phase 2.7 E: ask only for postings in India (the API's country filter), so a big
        # company's worldwide list isn't downloaded just to be left out by the pre-check.
        rows: list[dict] = []
        for page in range(MAX_PAGES):
            data = http.get_json(API.format(board=board), params={"limit": PAGE, "offset": page * PAGE, "country": "in"}) or {}
            batch = [r for r in data.get("content") or [] if isinstance(r, dict)]
            rows += batch
            if len(batch) < PAGE or len(rows) >= int(data.get("totalFound") or 0):
                break
        out = []
        for j in rows:
            if not j.get("id") or not clean_str(j.get("name")):
                continue
            loc = j.get("location") or {}
            from backend.services.job_facts import country_name

            code = clean_str(loc.get("country"))
            places = [clean_str(loc.get("city")), clean_str(loc.get("region")),
                      (country_name(code.upper()) or code.upper()) if code else None]
            location = ", ".join(dict.fromkeys(x for x in places if x)) or clean_str(loc.get("fullLocation"))
            remote = loc.get("remote") is True
            emp = str(((j.get("typeOfEmployment") or {}).get("label")) or "").lower()
            page_url = f"https://jobs.smartrecruiters.com/{board}/{j['id']}"
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{j['id']}",
                company_name=company or clean_str((j.get("company") or {}).get("name")),
                title=clean_str(j["name"]), location_text=location,
                is_remote=remote or None, workplace_type="remote" if remote else None,
                category=next((v for k, v in EMPLOYMENT.items() if k in emp), None),
                job_url=page_url, apply_url=page_url, apply_links=[{"url": page_url, "direct": True}],
                source_published_at=parse_datetime(j.get("releasedDate")),
                raw=j,
            ))
        return out

    def complete(self, http: SourceHttp, board: str, job: NormalizedJob) -> NormalizedJob:
        pid = job.source_job_id.split(":", 1)[-1]
        data = http.get_json(f"{API.format(board=board)}/{pid}") or {}
        sections = ((data.get("jobAd") or {}).get("sections") or {})
        parts = []
        for key in SECTIONS:
            sec = sections.get(key) or {}
            if clean_str(sec.get("text")):
                parts.append(f"<h3>{sec.get('title') or ''}</h3>{sec['text']}")
        apply = first_text(data.get("applyUrl"), data.get("postingUrl"), job.apply_url)
        return job.model_copy(update={
            "description_html": "".join(parts) or job.description_html,
            "apply_url": apply,
            "apply_links": [{"url": apply, "direct": True}] if apply else job.apply_links,
        })
