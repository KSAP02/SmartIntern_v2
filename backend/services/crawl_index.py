"""Board addresses from the Common Crawl URL index (Phase 2.7 E): a free, public index of the web
pages Common Crawl visits every month. Every address it saw under jobs.lever.co/*,
boards.greenhouse.io/*, *.keka.com, ... names one company's job board; each new one becomes a
`company_leads` row (origin "crawl") that the company finder checks for jobs in India. That's
how startups we'd never think of get in: thousands of companies of every size use these boards.

How it's read (2026-11-23): from the index **files** on data.commoncrawl.org (Amazon S3), not the
CDX query server (index.commoncrawl.org/...-index), which was answering every query with HTTP
504. The files (MD_files/api_references/common_crawl.md):
- `collinfo.json` lists the crawls, newest first.
- `cc-index/collections/<crawl>/indexes/cluster.idx` (~100 MB, sorted by SURT key, e.g.
  "co,lever,jobs)/acme/123"): one line per block of 3,000 index rows: "<key> <time>\\t<file>\\t
  <offset>\\t<length>\\t<n>". We binary-search it with small byte-range requests (~10 per board
  system), so we never download it whole.
- `cdx-000NN.gz` blocks (~250 KB gzip each): the index rows, one capture a line
  "<key> <time> {json with "url"}". A board system is 1-21 blocks; the whole set ~50 blocks,
  ~12 MB (Oct 2026: ~12,000 company boards).
Free and public (https://commoncrawl.org/terms-of-use); one request at a time with a pause; only
company board ids are kept, never personal data.

Progress lives in `meta` (`crawl_index_state`): the crawl being read, per board system its blocks
and the next one, and which crawls are done. The newest `crawl_collections` crawls are read
(newest first); a new crawl is picked up the day it appears.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
import zlib

from sqlmodel import Session, select

from backend.db import CompanyLead, Employer, get_meta, new_session, set_meta
from backend.job_schemas import CrawlProgressOut, FinderSettings
from backend.services.sources import BOARDS, SourceError, SourceHttp, parse_careers_url

log = logging.getLogger(__name__)

COLLINFO = "https://index.commoncrawl.org/collinfo.json"
DATA = "https://data.commoncrawl.org/cc-index/collections/{crawl}/indexes/"
STATE_KEY = "crawl_index_state"
# (board system, the address as people know it, its SURT key prefix in the index). Indian board
# systems first, so a short run finds Indian companies first.
PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("keka", "*.keka.com", "com,keka,"),
    ("darwinbox", "*.darwinbox.in", "in,darwinbox,"),
    ("zohorecruit", "*.zohorecruit.in", "in,zohorecruit,"),
    ("zohorecruit", "*.zohorecruit.com", "com,zohorecruit,"),
    ("lever", "jobs.lever.co", "co,lever,jobs)/"),
    ("ashby", "jobs.ashbyhq.com", "com,ashbyhq,jobs)/"),
    ("smartrecruiters", "jobs.smartrecruiters.com", "com,smartrecruiters,jobs)/"),
    ("recruitee", "*.recruitee.com", "com,recruitee,"),
    ("greenhouse", "boards.greenhouse.io", "io,greenhouse,boards)/"),
    ("greenhouse", "job-boards.greenhouse.io", "io,greenhouse,job-boards)/"),
    ("workable", "apply.workable.com", "com,workable,apply)/"),
)
SPAN = 256 * 1024  # bytes of cluster.idx read at once while scanning a board system's lines
PROBE = 16 * 1024  # bytes read per binary-search step


def _state(s: Session) -> dict:
    try:
        return json.loads(get_meta(s, STATE_KEY) or "{}")
    except ValueError:
        return {}


def _save(st: dict) -> None:
    with new_session() as s:
        set_meta(s, STATE_KEY, json.dumps(st))
        s.commit()


def slugs(text: str, prefix: str | None = None) -> set[tuple[str, str]]:
    """(kind, board) for every capture in index rows ("<key> <time> {json}", or plain JSON lines);
    with `prefix`, only rows whose key starts with it."""
    out: set[tuple[str, str]] = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or (prefix and not line.startswith(prefix)):
            continue
        try:
            url = json.loads(line[line.index("{"):]).get("url")
        except ValueError:
            continue
        parsed = parse_careers_url(url) if isinstance(url, str) else None
        if parsed and parsed[0] in BOARDS:
            out.add((parsed[0], parsed[1]))
    return out


def _old_name(board: str) -> str:
    """How names were made before 2026-11-23 (to fix those rows once)."""
    return " ".join(w.capitalize() for w in board.replace("_", "-").replace(".", "-").split("-") if w) or board


def board_name(board: str) -> str:
    """A readable company name from a board id: "content-whale-in.in" -> "Content Whale",
    "athenainfonomics" -> "Athenainfonomics" (the real name appears once the board is read)."""
    b = board.lower().strip()
    for suffix in (".co.in", ".com", ".in", ".co", ".io", ".net", ".org", ".ai"):
        b = b.removesuffix(suffix)
    words = [w for w in b.replace("_", "-").replace(".", "-").split("-") if w]
    while len(words) > 1 and words[-1] in ("in", "india", "com", "careers", "jobs"):
        words.pop()
    out: list[str] = []
    for w in words:
        if not out or out[-1].lower() != w:  # "incubyte-incubyte" -> "Incubyte"
            out.append(w.capitalize())
    return " ".join(out) or board


def fix_names() -> int:
    """Rename web-index companies still carrying the old made-up name (and the companies scans read
    that came from them). Returns rows renamed."""
    changed = 0
    with new_session() as s:
        for lead in s.exec(select(CompanyLead).where(CompanyLead.origin == "crawl")).all():
            if lead.board and lead.name == _old_name(lead.board) and board_name(lead.board) != lead.name:
                old, lead.name = lead.name, board_name(lead.board)
                s.add(lead)
                changed += 1
                if lead.employer_id:
                    e = s.get(Employer, lead.employer_id)
                    if e is not None and e.name == old:
                        e.name = lead.name
                        s.add(e)
        s.commit()
    return changed


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
            s.add(CompanyLead(name=board_name(board), origin="crawl", kind=kind, board=board, how="crawl"))
            known.add((kind, board.lower()))
            added += 1
        s.commit()
    return added


def _key(line: bytes) -> str:
    return line.split(b" ", 1)[0].decode("utf-8", "replace")


def locate(http: SourceHttp, url: str, size: int, prefix: str, pause) -> list[list]:
    """The index blocks [file, offset, length] holding keys that start with `prefix`: binary-search
    cluster.idx with small byte ranges, then read forward until the keys pass the prefix. The block
    before the first matching line is included (its tail can hold the first matching rows)."""
    lo, hi = 0, size  # invariant: the first full line after `lo` sorts before `prefix` (or lo = 0)
    while hi - lo > SPAN:
        mid = (lo + hi) // 2
        pause()
        lines = http.get_bytes(url, {"Range": f"bytes={mid}-{min(mid + PROBE, size) - 1}"}).split(b"\n")
        if len(lines) > 2 and _key(lines[1]) >= prefix:
            hi = mid
        else:
            lo = mid
    prev, out, pos, partial = None, [], lo, lo > 0
    while pos < size:
        pause()
        chunk = http.get_bytes(url, {"Range": f"bytes={pos}-{min(pos + SPAN, size) - 1}"})
        end = len(chunk) if pos + len(chunk) >= size else chunk.rfind(b"\n") + 1
        if end <= 0:
            break
        lines = chunk[:end].split(b"\n")
        for raw in lines[1:] if partial else lines:
            if not raw.strip():
                continue
            key = _key(raw)
            if key < prefix:
                prev = raw
            elif key.startswith(prefix):
                out.append(raw)
            else:
                return _blocks(prev, out)
        pos, partial = pos + end, False
    return _blocks(prev, out)


def _blocks(prev: bytes | None, lines: list[bytes]) -> list[list]:
    out = []
    for raw in ([prev] if prev else []) + lines:
        f = raw.decode("utf-8", "replace").split("\t")
        if len(f) >= 4 and f[2].isdigit() and f[3].isdigit():
            out.append([f[1], int(f[2]), int(f[3])])
    return out


def _gunzip(data: bytes) -> str:
    try:
        return gzip.decompress(data).decode("utf-8", "replace")
    except (OSError, EOFError, zlib.error) as e:
        raise SourceError(f"Common Crawl index: a block couldn't be unpacked ({e})") from e


def _next_crawl(http: SourceHttp, st: dict, cfg: FinderSettings, pause) -> str | None:
    """The newest recent crawl not read yet (the list is fetched once a day)."""
    if st.get("recent_date") != _today() or not st.get("recent"):
        pause()
        crawls = http.get_json(COLLINFO)
        st["recent"] = [c["id"] for c in crawls if isinstance(c, dict) and c.get("id")][: max(1, cfg.crawl_collections)]
        st["recent_date"] = _today()
    done = set(st.get("done_collections") or [])
    return next((c for c in st["recent"] if c not in done), None)


def harvest(cfg: FinderSettings, http: SourceHttp | None = None, stats: dict | None = None) -> int:
    """Read up to `crawl_pages_per_run` index blocks, politely. Returns leads added; `stats` gets
    {"collections": [crawls read from], "blocks": n, "error": ...} for the run's record."""
    stats = stats if stats is not None else {}
    stats.update(collections=[], blocks=0)
    own = http is None
    http = http or SourceHttp(timeout=90, max_retries=2)
    http.label = "Common Crawl index"
    with new_session() as s:
        st = _state(s)
    if "api" in st:  # the old CDX-server state (before 2026-11-23): start over from the files
        st = {"leads": st.get("leads", 0)}
    added = requests = 0
    budget = cfg.crawl_pages_per_run

    def pause():
        nonlocal requests
        if requests:
            time.sleep(cfg.crawl_delay_seconds)
        requests += 1

    try:
        st["last_error"] = None
        while budget > 0:
            if not st.get("collection"):
                nxt = _next_crawl(http, st, cfg, pause)
                if not nxt:
                    break
                st.update(collection=nxt, hosts={}, size=None)
                _save(st)
            base = DATA.format(crawl=st["collection"])
            if not st.get("size"):
                pause()
                st["size"] = http.size(base + "cluster.idx")
            for _kind, _label, prefix in PATTERNS:
                h = st["hosts"].setdefault(prefix, {"blocks": None, "next": 0, "done": False})
                if h["blocks"] is None:
                    h["blocks"] = locate(http, base + "cluster.idx", st["size"], prefix, pause)
                    h["done"] = not h["blocks"]
                    _save(st)
                while not h["done"] and budget > 0:
                    file, offset, length = h["blocks"][h["next"]]
                    pause()
                    data = http.get_bytes(base + file, {"Range": f"bytes={offset}-{offset + length - 1}"})
                    n = add_leads(slugs(_gunzip(data), prefix))
                    added += n
                    st["leads"] = st.get("leads", 0) + n
                    h["next"] += 1
                    h["done"] = h["next"] >= len(h["blocks"])
                    budget -= 1
                    stats["blocks"] += 1
                    if st["collection"] not in stats["collections"]:
                        stats["collections"].append(st["collection"])
                    _save(st)
                if budget <= 0:
                    break
            if all(st["hosts"].get(p, {}).get("done") for _k, _l, p in PATTERNS):
                st["done_collections"] = [*(st.get("done_collections") or []), st["collection"]][-24:]
                st["collection"] = None
                _save(st)
        _save(st)
    except SourceError as e:  # slow or busy server: stop here, carry on from the same place next run
        log.info("crawl index: stopped for this run: %s", e)
        st["last_error"] = str(e)[:200]
        stats["error"] = st["last_error"]
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
    if "api" in st:  # old state, replaced on the next run
        st = {"leads": st.get("leads", 0)}
    hosts_st = st.get("hosts") or {}
    hosts = []
    for _kind, label, prefix in PATTERNS:
        h = hosts_st.get(prefix) or {}
        blocks = h.get("blocks")
        hosts.append({"host": label, "pages": len(blocks) if blocks is not None else None,
                      "done": h.get("next", 0), "finished": bool(h.get("done"))})
    return CrawlProgressOut(collection=st.get("collection"), hosts=hosts, leads=int(st.get("leads") or 0),
                            collections_done=list(st.get("done_collections") or []),
                            last_error=st.get("last_error"))
