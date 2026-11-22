"""How a job can be applied to (Phase 2.7 A0): the first thing the future applying agent needs.

Route values (stored on `jobs.apply_route`, with the link in `jobs.apply_route_url`):

- `form:<ats>`       a public ATS form that needs no account (the agent's target)
- `direct`           the employer's own site, form unknown (the agent may try)
- `account:<ats>`    an ATS that makes you create an account first (needs you)
- `aggregator:<name>` a job board that redirects (Jooble, Talent.com, ...) (needs you)
- `platform:<name>`  a login platform (LinkedIn, Naukri, ...) (never automated)

A job with several apply links gets the best route, in that order. Classification is by the
link's host only; nothing is fetched. Hosts marked "to verify" in the 2.7 doc (D5) are listed
with their best-known behaviour and revisited in step A2.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from backend.services.job_text import normalize_company

# ATS whose public job forms need no account (A2 research, 2026-11-20: Greenhouse, Lever, Ashby,
# Recruitee yes; Workable likely; SmartRecruiters depends on the employer: guest or account).
# Greenhouse / Recruitee may show a CAPTCHA to risky submissions: never bypassed (needs you).
FORM_ATS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io",
                   "job-boards.eu.greenhouse.io", "grnh.se"),
    "lever": ("jobs.lever.co", "jobs.eu.lever.co"),
    "ashby": ("jobs.ashbyhq.com",),
    "smartrecruiters": ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"),
    "workable": ("apply.workable.com",),
    "recruitee": ("recruitee.com",),
}
# ATS that usually make you create an account first.
ACCOUNT_ATS: dict[str, tuple[str, ...]] = {
    "workday": ("myworkdayjobs.com", "myworkdaysite.com"),
    "taleo": ("taleo.net",),
    "successfactors": ("successfactors.com", "successfactors.eu", "jobs.sap.com"),
    "icims": ("icims.com",),
    "oracle": ("oraclecloud.com",),
    # Indian systems (Phase 2.7 E research, 2026-11-22): no account on Keka, but every form has a
    # CAPTCHA (Keka image, Zoho Recruit) or a login / OTP + Turnstile (Darwinbox): needs you.
    "keka": ("keka.com",),
    "darwinbox": ("darwinbox.in",),
    "zohorecruit": ("zohorecruit.in", "zohorecruit.com", "zohorecruit.eu", "zohorecruit.com.au"),
}
# Platforms that need a login to apply (never automated).
PLATFORMS: dict[str, tuple[str, ...]] = {
    "linkedin": ("linkedin.com",),
    "naukri": ("naukri.com",),
    "indeed": ("indeed.com",),
    "glassdoor": ("glassdoor.com", "glassdoor.co.in"),
    "internshala": ("internshala.com",),
    "foundit": ("foundit.in", "monsterindia.com"),
    "instahyre": ("instahyre.com",),
    "wellfound": ("wellfound.com", "angel.co"),
    "shine": ("shine.com",),
    "apna": ("apna.co",),
    "hirist": ("hirist.tech", "hirist.com"),
    "cutshort": ("cutshort.io",),
    "iimjobs": ("iimjobs.com",),
    "timesjobs": ("timesjobs.com",),
}
# Job boards / aggregators we know by name (anything unknown that isn't the employer is one too).
AGGREGATORS: dict[str, tuple[str, ...]] = {
    "jooble": ("jooble.org",),
    "talent.com": ("talent.com",),
    "kitjob": ("kitjob.in",),
    "jaabz": ("jaabz.com",),
    "jobrapido": ("jobrapido.com",),
    "simplyhired": ("simplyhired.co.in", "simplyhired.com"),
    "jobleads": ("jobleads.com",),
    "careerjet": ("careerjet.co.in", "careerjet.com"),
    "adzuna": ("adzuna.in", "adzuna.com"),
    "prosple": ("prosple.com",),
    "himalayas": ("himalayas.app",),  # remote feeds (Phase 2.7 C1): their own job pages
    "remotive": ("remotive.com",),
    "remotejobs.org": ("remotejobs.org",),
}
RANK = {"form": 0, "direct": 1, "account": 2, "aggregator": 3, "platform": 4}
_GENERIC_LABELS = {"www", "jobs", "job", "careers", "career", "apply", "in", "co", "com", "org", "net", "io"}


def host_of(url: str | None) -> str:
    try:
        return (urlparse(url or "").netloc or "").lower().split("@")[-1].split(":")[0]
    except ValueError:
        return ""


def _matches(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _employer_host(host: str, company: str | None) -> bool:
    """The host belongs to the employer: "jobs.gsk.com" for GSK, "careers-inc.nttdata.com" for NTT DATA."""
    if not company or not host:
        return False
    name = re.sub(r"[^a-z0-9]", "", normalize_company(company))
    labels = [x for x in re.split(r"[.\-]", host) if x and x not in _GENERIC_LABELS]
    if len(name) >= 3 and any(name in label for label in labels):
        return True
    first = re.sub(r"[^a-z0-9]", "", (normalize_company(company).split() or [""])[0])
    return len(first) >= 4 and any(label == first for label in labels)


def _site_name(host: str) -> str:
    labels = [x for x in host.split(".") if x and x not in _GENERIC_LABELS]
    return labels[-2] if len(labels) >= 2 else (labels[0] if labels else host or "unknown")


def route_of(url: str | None, *, direct: bool = False, company: str | None = None) -> str | None:
    """One apply link -> its route, or None without a usable link."""
    host = host_of(url)
    if not host:
        return None
    for kind, table in (("form", FORM_ATS), ("account", ACCOUNT_ATS), ("platform", PLATFORMS)):
        for name, suffixes in table.items():
            if _matches(host, suffixes):
                return f"{kind}:{name}"
    for name, suffixes in AGGREGATORS.items():
        if _matches(host, suffixes):
            return f"aggregator:{name}"
    if direct or _employer_host(host, company):
        return "direct"
    return f"aggregator:{_site_name(host)}"


def best(links: list[tuple[str | None, bool]], company: str | None) -> tuple[str | None, str | None]:
    """[(url, the source says it's the employer's own)] -> (best route, its link)."""
    found: list[tuple[int, str, str]] = []
    for url, direct in links:
        r = route_of(url, direct=direct, company=company)
        if r and url:
            found.append((RANK[r.split(":")[0]], r, url))
    if not found:
        return None, None
    _, r, url = min(found, key=lambda x: x[0])
    return r, url


def better(a: str | None, b: str | None) -> bool:
    """Route `a` beats route `b` (None loses to anything)."""
    if a is None:
        return False
    return b is None or RANK[a.split(":")[0]] < RANK[b.split(":")[0]]
