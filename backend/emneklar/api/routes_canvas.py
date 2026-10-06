"""Canvas connection (setup wizard + settings) and the global course context."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.auth.secrets import CANVAS_TOKEN
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import CanvasError, validate_base_url
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.storage.models import Course
from emneklar.core.storage.settings import AppSettings, CanvasIdentity

router = APIRouter(prefix="/api")

CAPABILITIES: list[tuple[str, str, list[str]]] = [
    ("read", "Lese alt innhold i emnet (også upublisert)", ["read_as_admin", "manage"]),
    ("pages", "Redigere sider", ["manage_wiki_update"]),
    ("create_pages", "Opprette sider", ["manage_wiki_create"]),
    ("modules", "Endre moduler og modulkrav", ["manage_course_content_edit"]),
    ("assignments", "Endre oppgaver og klassiske quizer", ["manage_assignments_edit"]),
    ("create_quizzes", "Opprette quizer", ["manage_assignments_add"]),
    ("settings", "Endre emneinnstillinger", ["update_course_details"]),
]


class ConnectionTest(BaseModel):
    base_url: str = Field(max_length=300)
    token: str | None = Field(default=None, max_length=2000)


class ConnectionSave(BaseModel):
    base_url: str = Field(max_length=300)
    token: str | None = Field(default=None, max_length=2000)


def _course_dict(course: dict[str, Any]) -> dict[str, Any]:
    term = course.get("term") or {}
    return {
        "id": str(course["id"]),
        "name": course.get("name") or course.get("original_name") or "",
        "course_code": course.get("course_code"),
        "term_name": term.get("name") if isinstance(term, dict) else None,
        "workflow_state": course.get("workflow_state"),
        "is_blueprint": bool(course.get("blueprint")),
        "default_view": course.get("default_view"),
        "roles": course.get("_teaching_roles") or [],
    }


async def _test_connection(c: AppContainer, base_url: str, token: str | None) -> dict[str, Any]:
    base = validate_base_url(base_url, allow_http=c.config.allow_insecure_canvas)
    token_value = (token or "").strip() or c.canvas_token()
    if not token_value:
        raise AppError("canvas_token_missing")
    client = c.build_canvas_client(base, lambda: token_value, max_concurrency=2)
    try:
        api = CanvasAPI(client)
        me = await api.users_self()
        courses = await api.list_courses()
    except CanvasError as exc:
        if exc.code == "canvas_not_found":
            raise AppError("canvas_url_invalid", detail="Fant ikke Canvas-API-et på denne adressen") from exc
        raise
    finally:
        await client.aclose()
    return {
        "base_url": base,
        "identity": {"id": str(me.get("id")), "name": me.get("name") or me.get("short_name") or ""},
        "teaching_courses": len(courses),
    }


@router.post("/canvas/test")
async def test_connection(body: ConnectionTest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    result = await _test_connection(c, body.base_url, body.token)
    return {"ok": True, **result}


@router.put("/canvas/connection")
async def save_connection(body: ConnectionSave, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    result = await _test_connection(c, body.base_url, body.token)
    if body.token and body.token.strip():
        c.secrets.set(CANVAS_TOKEN, body.token.strip())

    def mutate(s: AppSettings) -> None:
        if s.canvas.base_url != result["base_url"]:
            s.current_course_id = None
            s.general.default_course_id = None
        s.canvas.base_url = result["base_url"]
        s.canvas.identity = CanvasIdentity(**result["identity"])
        s.canvas.last_verified_at = datetime.now(UTC)

    c.settings.update(mutate)
    c.reset_canvas()
    return {"ok": True, **result}


@router.delete("/canvas/token")
async def delete_token(c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    c.secrets.delete(CANVAS_TOKEN)
    c.reset_canvas()
    return {"ok": True}


@router.get("/canvas/status")
async def canvas_status(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    s = c.settings.get()
    return {
        "base_url": s.canvas.base_url,
        "token_configured": c.secrets.has(CANVAS_TOKEN),
        "identity": s.canvas.identity.model_dump() if s.canvas.identity else None,
        "last_verified_at": s.canvas.last_verified_at.isoformat() if s.canvas.last_verified_at else None,
        "secret_backend": getattr(c.secrets, "backend_name", lambda: "ukjent")(),
    }


@router.post("/canvas/verify")
async def verify_stored(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    s = c.settings.get()
    if not s.canvas.base_url:
        raise AppError("canvas_not_configured")
    result = await _test_connection(c, s.canvas.base_url, None)

    def mutate(st: AppSettings) -> None:
        st.canvas.identity = CanvasIdentity(**result["identity"])
        st.canvas.last_verified_at = datetime.now(UTC)

    c.settings.update(mutate)
    return {"ok": True, **result}


# -- courses ------------------------------------------------------------------------------------


def _cached_courses(c: AppContainer) -> tuple[list[dict[str, Any]], str | None]:
    with c.db.session() as session:
        rows = session.scalars(select(Course).order_by(Course.name)).all()
        newest = max((r.refreshed_at for r in rows), default=None)
        return ([{"id": r.id, "name": r.name, "course_code": r.course_code, "term_name": r.term_name,
                  "workflow_state": r.workflow_state, "is_blueprint": r.is_blueprint, "default_view": r.default_view,
                  "roles": r.enrollment_roles} for r in rows], newest.isoformat() if newest else None)


async def refresh_courses(c: AppContainer) -> list[dict[str, Any]]:
    courses = [_course_dict(x) for x in await CanvasAPI(c.canvas()).list_courses()]
    with c.db.session() as session:
        existing = {r.id: r for r in session.scalars(select(Course)).all()}
        seen = set()
        for data in courses:
            seen.add(data["id"])
            row = existing.get(data["id"])
            if row is None:
                row = Course(id=data["id"], name=data["name"])
                session.add(row)
            row.name = data["name"]
            row.course_code = data["course_code"]
            row.term_name = data["term_name"]
            row.workflow_state = data["workflow_state"]
            row.is_blueprint = data["is_blueprint"]
            row.default_view = data["default_view"]
            row.enrollment_roles = data["roles"]
            row.refreshed_at = datetime.now(UTC)
        for course_id, row in existing.items():
            if course_id not in seen:
                session.delete(row)
    return courses


@router.get("/courses")
async def list_courses(refresh: bool = False, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    cached, fetched_at = _cached_courses(c)
    if cached and not refresh:
        return {"courses": cached, "fetched_at": fetched_at, "from_cache": True}
    await refresh_courses(c)
    courses, fetched_at = _cached_courses(c)
    return {"courses": courses, "fetched_at": fetched_at, "from_cache": False}


class CourseSelect(BaseModel):
    course_id: str


@router.put("/context/course")
async def select_course(body: CourseSelect, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(body.course_id)
    cached, _ = _cached_courses(c)
    if not any(x["id"] == course_id for x in cached):
        await refresh_courses(c)
        cached, _ = _cached_courses(c)
        if not any(x["id"] == course_id for x in cached):
            raise AppError("course_not_found", status=404)
    c.settings.update(lambda s: setattr(s, "current_course_id", course_id))
    return {"current_course_id": course_id}


async def course_capabilities(c: AppContainer, course_id: str) -> dict[str, Any]:
    api = CanvasAPI(c.canvas())
    perms, template, subscriptions = await asyncio.gather(
        api.course_permissions(course_id), api.blueprint_template(course_id), api.blueprint_subscriptions(course_id))
    capabilities = [
        {"key": key, "label": label, "granted": any(perms.get(k) for k in keys), "permissions": keys}
        for key, label, keys in CAPABILITIES
    ]
    return {
        "course_id": course_id,
        "capabilities": capabilities,
        "permissions": perms,
        "blueprint": {
            "is_blueprint": template is not None,
            "associated_course_count": (template or {}).get("associated_course_count"),
            "is_child": bool(subscriptions),
            "parent": (subscriptions[0].get("blueprint_course") if subscriptions else None),
        },
    }


@router.get("/courses/{course_id}/capabilities")
async def capabilities(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return await course_capabilities(c, require_course_id(course_id))


@router.get("/canvas/capability-summary")
async def capability_summary(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Setup step «Sjekk tilganger»: teaching courses and permissions in a sample of them."""
    courses = await refresh_courses(c)
    sample = courses[:5]
    results = await asyncio.gather(*(course_capabilities(c, x["id"]) for x in sample), return_exceptions=True)
    summary: dict[str, dict[str, int]] = {key: {"granted": 0, "checked": 0} for key, _, _ in CAPABILITIES}
    errors = 0
    for result in results:
        if isinstance(result, BaseException):
            errors += 1
            continue
        for cap in result["capabilities"]:
            summary[cap["key"]]["checked"] += 1
            summary[cap["key"]]["granted"] += int(cap["granted"])
    return {
        "teaching_courses": len(courses),
        "checked_courses": len(sample) - errors,
        "capabilities": [{"key": key, "label": label, **summary[key]} for key, label, _ in CAPABILITIES],
    }


class SetupComplete(BaseModel):
    default_course_id: str | None = None
    regulatory_profile: str | None = None


@router.post("/setup/complete")
async def complete_setup(body: SetupComplete, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    from emneklar.features.accessibility.profiles import load_profiles

    if not c.settings.get().canvas.base_url or not c.secrets.has(CANVAS_TOKEN):
        raise AppError("canvas_not_configured")
    if body.regulatory_profile and body.regulatory_profile not in load_profiles():
        raise AppError("validation_error", detail="Ukjent regulatorisk profil")
    course_id = require_course_id(body.default_course_id) if body.default_course_id else None

    def mutate(s: AppSettings) -> None:
        s.setup_completed = True
        if course_id:
            s.general.default_course_id = course_id
            s.current_course_id = course_id
        if body.regulatory_profile:
            s.analysis.regulatory_profile = body.regulatory_profile

    c.settings.update(mutate)
    return {"ok": True}
