"""Board addresses from the Common Crawl URL index (Phase 2.7 E): a free, public index of the web
pages Common Crawl visited. Listing every URL it saw under jobs.lever.co/*, boards.greenhouse.io/*,
... gives company board ids we'd never find otherwise; each becomes a `company_leads` row (origin
"crawl") that the company finder checks for jobs in India.

API (pywb CDX server, MD_files/api_references/common_crawl.md):
- `GET https://index.commoncrawl.org/collinfo.json` -> crawls, newest first; `[0]["cdx-api"]`.
- `GET {cdx-api}?url=<host>/*&output=json&showNumPages=true` -> {"pages": N, ...}
- `GET {cdx-api}?url=<host>/*&output=json&filter==status:200&page=i` -> NDJSON, one capture a line.
Their guidance: heavily rate limited; one request at a time, sleep between calls, slow down on
503 (we stop the run and continue next time). Terms: https://commoncrawl.org/terms-of-use (no
personal data is collected: only company board ids).

Progress lives in `meta` (`crawl_index_state`): the crawl being read and, per host, the next page.
A newer crawl is started once the current one is finished.
"""
from __future__ import annotations

import json
import logging
import time

from sqlmodel import Session, select

from backend.db import CompanyLead, Employer, get_meta, new_session, set_meta
from backend.job_schemas import CrawlProgressOut, FinderSettings
from backend.services.sources import BOARDS, SourceError, SourceHttp, parse_careers_url

log = logging.getLogger(__name__)

COLLINFO = "https://index.commoncrawl.org/collinfo.json"
STATE_KEY = "crawl_index_state"
# Board addresses per board system (`url=` patterns; `*.x` = every subdomain).
PATTERNS: tuple[tuple[str, str], ...] = (
    ("greenhouse", "boards.greenhouse.io/*"),
    ("greenhouse", "job-boards.greenhouse.io/*"),
    ("lever", "jobs.lever.co/*"),
    ("ashby", "jobs.ashbyhq.com/*"),
    ("workable", "apply.workable.com/*"),
    ("smartrecruiters", "jobs.smartrecruiters.com/*"),
    ("recruitee", "*.recruitee.com"),
    ("keka", "*.keka.com"),
    ("darwinbox", "*.darwinbox.in"),
    ("zohorecruit", "*.zohorecruit.in"),
    ("zohorecruit", "*.zohorecruit.com"),
)


def _state(s: Session) -> dict:
    try:
        return json.loads(get_meta(s, STATE_KEY) or "{}")
    except ValueError:
        return {}


def _save(st: dict) -> None:
    with new_session() as s:
        set_meta(s, STATE_KEY, json.dumps(st))
        s.commit()


def slugs(ndjson: str) -> set[tuple[str, str]]:
    """(kind, board) for every capture URL in one index page."""
    out: set[tuple[str, str]] = set()
    for line in (ndjson or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            url = json.loads(line).get("url")
        except ValueError:
            continue
        parsed = parse_careers_url(url) if isinstance(url, str) else None
        if parsed and parsed[0] in BOARDS:
            out.add((parsed[0], parsed[1]))
    return out


def add_leads(found: set[tuple[str, str]]) -> int:
    """New leads for board ids we don't know yet (as a lead or as a company). Returns added."""
    if not found:
        return 0
    with new_session() as s:
        known = {(lead.kind, (lead.board or "").lower()) for lead in s.exec(select(CompanyLead).where(CompanyLead.kind != None)).all()}  # noqa: E711
        known |= {(e.kind, e.board.lower()) for e in s.exec(select(Employer)).all()}
        added = 0
        for kind, board in sorted(found):
            if (kind, board.lower()) in known:
                continue
            name = " ".join(w.capitalize() for w in board.replace("_", "-").replace(".", "-").split("-") if w) or board
            s.add(CompanyLead(name=name, origin="crawl", kind=kind, board=board, how="crawl"))
            known.add((kind, board.lower()))
            added += 1
        s.commit()
    return added


def harvest(cfg: FinderSettings, http: SourceHttp | None = None) -> int:
    """Read up to `crawl_pages_per_run` index pages, politely. Returns leads added."""
    own = http is None
    http = http or SourceHttp(timeout=90, max_retries=1)
    http.label = "Common Crawl index"
    with new_session() as s:
        st = _state(s)
    added = requests = 0

    def pause():
        nonlocal requests
        if requests:
            time.sleep(cfg.crawl_delay_seconds)
        requests += 1

    try:
        if not st.get("collection") or (st.get("finished") and st.get("checked_newer") != _today()):
            pause()
            crawls = http.get_json(COLLINFO)
            newest = crawls[0] if isinstance(crawls, list) and crawls else None
            st["checked_newer"] = _today()
            if newest and newest.get("id") != st.get("collection"):
                st = {"collection": newest["id"], "api": newest["cdx-api"], "hosts": {}, "leads": st.get("leads", 0),
                      "checked_newer": _today()}
            _save(st)
        if st.get("finished"):
            return 0
        pages_left = cfg.crawl_pages_per_run
        for _kind, pattern in PATTERNS:
            h = st["hosts"].setdefault(pattern, {"pages": None, "next": 0, "done": False})
            while not h["done"] and pages_left > 0:
                if h["pages"] is None:
                    pause()
                    info = http.get_json(st["api"], params={"url": pattern, "output": "json", "showNumPages": "true"})
                    h["pages"] = int((info or {}).get("pages") or 0)
                    if h["pages"] == 0:
                        h["done"] = True
                    _save(st)
                    continue
                pause()
                try:
                    text = http.get_text(st["api"], params={"url": pattern, "output": "json", "filter": "=status:200",
                                                            "page": str(h["next"])})
                except SourceError as e:
                    if "HTTP 400" in str(e) or "404" in str(e):  # past the last page / nothing captured
                        h["done"] = True
                        _save(st)
                        continue
                    raise
                n = add_leads(slugs(text))
                added += n
                st["leads"] = st.get("leads", 0) + n
                h["next"] += 1
                h["done"] = h["next"] >= h["pages"]
                pages_left -= 1
                _save(st)
            if pages_left <= 0:
                break
        st["finished"] = all(st["hosts"].get(p, {}).get("done") for _k, p in PATTERNS)
        _save(st)
    except SourceError as e:  # rate limited / slow server: stop here, continue next run
        log.info("crawl index: stopped for this run: %s", e)
        st["last_error"] = str(e)[:200]
        _save(st)
    finally:
        if own:
            http.close()
    return added


def _today() -> str:
    from backend.db import utcnow

    return utcnow().strftime("%Y-%m-%d")


def progress(session: Session) -> CrawlProgressOut:
    st = _state(session)
    hosts = [{"host": p, "pages": (st.get("hosts") or {}).get(p, {}).get("pages"),
              "done": (st.get("hosts") or {}).get(p, {}).get("next", 0),
              "finished": bool((st.get("hosts") or {}).get(p, {}).get("done"))} for _k, p in PATTERNS]
    return CrawlProgressOut(collection=st.get("collection"), hosts=hosts, leads=int(st.get("leads") or 0))
