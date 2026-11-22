"""Greenhouse job boards: GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
(public, no key, one response). `content` is entity-escaped HTML (unescape once). Each job's
hosted application form: https://job-boards.greenhouse.io/{token}/jobs/{id} (no account;
Greenhouse's invisible reCAPTCHA may challenge a submission).

EU boards (e.g. Groww: job-boards.eu.greenhouse.io/groww) are stored as "eu:<token>" and read
from boards-api.eu.greenhouse.io (that API host follows Greenhouse's naming; check it with
Companies -> Check)."""
from __future__ import annotations

import html
from urllib.parse import parse_qs, unquote, urlparse

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter

US_HOSTS = ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io")
EU_HOSTS = ("boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io", "boards-api.eu.greenhouse.io")


def _split(board: str) -> tuple[str, str]:
    """"eu:groww" -> ("eu.", "groww"); "postman" -> ("", "postman")."""
    return ("eu.", board[3:]) if board.startswith("eu:") else ("", board)


class GreenhouseBoard(BoardAdapter):
    name = "greenhouse"
    label = "Greenhouse"
    terms_url = "https://developers.greenhouse.io/job-board.html"
    hosts = US_HOSTS + EU_HOSTS

    def board_url(self, board: str) -> str:
        region, token = _split(board)
        return f"https://job-boards.{region}greenhouse.io/{token}"

    def parse(self, url: str) -> str | None:
        try:
            u = urlparse(url if "://" in url else "https://" + url)
        except ValueError:
            return None
        host = (u.netloc or "").lower().split(":")[0]
        if host not in self.hosts:
            return None
        prefix = "eu:" if host in EU_HOSTS else ""
        parts = [unquote(p) for p in u.path.split("/") if p]
        if parts[:2] == ["v1", "boards"] and len(parts) >= 3:  # the API link
            return prefix + parts[2]
        if parts[:1] == ["embed"]:  # embed/job_board?for=<token>
            token = (parse_qs(u.query).get("for") or [None])[0]
            return prefix + token if token else None
        board = super().parse(url)
        return prefix + board if board else None

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        region, token = _split(board)
        http.label = f"Greenhouse ({token})"
        data = http.get_json(f"https://boards-api.{region}greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
        out = []
        for j in (data or {}).get("jobs") or []:
            if not isinstance(j, dict) or not j.get("id") or not clean_str(j.get("title")):
                continue
            jid = str(j["id"])
            form = f"https://job-boards.{region}greenhouse.io/{token}/jobs/{jid}"
            loc = clean_str((j.get("location") or {}).get("name"))
            offices = [clean_str(o.get("name")) for o in j.get("offices") or [] if isinstance(o, dict)]
            location = ", ".join(dict.fromkeys(x for x in [loc, *offices] if x)) or None
            remote = bool(location and "remote" in location.lower())
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{jid}", company_name=company,
                title=clean_str(j["title"]), description_html=html.unescape(j.get("content") or "") or None,
                location_text=location, is_remote=remote or None, workplace_type="remote" if remote else None,
                job_url=clean_str(j.get("absolute_url")) or form, apply_url=form,
                apply_links=[{"url": form, "direct": True}],
                source_published_at=parse_datetime(j.get("first_published") or j.get("updated_at")),
                raw=j,
            ))
        return out
