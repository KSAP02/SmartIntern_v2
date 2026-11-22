"""Job sources (Phase 2.7 contract: see base.py): JSearch (search) + company job boards
(Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee; Indian systems Keka,
Darwinbox, Zoho Recruit since Phase 2.7 E) + remote feeds
(Himalayas, RemoteJobs.org, Remotive). Add a source = one file + one line below.
Former sources: MD_files/api_references/former_sources.md."""
from __future__ import annotations

from backend.services.sources.ashby import AshbyBoard
from backend.services.sources.base import SourceAdapter, SourceError, SourceHttp
from backend.services.sources.darwinbox import DarwinboxBoard
from backend.services.sources.boards import BoardAdapter
from backend.services.sources.feeds import FeedAdapter
from backend.services.sources.greenhouse import GreenhouseBoard
from backend.services.sources.himalayas import HimalayasFeed
from backend.services.sources.jsearch import JSearchClient, JSearchError
from backend.services.sources.keka import KekaBoard
from backend.services.sources.lever import LeverBoard
from backend.services.sources.remotejobs import RemoteJobsFeed
from backend.services.sources.recruitee import RecruiteeBoard
from backend.services.sources.remotive import RemotiveFeed
from backend.services.sources.smartrecruiters import SmartRecruitersBoard
from backend.services.sources.workable import WorkableBoard
from backend.services.sources.zohorecruit import ZohoRecruitBoard

JSEARCH = JSearchClient()

# Company job boards: name -> adapter (the system manages the companies; one tick box each in Scan now).
BOARDS: dict[str, BoardAdapter] = {a.name: a for a in (GreenhouseBoard(), LeverBoard(), AshbyBoard(),
                                                        SmartRecruitersBoard(), WorkableBoard(), RecruiteeBoard(),
                                                        KekaBoard(), DarwinboxBoard(), ZohoRecruitBoard())}

# Remote-job feeds, only jobs open to India (Phase 2.7 C1; services/remote_feeds.py).
FEEDS: dict[str, FeedAdapter] = {a.name: a for a in (HimalayasFeed(), RemoteJobsFeed(), RemotiveFeed())}

# The registry: name -> adapter, in the order Scan now lists them. Add a source here.
SOURCES: dict[str, SourceAdapter] = {JSEARCH.name: JSEARCH, **BOARDS, **FEEDS}
ADAPTERS = SOURCES  # older name, used for labels and health


def parse_careers_url(url: str) -> tuple[str, str] | None:
    """A careers / board / job link -> (ATS name, board id), e.g. jobs.lever.co/acme -> ("lever", "acme")."""
    for name, a in BOARDS.items():
        board = a.parse(url.strip())
        if board:
            return name, board
    return None


__all__ = ["ADAPTERS", "BOARDS", "FEEDS", "JSEARCH", "JSearchError", "SOURCES", "SourceAdapter", "SourceError", "SourceHttp",
           "parse_careers_url"]
