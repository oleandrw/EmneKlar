"""Canvas-verktøy → Canvas-innstillinger (live analysis, explicit staging of chosen values)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.features.canvas_settings.analysis import DEFAULT_VIEW_LABELS, PREFERENCES, analyze

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/canvas-settings")
async def canvas_settings(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    api = CanvasAPI(c.canvas())
    course, settings, front = await asyncio.gather(api.get_course(course_id), api.course_settings(course_id),
                                                   api.get_front_page(course_id))
    tabs, pages, assignments, quizzes, modules = await asyncio.gather(
        api.course_tabs(course_id), api.list_pages(course_id, include_body=False), api.list_assignments(course_id),
        api.list_quizzes(course_id), api.list_modules(course_id))
    return analyze(course=course, settings=settings, tabs=tabs, front_page=front, pages=pages,
                   assignments=assignments, quizzes=quizzes, modules=modules)


class SettingsChange(BaseModel):
    kind: Literal["default_view", "setting"]
    key: str | None = Field(default=None, max_length=64)
    value: str | bool


@router.post("/courses/{course_id}/canvas-settings/stage")
async def stage(course_id: str, body: SettingsChange, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    api = CanvasAPI(c.canvas())
    if body.kind == "default_view":
        value = str(body.value)
        if value not in DEFAULT_VIEW_LABELS:
            raise AppError("validation_error", message="Ugyldig startside.")
        course, front = await asyncio.gather(api.get_course(course_id, include=()), api.get_front_page(course_id))
        if value == "wiki" and not front:
            raise AppError("validation_error", message="Emnet har ingen forside. Lag en forside først.")
        current = course.get("default_view")
        if current == value:
            raise AppError("validation_error", message="Startsiden har allerede denne verdien.")
        return c.changes.stage(
            course_id=course_id, domain="canvas", kind="course.update",
            title=f"Startside: {DEFAULT_VIEW_LABELS[value]}",
            target={"object_type": "course", "object_id": course_id, "title": course.get("name")},
            before={"default_view": current}, proposed={"default_view": value},
            rationale=(f"Startsiden endres fra «{DEFAULT_VIEW_LABELS.get(str(current), current)}» til "
                       f"«{DEFAULT_VIEW_LABELS[value]}». Det er det første studentene ser i emnet."),
            risk="medium", source={"feature": "canvas_settings"}, merge=True)
    key = body.key or ""
    if key not in PREFERENCES or not isinstance(body.value, bool):
        raise AppError("validation_error", message="Denne innstillingen kan ikke endres her.")
    settings = await api.course_settings(course_id)
    if not isinstance(settings.get(key), bool):
        raise AppError("unsupported", message="Canvas rapporterer ikke denne innstillingen for emnet.")
    if settings[key] == body.value:
        raise AppError("validation_error", message="Innstillingen har allerede denne verdien.")
    label = PREFERENCES[key][0]
    return c.changes.stage(
        course_id=course_id, domain="canvas", kind="course.update_settings",
        title=f"Innstilling: {label}", target={"object_type": "course", "object_id": course_id, "title": label},
        before={key: settings[key]}, proposed={key: body.value},
        rationale=f"Preferanse valgt av deg: «{label}» settes til {'på' if body.value else 'av'}.",
        risk="low", source={"feature": "canvas_settings"}, merge=False)
