"""Darwinbox careers pages (Phase 2.7 E), used by larger Indian companies and unicorns.

List:   GET https://{tenant}.darwinbox.in/ms/candidateapi/job?page=N&limit=50
        -> {"status", "message": {"jobscount", "jobs": [...]}}  (no description)
Detail: GET https://{tenant}.darwinbox.in/ms/candidateapi/job/{id}
        -> {"message": {"job": [{"jd" (HTML-escaped), "is_remote", "experience", ...}]}}
The JSON the public careers page loads; no key. Verified live 2026-11-22
(MD_files/api_references/indian_ats.md). Details are fetched only for jobs that pass the
pre-check (`complete`, capped by [scout.search.boards] max_details_per_board).

Applying: candidate login / OTP and a Turnstile CAPTCHA, so these jobs are "needs you"
(apply_route: account:darwinbox).
"""
from __future__ import annotations

import html
from datetime import UTC, datetime
from urllib.parse import urlparse

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp, clean_str, parse_datetime
from backend.services.sources.boards import BoardAdapter

BASE = "https://{board}.darwinbox.in/ms/candidateapi/job"
PAGE = 50
MAX_PAGES = 10
NOT_BOARDS = {"www", "app", "help", "api", "blog", "support"}


def _when(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return parse_datetime(value)


def _category(emp_type: str | None) -> str | None:
    t = (emp_type or "").lower()
    if "intern" in t:
        return "internship"
    if "contract" in t or "temporary" in t:
        return "contract"
    if "part" in t:
        return "part_time"
    if "permanent" in t or "full" in t:
        return "full_time"
    return None


class DarwinboxBoard(BoardAdapter):
    name = "darwinbox"
    label = "Darwinbox"
    agent_can_apply = False  # CAPTCHA / OTP on the form: you apply
    terms_url = "https://darwinbox.com/terms-of-use"
    hosts = ("darwinbox.in",)

    def board_url(self, board: str) -> str:
        return f"https://{board}.darwinbox.in/ms/candidate/careers"

    def parse(self, url: str) -> str | None:
        try:
            u = urlparse(url if "://" in url else "https://" + url)
        except ValueError:
            return None
        host = (u.netloc or "").lower().split(":")[0]
        if not host.endswith(".darwinbox.in") or "/candidate" not in u.path.lower():
            return None
        board = host[: -len(".darwinbox.in")]
        return board if board and "." not in board and board not in NOT_BOARDS else None

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        http.label = f"Darwinbox ({board})"
        rows: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            data = http.get_json(BASE.format(board=board), params={"page": page, "limit": PAGE}) or {}
            msg = data.get("message") if isinstance(data, dict) else None
            batch = [r for r in ((msg or {}).get("jobs") or []) if isinstance(r, dict)] if isinstance(msg, dict) else []
            rows += batch
            total = int((msg or {}).get("jobscount") or 0) if isinstance(msg, dict) else 0
            if len(batch) < PAGE or len(rows) >= total:
                break
        out = []
        for j in rows:
            if not j.get("id") or not clean_str(j.get("title")):
                continue
            page_url = f"{self.board_url(board)}/{j['id']}"
            out.append(NormalizedJob(
                source=self.name, source_job_id=f"{board}:{j['id']}", company_name=company,
                title=clean_str(j["title"]), location_text=clean_str(j.get("officelocation_show_arr")),
                category=_category(j.get("emp_type")), job_url=page_url, apply_url=page_url,
                apply_links=[{"url": page_url, "direct": True}],
                source_published_at=_when(j.get("job_posting_on")) or parse_datetime(j.get("created_on")), raw=j,
            ))
        return out

    def complete(self, http: SourceHttp, board: str, job: NormalizedJob) -> NormalizedJob:
        """The description (and remote flag) live in the job's detail."""
        jid = job.source_job_id.split(":", 1)[-1]
        try:
            data = http.get_json(f"{BASE.format(board=board)}/{jid}") or {}
            d = ((data.get("message") or {}).get("job") or [None])[0] or {}
        except Exception:  # noqa: BLE001 - a missing detail leaves the job as listed
            return job
        remote = str(d.get("is_remote")) == "1"
        return job.model_copy(update={
            "description_html": html.unescape(d.get("jd") or "") or job.description_html,
            "is_remote": remote or job.is_remote, "workplace_type": "remote" if remote else job.workplace_type,
        })
