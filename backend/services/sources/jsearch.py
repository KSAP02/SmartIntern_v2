"""JSearch client (Google for Jobs: LinkedIn, Naukri, Indeed, company sites...).

Two ways in, same data (`[scout.search.sources] provider`):
- "openwebninja" (default): GET https://api.openwebninja.com/jsearch/search, header x-api-key.
  Also GET https://api.openwebninja.com/usage?api_id=jsearch = plan, billing period, quota left.
- "rapidapi": GET https://jsearch.p.rapidapi.com/search, headers X-RapidAPI-Key + X-RapidAPI-Host.
The key is JSEARCH_API_KEY in the root .env. One request = one page of up to 10 jobs.
Full reference: MD_files/api_references/jsearch.md.

This module only talks HTTP and maps fields both ways: JSearch's records -> our jobs, and our
provider-neutral criteria -> JSearch's filter values (`job_requirements`, `employment_types`).
*What* to ask for comes from `services/search_plan.py`; *whether* a request may be spent from
`services/api_budget.py`.
Never retries: a retry would spend quota.
"""
from __future__ import annotations

import re
from typing import Literal

from backend.config import get_settings
from backend.job_schemas import Category, NormalizedJob
from backend.services.sources.base import SourceError, SourceHttp, clean_str, parse_datetime, positive_number

HOST = "jsearch.p.rapidapi.com"
URL = f"https://{HOST}/search"  # RapidAPI
OWN_URL = "https://api.openwebninja.com/jsearch/search"  # OpenWeb Ninja direct
USAGE_URL = "https://api.openwebninja.com/usage"
API_ID = "jsearch"
PAGE_SIZE = 10

EMPLOYMENT: dict[str, Category] = {
    "FULLTIME": "full_time", "PARTTIME": "part_time", "CONTRACTOR": "contract", "INTERN": "internship",
}
PERIOD = {"YEAR": "year", "MONTH": "month", "WEEK": "week", "DAY": "day", "HOUR": "hour"}
HIGHLIGHT_KEYS = ("Qualifications", "Responsibilities", "Benefits")


# ── our criteria -> JSearch filters ────────────────────────────────────────────
# Criteria stay provider-neutral (e.g. years of experience as a number); each job API gets its
# own translation here, in its adapter. JSearch's job_requirements knows only these values:
# no_experience, under_3_years_experience, more_than_3_years_experience, no_degree.

TO_EMPLOYMENT: dict[str, str] = {"internship": "INTERN", "full_time": "FULLTIME", "part_time": "PARTTIME",
                                 "contract": "CONTRACTOR", "freelance": "CONTRACTOR"}


def job_requirements(years: int | None) -> str | None:
    """Your years of experience -> JSearch's nearest bucket. 0 -> no_experience; 1-2 -> under 3
    years (plus no_experience); 3+ or empty -> nothing (more_than_3_years_experience would hide
    the junior jobs you can also do). The exact number is applied after the call."""
    if years is None or years >= 3:
        return None
    return "no_experience" if years == 0 else "under_3_years_experience,no_experience"


MAX_TITLES = 8  # Google ignores very long queries


def _plain(text: str) -> str:
    """No characters Google Jobs reads as operators: ( ) " [ ] { } (an "(AI)" broke a query)."""
    return re.sub(r"\s+", " ", re.sub(r"[()\[\]{}\"“”]", " ", text or "")).strip()


def build_query(titles: list[str], place: str, *, exact: bool = False, keywords: list[str] | None = None) -> str:
    """Our wording -> Google Jobs syntax. One title: `AI Engineer in India` or, exact,
    `"AI Engineer" in India`. Several: `A OR B in India`, or exact `("A" OR "B") in India`.
    Keywords are appended (quoted if they have spaces)."""
    seen: set[str] = set()
    clean: list[str] = []
    for t in titles:
        p = _plain(t)
        if p and p.lower() not in seen:
            seen.add(p.lower())
            clean.append(p)
    clean = clean[:MAX_TITLES]
    if exact:
        parts = [f'"{t}"' for t in clean]
        head = parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    else:
        head = " OR ".join(clean)
    for k in keywords or []:
        k = _plain(k)
        if k:
            head += f' "{k}"' if " " in k else f" {k}"
    return f"{head} in {_plain(place)}"


def employment_types(job_types: list[str]) -> str | None:
    """Your job types -> JSearch's employment_types (comma list), or None for all."""
    out = sorted({TO_EMPLOYMENT[t] for t in job_types if t in TO_EMPLOYMENT})
    return ",".join(out) or None


# ── what each parameter does (shown before and after a request) ───────────────
# How Google for Jobs (behind JSearch) treats each value, in plain words. Sources and our own
# observations: MD_files/api_references/jsearch.md §8.

PARAM_ORDER = ["query", "country", "date_posted", "job_requirements", "employment_types", "work_from_home",
               "exclude_job_publishers", "page", "num_pages"]
DATE_POSTED = {"all": "any date", "today": "the last 24 hours", "3days": "the last 3 days",
               "week": "the last 7 days", "month": "the last 30 days"}
REQUIREMENTS = {"no_experience": "no experience", "under_3_years_experience": "under 3 years",
                "more_than_3_years_experience": "more than 3 years", "no_degree": "no degree"}
FROM_EMPLOYMENT = {"FULLTIME": "Full-time", "PARTTIME": "Part-time", "CONTRACTOR": "Contract", "INTERN": "Internship"}


def split_query(query: str) -> tuple[str, str | None]:
    """`AI Engineer in India` -> ("AI Engineer", "India"); the last " in " starts the place."""
    i = (query or "").rfind(" in ")
    return (query[:i], query[i + 4:]) if i > 0 else (query or "", None)


def explain_param(key: str, value) -> tuple[str, bool, bool]:
    """(meaning, narrows the results, worth a warning) for one sent parameter."""
    v = str(value)
    if key == "query":
        what, place = split_query(v)
        where = f' "{place}" is read as the place.' if place else ""
        if '"' in what:
            return ('Quoted titles must appear word for word in the posting (title or description); '
                    'OR = any of them. Strict: postings that word the title differently are missed.' + where, True, False)
        if " OR " in what:
            return ("Any of these titles. Unquoted, so Google still matches each one loosely." + where, False, False)
        return ("Read loosely: Google guesses an occupation from these words and returns postings for it, "
                "so results can contain none of them (e.g. a generic engineering job for “AI Engineer”)." + where,
                False, False)
    if key == "country":
        return (f"Searches Google's {v.upper()} job listings. Remote postings marked “Anywhere” count too, and "
                "they fill the page when few local jobs match.", True, False)
    if key == "date_posted":
        return (f"Only postings from {DATE_POSTED.get(v, v)}. Set from when this search last ran, never "
                "narrower than the floor in Admin → JSearch.", v != "all", v in ("today", "3days"))
    if key == "job_requirements":
        levels = " or ".join(REQUIREMENTS.get(x, x) for x in v.split(","))
        return (f"Only postings Google itself tagged as needing {levels} (from your years of experience). "
                "Postings without such a tag are left out, and the tag favours generic “Fresher” postings of "
                "any field, so this is usually the narrowest filter. Switch: Admin → JSearch → Send the "
                "experience filter.", True, True)
    if key == "employment_types":
        return ("Only these job types: " + ", ".join(FROM_EMPLOYMENT.get(x, x) for x in v.split(",")) + ".", True, False)
    if key == "work_from_home":
        return ("Remote jobs only.", True, False)
    if key == "exclude_job_publishers":
        return ("Listings from these job boards are skipped (Admin settings).", True, False)
    if key == "page":
        return ("Which page of Google's results (1 = the top 10).", False, False)
    if key == "num_pages":
        return ("Pages per request: 1 = up to 10 jobs for 1 request.", False, False)
    return ("", False, False)


class JSearchError(SourceError):
    """A failed request. `http_status` tells the budget what happened (429 = stop for today)."""

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


class JSearchClient:
    name = "jsearch"
    label = "JSearch"
    kind: Literal["feed", "ats"] = "feed"
    terms_url = "https://www.openwebninja.com/terms"
    env_keys = ("JSEARCH_API_KEY",)

    def configured(self) -> bool:
        return bool(get_settings().jsearch_api_key)

    def search(self, http: SourceHttp, params: dict, provider: str = "openwebninja") -> tuple[list[NormalizedJob], int]:
        """One request. Returns (jobs, raw result count). Raises JSearchError."""
        rows = _rows(self.fetch_raw(http, params, provider))
        if rows is None:
            raise JSearchError(f"{self.label}: unexpected response shape")
        jobs = [j for j in (self.normalize(r) for r in rows) if j]
        return jobs, len(rows)

    def fetch_raw(self, http: SourceHttp, params: dict, provider: str = "openwebninja") -> dict:
        """One request, the response as JSearch sent it (calibration keeps these)."""
        url, headers = _endpoint(provider)
        return self._get(http, url, params, headers)

    def usage(self, http: SourceHttp) -> dict:
        """Your OpenWeb Ninja plan, billing period and quota left for JSearch (not a job search)."""
        return self._get(http, USAGE_URL, {"api_id": API_ID}, {"x-api-key": get_settings().jsearch_api_key})

    def _get(self, http: SourceHttp, url: str, params: dict, headers: dict) -> dict:
        http.label = self.label
        http.max_retries = 0
        if not self.configured():
            raise JSearchError("JSearch: API key missing. Add JSEARCH_API_KEY to the root .env.")
        try:
            data = http.get_json(url, params=params, headers=headers)
        except SourceError as e:
            msg = str(e)
            code = next((c for c in (401, 403, 429, 404) if f"HTTP {c}" in msg), None)
            if "no active subscription" in msg.lower():
                raise JSearchError("OpenWeb Ninja: no active subscription for JSearch. Subscribe to its (free) plan in the OpenWeb Ninja dashboard, then try again.", code) from e
            if code in (401, 403):
                raise JSearchError("JSearch rejected the key (check JSEARCH_API_KEY and that you subscribed to the free plan).", code) from e
            if code == 429:
                raise JSearchError("JSearch: quota or rate limit hit at RapidAPI (HTTP 429). Paused until tomorrow.", 429) from e
            raise JSearchError(msg, code) from e
        if not isinstance(data, dict):
            raise JSearchError(f"{self.label}: unexpected response shape")
        return data

    def normalize(self, rec: dict) -> NormalizedJob | None:
        from backend.services.job_facts import country_name

        if not isinstance(rec, dict) or not rec.get("job_id") or not clean_str(rec.get("job_title")):
            return None
        code = clean_str(rec.get("job_country"))
        parts = [clean_str(rec.get("job_city")), clean_str(rec.get("job_state")), country_name(code) or code]
        location = ", ".join(dict.fromkeys(p for p in parts if p)) or clean_str(rec.get("job_location"))
        remote = rec.get("job_is_remote")
        types = rec.get("job_employment_types") or [rec.get("job_employment_type")]
        category = next((EMPLOYMENT[t] for t in (str(x or "").upper() for x in types) if t in EMPLOYMENT), None)
        lo, hi = positive_number(rec.get("job_min_salary")), positive_number(rec.get("job_max_salary"))
        period = PERIOD.get(str(rec.get("job_salary_period") or "").upper())
        currency = clean_str(rec.get("job_salary_currency"))
        has_pay = bool((lo or hi) and period and currency)
        publisher = clean_str(rec.get("job_publisher"))
        return NormalizedJob(
            source=self.name,
            source_job_id=str(rec["job_id"]),
            company_name=clean_str(rec.get("employer_name")),
            title=clean_str(rec["job_title"]),
            description_text=clean_str(rec.get("job_description")),
            location_text=location,
            is_remote=remote if isinstance(remote, bool) else None,
            workplace_type="remote" if remote is True else None,
            category=category,
            salary_min=lo if has_pay else None,
            salary_max=hi if has_pay else None,
            salary_currency=currency.upper() if has_pay and currency else None,
            salary_period=period if has_pay else None,
            tags=[f"via {publisher}"] if publisher else [],
            job_url=_best_link(rec),
            source_published_at=parse_datetime(rec.get("job_posted_at_datetime_utc") or rec.get("job_posted_at_timestamp")),
            highlights=_highlights(rec.get("job_highlights")),
            raw=rec,
        )


def _endpoint(provider: str) -> tuple[str, dict]:
    key = get_settings().jsearch_api_key
    if provider == "rapidapi":
        return URL, {"X-RapidAPI-Key": key, "X-RapidAPI-Host": HOST}
    return OWN_URL, {"x-api-key": key}


def _rows(data) -> list | None:
    """RapidAPI /search: {"data": [...]}; OpenWeb Ninja search-v2: {"data": {"jobs": [...]}}."""
    if not isinstance(data, dict):
        return None
    d = data.get("data")
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get("jobs"), list):
        return d["jobs"]
    return None


def _best_link(rec: dict) -> str | None:
    """A direct apply link on the employer's site if there is one, else the main one."""
    for opt in rec.get("apply_options") or []:
        if isinstance(opt, dict) and opt.get("is_direct") and clean_str(opt.get("apply_link")):
            return clean_str(opt["apply_link"])
    return clean_str(rec.get("job_apply_link")) or clean_str(rec.get("job_google_link"))


def _highlights(value) -> dict[str, list[str]] | None:
    if not isinstance(value, dict):
        return None
    out = {k: [s for s in (clean_str(x) for x in value.get(k) or []) if s] for k in HIGHLIGHT_KEYS}
    out = {k: v for k, v in out.items() if v}
    return out or None
