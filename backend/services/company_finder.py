"""The company finder (Phase 2.7 E): finds companies hiring in India and their job boards, so the
scan reads more than the companies we happened to know about.

Leads (`company_leads`):
- **seed**: the seed list of companies hiring engineers in India (`seed_companies.csv`, compiled
  from public lists), synced on start.
- **crawl**: board addresses (jobs.lever.co/<x>, boards.greenhouse.io/<x>, ...) listed in the free
  Common Crawl URL index (`crawl_index.py`), a few index pages per run.

For each lead the finder works out the board, cheapest first:
1. already known (crawl leads);
2. the company's careers page, read once (robots.txt honoured), for a link to a board system we
   read (`sources.parse_careers_url`);
3. the company's name tried on each board system (boards.greenhouse.io/<name>, ...).
Then it reads the board once and runs the scan's pre-check: a board with jobs in India becomes an
`employers` row (origin "discovered") that every scan reads; otherwise the lead is checked again
after `recheck_after_days` (`no_board_recheck_days` when no board was found).

Free and legal: public careers pages and public, keyless boards only; one request at a time with a
delay; never a login, never a form. It stores no jobs: the next scan reads the kept boards.
Runs in a background thread (Scan Jobs -> Company finder -> Find companies, or after each scan).
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import threading
import time
from datetime import timedelta
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

from sqlmodel import Session, col, select

from backend.config import get_tuning
from backend.db import CompanyLead, Employer, get_meta, new_session, set_meta, utcnow
from backend.job_schemas import FinderLeadOut, FinderSettings, FinderStatusOut
from backend.services.sources import BOARDS, SourceError, SourceHttp, parse_careers_url
from backend.services.sources.base import USER_AGENT

log = logging.getLogger(__name__)

SEED_FILE = Path(__file__).with_name("seed_companies.csv")
STATE_KEY = "company_finder_state"
# Board systems tried with a company's name, most common among Indian tech companies first.
# Zoho Recruit isn't guessed (a ~2 MB page per try); its careers-page links are still found.
GUESS_ORDER = ("greenhouse", "lever", "ashby", "keka", "darwinbox", "workable", "smartrecruiters", "recruitee")
CAREERS_PATHS = ("/careers", "/jobs", "/careers/", "/company/careers", "/")
_lock = threading.Lock()
_running = threading.Event()


def settings() -> FinderSettings:
    raw = ((get_tuning().scout or {}).get("search") or {}).get("finder") or {}
    return FinderSettings(**raw)


def _aware(dt):
    from datetime import UTC

    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


# ── the seed list ──────────────────────────────────────────────────────────────


def seed_rows() -> list[dict]:
    if not SEED_FILE.exists():
        return []
    with SEED_FILE.open(encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("name") or "").strip()]


def sync_seed(session: Session) -> int:
    """Add seed companies that aren't leads yet (on start, when the file changed). Returns added."""
    rows = seed_rows()
    version = hashlib.sha1(SEED_FILE.read_bytes()).hexdigest()[:12] if rows else "none"
    if get_meta(session, "seed_companies_version") == version:
        return 0
    have = {(lead.name or "").strip().lower() for lead in session.exec(select(CompanyLead).where(CompanyLead.origin == "seed")).all()}
    added = 0
    for r in rows:
        name = r["name"].strip()
        if name.lower() in have:
            continue
        careers = (r.get("careers_url") or "").strip() or None
        parsed = parse_careers_url(careers) if careers else None
        session.add(CompanyLead(name=name, domain=_domain(r.get("domain")), careers_url=careers, origin="seed",
                                category=(r.get("category") or "").strip() or None,
                                kind=parsed[0] if parsed else None, board=parsed[1] if parsed else None,
                                how="careers_page" if parsed else None))
        have.add(name.lower())
        added += 1
    set_meta(session, "seed_companies_version", version)
    session.commit()
    return added


def _domain(value: str | None) -> str | None:
    v = (value or "").strip().lower()
    if not v:
        return None
    host = urlparse(v if "://" in v else "https://" + v).netloc
    return host.removeprefix("www.") or None


# ── working out a company's board ──────────────────────────────────────────────


def slug_candidates(name: str, domain: str | None) -> list[str]:
    """Board ids a company plausibly uses: its domain's name, its name squashed / hyphenated."""
    base = re.sub(r"\b(technologies|technology|labs|private|pvt|ltd|limited|inc|india|software|solutions)\b\.?", "",
                  name.lower())
    words = re.findall(r"[a-z0-9]+", base) or re.findall(r"[a-z0-9]+", name.lower())
    out = []
    if domain:
        out.append(domain.split(".")[0])
    out += ["".join(words), "-".join(words)]
    # Too short or too common to be sure it's this company's board.
    return [s for s in dict.fromkeys(out) if len(s) >= 4]


def _allowed(http: SourceHttp, url: str, robots: dict[str, robotparser.RobotFileParser | None]) -> bool:
    u = urlparse(url)
    origin = f"{u.scheme}://{u.netloc}"
    if origin not in robots:
        rp = robotparser.RobotFileParser()
        try:
            rp.parse(http.get_text(origin + "/robots.txt").splitlines())
            robots[origin] = rp
        except SourceError:
            robots[origin] = None  # no robots.txt (or unreadable): allowed
    rp = robots[origin]
    return rp is None or rp.can_fetch(USER_AGENT, url)


_LINK = re.compile(r"""(?:href|src|data-src|action)\s*=\s*["']([^"']+)["']|(https?://[^\s"'<>\\)]+)""", re.I)


def board_links(html: str, base: str) -> list[tuple[str, str, str]]:
    """Every (kind, board, url) a careers page links to or embeds (iframes and scripts included)."""
    found: dict[tuple[str, str], str] = {}
    for m in _LINK.finditer(html or ""):
        raw = (m.group(1) or m.group(2) or "").strip()
        if not raw or raw.startswith(("#", "mailto:", "javascript:")):
            continue
        url = urljoin(base, raw)
        parsed = parse_careers_url(url)
        if parsed and (parsed[0], parsed[1].lower()) not in found:
            found[(parsed[0], parsed[1].lower())] = url
    return [(k, b, u) for (k, b), u in found.items()]


def from_careers_page(http: SourceHttp, lead: CompanyLead, delay: float) -> tuple[str, str] | None:
    pages = [lead.careers_url] if lead.careers_url else []
    if lead.domain:
        pages += [f"https://{lead.domain}{p}" for p in CAREERS_PATHS]
    robots: dict = {}
    for url in dict.fromkeys(p for p in pages if p):
        parsed = parse_careers_url(url)
        if parsed:
            return parsed
        try:
            if not _allowed(http, url, robots):
                continue
            time.sleep(delay)
            html = http.get_text(url)
        except SourceError:
            continue
        links = board_links(html, url)
        if links:
            return links[0][0], links[0][1]
    return None


def read_board(http: SourceHttp, kind: str, board: str, name: str, phrases) -> tuple[int, int, int] | None:
    """(postings, in India, matching your roles), or None when there's no such board."""
    from backend.services.employers import precheck

    try:
        jobs = BOARDS[kind].list_jobs(http, board, name)
    except SourceError:
        return None
    kept, out_scope, _ = precheck(jobs, phrases)
    return len(jobs), len(jobs) - out_scope, len(kept)


def guess_board(http: SourceHttp, lead: CompanyLead, phrases, delay: float):
    """Try the company's name on each board system; the first board with postings wins."""
    for slug in slug_candidates(lead.name, lead.domain):
        for kind in GUESS_ORDER:
            if kind not in BOARDS:
                continue
            time.sleep(delay)
            counts = read_board(http, kind, slug, lead.name, phrases)
            if counts and counts[0] > 0:
                return kind, slug, counts
    return None


# ── checking one lead ──────────────────────────────────────────────────────────


def check_lead(s: Session, http: SourceHttp, lead: CompanyLead, phrases, cfg: FinderSettings) -> str:
    """Work out the lead's board, read it once, keep it or schedule the next look. Returns the status."""
    now = utcnow()
    lead.attempts += 1
    lead.checked_at = now
    counts = None
    if not lead.kind:
        hit = from_careers_page(http, lead, cfg.delay_seconds) if (lead.careers_url or lead.domain) else None
        if hit:
            lead.kind, lead.board, lead.how = hit[0], hit[1], "careers_page"
        else:
            guessed = guess_board(http, lead, phrases, cfg.delay_seconds)
            if guessed:
                lead.kind, lead.board, counts = guessed
                lead.how = "guessed"
    if lead.kind and counts is None:
        time.sleep(cfg.delay_seconds)
        counts = read_board(http, lead.kind, lead.board, lead.name, phrases)
    if not lead.kind or counts is None:
        if lead.kind:
            lead.note = "Its board is gone or couldn't be read"
            if lead.origin != "crawl":
                lead.kind = lead.board = lead.how = None  # look for it afresh next time
        else:
            lead.note = "No job board found on a system the app reads"
        lead.status = "no_board"
        lead.next_check_at = now + timedelta(days=cfg.no_board_recheck_days)
        s.add(lead)
        return lead.status
    lead.total_jobs, lead.india_jobs, lead.matching_jobs = counts
    if lead.india_jobs <= 0:
        lead.status = "no_india_jobs"
        lead.note = f"{lead.total_jobs} postings, none in India"
        lead.next_check_at = now + timedelta(days=cfg.recheck_after_days)
        s.add(lead)
        return lead.status
    lead.status, lead.next_check_at = "kept", None
    lead.note = f"{lead.india_jobs} of {lead.total_jobs} postings in India, {lead.matching_jobs} matching your roles"
    lead.employer_id = _keep(s, lead).id
    s.add(lead)
    return lead.status


def _keep(s: Session, lead: CompanyLead) -> Employer:
    """The lead becomes (or switches back on) a company the scan reads."""
    a = BOARDS[lead.kind]
    e = s.exec(select(Employer).where(Employer.kind == lead.kind, col(Employer.board).ilike(lead.board))).first()
    how = {"careers_page": "its careers page", "guessed": "its name", "crawl": "the Common Crawl index"}.get(lead.how or "", "the finder")
    if e is None:
        e = Employer(name=lead.name, kind=lead.kind, board=lead.board, careers_url=a.board_url(lead.board),
                     origin="discovered", enabled=True, note=f"Found by the company finder through {how}"[:300])
    elif not e.enabled and not e.last_error:
        e.enabled, e.empty_scans, e.next_read_at = True, None, None
    e.last_found, e.last_in_scope, e.last_kept = lead.total_jobs, lead.india_jobs, lead.matching_jobs
    s.add(e)
    s.commit()
    s.refresh(e)
    return e


# ── a run ──────────────────────────────────────────────────────────────────────


def due_leads(s: Session, limit: int) -> list[CompanyLead]:
    """Pending leads first (seed before crawl), then those whose re-check date has come."""
    now = utcnow()
    rows = s.exec(select(CompanyLead).where(CompanyLead.status != "kept")).all()
    due = [r for r in rows if r.next_check_at is None or _aware(r.next_check_at) <= now]
    due.sort(key=lambda r: (r.status != "pending", r.origin != "seed", r.id or 0))
    return due[:limit]


def _state(s: Session) -> dict:
    try:
        return json.loads(get_meta(s, STATE_KEY) or "{}")
    except ValueError:
        return {}


def _save_state(**changes) -> None:
    with new_session() as s:
        st = _state(s)
        st.update(changes)
        set_meta(s, STATE_KEY, json.dumps(st, default=str))
        s.commit()


def run(trigger: str = "manual") -> dict[str, int]:
    """One finder run: harvest a few Common Crawl index pages, then check `leads_per_run` leads."""
    from backend.services import crawl_index
    from backend.services.employers import role_phrases

    cfg = settings()
    counts: dict[str, int] = {}
    _save_state(running=True, trigger=trigger, started_at=utcnow().isoformat(), finished_at=None,
                message="Starting", error=None)
    try:
        with new_session() as s:
            sync_seed(s)
        if cfg.crawl and cfg.crawl_pages_per_run > 0:
            _save_state(message="Reading the Common Crawl index")
            counts["crawl_leads"] = crawl_index.harvest(cfg)
        with new_session() as s:
            phrases = role_phrases(s)
            leads = due_leads(s, cfg.leads_per_run)
            with SourceHttp(timeout=cfg.timeout_seconds, max_retries=0) as http:
                for i, lead in enumerate(leads):
                    _save_state(message=f"Checking {lead.name} ({i + 1} of {len(leads)})")
                    try:
                        status = check_lead(s, http, lead, phrases, cfg)
                    except Exception as e:  # noqa: BLE001 - one bad page never stops the run
                        log.warning("finder: %s failed: %s", lead.name, e)
                        lead.status, lead.note = "error", f"{type(e).__name__}: {e}"[:300]
                        lead.next_check_at = utcnow() + timedelta(days=cfg.recheck_after_days)
                        s.add(lead)
                        status = "error"
                    s.commit()
                    counts[status] = counts.get(status, 0) + 1
                    counts["checked"] = counts.get("checked", 0) + 1
        _save_state(running=False, finished_at=utcnow().isoformat(), last_run=counts,
                    message=f"Checked {counts.get('checked', 0)} companies, kept {counts.get('kept', 0)}")
    except Exception as e:  # noqa: BLE001 - shown on the finder card
        log.exception("company finder failed")
        _save_state(running=False, finished_at=utcnow().isoformat(), error=f"{type(e).__name__}: {e}"[:300],
                    message="Failed")
    return counts


def start(trigger: str = "manual") -> bool:
    """Start a run in the background. False when it's off or already running."""
    if not settings().enabled or not _lock.acquire(blocking=False):
        return False
    _running.set()

    def go():
        try:
            run(trigger)
        finally:
            _running.clear()
            _lock.release()

    threading.Thread(target=go, name="company-finder", daemon=True).start()
    return True


def is_running() -> bool:
    return _running.is_set()


def recover() -> None:
    """On start: a run cut off by a restart isn't running any more; sync the seed list."""
    with new_session() as s:
        sync_seed(s)
        st = _state(s)
        if st.get("running"):
            st.update(running=False, message="Interrupted by a restart")
            set_meta(s, STATE_KEY, json.dumps(st))
            s.commit()


def status(session: Session) -> FinderStatusOut:
    from backend.services import crawl_index

    cfg = settings()
    st = _state(session)
    leads = session.exec(select(CompanyLead)).all()
    by_status: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    for lead in leads:
        by_status[lead.status] = by_status.get(lead.status, 0) + 1
        by_origin[lead.origin] = by_origin.get(lead.origin, 0) + 1
    kept = sorted((x for x in leads if x.status == "kept"), key=lambda x: -(x.matching_jobs or 0))
    return FinderStatusOut(
        enabled=cfg.enabled, running=is_running(), trigger=st.get("trigger"), message=st.get("message"),
        error=st.get("error"), started_at=st.get("started_at"), finished_at=st.get("finished_at"),
        last_run=st.get("last_run") or {}, by_status=by_status, by_origin=by_origin,
        crawl=crawl_index.progress(session) if cfg.crawl else None,
        kept=[FinderLeadOut(name=x.name, kind=x.kind, kind_label=BOARDS[x.kind].label if x.kind in BOARDS else x.kind,
                            how=x.how, total_jobs=x.total_jobs, india_jobs=x.india_jobs,
                            matching_jobs=x.matching_jobs, checked_at=x.checked_at) for x in kept[:50]],
    )
