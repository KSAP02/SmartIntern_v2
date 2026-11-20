"""The job source: JSearch only (Phase 2.5). Former sources: MD_files/api_references/former_sources.md."""
from __future__ import annotations

from backend.services.sources.base import SourceError, SourceHttp
from backend.services.sources.jsearch import JSearchClient, JSearchError

JSEARCH = JSearchClient()

# name -> client; used for labels and health. One entry since Phase 2.5.
ADAPTERS: dict[str, JSearchClient] = {JSEARCH.name: JSEARCH}

__all__ = ["ADAPTERS", "JSEARCH", "JSearchError", "SourceError", "SourceHttp"]
