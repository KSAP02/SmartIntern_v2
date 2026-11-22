"""Shared base for company job-board sources (Phase 2.7 A1): Greenhouse, Lever, Ashby,
SmartRecruiters. One company = one public board, read with one GET (plus paging / details).
Endpoints and quirks: MD_files/api_references/former_sources.md and ats_boards.md.

A board lists only open postings, so what it returns is live. Adapters only map fields; the
India scope + title pre-check and storing happen in services/employers.py.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import unquote, urlparse

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp


class BoardAdapter:
    name = "board"
    label = "Board"
    kind: Literal["board"] = "board"
    quota = False  # free: no request budget
    terms_url: str | None = None
    env_keys: tuple[str, ...] = ()
    # Hosts whose first path segment is the board id, e.g. ("jobs.lever.co",).
    hosts: tuple[str, ...] = ()
    # The agent may fill this system's application form (no account, no CAPTCHA by default).
    agent_can_apply = True

    def configured(self) -> bool:
        return True  # public boards need no key

    def board_url(self, board: str) -> str:
        return f"https://{self.hosts[0]}/{board}"

    def parse(self, url: str) -> str | None:
        """The board id in a careers / board / job link, or None if the link isn't this ATS."""
        try:
            u = urlparse(url if "://" in url else "https://" + url)
        except ValueError:
            return None
        host = (u.netloc or "").lower().split(":")[0]
        if host not in self.hosts:
            return None
        parts = [unquote(p) for p in u.path.split("/") if p]
        board = parts[0] if parts else ""
        return board if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,79}", board or "") else None

    def list_jobs(self, http: SourceHttp, board: str, company: str) -> list[NormalizedJob]:
        raise NotImplementedError

    def complete(self, http: SourceHttp, board: str, job: NormalizedJob) -> NormalizedJob:
        """Fill in what the list lacks (SmartRecruiters: the description). Default: nothing."""
        return job


def first_text(*values) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None
