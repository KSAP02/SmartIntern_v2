"""Component health for Desk and Switchboard. No network calls to model providers."""
from __future__ import annotations

from collections.abc import Callable

from backend import vectors
from backend.db import db_check
from backend.model import embedding_status, llm_status
from backend.schemas import ComponentStatus
from backend.storage import get_storage


def _try(fn: Callable[[], str]) -> ComponentStatus:
    try:
        return ComponentStatus(ok=True, detail=fn())
    except Exception as e:  # noqa: BLE001 - shown as a status message
        return ComponentStatus(ok=False, detail=str(e)[:300])


def _model(status: dict) -> ComponentStatus:
    if status["configured"]:
        return ComponentStatus(ok=True, detail=f"{status['provider']} / {status['model']} (key set)")
    return ComponentStatus(ok=False, detail=status["detail"])


def components() -> dict[str, ComponentStatus]:
    return {
        "llm": _model(llm_status()),
        "embeddings": _model(embedding_status()),
        "vectors": _try(vectors.status),
        "database": _try(db_check),
        "storage": _try(lambda: get_storage().check()),
    }
