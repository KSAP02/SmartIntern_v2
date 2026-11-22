"""Lever job boards: GET https://api.lever.co/v0/postings/{site}?mode=json&skip=&limit= (public,
no key, paginated). Only the apply POST is rate-limited. The hosted form (applyUrl,
jobs.lever.co/<site>/<id>/apply) needs no account. EU boards (api.eu.lever.co) aren't read yet."""
from __future__ import annotations

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter, first_text

API = "https://api.lever.co/v0/postings/{board}"
PAGE = 100
MAX_PAGES = 10
COMMITMENT = {"intern": "internship", "full": "full_time", "part": "part_time", "contract": "contract",
              "freelance": "freelance", "temporary": "contract"}
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}


def _category(commitment: str | None):
    c = (commitment or "").lower()
    return next((v for k, v in COMMITMENT.items() if k in c), None)


class LeverBoard(BoardAdapter):
    name = "lever"
    label = "Lever"
    terms_url = "https://github.com/lever/postings-api"
    hosts = ("jobs.lever.co",)

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"Lever ({board})"
        rows: list[dict] = []
        for page in range(MAX_PAGES):
            data = http.get_json(API.format(board=board), params={"mode": "json", "skip": page * PAGE, "limit": PAGE})
            batch = data if isinstance(data, list) else []
            rows += [r for r in batch if isinstance(r, dict)]
            if len(batch) < PAGE:
                break
        out = []
        for j in rows:
            if not j.get("id") or not clean_str(j.get("text")):
                continue
            cats = j.get("categories") or {}
            places = [clean_str(cats.get("location")), *[clean_str(x) for x in cats.get("allLocations") or []]]
            location = ", ".join(dict.fromkeys(x for x in places if x)) or None
            country = clean_str(j.get("country"))
            if country and location and country.upper() not in location.upper():
                from backend.services.job_facts import country_name

                location = f"{location}, {country_name(country) or country}"
            parts = [j.get("description") or ""]
            for lst in j.get("lists") or []:
                if isinstance(lst, dict):
                    parts.append(f"<h3>{lst.get('text') or ''}</h3><ul>{lst.get('content') or ''}</ul>")
            parts.append(j.get("additional") or "")
            apply = first_text(j.get("applyUrl"), j.get("hostedUrl"))
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{j['id']}", company_name=company,
                title=clean_str(j["text"]), description_html="".join(parts).strip() or None,
                description_text=None if any(parts) else clean_str(j.get("descriptionPlain")),
                location_text=location,
                workplace_type=WORKPLACE.get(str(j.get("workplaceType") or "").lower()),
                category=_category(cats.get("commitment")),
                job_url=clean_str(j.get("hostedUrl")) or apply, apply_url=apply,
                apply_links=[{"url": apply, "direct": True}] if apply else [],
                source_published_at=parse_datetime(j.get("createdAt")),
                raw=j,
            ))
        return out
