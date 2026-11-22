"""Shared base for remote-job feeds (Phase 2.7 C1): Himalayas, RemoteJobs.org, Remotive.

A feed lists remote jobs from many companies. Only jobs **open to candidates in India** are kept
(worldwide / anywhere / Asia / APAC / India); "USA only", "EU only" and lists without India are
left out. Each adapter knows its own eligibility field (`open_to_india`); the title pre-check
and storing happen in services/remote_feeds.py. Free, no key. Every feed's terms ask for a
visible credit and a link back to its job page: the job's link (`job_url`) is the feed's page
and the job shows "via <feed>". Notes: MD_files/api_references/remote_feeds.md.
"""
from __future__ import annotations

import re
from typing import Literal

from backend.job_schemas import NormalizedJob
from backend.services.sources.base import SourceHttp

def open_text(value: str | None) -> bool:
    """A free-text location rule -> open to someone in India? Empty = no rule = open.
    "Worldwide", "Anywhere", "APAC", "Asia", "India" -> open; "USA Only", "Europe", "UK, Canada" -> not."""
    t = (value or "").strip().lower()
    if not t:
        return True
    if "india" in t or re.search(r"\b(worldwide|anywhere|global|apac|asia)\b", t) or "asia-pacific" in t:
        return True
    return t in ("remote", "remote only", "100% remote", "fully remote")  # a bare "remote", no region named


class FeedAdapter:
    name = "feed"
    label = "Feed"
    kind: Literal["feed"] = "feed"
    quota = False  # free: no request budget (each feed's own fair-use limit is respected in code)
    terms_url: str | None = None
    env_keys: tuple[str, ...] = ()
    searchable = True  # takes one query per role; False = one request for the whole feed
    min_hours_between_reads = 0.0  # e.g. Remotive asks for only a few reads a day

    def configured(self) -> bool:
        return True

    def fetch(self, http: SourceHttp, query: str | None) -> list[NormalizedJob]:
        """One request: remote jobs (open to India where the feed can filter on its side)."""
        raise NotImplementedError

    def open_to_india(self, job: NormalizedJob) -> bool:
        """From the feed's own eligibility field in `job.raw` (see each adapter)."""
        raise NotImplementedError


def category_of(value: str | None) -> str | None:
    v = (value or "").lower().replace("-", " ").replace("_", " ")
    for key, cat in (("intern", "internship"), ("full", "full_time"), ("part", "part_time"),
                     ("contract", "contract"), ("freelanc", "freelance"), ("temporar", "contract")):
        if key in v:
            return cat
    return None
