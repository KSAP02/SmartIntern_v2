"""The company finder (Phase 2.7 E): finds companies hiring in India and their job boards, so the
scan reads more than the companies we happened to know about.

Leads (`company_leads`):
- **seed**: the seed list of companies hiring engineers in India (`seed_companies.csv`, compiled
  from public lists), synced on start.
- **yc**: Y Combinator companies based in India, from the free YC open-data list
  (yc-oss.github.io/api, rebuilt daily from YC's public directory), read at most weekly.
- **crawl**: board addresses (jobs.lever.co/<x>, boards.greenhouse.io/<x>, *.keka.com, ...) listed
  in the free Common Crawl URL index (`crawl_index.py`): ~12,000 companies of every size.

Order (2026-11-23, user: startups as well as the big names): startups / product companies, YC
companies and companies on Indian board systems (Keka, Darwinbox, Zoho Recruit) first, then
unicorns, then other crawl companies, then global companies.

A run checks two groups side by side: up to `leads_per_run` companies whose board must be searched
for (slow), and up to `board_checks_per_run` whose board is already known (one board read each;
one worker per board system, so each system still gets one request at a time).

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
Runs in a background thread. **By itself** (2026-11-23, user): while the backend runs, one run
starts after another while companies are waiting (`auto_tick`, from the 30 s timer in
`scheduler.py`), then every `idle_check_hours`. Admin settings -> Company finder -> **Run now**
starts one at once. Each run is a `finder_runs` row (Admin -> Company finder analytics).
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

from sqlmodel import Session, col, select

from backend.config import get_tuning
from backend.db import CompanyLead, Employer, FinderRun, get_meta, new_session, set_meta, utcnow
from backend.job_schemas import (
    FinderBreakdownRow, FinderDashboardOut, FinderLeadOut, FinderRunOut, FinderSettings, FinderStatusOut,
)
from backend.services.sources import BOARDS, SourceError, SourceHttp, parse_careers_url
from backend.services.sources.base import USER_AGENT

log = logging.getLogger(__name__)

SEED_FILE = Path(__file__).with_name("seed_companies.csv")
STATE_KEY = "company_finder_state"
# Board systems tried with a company's name, most common among Indian tech companies first.
# Zoho Recruit isn't guessed (a ~2 MB page per try); its careers-page links are still found.
GUESS_ORDER = ("greenhouse", "lever", "ashby", "keka", "darwinbox", "workable", "smartrecruiters", "recruitee")
CAREERS_PATHS = ("/careers", "/jobs", "/careers/", "/company/careers", "/")
YC_LIST = "https://yc-oss.github.io/api/companies/all.json"
YC_KEY = "yc_list_date"
# Board systems used mostly by Indian companies: their crawl companies are checked first.
INDIAN_KINDS = ("keka", "darwinbox", "zohorecruit")
_lock = threading.Lock()
_running = threading.Event()


def settings() -> FinderSettings:
    raw = ((get_tuning().scout or {}).get("search") or {}).get("finder") or {}
    cfg = FinderSettings(**raw)
    if not server_allows():
        cfg.enabled = cfg.auto = False
    return cfg


def server_allows() -> bool:
    """False on a server started with COMPANY_FINDER=false (the deployed backend): no runs there,
    scans still read the companies already in the database."""
    from backend.config import get_settings

    return get_settings().company_finder


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


# ── the YC list ────────────────────────────────────────────────────────────────


def _says_india(value) -> bool:
    items = value if isinstance(value, list) else [value]
    return any("india" in str(v).lower() for v in items if v)


def yc_rows(data) -> list[dict]:
    """Active YC companies based in India, from the open-data list."""
    out = []
    for c in data if isinstance(data, list) else []:
        if not isinstance(c, dict) or not (c.get("name") or "").strip():
            continue
        if str(c.get("status") or "").lower() not in ("active", "public"):
            continue
        if not (_says_india(c.get("regions")) or _says_india(c.get("all_locations"))):
            continue
        out.append({"name": c["name"].strip(), "domain": _domain(c.get("website"))})
    return out


def sync_yc(http: SourceHttp, session: Session, every_days: int = 7) -> int:
    """Add YC companies based in India that aren't leads yet (at most once every `every_days`)."""
    last = get_meta(session, YC_KEY)
    if last and last > (utcnow() - timedelta(days=every_days)).strftime("%Y-%m-%d"):
        return 0
    rows = yc_rows(http.get_json(YC_LIST))
    leads = session.exec(select(CompanyLead)).all()
    names = {(x.name or "").strip().lower() for x in leads}
    domains = {x.domain for x in leads if x.domain}
    added = 0
    for r in rows:
        if r["name"].lower() in names or (r["domain"] and r["domain"] in domains):
            continue
        session.add(CompanyLead(name=r["name"], domain=r["domain"], origin="yc", category="startup"))
        names.add(r["name"].lower())
        if r["domain"]:
            domains.add(r["domain"])
        added += 1
    set_meta(session, YC_KEY, utcnow().strftime("%Y-%m-%d"))
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
    if lead.origin == "yc":
        how += " (YC list)"
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


def rank(lead: CompanyLead) -> int:
    """Who is checked first: startups and Indian boards, then unicorns, other crawl companies, global."""
    if lead.kind in INDIAN_KINDS or lead.origin == "yc" or lead.category in ("startup", "product"):
        return 0
    if lead.category == "unicorn":
        return 1
    if lead.origin == "crawl":
        return 2
    return 3


def due_leads(s: Session, limit: int, board_known: bool | None = None) -> list[CompanyLead]:
    """Pending leads first (in `rank` order), then those whose re-check date has come. With
    `board_known`, only leads whose board is (True) or isn't (False) known yet."""
    now = utcnow()
    rows = s.exec(select(CompanyLead).where(CompanyLead.status != "kept")).all()
    due = [r for r in rows if (r.next_check_at is None or _aware(r.next_check_at) <= now)
           and (board_known is None or bool(r.kind) == board_known)]
    due.sort(key=lambda r: (r.status != "pending", rank(r), r.id or 0))
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


class _Tally:
    """One run's counts, saved to its `finder_runs` row as the run goes (every 10 companies)."""

    def __init__(self, run_id: int, planned: int):
        self.run_id, self.planned = run_id, planned
        self.lock = threading.Lock()
        self.counts: dict[str, int] = {}
        self.by_kind: dict[str, dict[str, int]] = {}
        self.by_origin: dict[str, dict[str, int]] = {}
        self.kept: list[dict] = []
        self.india = self.matching = 0

    def add(self, status: str, lead: dict) -> None:
        with self.lock:
            c = self.counts
            c[status] = c.get(status, 0) + 1
            c["checked"] = c.get("checked", 0) + 1
            for table, key in ((self.by_kind, lead["kind"] or "none"), (self.by_origin, lead["origin"])):
                row = table.setdefault(key, {"checked": 0, "kept": 0, "india_jobs": 0, "matching_jobs": 0})
                row["checked"] += 1
                if status == "kept":
                    row["kept"] += 1
                    row["india_jobs"] += lead["india_jobs"] or 0
                    row["matching_jobs"] += lead["matching_jobs"] or 0
            if status == "kept":
                self.kept.append(lead)
                self.india += lead["india_jobs"] or 0
                self.matching += lead["matching_jobs"] or 0
            done = c["checked"]
            if done == self.planned or done % 10 == 0:
                msg = f"Checked {done} of {self.planned} companies, kept {c.get('kept', 0)}"
                self.save(message=msg)
                _save_state(message=msg)

    def save(self, **extra) -> None:
        copy = json.loads(json.dumps({"counts": self.counts, "by_kind": self.by_kind, "by_origin": self.by_origin,
                                      "kept": self.kept}))
        _update_run(self.run_id, india_jobs=self.india, matching_jobs=self.matching, **copy, **extra)


def _update_run(run_id: int, **fields) -> None:
    with new_session() as s:
        r = s.get(FinderRun, run_id)
        if r is None:
            return
        for k, v in fields.items():
            setattr(r, k, v)
        s.add(r)
        s.commit()


def _snapshot(lead: CompanyLead) -> dict:
    return {"name": lead.name, "kind": lead.kind, "origin": lead.origin, "how": lead.how,
            "total_jobs": lead.total_jobs, "india_jobs": lead.india_jobs, "matching_jobs": lead.matching_jobs}


def _check_all(ids: list[int], phrases, cfg: FinderSettings, tally: _Tally) -> None:
    """One worker: check these leads one after another (own session and HTTP client)."""
    with new_session() as s, SourceHttp(timeout=cfg.timeout_seconds, max_retries=0) as http:
        for lead_id in ids:
            lead = s.get(CompanyLead, lead_id)
            if lead is None:
                continue
            try:
                status = check_lead(s, http, lead, phrases, cfg)
            except Exception as e:  # noqa: BLE001 - one bad page never stops the run
                log.warning("finder: %s failed: %s", lead.name, e)
                lead.status, lead.note = "error", f"{type(e).__name__}: {e}"[:300]
                lead.next_check_at = utcnow() + timedelta(days=cfg.recheck_after_days)
                status = "error"
            lead.run_id = tally.run_id
            s.add(lead)
            s.commit()
            tally.add(status, _snapshot(lead))


def run(trigger: str = "manual") -> dict[str, int]:
    """One finder run: new leads (seed list, YC list, Common Crawl index), then the checks: leads
    whose board must be searched for in one worker, leads with a known board in one worker per
    board system, all at the same time. Recorded in `finder_runs` as it goes; a run that found
    nothing to do (the idle check) leaves no row."""
    from backend.services import crawl_index
    from backend.services.employers import role_phrases

    cfg = settings()
    with new_session() as s:
        row = FinderRun(trigger=trigger, message="Starting")
        s.add(row)
        s.commit()
        run_id = int(row.id)
    out: dict[str, int] = {}
    _save_state(running=True, trigger=trigger, run_id=run_id, started_at=utcnow().isoformat(), finished_at=None,
                message="Starting", error=None)
    try:
        new = {"seed": 0, "yc": 0, "crawl": 0}
        with new_session() as s:
            new["seed"] = sync_seed(s)
        if cfg.yc_list:
            _save_state(message="Reading the YC list of companies in India")
            try:
                with new_session() as s, SourceHttp(timeout=60, max_retries=1) as http:
                    http.label = "YC list"
                    new["yc"] = sync_yc(http, s)
            except SourceError as e:  # the list is a bonus: the run goes on without it
                log.info("finder: YC list skipped: %s", e)
        crawl: dict = {}
        if cfg.crawl and cfg.crawl_pages_per_run > 0:
            _save_state(message="Reading the Common Crawl index")
            _update_run(run_id, message="Reading the Common Crawl index")
            new["crawl"] = crawl_index.harvest(cfg, stats=crawl)
        with new_session() as s:
            phrases = role_phrases(s)
            search = [x.id for x in due_leads(s, cfg.leads_per_run, board_known=False)]
            known = due_leads(s, cfg.board_checks_per_run, board_known=True)
        groups: dict[str, list[int]] = defaultdict(list)
        for lead in known:
            groups[lead.kind].append(lead.id)
        work = ([search] if search else []) + list(groups.values())
        total = len(search) + len(known)
        tally = _Tally(run_id, total)
        msg = f"Checking {total} companies"
        _update_run(run_id, new_leads=new, crawl=crawl, planned=total, message=msg)
        _save_state(message=msg)
        if work:
            with ThreadPoolExecutor(max_workers=len(work), thread_name_prefix="finder") as pool:
                for f in [pool.submit(_check_all, ids, phrases, cfg, tally) for ids in work]:
                    f.result()
        out = {**tally.counts, **{f"{k}_leads": v for k, v in new.items() if v}}
        msg = f"Checked {tally.counts.get('checked', 0)} companies, kept {tally.counts.get('kept', 0)}"
        if not tally.counts and not any(new.values()):
            with new_session() as s:  # an idle check that found nothing to do: no row
                r = s.get(FinderRun, run_id)
                if r is not None:
                    s.delete(r)
                    s.commit()
            msg = "Nothing waiting: every company has been checked"
        else:
            tally.save(status="done", finished_at=utcnow(), message=msg)
        _save_state(running=False, finished_at=utcnow().isoformat(), last_run=out, message=msg)
    except Exception as e:  # noqa: BLE001 - shown on the finder card
        log.exception("company finder failed")
        err = f"{type(e).__name__}: {e}"[:300]
        _update_run(run_id, status="failed", finished_at=utcnow(), error=err, message="Failed")
        _save_state(running=False, finished_at=utcnow().isoformat(), error=err, message="Failed")
    return out


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


# ── running by itself ──────────────────────────────────────────────────────────


def due_count(s: Session) -> int:
    """Companies on the waiting list whose check is due now."""
    now = utcnow()
    return sum(1 for nc in s.exec(select(CompanyLead.next_check_at).where(CompanyLead.status != "kept")).all()
               if nc is None or _aware(nc) <= now)


def _seconds_since(iso: str | None) -> float:
    from datetime import datetime

    if not iso:
        return float("inf")
    try:
        return (utcnow() - _aware(datetime.fromisoformat(iso))).total_seconds()
    except ValueError:
        return float("inf")


def auto_tick() -> bool:
    """Called by the in-process timer every 30 s. While companies are waiting (or a Common Crawl
    crawl is half read), starts the next run `pause_between_runs_seconds` after the last one
    ended; when nothing is waiting, looks again every `idle_check_hours` (new crawl, YC list,
    re-check dates). Never during a scan; after a failed run, waits `error_backoff_minutes`.
    Returns True when it started a run."""
    from backend.services import crawl_index, job_search

    cfg = settings()
    if not (cfg.enabled and cfg.auto) or is_running() or job_search.running_scan_id() is not None:
        return False
    with new_session() as s:
        st = _state(s)
        busy = due_count(s) > 0 or bool(crawl_index._state(s).get("collection"))
    since = _seconds_since(st.get("finished_at"))
    if st.get("error") and since < cfg.error_backoff_minutes * 60:
        return False
    wait = cfg.pause_between_runs_seconds if busy else cfg.idle_check_hours * 3600
    return since >= wait and start("auto")


def recover() -> None:
    """On start: a run cut off by a restart isn't running any more (its row is marked interrupted,
    its counts kept; the companies it checked stay checked); sync the seed list."""
    from backend.services import crawl_index

    crawl_index.fix_names()
    with new_session() as s:
        sync_seed(s)
        for r in s.exec(select(FinderRun).where(FinderRun.status == "running")).all():
            r.status, r.finished_at = "interrupted", utcnow()
            r.message = (r.message or "") + " (interrupted by a restart)"
            s.add(r)
        st = _state(s)
        if st.get("running"):
            st.update(running=False, message="Interrupted by a restart", finished_at=utcnow().isoformat())
            set_meta(s, STATE_KEY, json.dumps(st))
        s.commit()


def status(session: Session) -> FinderStatusOut:
    from backend.services import crawl_index

    cfg = settings()
    st = _state(session)
    leads = session.exec(select(CompanyLead)).all()
    by_status: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    pending: dict[str, int] = {}
    for lead in leads:
        by_status[lead.status] = by_status.get(lead.status, 0) + 1
        by_origin[lead.origin] = by_origin.get(lead.origin, 0) + 1
        if lead.status == "pending":
            pending[lead.origin] = pending.get(lead.origin, 0) + 1
    kept = sorted((x for x in leads if x.status == "kept"), key=lambda x: -(x.matching_jobs or 0))
    return FinderStatusOut(
        enabled=cfg.enabled, server_allows=server_allows(), auto=cfg.auto, running=is_running(), run_id=st.get("run_id"),
        due_now=due_count(session), leads_per_run=cfg.leads_per_run,
        board_checks_per_run=cfg.board_checks_per_run, trigger=st.get("trigger"), pending_by_origin=pending,
        message=st.get("message"),
        error=st.get("error"), started_at=st.get("started_at"), finished_at=st.get("finished_at"),
        last_run=st.get("last_run") or {}, by_status=by_status, by_origin=by_origin,
        crawl=crawl_index.progress(session) if cfg.crawl else None,
        kept=[FinderLeadOut(name=x.name, kind=x.kind, kind_label=BOARDS[x.kind].label if x.kind in BOARDS else x.kind,
                            how=x.how, total_jobs=x.total_jobs, india_jobs=x.india_jobs,
                            matching_jobs=x.matching_jobs, checked_at=x.checked_at) for x in kept[:50]],
    )


# ── analytics (Admin -> Company finder) ────────────────────────────────────────

ORIGIN_LABEL = {"seed": "Seed list", "yc": "YC list", "crawl": "Web index (Common Crawl)"}


def _breakdown(leads: list[CompanyLead], key, label) -> list[FinderBreakdownRow]:
    rows: dict[str, FinderBreakdownRow] = {}
    for lead in leads:
        k = key(lead) or "none"
        r = rows.get(k) or FinderBreakdownRow(key=k, label=label(k))
        rows[k] = r
        r.total += 1
        if lead.status in ("pending", "kept", "no_india_jobs", "no_board", "error"):
            setattr(r, lead.status, getattr(r, lead.status) + 1)
        if lead.status == "kept":
            r.india_jobs += lead.india_jobs or 0
            r.matching_jobs += lead.matching_jobs or 0
    return sorted(rows.values(), key=lambda r: (-r.kept, -r.total))


def run_out(r: FinderRun) -> FinderRunOut:
    end = _aware(r.finished_at) if r.finished_at else (utcnow() if r.status == "running" else None)
    return FinderRunOut(
        id=r.id, trigger=r.trigger, status=r.status, started_at=r.started_at, finished_at=r.finished_at,
        duration_seconds=round((end - _aware(r.started_at)).total_seconds(), 1) if end else None,
        message=r.message, error=r.error, new_leads=r.new_leads or {}, crawl=r.crawl or {}, planned=r.planned,
        counts=r.counts or {}, by_kind=r.by_kind or {}, by_origin=r.by_origin or {}, india_jobs=r.india_jobs,
        matching_jobs=r.matching_jobs, kept=r.kept or [])


def dashboard(session: Session, limit: int = 100) -> FinderDashboardOut:
    leads = session.exec(select(CompanyLead)).all()
    runs = session.exec(select(FinderRun).order_by(col(FinderRun.started_at).desc()).limit(limit)).all()
    read = [e for e in session.exec(select(Employer).where(Employer.enabled == True)).all()]  # noqa: E712
    by_kind_read: dict[str, int] = {}
    for e in read:
        by_kind_read[e.kind] = by_kind_read.get(e.kind, 0) + 1
    return FinderDashboardOut(
        status=status(session),
        runs=[run_out(r) for r in runs],
        by_kind=_breakdown([x for x in leads if x.status != "pending" or x.kind], lambda x: x.kind,
                           lambda k: BOARDS[k].label if k in BOARDS else "No board found"),
        by_origin=_breakdown(leads, lambda x: x.origin, lambda k: ORIGIN_LABEL.get(k, k)),
        companies_read=len(read), companies_read_by_kind=by_kind_read,
    )
