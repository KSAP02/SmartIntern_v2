"""System / Switchboard: configuration and component status."""
from fastapi import APIRouter

from backend.config import get_settings, get_tuning
from backend.schemas import StatusOut
from backend.services import status

router = APIRouter(prefix="/system/status", tags=["system: switchboard"])


@router.get("", response_model=StatusOut)
def system_status():
    t = get_tuning()
    llm = t.llm.model_dump(exclude={"tasks"})
    llm["tasks"] = {name: t.llm.for_task(name).model_dump() for name in t.llm.tasks}
    return StatusOut(
        app=t.app.name,
        config_file=str(get_settings().config_file),
        config_loaded=t.loaded_from is not None,
        llm=llm,
        embedding=t.embedding.model_dump(),
        limits={"max_upload_mb": t.records.vault.max_upload_mb, "allowed_types": t.records.vault.allowed_types},
        components=status.components(),
    )
