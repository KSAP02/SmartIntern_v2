"""What a JSearch request does, in plain words, before it is sent and after it came back.

- Before (Scan now, Search plan): each parameter's meaning (the JSearch adapter knows it), what
  the same search returned before, and what we check on the jobs that come back.
- After (Scan Jobs → Requests): why that request returned what it did, read from the jobs it
  returned and what became of them, plus what to change next time.

Reads only our own records: never calls JSearch.
"""
from __future__ import annotations

import re
from collections import Counter

from sqlmodel import Session, col, select

from backend.db import ApiCall, ApiCallJob, Job
from backend.job_schemas import CallExplainOut, ParamNote, PastRequest, SearchCriteria, SearchPlanOut
from backend.services import search_settings
from backend.services.job_text import TITLE_ABBREVIATIONS
from backend.services.sources.jsearch import PARAM_ORDER, explain_param, split_query

# Words that name no field: a title sharing only these with the search isn't on topic.
GENERIC_WORDS = {
    "engineer", "engineers", "engineering", "developer", "developers", "development", "associate", "specialist",
    "senior", "sr", "junior", "jr", "lead", "intern", "internship", "fresher", "freshers", "trainee", "graduate",
    "entry", "level", "and", "or", "of", "the", "for", "with", "in", "a", "an", "to", "role", "job", "jobs", "i", "ii",
}
_REMOTE = re.compile(r"\b(?:anywhere|remote|worldwide)\b", re.IGNORECASE)
_ENTRY = re.compile(r"\b(?:fresher|freshers|entry[- ]level|trainee|graduate)\b", re.IGNORECASE)
_SKIP_COMPARE = {"num_pages"}


def explain_params(params: dict) -> list[ParamNote]:
    keys = sorted(params, key=lambda k: PARAM_ORDER.index(k) if k in PARAM_ORDER else 99)
    out = []
    for k in keys:
        meaning, narrows, warn = explain_param(k, params[k])
        out.append(ParamNote(key=k, value=str(params[k]), meaning=meaning, narrows=narrows, warn=warn))
    return out


# ── the same search before ─────────────────────────────────────────────────────


def _differs(past: dict, now: dict) -> list[str]:
    out = []
    for k in sorted(set(past) | set(now), key=lambda k: PARAM_ORDER.index(k) if k in PARAM_ORDER else 99):
        if k in _SKIP_COMPARE or past.get(k) == now.get(k):
            continue
        out.append(f"no {k}" if k not in past else f"{k}: {past[k]}")
    return out


def history(session: Session, params: dict, query_id: int | None, exclude_id: int | None = None,
            limit: int = 6) -> list[PastRequest]:
    """Earlier answered requests for the same search (same role and place, or the same text),
    newest first, each with what it sent differently from `params`."""
    text = (params.get("query") or "").strip().lower()
    calls = session.exec(select(ApiCall).where(col(ApiCall.status) == "ok").order_by(col(ApiCall.at).desc())).all()
    out = []
    for c in calls:
        if c.id == exclude_id:
            continue
        same = (query_id is not None and c.query_id == query_id) or (c.params or {}).get("query", "").strip().lower() == text
        if not same:
            continue
        out.append(PastRequest(id=c.id, at=c.at, query=(c.params or {}).get("query", ""), results=c.results,
                               relevant=c.relevant_jobs, variant=c.variant, differs=_differs(c.params or {}, params)))
        if len(out) >= limit:
            break
    return out


# ── what we check after JSearch answers ────────────────────────────────────────


def after_checks(session: Session, criteria: SearchCriteria) -> list[str]:
    from backend.services.job_search import clean_roles

    m = search_settings.get(session, "matching")
    schedule = search_settings.get(session, "schedule")
    pct = lambda x: f"{round(x * 100)}%"  # noqa: E731
    out = ["Jobs you already have (same posting or the same job on another board) aren't added again."]
    if schedule.recency_days:
        out.append(f"Postings older than {schedule.recency_days} days are skipped.")
    roles = clean_roles(criteria.roles)
    if roles:
        out.append(f"Title check: a job reaches Matches when its title is at least {pct(m.role_threshold)} like one "
                   f"of your roles ({', '.join(roles)}), or at least {pct(m.borderline_role_threshold)} and the "
                   f"posting is at least {pct(m.borderline_context_threshold)} like that role's context "
                   "(Memory ▾ Role contexts). Others go to Not relevant.")
    else:
        out.append("No roles set: every job passes the title check.")
    out.append("Search criteria don't remove jobs: filter by type or workplace on the Jobs page.")
    return out


def annotate(session: Session, plan: SearchPlanOut, criteria: SearchCriteria) -> None:
    """Fill in the plain-words explanation, history and after-checks of a plan (in place)."""
    for call in plan.calls:
        call.explain = explain_params(call.params)
        for note in call.explain:
            note.source = call.sources.get(note.key, "")
        call.history = history(session, call.params, call.query_id)
        same = next((h for h in call.history if not h.differs), None)
        if same:
            plan.notes.append(f"“{call.query}” with these exact filters returned {same.results} job"
                              f"{'s' if same.results != 1 else ''} ({same.relevant} relevant) on "
                              f"{same.at:%d %b}. Sending it again will likely return much the same.")
    plan.after = after_checks(session, criteria)


# ── why a past request returned what it did ───────────────────────────────────


def key_words(query: str) -> set[str]:
    """The words that name the field: `"AI Engineer" in India` -> {ai, artificial, intelligence}."""
    what, _ = split_query(query)
    words = {w for w in re.findall(r"[a-z0-9+#]+", what.lower()) if w not in GENERIC_WORDS and w not in {"or", "and"}}
    for w in list(words):
        if w in TITLE_ABBREVIATIONS:
            words |= set(TITLE_ABBREVIATIONS[w].split())
    rev = {v: k for k, v in TITLE_ABBREVIATIONS.items()}
    for phrase, short in rev.items():  # "machine learning" in the search also matches "ML" in a title
        if short not in ("be", "fe") and all(p in words for p in phrase.split()):
            words.add(short)
    return words - GENERIC_WORDS


def on_topic(title: str, words: set[str]) -> bool:
    return bool(set(re.findall(r"[a-z0-9+#]+", (title or "").lower())) & words)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def explain_call(session: Session, call_id: int) -> CallExplainOut | None:
    call = session.get(ApiCall, call_id)
    if call is None:
        return None
    params = call.params or {}
    rows = session.exec(select(ApiCallJob).where(ApiCallJob.call_id == call_id).order_by(ApiCallJob.position)).all()
    jobs = {j.id: j for j in session.exec(select(Job).where(col(Job.id).in_([r.job_id for r in rows if r.job_id]))).all()}
    n = len(rows) or call.results
    exp_on = "job_requirements" in params
    country = (params.get("country") or "").upper()
    query = params.get("query") or ""
    words = key_words(query)
    findings: list[str] = []
    tips: list[str] = []

    if call.status != "ok":
        findings.append("This request failed, so nothing came back." + (f" ({call.error})" if call.error else ""))
        return CallExplainOut(params=explain_params(params), findings=findings, suggestions=tips,
                              history=history(session, params, call.query_id, exclude_id=call.id))

    if n == 0:
        narrowing = [k for k in ("job_requirements", "date_posted", "employment_types", "work_from_home") if k in params]
        if '"' in query:
            narrowing.insert(0, "quoted title")
        findings.append("Google returned no postings for this text with these filters"
                        + (f" (narrowed by: {', '.join(narrowing)})." if narrowing else "."))
    elif n < 10 and call.page == 1:
        findings.append(f"Only {n} of a possible 10 came back: few postings matched every filter, and Google fills a "
                        "thin page with the closest it has.")

    remote = [r for r in rows if _REMOTE.search(r.location_text or "")]
    off = [r for r in rows if words and not on_topic(r.title, words)]
    entry_off = [r for r in off if _ENTRY.search(r.title or "")]
    if remote and country:
        findings.append(f"{len(remote)} of {n} were remote “Anywhere” listings, not jobs listed in {country}.")
    if off:
        findings.append(f"{len(off)} of {n} titles contain none of the search's key words ({', '.join(sorted(words))}): "
                        "Google matched them to a broader occupation.")
    if exp_on and entry_off:
        findings.append(f"{_plural(len(entry_off), 'was a', 'were')} generic “Fresher” / entry-level "
                        f"posting{'s' if len(entry_off) != 1 else ''} from other fields, the kind the experience "
                        "filter favours.")

    states = [jobs.get(r.job_id) for r in rows]
    title_fail = sum(1 for j in states if j and j.pipeline_status == "not_relevant")
    excluded = Counter(j.status_reason or "criteria" for j in states if j and j.pipeline_status == "excluded")
    years = sum(v for k, v in excluded.items() if k.startswith("Asks for"))
    known = sum(1 for r in rows if r.outcome in ("unchanged", "duplicate", "already_seen"))
    if known:
        findings.append(f"{known} of {n} you already had (the same posting, or the same job on another board).")
    if title_fail:
        findings.append(f"{title_fail} of {n} failed the title check against your roles (Not relevant).")
    if excluded:
        why = "; ".join(f"{k}{f' ×{v}' if v > 1 else ''}" for k, v in excluded.most_common(4))
        findings.append(f"{sum(excluded.values())} of {n} went to Excluded by your criteria ({why}).")
    if exp_on and years:
        findings.append(f"{_plural(years, 'job')} asked for more years than yours even with the experience filter "
                        "on: Google's experience tag isn't reliable.")
    if n:
        findings.append(f"{call.relevant_jobs} of {n} reached your Matches.")

    # What to change next time.
    if exp_on and (n < 5 or entry_off or years):
        tips.append("Turn off “Send the experience filter” (Admin → JSearch): it hides postings Google hasn't "
                    "tagged by experience.")
    if '"' in query and n < 3:
        tips.append("Exact wording found little: try “Title group” (several quoted titles) or Plain.")
    elif '"' not in query and n and len(off) * 2 >= n:
        tips.append("Most titles were off-topic: try “Exact title” or “Title group” wording so the title must "
                    "appear in the posting.")
    if params.get("date_posted") in ("today", "3days", "week") and n < 5:
        tips.append(f"The window was {params['date_posted']}: a repeat search only looks back to its last run (at "
                    "least the floor in Admin → JSearch). Wait longer between repeats, or set the floor to month.")
    if remote and country and len(remote) * 2 >= n:
        tips.append(f"Mostly remote filler: the filters left little to find in {country}, so loosen them first.")

    return CallExplainOut(params=explain_params(params), findings=findings, suggestions=tips,
                          history=history(session, params, call.query_id, exclude_id=call.id))
