"""Scout / Search: Job Search (Overview, Jobs, Search Settings, the JSearch search plan)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, col, select

from backend.db import Job, Scan, SearchQuery, get_session, utcnow
from backend.job_schemas import (
    ApiCallOut,
    ApplyKind,
    AutoscanToggle,
    CallExplainOut,
    CountryOption,
    EmployerAdd,
    EmployerCheckOut,
    EmployerOut,
    EmployerPatch,
    CallJobOut,
    JobCard,
    JobDetail,
    JobPatch,
    JobsDecide,
    JobsOut,
    JobsView,
    OverviewOut,
    QueryOut,
    QueryPatch,
    RelevanceOverride,
    RoleAdd,
    ScanSelection,
    ScanOut,
    ScanRequestsOut,
    FinderDashboardOut,
    FinderStatusOut,
    ScheduleSettings,
    SearchPlanOut,
    SearchSettings,
    SettingsPatch,
    SettingsReset,
    SourceOut,
)
from backend.services import (
    admin_settings, api_budget, job_search, job_views, jsearch_analytics, request_explain, search_plan, search_settings, settings_effects,
)

router = APIRouter(prefix="/scout/search", tags=["scout: search"])


# ── Overview + scans ───────────────────────────────────────────────────────────


@router.get("/overview", response_model=OverviewOut)
def overview(session: Session = Depends(get_session)):
    job_search.ensure_sources(session)
    return job_views.overview(session, job_search.running_scan_id())


@router.post("/scan", response_model=ScanOut, status_code=202)
def scan(body: ScanSelection | None = None, session: Session = Depends(get_session)):
    """Scan now. With a body: only the roles you chose, one request each or one combined (OR)
    request; refused (400) if it needs more requests than are left today. Without: the
    automatic-scan plan."""
    if body is not None:
        plan, _ = search_plan.build(session, selection=body)
        if not plan.fits_budget:
            raise HTTPException(400, " ".join(plan.notes) or "This choice can't be sent right now.")
    try:
        scan_id = job_search.start_scan("manual", body)
    except job_search.ScanRunning as e:
        raise HTTPException(409, str(e)) from e
    return job_views.scan_out(session, session.get(Scan, scan_id))


@router.get("/scans", response_model=list[ScanOut])
def scans(session: Session = Depends(get_session)):
    return job_views.recent_scans(session)


@router.put("/autoscan", response_model=ScheduleSettings)
def autoscan(body: AutoscanToggle, session: Session = Depends(get_session)):
    return admin_settings.set_autoscan(body.enabled)


# ── Jobs ───────────────────────────────────────────────────────────────────────


@router.get("/jobs", response_model=JobsOut)
def jobs(q: str | None = None, category: str | None = None, workplace: str | None = None,
         view: JobsView = "matches", max_years: float | None = None, apply: ApplyKind | None = None,
         found_from: date | None = None, found_to: date | None = None, tz: str | None = None,
         session: Session = Depends(get_session)):
    """One Jobs-page tab: matches (undecided relevant; fits / other), selected, applied,
    discarded, not_relevant, excluded. `found_from` / `found_to`: days the jobs were first found
    (inclusive, in `tz`, e.g. Asia/Kolkata; default UTC); `days` lists every day with its count."""
    return job_views.list_jobs(session, q=q, category=category, workplace=workplace, view=view, max_years=max_years,
                               apply=apply, found_from=found_from, found_to=found_to, tz=tz)


@router.post("/jobs/decide", response_model=dict)
def decide_jobs(body: JobsDecide, session: Session = Depends(get_session)):
    """Your call on several jobs at once (e.g. select some, discard the rest)."""
    rows = list(session.exec(select(Job).where(col(Job.id).in_(body.ids))).all())
    job_search.decide(session, rows, body.decision)
    return {"updated": len(rows), "decision": body.decision}


@router.post("/jobs/{job_id}/relevance", response_model=JobCard)
def set_relevance(job_id: int, body: RelevanceOverride, session: Session = Depends(get_session)):
    """Move a job to your matches ("relevant"), out of them ("not_relevant"), or let the checks
    decide again (null). Your call beats the title check and your search criteria."""
    _job(session, job_id)
    job_search.set_relevance_override(job_id, body.override)
    session.expire_all()
    job = _job(session, job_id)
    titles = job_views._card_titles(session, {job.relevance_card_id} if job.relevance_card_id else set())
    return job_views.job_card(job, search_settings.get(session, "preset"), titles, job_views.searched_places(session, [job]))


@router.post("/roles", response_model=SearchSettings)
def add_role(body: RoleAdd, background: BackgroundTasks, session: Session = Depends(get_session)):
    """Add a job title to Search criteria -> Roles you want (e.g. "Add title to my roles" on a
    job). Jobs already gathered are re-checked; the next plans include a search for it."""
    role = " ".join(body.role.split())
    before = search_settings.get_all(session)
    roles = list(before.criteria.roles)
    if role.lower() not in {r.lower() for r in roles}:
        roles.append(role)
    after, changed = search_settings.patch(session, SettingsPatch(criteria=before.criteria.model_copy(update={"roles": roles})))
    if changed:
        background.add_task(settings_effects.apply, before, after, changed)
    return after


def _job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found (it may have been pruned).")
    return job


@router.get("/jobs/{job_id}", response_model=JobDetail)
def job_detail(job_id: int, session: Session = Depends(get_session)):
    return job_views.job_detail(session, _job(session, job_id))


@router.patch("/jobs/{job_id}", response_model=JobCard)
def patch_job(job_id: int, body: JobPatch, session: Session = Depends(get_session)):
    job = _job(session, job_id)
    job_search.decide(session, [job], body.decision)
    session.refresh(job)
    titles = job_views._card_titles(session, {job.relevance_card_id} if job.relevance_card_id else set())
    return job_views.job_card(job, search_settings.get(session, "preset"), titles, job_views.searched_places(session, [job]))


# ── Search Settings ────────────────────────────────────────────────────────────


@router.get("/settings", response_model=SearchSettings)
def get_search_settings(session: Session = Depends(get_session)):
    return search_settings.get_all(session)


@router.patch("/settings", response_model=SearchSettings)
def patch_settings(body: SettingsPatch, background: BackgroundTasks, session: Session = Depends(get_session)):
    before = search_settings.get_all(session)
    after, changed = search_settings.patch(session, body)
    if changed:
        background.add_task(settings_effects.apply, before, after, changed)
    return after


@router.post("/settings/reset", response_model=SearchSettings)
def reset_settings(body: SettingsReset, background: BackgroundTasks, session: Session = Depends(get_session)):
    before = search_settings.get_all(session)
    after = search_settings.reset(session, body.section)
    if getattr(before, body.section) != getattr(after, body.section):
        background.add_task(settings_effects.apply, before, after, {body.section})
    return after


@router.get("/settings/sources", response_model=list[SourceOut])
def sources(session: Session = Depends(get_session)):
    job_search.ensure_sources(session)
    return job_views.sources_out(session)


# ── Search plan (JSearch) ──────────────────────────────────────────────────────


@router.post("/plan", response_model=SearchPlanOut)
def plan_for_choice(body: ScanSelection, session: Session = Depends(get_session)):
    """What Scan now would send for this choice of roles (and its cost). Calls nothing."""
    plan, _ = search_plan.build(session, selection=body)
    return plan


@router.get("/plan", response_model=SearchPlanOut)
def search_plan_preview(session: Session = Depends(get_session)):
    """What the next scan would send to JSearch, and the budget. Builds the plan; calls nothing."""
    plan, _ = search_plan.build(session)
    return plan


@router.patch("/queries/{query_id}", response_model=QueryOut)
def patch_query(query_id: int, body: QueryPatch, session: Session = Depends(get_session)):
    """Pause or resume one search."""
    q = session.get(SearchQuery, query_id)
    if q is None:
        raise HTTPException(404, "Search not found.")
    q.enabled = body.enabled
    session.add(q)
    session.commit()
    session.refresh(q)
    return search_plan.query_out(q)


@router.get("/places", response_model=list[CountryOption])
def api_places():
    """Countries (and their known states / cities) for the location picker. A saved location is
    "State or city, Country" or just "Country": the country becomes JSearch's `country`, and the
    whole text goes into the query ("AI Engineer in Karnataka, India")."""
    from backend.services.job_facts import place_options

    return place_options()


@router.get("/calls/{call_id}/explain", response_model=CallExplainOut)
def api_call_explain(call_id: int, session: Session = Depends(get_session)):
    """Why one request returned what it did: each parameter in plain words, what the returned jobs
    show, what to change next time, and the same search's other requests. Calls nothing."""
    out = request_explain.explain_call(session, call_id)
    if out is None:
        raise HTTPException(404, "Request not found")
    return out


@router.get("/calls/{call_id}/jobs", response_model=list[CallJobOut])
def api_call_jobs(call_id: int, session: Session = Depends(get_session)):
    """The jobs one request returned (JSearch's order) and what became of each."""
    from backend.db import ApiCallJob

    rows = session.exec(select(ApiCallJob).where(ApiCallJob.call_id == call_id).order_by(ApiCallJob.position)).all()
    jobs = {j.id: j for j in session.exec(select(Job).where(col(Job.id).in_([r.job_id for r in rows if r.job_id]))).all()}
    out = []
    for r in rows:
        j = jobs.get(r.job_id) if r.job_id else None
        out.append(CallJobOut(position=r.position, title=r.title, company_name=r.company_name, location_text=r.location_text,
                              outcome=r.outcome, job_id=r.job_id if j else None,
                              pipeline_status=j.pipeline_status if j else None, status_reason=j.status_reason if j else None,
                              decision=j.decision if j else None, role_score=j.role_score if j else None,
                              role_match=j.role_match if j else None))
    return out


@router.get("/finder", response_model=FinderStatusOut)
def finder_status(session: Session = Depends(get_session)):
    """Scan Jobs -> Company finder: what it has checked and kept (Phase 2.7 E)."""
    from backend.services import company_finder

    return company_finder.status(session)


@router.get("/finder/dashboard", response_model=FinderDashboardOut)
def finder_dashboard(limit: int = 100, session: Session = Depends(get_session)):
    """Admin -> Company finder analytics: every run, and all companies by hiring system and origin."""
    from backend.services import company_finder

    return company_finder.dashboard(session, max(1, min(limit, 500)))


@router.post("/finder/run", response_model=FinderStatusOut, status_code=202)
def finder_run(session: Session = Depends(get_session)):
    """Start a company-finder run in the background (free: public pages and boards only)."""
    from backend.services import company_finder

    if not company_finder.server_allows():
        raise HTTPException(400, "The company finder doesn't run on this server (COMPANY_FINDER=false); it runs on your local app.")
    if not company_finder.settings().enabled:
        raise HTTPException(400, "The company finder is switched off ([scout.search.finder] enabled = false).")
    if not company_finder.start("manual"):
        raise HTTPException(409, "The company finder is already running.")
    return company_finder.status(session)


@router.get("/scan-requests", response_model=list[ScanRequestsOut])
def scan_requests(limit: int = 10, session: Session = Depends(get_session)):
    """Scan Jobs → Requests: the last scans, each with every request it sent, newest first."""
    return jsearch_analytics.scan_history(session, max(1, min(limit, 50)))


@router.get("/calls", response_model=list[ApiCallOut])
def api_calls(limit: int = 50, session: Session = Depends(get_session)):
    """Recent requests to every source (JSearch + company boards), newest first."""
    texts = jsearch_analytics.query_texts(session)
    return [jsearch_analytics.call_out(c, texts) for c in api_budget.recent_calls(session, max(1, min(limit, 500)), api=None)]


# ── Companies (company job boards, Phase 2.7 A1) ─────────────────────────────────


def _employer(session: Session, employer_id: int):
    from backend.db import Employer

    e = session.get(Employer, employer_id)
    if e is None:
        raise HTTPException(404, "Company not found")
    return e


@router.get("/companies", response_model=list[EmployerOut])
def companies(session: Session = Depends(get_session)):
    """Your companies: their job boards are collected on every scan while switched on."""
    from backend.services import employers

    return [employers.out(e) for e in employers.list_all(session)]


@router.post("/companies", response_model=EmployerOut)
def company_add(body: EmployerAdd, session: Session = Depends(get_session)):
    """Add a company from its careers / board link (Greenhouse, Lever, Ashby, SmartRecruiters)."""
    from backend.services import employers

    try:
        return employers.out(employers.add(session, body.url, body.name))
    except employers.EmployerError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/companies/starter", response_model=list[EmployerOut])
def company_starter(session: Session = Depends(get_session)):
    """Add the drafted starter companies you don't have yet, switched off."""
    from backend.services import employers

    return [employers.out(e) for e in employers.add_starter(session)]


@router.patch("/companies/{employer_id}", response_model=EmployerOut)
def company_patch(employer_id: int, body: EmployerPatch, session: Session = Depends(get_session)):
    from backend.services import employers

    e = _employer(session, employer_id)
    if body.enabled is not None:
        e.enabled = body.enabled
    if body.name is not None:
        e.name = body.name.strip()
    session.add(e)
    session.commit()
    session.refresh(e)
    return employers.out(e)


@router.delete("/companies/{employer_id}")
def company_delete(employer_id: int, session: Session = Depends(get_session)):
    """Remove a company (jobs already collected from it stay)."""
    session.delete(_employer(session, employer_id))
    session.commit()
    return {"ok": True}


@router.post("/companies/{employer_id}/check", response_model=EmployerCheckOut)
def company_check(employer_id: int, session: Session = Depends(get_session)):
    """Read the company's board now (one free request) and say what a scan would keep. Stores no jobs."""
    from backend.services import employers

    return employers.check(session, _employer(session, employer_id))

