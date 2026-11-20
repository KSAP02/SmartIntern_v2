"""Entrypoint, wiring only: app, routers, error handlers, startup."""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.insight import desk
from backend.api.records import memory, profile, vault
from backend.api.scout import compass, search
from backend.api.system import admin, jsearch, status
from backend.config import ConfigWriteError, get_settings, get_tuning
from backend.db import init_db
from backend.model import ModelConfigError, UpstreamError, llm_status
from backend.services import job_search, role_contexts, scheduler, search_settings, settings_effects
from backend.services import memory as memory_service
from backend.services import vault as vault_service
from backend.storage import StorageError
from backend.vectors import VectorStoreError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smartintern")


def _recover() -> None:
    """Finish work interrupted by a restart: stuck resume parses, pending/changed embeddings, scans."""
    for resume_id in vault_service.requeue_unfinished():
        vault_service.parse_resume(resume_id)
    try:
        job_search.recover_interrupted()
        job_search.migrate_hidden_to_decision()
        search_settings.move_db_settings_to_toml()
        search_settings.apply_metric()
        memory_service.check_embedding_signature()
        memory_service.drop_unused_vectors()  # Phase 2.6: card / requirement vectors are gone
        settings_effects.sync_config(force=True)  # config.toml edited while the app was down
        job_search.reapply_criteria_if_needed()  # what the criteria exclude changed (e.g. location, 2026-11-20)
        job_search.rescore_titles_if_needed()  # title scoring method changed since last start
        job_search.backfill_call_jobs()  # requests made before api_call_jobs existed
        role_contexts.ensure_for_roles()  # roles without a role context get one (model calls)
        job_search.reembed_jobs_if_needed()  # the embedded job text changed (Phase 2.6)
    except Exception as e:  # noqa: BLE001 - startup must not fail on this
        log.warning("memory recovery skipped: %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    stop = threading.Event()
    threading.Thread(target=_recover, name="startup-recovery", daemon=True).start()
    scheduler.start(stop)
    yield
    stop.set()


app = FastAPI(title=get_tuning().app.name, lifespan=lifespan)

_origins = [o.strip().rstrip("/") for o in get_settings().cors_origins.split(",") if o.strip()]
if _origins:  # deployed split (e.g. Vercel frontend -> Render backend)
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])

for router in (vault.router, profile.router, memory.router, search.router, compass.router, desk.router, status.router,
               admin.router, jsearch.router):
    app.include_router(router)


@app.exception_handler(ModelConfigError)
@app.exception_handler(ConfigWriteError)
@app.exception_handler(StorageError)
@app.exception_handler(VectorStoreError)
def config_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(UpstreamError)
def upstream_error(_: Request, exc: UpstreamError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": get_tuning().app.name, "llm": llm_status()}
