"""Keka Hire careers pages (Phase 2.7 E), common at Indian small / mid-size companies.

List: GET https://{tenant}.keka.com/careers/api/jobs/default/active  (the JSON the public careers
page loads; no key; full descriptions included, one request per company). robots.txt allows
/careers. Verified live 2026-11-22 (MD_files/api_references/indian_ats.md).

Applying: no account, but the form has an image CAPTCHA, so these jobs are "needs you"
(apply_route: account:keka). The agent never fills it.
"""
from __future__ import annotations

from urllib.parse import urlparse

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter, first_text

API = "https://{board}.keka.com/careers/api/jobs/default/active"
NOT_BOARDS = {"www", "app", "help", "api", "status", "blog", "community", "developers", "login", "hire"}
JOB_TYPES = {1: "part_time", 2: "full_time", 3: "internship", 4: "contract"}


class KekaBoard(BoardAdapter):
    name = "keka"
    label = "Keka"
    agent_can_apply = False  # CAPTCHA / OTP on the form: you apply
    terms_url = "https://www.keka.com/terms-of-service"
    hosts = ("keka.com",)

    def board_url(self, board: str) -> str:
        return f"https://{board}.keka.com/careers"

    def parse(self, url: str) -> str | None:
        try:
            u = urlparse(url if "://" in url else "https://" + url)
        except ValueError:
            return None
        host = (u.netloc or "").lower().split(":")[0]
        if not host.endswith(".keka.com") or not u.path.lower().startswith("/careers"):
            return None
        board = host[: -len(".keka.com")]
        return board if board and "." not in board and board not in NOT_BOARDS else None

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"Keka ({board})"
        data = http.get_json(API.format(board=board))
        rows = data if isinstance(data, list) else (data or {}).get("jobs") or []
        out = []
        for j in rows:
            if not isinstance(j, dict) or not j.get("id") or not clean_str(j.get("title")):
                continue
            places = []
            for x in j.get("jobLocations") or []:
                if isinstance(x, dict):
                    parts = [clean_str(x.get("city")), clean_str(x.get("state")), clean_str(x.get("countryName"))]
                    places.append(", ".join(dict.fromkeys(p for p in parts if p)))
            location = "; ".join(dict.fromkeys(p for p in places if p)) or None
            try:
                category = JOB_TYPES.get(int(j.get("jobType")))
            except (TypeError, ValueError):
                category = None
            page = f"https://{board}.keka.com/careers/jobdetails/{j['id']}"
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{j['id']}", company_name=company,
                title=clean_str(j["title"]), description_html=first_text(j.get("description"), j.get("excerpt")),
                location_text=location, category=category, job_url=page, apply_url=page,
                apply_links=[{"url": page, "direct": True}],
                source_published_at=parse_datetime(j.get("publishedOn")), raw=j,
            ))
        return out
