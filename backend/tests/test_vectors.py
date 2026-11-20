"""Real Milvus Lite (local file, no network)."""
from backend import vectors
from backend.config import get_tuning


def _vec(i: int) -> list[float]:
    dims = get_tuning().embedding.dimensions
    v = [0.0] * dims
    v[i % dims] = 1.0
    return v


def test_upsert_search_delete_and_search_after_release():
    vectors.reset("jobs")
    vectors.upsert("jobs", [(1, _vec(1)), (2, _vec(2))])
    assert vectors.search_many("jobs", [_vec(2)], limit=2)[0][0][0] == 2

    # Simulate a restart: the collection reopens 'released' and must be loaded again.
    vectors._client().release_collection(vectors.collection_name("jobs"))
    vectors._ready.clear()
    assert vectors.search_many("jobs", [_vec(1)], limit=1)[0][0][0] == 1

    vectors.delete("jobs", [1])
    assert {i for i, _ in vectors.search_many("jobs", [_vec(1)], limit=5)[0]} == {2}


def test_metrics_give_same_ranking_and_0_to_1_similarity():
    """OpenAI vectors are unit-length: COSINE, IP and L2 rank identically (see plan §5)."""
    import math

    dims = get_tuning().embedding.dimensions

    def unit(a: float) -> list[float]:
        v = [0.0] * dims
        v[0], v[1] = math.cos(a), math.sin(a)
        return v

    rankings = {}
    try:
        for m in ("COSINE", "IP", "L2"):
            vectors.set_metric(m)
            vectors.reset("jobs")
            vectors.upsert("jobs", [(1, unit(0.1)), (2, unit(0.5)), (3, unit(1.2))])
            hits = vectors.search_many("jobs", [unit(0.0)], limit=3)[0]
            rankings[m] = [i for i, _ in hits]
            assert all(0.0 <= s <= 1.0 for _, s in hits)
            assert abs(hits[0][1] - math.cos(0.1)) < 1e-3  # similarity, not raw distance
        assert rankings["COSINE"] == rankings["IP"] == rankings["L2"] == [1, 2, 3]
    finally:
        vectors.set_metric("COSINE")
        vectors.reset("jobs")
