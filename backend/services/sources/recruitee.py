"""Recruitee job boards: GET https://{company}.recruitee.com/api/offers/ (Recruitee's documented
Careers Site API, docs.recruitee.com/reference/offers): every published offer with its HTML
description, one response.

**Caveat:** Recruitee says this API will need the company's `X-Careers-Sites-Token` from
10 Feb 2027; without it the board answers 401 (shown as a failed read, not switched off). The
hosted form ({company}.recruitee.com/o/{slug}/c/new) is a guest form, no account; an invisible
CAPTCHA may challenge risky submissions (never bypassed)."""
from __future__ import annotations

from urllib.parse import urlparse

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter, first_text
from backend.services.sources.feeds import category_of

NOT_BOARDS = {"www", "api", "app", "support", "docs", "help", "blog", "careers", "jobs"}


class RecruiteeBoard(BoardAdapter):
    name = "recruitee"
    label = "Recruitee"
    terms_url = "https://docs.recruitee.com/reference/offers"

    def board_url(self, board: str) -> str:
        return f"https://{board}.recruitee.com"

    def parse(self, url: str) -> str | None:
        try:
            u = urlparse(url if "://" in url else "https://" + url)
        except ValueError:
            return None
        host = (u.netloc or "").lower().split(":")[0]
        if not host.endswith(".recruitee.com"):
            return None
        board = host[: -len(".recruitee.com")]
        return board if board and "." not in board and board not in NOT_BOARDS else None

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"Recruitee ({board})"
        data = http.get_json(f"https://{board}.recruitee.com/api/offers/")
        out = []
        for j in (data or {}).get("offers") or []:
            if not isinstance(j, dict) or not j.get("id") or not clean_str(j.get("title")):
                continue
            if j.get("status") and j.get("status") != "published":
                continue
            places = []
            for x in j.get("locations") or []:
                if isinstance(x, dict):
                    places.append(clean_str(x.get("name")) or ", ".join(
                        p for p in (clean_str(x.get("city")), clean_str(x.get("state")), clean_str(x.get("country"))) if p))
            location = "; ".join(dict.fromkeys(p for p in places if p)) or first_text(
                j.get("location"), ", ".join(p for p in (clean_str(j.get("city")), clean_str(j.get("country"))) if p))
            remote, hybrid = bool(j.get("remote")), bool(j.get("hybrid"))
            workplace = "remote" if remote and not j.get("on_site") and not hybrid else "hybrid" if hybrid else (
                "onsite" if j.get("on_site") else None)
            slug = clean_str(j.get("slug")) or str(j["id"])
            page = first_text(j.get("careers_url"), f"https://{board}.recruitee.com/o/{slug}")
            form = first_text(j.get("careers_apply_url"), f"https://{board}.recruitee.com/o/{slug}/c/new")
            body = "".join(x for x in (j.get("description"), j.get("requirements")) if isinstance(x, str))
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{j['id']}", company_name=company,
                title=clean_str(j["title"]), description_html=body or None,
                location_text=location or ("Remote" if remote else None), is_remote=remote or None,
                workplace_type=workplace, category=category_of(j.get("employment_type_code")),
                job_url=page, apply_url=form, apply_links=[{"url": form, "direct": True}],
                source_published_at=parse_datetime(j.get("published_at") or j.get("created_at")), raw=j,
            ))
        return out
