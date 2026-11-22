"""Workable job boards: GET https://apply.workable.com/api/v1/widget/accounts/{sub}?details=true
(public, no key, one response, published jobs only; Workable help article 115012771647).

Hosted form: apply.workable.com/{sub}/j/{shortcode}/apply/ (a guest form, no account; Workable
may show a CAPTCHA to suspicious traffic: never bypassed). The share link
apply.workable.com/j/{shortcode} carries no account, so it can't name a board. Some key names in
the widget payload are only partly confirmed: mapping is defensive (unverified live)."""
from __future__ import annotations

from urllib.parse import unquote, urlparse

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter, first_text
from backend.services.sources.feeds import category_of

API = "https://apply.workable.com/api/v1/widget/accounts/{board}"
NOT_BOARDS = {"j", "api", "careers", "jobs", "www", "apply"}


def _place(x: dict) -> str | None:
    country = clean_str(x.get("country"))
    parts = [clean_str(x.get("city")), clean_str(x.get("region") or x.get("state")), country]
    return ", ".join(dict.fromkeys(p for p in parts if p)) or None


class WorkableBoard(BoardAdapter):
    name = "workable"
    label = "Workable"
    terms_url = "https://help.workable.com/hc/en-us/articles/115012771647"
    hosts = ("apply.workable.com",)

    def parse(self, url: str) -> str | None:
        try:
            u = urlparse(url if "://" in url else "https://" + url)
        except ValueError:
            return None
        host = (u.netloc or "").lower().split(":")[0]
        parts = [unquote(p) for p in u.path.split("/") if p]
        if host.endswith(".workable.com") and host not in ("apply.workable.com", "www.workable.com", "jobs.workable.com"):
            board = host.split(".")[0]  # old style <sub>.workable.com
            return board if board not in NOT_BOARDS else None
        if host != "apply.workable.com" or not parts:
            return None
        if parts[0] == "api":  # api/v1/widget/accounts/<sub> or api/v3/accounts/<sub>
            return parts[parts.index("accounts") + 1] if "accounts" in parts[:-1] else None
        return None if parts[0].lower() in NOT_BOARDS else super().parse(url)

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"Workable ({board})"
        data = http.get_json(API.format(board=board), params={"details": "true"})
        out = []
        for j in (data or {}).get("jobs") or []:
            if not isinstance(j, dict) or not clean_str(j.get("title")):
                continue
            code = clean_str(j.get("shortcode")) or clean_str(j.get("code"))
            if not code:
                continue
            places = [_place(x) for x in j.get("locations") or [] if isinstance(x, dict) and not x.get("hidden")]
            location = "; ".join(dict.fromkeys(p for p in places if p)) or _place(j)
            remote = bool(j.get("telecommuting")) or str((j.get("location") or {}).get("workplace_type") or "").lower() == "remote"
            page = first_text(j.get("url"), f"https://apply.workable.com/{board}/j/{code}/")
            form = first_text(j.get("application_url"), f"https://apply.workable.com/{board}/j/{code}/apply/")
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{code}", company_name=company,
                title=clean_str(j["title"]), description_html=j.get("description") or None,
                location_text=location or ("Remote" if remote else None), is_remote=remote or None,
                workplace_type="remote" if remote else None, category=category_of(j.get("employment_type")),
                job_url=page, apply_url=form, apply_links=[{"url": form, "direct": True}],
                source_published_at=parse_datetime(j.get("published_on") or j.get("created_at")), raw=j,
            ))
        return out
