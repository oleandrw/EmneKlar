"""Innstillinger: settings sections, feature flags, local data and updates.

Canvas connection and AI providers have their own routes (routes_canvas, core/ai/api).
Secrets never pass through these endpoints.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from emneklar import __version__
from emneklar.api.deps import get_container
from emneklar.core import flags
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.maintenance import clear, storage_overview
from emneklar.core.storage.settings import AppSettings

router = APIRouter(prefix="/api")

#: Fields the settings pages may change. Others (dry run, Canvas, AI) have dedicated endpoints.
EDITABLE: dict[str, set[str]] = {
    "general": {"theme", "start_page", "default_course_id", "page_size"},
    "analysis": {"default_domains", "regulatory_profile", "check_external_links", "link_timeout_seconds",
                 "link_concurrency", "link_per_host", "link_cache_hours", "check_documents", "max_document_mb",
                 "canvas_concurrency", "include_unpublished"},
    "privacy": {"allow_external_ai", "confirm_before_send", "snapshot_retention_days"},
    "appearance": {"text_size", "density", "reduce_motion", "underline_links"},
    "notifications": {"notify_job_complete", "browser_notifications"},
    "advanced": {"update_repository", "update_channel", "check_updates", "debug_logging"},
    "rag": {"embedding_backend", "embedding_model", "embedding_provider_id", "embedding_provider_model",
            "reranker_enabled", "reranker_model", "device", "transcription", "transcription_provider_id",
            "transcription_model", "transcription_language", "whisper_model", "whisper_other_language_model",
            "youtube_captions", "vimeo_captions", "candidates", "top_k", "query_rewrite", "max_file_mb", "max_video_mb"},
}


def settings_payload(c: AppContainer) -> dict[str, Any]:
    settings = c.settings.get()
    data = settings.model_dump(mode="json", exclude={"ai"})
    return {"settings": data, "flags": flags.describe(settings), "version": __version__,
            "data_dir": str(c.config.data_dir)}


@router.get("/settings")
async def get_settings(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return settings_payload(c)


@router.patch("/settings/{section}")
async def patch_settings(section: str, body: dict[str, Any], c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    allowed = EDITABLE.get(section)
    if allowed is None:
        raise NotFoundError("not_found", detail="innstillingsdel")
    unknown = set(body) - allowed
    if unknown:
        raise AppError("validation_error", message="Disse innstillingene kan ikke endres her: "
                                                   + ", ".join(sorted(unknown)))
    if section == "analysis" and "regulatory_profile" in body:
        from emneklar.features.accessibility.profiles import load_profiles

        if body["regulatory_profile"] not in load_profiles():
            raise AppError("validation_error", message="Ukjent regulatorisk profil.")
    course = body.get("default_course_id")
    if section == "general" and course not in (None, "") and not str(course).isdigit():
        raise AppError("validation_error", message="Ugyldig emne.")
    if section == "general" and body.get("default_course_id") == "":
        body["default_course_id"] = None
    if section == "advanced" and body.get("update_repository") == "":
        body["update_repository"] = None

    def mutate(s: AppSettings) -> None:
        current = getattr(s, section).model_dump()
        current.update(body)
        setattr(s, section, type(getattr(s, section)).model_validate(current))

    try:
        c.settings.update(mutate)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise AppError("validation_error", detail=f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}") from exc
    return settings_payload(c)


# ------------------------------------------------------------------------------------- flags


class FlagBody(BaseModel):
    enabled: bool | None  # None = back to the default for the flag's stage


@router.put("/flags/{key}")
async def set_flag(key: str, body: FlagBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if not flags.known(key):
        raise NotFoundError("not_found", detail="funksjonsflagg")

    def mutate(s: AppSettings) -> None:
        if body.enabled is None:
            s.advanced.feature_flags.pop(key, None)
        else:
            s.advanced.feature_flags[key] = body.enabled

    settings = c.settings.update(mutate)
    return {"flags": flags.describe(settings)}


# ------------------------------------------------------------------------------------ local data


@router.get("/system/storage")
async def storage(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return storage_overview(c.config, c.db)


class ClearBody(BaseModel):
    target: Literal["cache", "analysis", "reports"]


@router.post("/system/storage/clear")
async def clear_data(body: ClearBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if body.target == "analysis" and c.jobs.list(active_only=True):
        raise AppError("conflict", status=409, message="Vent til pågående jobber er ferdige, eller avbryt dem først.")
    return {"removed": clear(c.config, c.db, body.target), **storage_overview(c.config, c.db)}


class FolderBody(BaseModel):
    folder: Literal["data", "backups", "reports", "logs"]


@router.post("/system/open-folder")
async def open_folder(body: FolderBody, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    """Open a data folder in Windows Explorer (local machine only, fixed folders)."""
    paths = {"data": c.config.data_dir, "backups": c.config.backups_dir, "reports": c.config.reports_dir,
             "logs": c.config.logs_dir}
    # sys.platform (not os.name) so mypy narrows the platform and accepts the Windows-only os.startfile.
    if sys.platform != "win32":
        raise AppError("unsupported", status=409, message="Å åpne mapper støttes bare på Windows.")
    paths[body.folder].mkdir(parents=True, exist_ok=True)
    os.startfile(paths[body.folder])  # noqa: S606 - fixed, known folder
    return {"ok": True}


@router.get("/system/log", response_class=PlainTextResponse)
async def log_tail(lines: int = 300, c: AppContainer = Depends(get_container)) -> PlainTextResponse:
    """The last lines of the (already redacted) log, for «Feilsøking»."""
    path = c.config.logs_dir / "emneklar.log"
    if not path.is_file():
        return PlainTextResponse("")
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(lines, 2000)):]
    return PlainTextResponse("\n".join(text))


# ---------------------------------------------------------------------------------------- updates


@router.get("/updates/status")
async def update_status(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if c.updates.check_due():
        c.updates.check_in_background()
    return c.updates.status()


@router.post("/updates/check")
async def update_check(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return await c.updates.check()


class StartUpdate(BaseModel):
    confirm_major: bool = False


@router.post("/updates/start")
async def update_start(body: StartUpdate, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    # Updating EmneKlar itself never touches Canvas, so Dry run does not apply here.
    return c.updates.start(confirm_major=body.confirm_major)
