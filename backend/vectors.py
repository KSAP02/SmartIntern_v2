"""Vector store seam (Milvus Lite now; Milvus server / Zilliz Cloud later by changing VECTOR_DB_URI).

Holds only vectors keyed by an id from SQLite. SQLite stays the source of truth for content
and flags, so e.g. toggling a card never touches the vector store.

Collections (logical name -> config):
  "jobs"          one digest per job        [vectors] jobs_collection
  "memory", "requirements": memory cards / requirement chunks, unused since Phase 2.6 (cards
  are no longer embedded; role contexts keep their one vector in SQLite). Dropped once on start.

Every search returns a 0–1 similarity, whatever the metric (OpenAI embeddings are
unit-length, so COSINE = IP, and L2 (squared) = 2 - 2·cos).
"""
from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache

from backend.config import data_dir, get_settings, get_tuning

# Milvus Lite 3.x runs a local gRPC server. On connect pymilvus probes an optional method
# (AllocTimestamp) the server doesn't implement, and gRPC logs keepalive chatter. Both are
# harmless noise; silence them so real errors stay visible. Must be set before grpc loads.
os.environ.setdefault("GRPC_VERBOSITY", "NONE")
logging.getLogger("grpc._server").setLevel(logging.CRITICAL)

_lock = threading.RLock()
_ready: set[str] = set()
_metric: str | None = None  # set by services (search settings); None -> [vectors] metric


class VectorStoreError(RuntimeError):
    """The vector store could not be opened or queried."""


def _uri() -> str:
    return get_settings().vector_db_uri or str(data_dir() / "milvus.db")


@lru_cache
def _client():
    try:
        from pymilvus import MilvusClient
    except ImportError as e:
        raise VectorStoreError("Package 'pymilvus' / 'milvus-lite' missing. Add them to requirements.txt.") from e
    try:
        return MilvusClient(_uri())
    except Exception as e:  # noqa: BLE001 - surface any open failure as a status message
        raise VectorStoreError(f"Could not open Milvus at {_uri()}: {e}") from e


def collection_name(kind: str) -> str:
    v = get_tuning().vectors
    return {"memory": v.memory_collection, "jobs": v.jobs_collection, "requirements": v.requirements_collection}[kind]


def metric() -> str:
    return (_metric or get_tuning().vectors.metric).upper()


def set_metric(value: str) -> None:
    """Called when the Matching setting changes; collections must then be reset (see services)."""
    global _metric
    _metric = value.upper()


def _call(what: str, kind: str, fn):
    try:
        return fn()
    except VectorStoreError:
        raise
    except Exception as e:  # noqa: BLE001 - surfaced as a 503 with a readable message
        _ready.discard(collection_name(kind))
        raise VectorStoreError(f"Vector store {what} failed: {e}") from e


def ensure(kind: str) -> None:
    """Create the collection if missing, and load it once per process.

    An existing collection reopens in the 'released' state after a restart and must be
    loaded before search/query.
    """
    name = collection_name(kind)
    if name in _ready:
        return
    t = get_tuning()
    with _lock:
        c = _client()

        def _ensure():
            if not c.has_collection(name):
                c.create_collection(
                    name,
                    dimension=t.embedding.dimensions,
                    metric_type=metric(),
                    primary_field_name="id",
                    vector_field_name="vector",
                    id_type="int",
                    auto_id=False,
                )
            c.load_collection(name)

        _call("setup", kind, _ensure)
        _ready.add(name)


def reset(kind: str) -> None:
    """Drop and recreate (embedding model, dimensions or metric changed)."""
    name = collection_name(kind)
    with _lock:
        c = _client()
        _ready.discard(name)
        _call("reset", kind, lambda: c.has_collection(name) and c.drop_collection(name))
    ensure(kind)


def drop(kind: str) -> None:
    """Remove a collection for good (no recreate)."""
    name = collection_name(kind)
    with _lock:
        c = _client()
        _ready.discard(name)
        _call("drop", kind, lambda: c.has_collection(name) and c.drop_collection(name))


def upsert(kind: str, rows: list[tuple[int, list[float]]]) -> None:
    if not rows:
        return
    ensure(kind)
    with _lock:
        _call("upsert", kind, lambda: _client().upsert(collection_name(kind), data=[{"id": i, "vector": v} for i, v in rows]))


def delete(kind: str, ids: list[int]) -> None:
    if not ids:
        return
    ensure(kind)
    with _lock:
        _call("delete", kind, lambda: _client().delete(collection_name(kind), ids=list(ids)))


def get_vectors(kind: str, ids: list[int]) -> dict[int, list[float]]:
    """Stored vectors by id (missing ids are left out). Lets us re-match without re-embedding."""
    if not ids:
        return {}
    ensure(kind)
    out: dict[int, list[float]] = {}
    with _lock:
        for i in range(0, len(ids), 500):
            part = ids[i : i + 500]
            rows = _call("get", kind, lambda p=part: _client().get(collection_name(kind), ids=p, output_fields=["vector"]))
            for r in rows or []:
                out[int(r["id"])] = [float(x) for x in r["vector"]]
    return out


def _similarity(distance: float) -> float:
    if metric() == "L2":  # Milvus returns squared L2; for unit vectors d² = 2 - 2·cos
        return max(0.0, min(1.0, 1.0 - distance / 2.0))
    return float(distance)


def search_many(kind: str, vectors: list[list[float]], limit: int) -> list[list[tuple[int, float]]]:
    """For each query vector: [(id, similarity 0–1)] best first."""
    if limit <= 0 or not vectors:
        return [[] for _ in vectors]
    ensure(kind)
    out: list[list[tuple[int, float]]] = []
    with _lock:
        for i in range(0, len(vectors), 100):
            part = vectors[i : i + 100]
            hits = _call("search", kind, lambda p=part: _client().search(collection_name(kind), data=p, limit=limit))
            for h in hits or []:
                out.append([(int(x["id"]), _similarity(float(x["distance"]))) for x in h])
    while len(out) < len(vectors):
        out.append([])
    return out


def count(kind: str) -> int:
    ensure(kind)
    with _lock:
        res = _call("count", kind, lambda: _client().query(collection_name(kind), filter="", output_fields=["count(*)"]))
    return int(res[0]["count(*)"]) if res else 0


def status() -> str:
    ensure("jobs")
    return f"Milvus Lite at {_uri()} (metric {metric()}; collection: {collection_name('jobs')})"
