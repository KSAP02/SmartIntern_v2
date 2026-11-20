"""System / Admin settings: the tuning in settings/config.toml (models, matching, sources,
schedule, limits). Reads show the file as it is now; saves write only the changed keys."""
from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.schemas import AdminSettingsIn, AdminSettingsOut
from backend.services import admin_settings, settings_effects

router = APIRouter(prefix="/system/admin", tags=["system: admin settings"])


@router.get("", response_model=AdminSettingsOut)
def get_admin_settings():
    return admin_settings.get()


@router.put("", response_model=AdminSettingsOut)
def save_admin_settings(body: AdminSettingsIn, background: BackgroundTasks):
    """Save & apply: writes config.toml, then re-embeds / re-maps in the background if needed."""
    try:
        out, areas = admin_settings.save(body.settings, body.version)
    except admin_settings.StaleVersion as e:
        raise HTTPException(409, str(e)) from e
    except admin_settings.InvalidSetting as e:
        raise HTTPException(400, str(e)) from e
    if areas & {"models", "matching"}:
        background.add_task(settings_effects.sync_config)
    return out
