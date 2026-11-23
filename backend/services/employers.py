"""Companies and their job boards (Phase 2.7 A1).

- Search Settings -> Companies: paste a careers link; the ATS and board id are read from it
  (`sources.parse_careers_url`). Starter list (A2): drafted companies, added switched off.
- **Pre-check** (board jobs only; a board lists every job the company has, worldwide): keep a
  job when it is in India or remote and open to India (unknown kept), AND its title matches one
  of your roles or their search titles (word match after abbreviation expansion, no
  embeddings). Search criteria still never remove a job; this is the source's scope.
- **Scan step** (`collect`): every due company; one worker per board system, each one request at a time with a polite delay (2026-11-23); free,
  so no request budget, but each board fetch is logged in `api_calls` (api = the ATS) like a
  JSearch request, so "Requests and what they found" and the per-source table cover it.
- A board lists only open postings: a stored job its board no longer lists is marked expired.
- The system manages the list (no Companies page since 2026-11-20): the starter list (A2), and
  companies **found automatically** (A3, `discover`) from the apply links of stored jobs. A
  board that's gone (404) or, for found companies, has no job in India is switched off.
"""
from __future__ import annotations

import logging
import queue
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session, select

from backend.config import get_tuning
from backend.db import ApiCall, Employer, Job, new_session, utcnow
from backend.job_schemas import BoardsSettings, EmployerCheckOut, EmployerOut, NormalizedJob
from backend.services import role_contexts, search_settings
from backend.services.job_facts import derive_facts, location_match
from backend.services.job_text import expand_abbreviations, job_plain_text
from backend.services.sources import BOARDS, SourceError, SourceHttp, parse_careers_url
from backend.services.starter_companies import STARTER

log = logging.getLogger(__name__)

GENERIC = {
    "engineer", "engineers", "engineering", "developer", "developers", "development", "associate", "specialist",
    "senior", "sr", "junior", "jr", "lead", "staff", "principal", "intern", "internship", "fresher", "trainee",
    "graduate", "entry", "level", "and", "or", "of", "the", "for", "with", "in", "a", "an", "to", "i", "ii", "iii",
}


class EmployerError(ValueError):
    """A readable problem with a company (bad link, duplicate)."""


def settings() -> BoardsSettings:
    raw = ((get_tuning().scout or {}).get("search") or {}).get("boards") or {}
    return BoardsSettings(**raw)


def out(e: Employer) -> EmployerOut:
    a = BOARDS[e.kind]
    return EmployerOut(
        id=e.id, name=e.name, kind=e.kind, kind_label=a.label, board=e.board, board_url=a.board_url(e.board),
        careers_url=e.careers_url, enabled=e.enabled,
        origin=e.origin if e.origin in ("you", "starter", "discovered") else "you",
        note=e.note, last_checked_at=e.last_checked_at, last_error=e.last_error, last_found=e.last_found,
        last_in_scope=e.last_in_scope, last_kept=e.last_kept,
    )


def list_all(session: Session) -> list[Employer]:
    return sorted(session.exec(select(Employer)).all(), key=lambda e: (not e.enabled, e.name.lower()))


def _pretty(board: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_.]+", board) if w) or board


def add(session: Session, url: str, name: str | None = None, *, origin: str = "you", note: str | None = None,
        enabled: bool = True) -> Employer:
    parsed = parse_careers_url(url)
    if not parsed:
        names = ", ".join(a.label for a in BOARDS.values())
        raise EmployerError(f"That isn't a job-board link the app reads ({names}). Paste the company's jobs "
                            "page on one of those (e.g. jobs.lever.co/acme or job-boards.greenhouse.io/acme).")
    kind, board = parsed
    dup = session.exec(select(Employer).where(Employer.kind == kind, Employer.board == board)).first()
    if dup:
        raise EmployerError(f"{dup.name} is already in your companies ({BOARDS[kind].label} board “{board}”).")
    e = Employer(name=(name or "").strip() or _pretty(board), kind=kind, board=board, careers_url=url.strip(),
                 origin=origin, note=note, enabled=enabled)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def add_starter(session: Session) -> list[Employer]:
    """Add the drafted starter companies you don't have yet, switched off (you check, then enable)."""
    added = []
    for row in STARTER:
        try:
            added.append(add(session, row["url"], row["name"], origin="starter", note=row.get("note"), enabled=False))
        except EmployerError:
            continue  # already there
    return added


# ── the pre-check ──────────────────────────────────────────────────────────────


def _words(text: str) -> set[str]:
    t = expand_abbreviations((text or "").lower().replace("back-end", "backend").replace("front-end", "frontend")
                             .replace("full-stack", "fullstack").replace("full stack", "fullstack"))
    return set(re.findall(r"[a-z0-9+#]+", t))


def role_phrases(session: Session) -> list[set[str]]:
    """The distinctive words of each role and each of its search titles (Memory -> Role contexts)."""
    from backend.services.job_search import clean_roles

    roles = clean_roles(search_settings.get(session, "criteria").roles)
    terms = role_contexts.search_terms(session)
    phrases = [*roles, *[t for r in roles for t in terms.get(role_contexts.role_key(r), ([], []))[0]]]
    out_: list[set[str]] = []
    for p in phrases:
        w = _words(p) - GENERIC
        if w and w not in out_:
            out_.append(w)
    return out_


def title_matches(title: str, phrases: list[set[str]]) -> bool:
    """No roles = everything matches; else every distinctive word of some role phrase is in the title."""
    if not phrases:
        return True
    words = _words(title)
    return any(p <= words for p in phrases)


def in_scope(n: NormalizedJob) -> bool:
    """In India, or remote and open to India; unknown location is kept."""
    f = derive_facts(n, job_plain_text(n))
    where = location_match(["IN"], f.get("country_codes") or [], f.get("remote_regions") or [],
                           f.get("workplace_type") or n.workplace_type, n.location_text)
    return where is not False


def precheck(jobs: list[NormalizedJob], phrases: list[set[str]]) -> tuple[list[NormalizedJob], int, int]:
    """(kept, left out as outside India, left out as title not matching)."""
    kept, out_scope, out_title = [], 0, 0
    for n in jobs:
        if not in_scope(n):
            out_scope += 1
        elif not title_matches(n.title, phrases):
            out_title += 1
        else:
            kept.append(n)
    return kept, out_scope, out_title


# ── check one company (Companies -> Check; stores no jobs) ─────────────────────


def check(session: Session, e: Employer) -> EmployerCheckOut:
    cfg = settings()
    a = BOARDS[e.kind]
    e.last_checked_at = utcnow()
    try:
        with SourceHttp(timeout=cfg.timeout_seconds, max_retries=1) as http:
            jobs = a.list_jobs(http, e.board, e.name)
    except SourceError as err:
        e.last_error = str(err)[:300]
        session.add(e)
        session.commit()
        return EmployerCheckOut(employer=out(e), found=0, in_scope=0, kept=0, examples=[], error=e.last_error)
    kept, out_scope, _ = precheck(jobs, role_phrases(session))
    e.last_error, e.last_found, e.last_in_scope, e.last_kept = None, len(jobs), len(jobs) - out_scope, len(kept)
    session.add(e)
    session.commit()
    examples = [f"{n.title} · {n.location_text or 'location not stated'}" for n in kept[:8]]
    return EmployerCheckOut(employer=out(e), found=len(jobs), in_scope=len(jobs) - out_scope, kept=len(kept),
                            examples=examples)


# ── the scan step ──────────────────────────────────────────────────────────────


def chosen(selection, kind: str) -> bool:
    """This board system is part of the scan (Scan now tick box; None = every source)."""
    return selection is None or selection.sources is None or kind in selection.sources


def due(e: Employer, now=None) -> bool:
    """Read this scan: switched on, and not a quiet board waiting for its next read (Phase 2.7 E)."""
    return e.enabled and (e.next_read_at is None or _aware(e.next_read_at) <= (now or utcnow()))


def _roles_key(phrases: list[set[str]]) -> str:
    import hashlib

    return hashlib.sha1("|".join(sorted(" ".join(sorted(p)) for p in phrases)).encode()).hexdigest()[:12]


def refresh_schedule(session: Session) -> None:
    """Your roles changed since the boards were last judged: every quiet board is due again."""
    from backend.db import get_meta, set_meta

    key = _roles_key(role_phrases(session))
    if get_meta(session, "boards_roles_key") == key:
        return
    for e in session.exec(select(Employer).where(Employer.next_read_at != None)).all():  # noqa: E711
        e.next_read_at = None
        session.add(e)
    set_meta(session, "boards_roles_key", key)
    session.commit()


def planned(session: Session, selection=None) -> int:
    """How many companies this scan will read (0 when boards are off or all their boxes are unticked)."""
    if not settings().enabled:
        return 0
    refresh_schedule(session)
    now = utcnow()
    return sum(1 for e in session.exec(select(Employer)).all() if due(e, now) and chosen(selection, e.kind))


def plan_rows(session: Session, selection=None) -> list:
    """Scan now: one tick box per board system, with the companies it covers."""
    from backend.job_schemas import PlanSource

    on = settings().enabled
    if on:
        refresh_schedule(session)
    now = utcnow()
    every = [e for e in list_all(session) if e.enabled]
    rows = []
    for kind, a in BOARDS.items():
        mine = [e for e in every if e.kind == kind]
        names = [e.name for e in mine if due(e, now)]
        quiet = len(mine) - len(names)
        pick = chosen(selection, kind)
        n = len(names)
        if not on:
            summary = "Switched off ([scout.search.boards] enabled = false)"
        elif n == 0 and quiet:
            summary = f"{quiet} compan{'y' if quiet == 1 else 'ies'}, none due · no matching jobs last time, read weekly"
        elif n == 0:
            summary = "No companies yet · the company finder adds them"
        elif not pick:
            summary = "Skipped this scan"
        else:
            found = sum(1 for e in mine if e.origin == "discovered")
            summary = (f"{n} compan{'y' if n == 1 else 'ies'}" + (f" ({found} found by the app)" if found else "")
                       + (f" · {quiet} more read weekly (no matching jobs last time)" if quiet else "") + " · free"
                       + ("" if a.agent_can_apply else " · you apply (the form has a CAPTCHA)"))
        rows.append(PlanSource(name=kind, label=a.label, kind="board", configured=True, enabled=on and n > 0,
                               chosen=on and n > 0 and pick, requests=0, summary=summary, details=names))
    return rows


# ── the system-managed company list ────────────────────────────────────────────


def _starter_version() -> str:
    import hashlib

    return hashlib.sha1("|".join(sorted(r["url"] for r in STARTER)).encode()).hexdigest()[:12]


def sync_starter() -> int:
    """Start-up: the system manages the companies. Starter companies you don't have yet are added
    switched on; companies the system switched off (a board that's gone) stay off. Returns added."""
    from backend.db import get_meta, set_meta

    with new_session() as s:
        if get_meta(s, "starter_companies_version") == _starter_version():
            return 0
        added = 0
        for row in STARTER:
            try:
                add(s, row["url"], row["name"], origin="starter", note=row.get("note"), enabled=True)
                added += 1
            except EmployerError:
                continue
        set_meta(s, "starter_companies_version", _starter_version())
        s.commit()
    return added


# ── finding companies automatically (Phase 2.7 A3) ─────────────────────────────


def _job_links(job: Job) -> list[str]:
    """Every link a stored job carries: its best apply link, apply / posting URLs, where each
    source saw it, and (while the raw record is kept) all of JSearch's apply options."""
    from backend.services.sources.jsearch import apply_links

    links = [job.apply_route_url, job.apply_url, job.job_url, *[x.get("job_url") for x in job.seen_on or []]]
    if isinstance(job.raw_payload, dict):
        links += [x["url"] for x in apply_links(job.raw_payload)]
    return [u for u in dict.fromkeys(links) if isinstance(u, str) and u]


def discover(session: Session | None = None) -> list[str]:
    """After the searches of a scan, before the boards are read: a stored job whose link points
    to a company board we read (Greenhouse, Lever, ...) adds that company (origin "discovered").
    Nothing is fetched here; the company's first board read in `collect` checks it has jobs in
    India, else it is switched off. A company switched off for having no India jobs is tried
    again after `retry_after_days` when a job links to it again. Returns the names added."""
    cfg = settings()
    if not cfg.enabled or not cfg.discover or cfg.max_new_per_scan <= 0:
        return []
    own = session is None
    s = session or new_session()
    try:
        known = {(e.kind, e.board.lower()): e for e in s.exec(select(Employer)).all()}
        found: dict[tuple[str, str], tuple[str, str, Job]] = {}
        for job in s.exec(select(Job).order_by(Job.id.desc())).all():  # newest jobs first
            if any(x.get("source") in BOARDS for x in job.seen_on or []):
                continue  # came from a board we already read
            for url in _job_links(job):
                parsed = parse_careers_url(url)
                if parsed and (parsed[0], parsed[1].lower()) not in found:
                    found[(parsed[0], parsed[1].lower())] = (parsed[1], url, job)
        retry_before = utcnow() - timedelta(days=cfg.retry_after_days)
        added: list[str] = []
        for (kind, key), (board, url, job) in found.items():
            if len(added) >= cfg.max_new_per_scan:
                break
            e = known.get((kind, key))
            if e is None:
                e = Employer(name=(job.company_name or "").strip() or _pretty(board), kind=kind, board=board,
                             careers_url=url, origin="discovered", enabled=True, found_via_job_id=job.id,
                             note=f"Found through “{job.title}”"[:300])
            elif (e.origin == "discovered" and not e.enabled and not e.last_error
                  and e.last_checked_at is not None and _aware(e.last_checked_at) < retry_before):
                e.enabled, e.empty_scans = True, None  # no India jobs last time: look again
            else:
                continue
            s.add(e)
            added.append(e.name)
        s.commit()
        return added
    finally:
        if own:
            s.close()


def _aware(dt):
    from datetime import UTC

    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _judge_discovered(e: Employer, in_scope: int, cfg: BoardsSettings) -> None:
    """A found company stays only while its board has jobs in India (see `discover`)."""
    if e.origin != "discovered":
        return
    if in_scope > 0:
        e.empty_scans = 0
        return
    first = e.empty_scans is None
    e.empty_scans = (e.empty_scans or 0) + 1
    if first or e.empty_scans >= cfg.drop_after_empty_scans:
        e.enabled = False
        e.note = ("Switched off: its board has no jobs in India" if first
                  else f"Switched off: no jobs in India for {e.empty_scans} reads in a row")


def _close_missing(session: Session, kind: str, board: str, live_ids: set[str]) -> int:
    """Stored jobs from this board that it no longer lists: the posting closed -> expired."""
    closed = 0
    prefix = f"{board}:"
    for job in session.exec(select(Job).where(Job.status == "active")).all():
        mine = [x for x in job.seen_on or [] if x.get("source") == kind and str(x.get("source_job_id", "")).startswith(prefix)]
        if mine and not any(x["source_job_id"] in live_ids for x in mine):
            job.status, job.status_changed_at = "expired", utcnow()
            session.add(job)
            closed += 1
    return closed


@dataclass
class _Read:
    """One board read by a worker; stored by the scan's own thread."""

    employer_id: int
    at: datetime
    jobs: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    out_scope: int = 0
    out_title: int = 0
    detailed: list = field(default_factory=list)
    error: SourceError | None = None


def _read_boards(companies: list[Employer], phrases, cfg: BoardsSettings) -> Iterator[_Read]:
    """Read the companies' boards, one worker per board system (each system still gets one request
    at a time, with the delay), and yield each read as it finishes. Only network work happens in the
    workers; the caller stores everything in its own session."""
    groups: dict[str, list[tuple[int, str, str]]] = {}
    for e in companies:
        groups.setdefault(e.kind, []).append((int(e.id), e.board, e.name))
    done: queue.Queue = queue.Queue()

    def work(kind: str, items: list[tuple[int, str, str]]) -> None:
        a = BOARDS[kind]
        try:
            with SourceHttp(timeout=cfg.timeout_seconds, max_retries=1) as http:
                for i, (eid, board, name) in enumerate(items):
                    if i and cfg.delay_seconds:
                        time.sleep(cfg.delay_seconds)
                    r = _Read(employer_id=eid, at=utcnow())
                    try:
                        r.jobs = a.list_jobs(http, board, name)
                        r.kept, r.out_scope, r.out_title = precheck(r.jobs, phrases)
                        r.detailed = [a.complete(http, board, n) if k < cfg.max_details_per_board else n
                                      for k, n in enumerate(r.kept)]
                    except SourceError as err:
                        r.error = err
                    except Exception as err:  # noqa: BLE001 - an odd answer fails this board, not the scan
                        r.error = SourceError(f"{a.label}: {type(err).__name__}: {err}")
                    done.put(r)
        finally:
            done.put(None)  # this worker is finished

    with ThreadPoolExecutor(max_workers=max(1, len(groups)), thread_name_prefix="boards") as pool:
        for kind, items in groups.items():
            pool.submit(work, kind, items)
        left = len(groups)
        while left:
            r = done.get()
            if r is None:
                left -= 1
            else:
                yield r


def collect(scan_id: str, totals: dict[str, int], selection=None) -> list[int]:
    """① for company boards: every due company, pre-checked, stored. Returns api_calls ids. Boards
    are read one worker per board system (2026-11-23), stored here one at a time."""
    from backend.services.job_search import ingest, record_call_jobs

    cfg = settings()
    if not cfg.enabled:
        return []
    call_ids: list[int] = []
    with new_session() as s:
        refresh_schedule(s)
        now = utcnow()
        companies = [e for e in list_all(s) if due(e, now) and chosen(selection, e.kind)]
        totals["boards_quiet"] = sum(1 for e in list_all(s) if e.enabled and not due(e, now) and chosen(selection, e.kind))
        if not totals["boards_quiet"]:
            del totals["boards_quiet"]
        if not companies:
            return []
        phrases = role_phrases(s)
        lim = search_settings.get(s, "limits")
        by_id = {e.id: e for e in companies}
        for read in _read_boards(companies, phrases, cfg):
            e = by_id[read.employer_id]
            a = BOARDS[e.kind]
            call = ApiCall(api=e.kind, purpose="scan", scan_id=scan_id,
                           params={"query": f"{e.name} · {a.label} board", "board": e.board, "company": e.name})
            s.add(call)
            s.commit()
            s.refresh(call)
            call_ids.append(int(call.id))
            e.last_checked_at = read.at
            if read.error is not None:
                call.status, call.error = "error", str(read.error)[:300]
                e.last_error = call.error
                if "HTTP 404" in call.error or "not found" in call.error.lower():
                    e.enabled = False  # the board is gone (or the id was wrong): the system stops reading it
                s.add(call)
                s.add(e)
                s.commit()
                totals["board_errors"] = totals.get("board_errors", 0) + 1
                continue
            jobs, kept, out_scope, out_title, detailed = read.jobs, read.kept, read.out_scope, read.out_title, read.detailed
            returned, new = [], 0
            for n in detailed:
                result = ingest(s, n, call.id, 0, lim.repost_window_days)  # a board lists only open jobs: no age limit
                returned.append((n, result))
                totals[result] = totals.get(result, 0) + 1
                new += result == "new"
            closed = _close_missing(s, e.kind, e.board, {n.source_job_id for n in jobs})
            s.commit()
            record_call_jobs(s, call.id, returned)
            call.status, call.http_status, call.results, call.new_jobs = "ok", 200, len(jobs), new
            call.skipped_scope, call.skipped_title = out_scope, out_title
            e.last_error, e.last_found, e.last_in_scope, e.last_kept = None, len(jobs), len(jobs) - out_scope, len(kept)
            _judge_discovered(e, len(jobs) - out_scope, cfg)
            # Read schedule: a board with nothing matching your roles is read again in a week.
            e.next_read_at = (utcnow() + timedelta(days=cfg.quiet_board_days)
                              if not kept and cfg.quiet_board_days > 0 else None)
            if not e.enabled:
                totals["companies_dropped"] = totals.get("companies_dropped", 0) + 1
            s.add(call)
            s.add(e)
            s.commit()
            totals["fetched"] = totals.get("fetched", 0) + len(detailed)
            totals["board_requests"] = totals.get("board_requests", 0) + 1
            totals["closed"] = totals.get("closed", 0) + closed
    return call_ids
