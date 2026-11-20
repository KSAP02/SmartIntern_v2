"""JSearch calibration (Phase 2.5 step 1): a few live calls that settle what the docs leave open.

    docker compose exec backend python -m backend.services.jsearch_calibration          # show the calls
    docker compose exec backend python -m backend.services.jsearch_calibration --run    # spend them

Spends from the monthly *reserve* (purpose "calibration"), never past the monthly limit, at
most `--max` calls (default 7). Each raw response is saved to <DATA_DIR>/jsearch_calibration/
(public job postings only; the key is never written) for test fixtures, and a summary is
printed: response shape, fields present, India coverage, whether OR / -word / filters work.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from backend.config import data_dir
from backend.db import init_db
from backend.services import api_budget, search_settings
from backend.services.sources import JSEARCH, JSearchError, SourceHttp

BASE = {"country": "in", "page": 1, "num_pages": 1, "date_posted": "month"}
CALLS: list[tuple[str, str, dict]] = [
    ("shape", "Response shape, fields, India coverage", {"query": "AI Engineer in India"}),
    ("intern", "employment_types=INTERN works for India?", {"query": "AI Engineer in India", "employment_types": "INTERN"}),
    ("junior", "job_requirements filter effect", {"query": "AI Engineer in India", "job_requirements": "under_3_years_experience,no_experience"}),
    ("or", "Can roles share one query (OR)?", {"query": "Backend Engineer OR AI Engineer in India"}),
    ("page2", "Overlap between page 1 and page 2", {"query": "AI Engineer in India", "page": 2}),
    ("city", "City vs country query", {"query": "AI Engineer in Bengaluru"}),
    ("minus", "Does -word exclude in query?", {"query": "AI Engineer -senior in India"}),
]


def _summary(name: str, data: dict) -> dict:
    d = data.get("data")
    rows = d if isinstance(d, list) else (d.get("jobs") if isinstance(d, dict) else None) or []
    fields = Counter(k for r in rows for k, v in r.items() if v not in (None, "", [], {}))
    return {
        "shape": "data[list]" if isinstance(d, list) else ("data.jobs" if isinstance(d, dict) else type(d).__name__),
        "results": len(rows),
        "countries": dict(Counter(r.get("job_country") for r in rows)),
        "publishers": dict(Counter(r.get("job_publisher") for r in rows).most_common(5)),
        "types": dict(Counter(t for r in rows for t in (r.get("job_employment_types") or [r.get("job_employment_type")]))),
        "has_currency": fields.get("job_salary_currency", 0),
        "has_highlights": fields.get("job_highlights", 0),
        "titles": [r.get("job_title") for r in rows][:10],
        "ids": [r.get("job_id") for r in rows],
        "fields_seen": sorted(fields),
    }


def test_request() -> dict:
    """Admin -> JSearch -> "Test with 1 request": one real request, from the reserve, exactly
    as a scan would send it for your top search. The raw answer is saved for reference, and the
    jobs go through the normal pipeline (so the request isn't wasted). Returns a summary."""
    from datetime import UTC, datetime

    from backend.db import new_session, utcnow
    from backend.services import compass, job_search, search_plan

    cfg = search_settings.load("sources")
    if not JSEARCH.configured():
        return {"ok": False, "error": "JSEARCH_API_KEY is not set in the root .env."}
    with new_session() as s:
        criteria = search_settings.get(s, "criteria")
        schedule = search_settings.get(s, "schedule")
        queries = search_plan.sync(s, criteria, cfg)
        if not queries:
            return {"ok": False, "error": "Add Roles you want in Search Settings first (JSearch searches by role)."}
        enabled = [q for q in queries if q.enabled] or queries
        q = sorted(enabled, key=lambda x: search_plan.score(x, utcnow()), reverse=True)[0]
        params = search_plan.params_for(q, criteria, schedule, cfg, utcnow())
        qid, qtext = q.id, search_plan.query_text(q)
    try:
        call_id = api_budget.reserve_call(cfg, purpose="calibration", params=params, query_id=qid)
    except api_budget.BudgetExhausted as e:
        return {"ok": False, "error": str(e), "query": qtext, "params": params}
    try:
        with SourceHttp(timeout=cfg.timeout_seconds, max_retries=0) as http:
            data = JSEARCH.fetch_raw(http, params, cfg.provider)
    except JSearchError as e:
        api_budget.finish_call(call_id, ok=False, http_status=e.http_status, error=str(e))
        if e.http_status == 429:
            api_budget.block_for_today()
        return {"ok": False, "error": str(e), "query": qtext, "params": params}
    out_dir = data_dir() / "jsearch_calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (out_dir / f"test-{stamp}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = _summary("test", data)
    rows = data.get("data") if isinstance(data.get("data"), list) else (data.get("data") or {}).get("jobs") or []
    jobs = [j for j in (JSEARCH.normalize(r) for r in rows) if j]
    new = 0
    with job_search.pipeline_lock:
        with new_session() as s:
            lim = search_settings.get(s, "limits")
            returned = []
            for n in jobs:
                outcome = job_search.ingest(s, n, call_id, schedule.recency_days, lim.repost_window_days)
                returned.append((n, outcome))
                new += outcome == "new"
            s.commit()
            job_search.record_call_jobs(s, call_id, returned)
            search_plan.record_run(s, qid, requests=1, results=len(rows), new_jobs=new, ok=True,
                                   backoff_after_empty=cfg.backoff_after_empty)
        api_budget.finish_call(call_id, ok=True, results=len(rows), new_jobs=new)
        with new_session() as s:
            job_search.process_new(s, {})
            search_plan.attribute_relevance(s, [call_id])
        compass.map_pending()
    with new_session() as s:
        from backend.db import ApiCall

        relevant = (s.get(ApiCall, call_id).relevant_jobs if s.get(ApiCall, call_id) else 0)
    summary.pop("ids", None)
    return {"ok": True, "error": None, "query": qtext, "params": params, "new_jobs": new, "relevant_jobs": relevant,
            "saved_as": f"jsearch_calibration/test-{stamp}.json", **summary}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="actually call JSearch (spends from the reserve)")
    ap.add_argument("--max", type=int, default=7, help="most calls to spend")
    args = ap.parse_args()
    init_db()
    cfg = search_settings.load("sources")
    plan = CALLS[: max(0, args.max)]
    for name, why, extra in plan:
        print(f"- {name:6} {why}: {json.dumps({**BASE, **extra})}")
    if not args.run:
        print(f"\nDry run: {len(plan)} call(s) would be spent from the reserve. Add --run to call JSearch.")
        return
    if not JSEARCH.configured():
        raise SystemExit("JSEARCH_API_KEY is not set in the root .env (then docker compose up -d).")
    out_dir = data_dir() / "jsearch_calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict] = {}
    with SourceHttp(timeout=cfg.timeout_seconds, max_retries=0) as http:
        for name, _why, extra in plan:
            params = {**BASE, **extra}
            try:
                call_id = api_budget.reserve_call(cfg, purpose="calibration", params=params, page=params["page"])
            except api_budget.BudgetExhausted as e:
                print(f"stopped: {e}")
                break
            try:
                data = JSEARCH.fetch_raw(http, params, cfg.provider)
            except JSearchError as e:
                api_budget.finish_call(call_id, ok=False, http_status=e.http_status, error=str(e))
                print(f"{name}: FAILED {e}")
                if e.http_status in (401, 403, 429):
                    break
                continue
            (out_dir / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            s = _summary(name, data)
            summaries[name] = s
            api_budget.finish_call(call_id, ok=True, results=s["results"])
    if "shape" in summaries and "page2" in summaries:
        overlap = set(summaries["shape"]["ids"]) & set(summaries["page2"]["ids"])
        summaries["page2"]["overlap_with_page1"] = len(overlap)
    for s in summaries.values():
        s.pop("ids", None)
    (out_dir / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=1))
    print(f"\nSaved to {out_dir}")


if __name__ == "__main__":
    main()
