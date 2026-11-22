"""Zoho Recruit careers pages (Phase 2.7 E), common at Indian small / mid-size companies.

There is no public JSON endpoint: the careers page (https://{co}.zohorecruit.{in|com|eu}/jobs/Careers)
carries its job list as HTML-escaped JSON in `<input type="hidden" id="jobs" value="[...]">` (an
earlier `id="jobs"` input holds portal settings: the one whose value is a list is used). robots.txt
allows /jobs/*. Verified live 2026-11-22 (MD_files/api_references/indian_ats.md). The page is
large (~2 MB), so it is read once per scan like any board.

Board id = subdomain + "." + Zoho's data-centre domain ("moneyforward.in" = moneyforward.zohorecruit.in).
Applying: the form has a CAPTCHA, so these jobs are "needs you" (apply_route: account:zohorecruit).
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urlparse

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceError, SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter
from backend.services.sources.feeds import category_of

TLDS = ("in", "com", "eu", "com.au")
NOT_BOARDS = {"www", "help", "api", "accounts", "recruit"}
_INPUT = re.compile(r"<input\b[^>]*\bid=[\"']jobs[\"'][^>]*>", re.I)
_VALUE = re.compile(r"\bvalue=(\"([^\"]*)\"|'([^']*)')", re.I)


def jobs_in_page(page: str) -> list[dict]:
    for m in _INPUT.finditer(page or ""):
        v = _VALUE.search(m.group(0))
        raw = html.unescape((v.group(2) if v.group(2) is not None else v.group(3)) if v else "").strip()
        if raw.startswith("["):
            try:
                rows = json.loads(raw)
            except ValueError:
                continue
            return [r for r in rows if isinstance(r, dict)]
    return []


def _slug(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-") or "job"


class ZohoRecruitBoard(BoardAdapter):
    name = "zohorecruit"
    label = "Zoho Recruit"
    agent_can_apply = False  # CAPTCHA / OTP on the form: you apply
    terms_url = "https://www.zoho.com/terms.html"
    hosts = tuple(f"zohorecruit.{t}" for t in TLDS)

    def _host(self, board: str) -> str:
        sub, _, tld = board.partition(".")
        return f"{sub}.zohorecruit.{tld or 'com'}"

    def board_url(self, board: str) -> str:
        return f"https://{self._host(board)}/jobs/Careers"

    def parse(self, url: str) -> str | None:
        try:
            u = urlparse(url if "://" in url else "https://" + url)
        except ValueError:
            return None
        host = (u.netloc or "").lower().split(":")[0]
        for tld in TLDS:
            suffix = f".zohorecruit.{tld}"
            if host.endswith(suffix):
                sub = host[: -len(suffix)]
                if sub and "." not in sub and sub not in NOT_BOARDS:
                    return f"{sub}.{tld}"
        return None

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"Zoho Recruit ({board})"
        page = http.get_text(self.board_url(board))
        rows = jobs_in_page(page)
        if not rows and 'id="jobs"' not in page and "id='jobs'" not in page:
            raise SourceError(f"Zoho Recruit ({board}): not found (HTTP 404): no job list on the careers page")
        out = []
        base = f"https://{self._host(board)}/jobs/Careers"
        for j in rows:
            title = clean_str(j.get("Posting_Title") or j.get("Job_Opening_Name"))
            if not j.get("id") or not title or j.get("Publish") is False:
                continue
            location = ", ".join(dict.fromkeys(x for x in (clean_str(j.get("City")), clean_str(j.get("State")),
                                                           clean_str(j.get("Country"))) if x)) or None
            remote = j.get("Remote_Job") is True
            link = f"{base}/{j['id']}/{_slug(title)}?source=CareerSite"
            desc = j.get("Job_Description") or ""
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{j['id']}", company_name=company, title=title,
                description_html=desc if "<" in desc else None, description_text=None if "<" in desc else (desc or None),
                location_text=location or ("Remote" if remote else None), is_remote=remote or None,
                workplace_type="remote" if remote else None, category=category_of(j.get("Job_Type")),
                job_url=link, apply_url=link, apply_links=[{"url": link, "direct": True}],
                source_published_at=parse_datetime(j.get("Date_Opened")), raw={k: v for k, v in j.items() if k != "Job_Description"},
            ))
        return out
