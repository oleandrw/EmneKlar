"""Canvas connection (setup wizard + settings) and the global course context."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.auth.secrets import CANVAS_TOKEN
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import CanvasError, validate_base_url
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.security.redaction import register_secret
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
    #: Setup wizard: also check permissions in a sample of the teaching courses – with this connection, before it is
    #: saved (read-only Canvas requests; nothing is stored).
    capabilities: bool = False


class ConnectionSave(BaseModel):
    base_url: str = Field(max_length=300)
    token: str | None = Field(default=None, max_length=2000)
    #: The Canvas user the teacher confirmed. If the token now belongs to someone else, nothing is saved.
    expected_user_id: str | None = Field(default=None, max_length=40)


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


def _token_for(c: AppContainer, base: str, token: str | None) -> str:
    """The token to test with: the one typed in, or the stored one – but the stored token only for the Canvas address it
    was saved for, so it is never sent to another host."""
    typed = (token or "").strip()
    if typed:
        register_secret(typed)  # masked in logs from now on, also if it is never saved
        return typed
    stored = c.canvas_token()
    if not stored:
        raise AppError("canvas_token_missing")
    saved_base = c.settings.get().canvas.base_url
    if saved_base and saved_base != base:
        raise AppError("canvas_token_other_url")
    return stored


async def _test_connection(c: AppContainer, base_url: str, token: str | None, *,
                           capabilities: bool = False) -> dict[str, Any]:
    base = validate_base_url(base_url, allow_http=c.config.allow_insecure_canvas)
    token_value = _token_for(c, base, token)
    client = c.build_canvas_client(base, lambda: token_value, max_concurrency=2)
    try:
        api = CanvasAPI(client)
        me = await api.users_self()
        courses = await api.list_courses()
        access = await _summarize_capabilities(api, [str(x["id"]) for x in courses]) if capabilities else None
    except CanvasError as exc:
        if exc.code == "canvas_not_found":
            raise AppError("canvas_url_invalid", detail="Fant ikke Canvas-API-et på denne adressen") from exc
        raise
    finally:
        await client.aclose()
    result: dict[str, Any] = {
        "base_url": base,
        "identity": {"id": str(me.get("id")), "name": me.get("name") or me.get("short_name") or ""},
        "teaching_courses": len(courses),
    }
    if access is not None:
        # The setup shows the courses by name (as in its course list); nothing about them is stored here.
        result["courses"] = [_course_brief(x) for x in courses]
        result["access"] = access
    return result


@router.post("/canvas/test")
async def test_connection(body: ConnectionTest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Test a connection without saving anything (a successful test never replaces the stored connection)."""
    result = await _test_connection(c, body.base_url, body.token, capabilities=body.capabilities)
    return {"ok": True, **result}


@router.put("/canvas/connection")
async def save_connection(body: ConnectionSave, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Save a connection the teacher has confirmed. Tested again first; if the token now belongs to another user than
    the one confirmed, or saving fails, the previous connection is kept as it was."""
    result = await _test_connection(c, body.base_url, body.token)
    if body.expected_user_id and result["identity"]["id"] != body.expected_user_id:
        raise AppError("canvas_identity_changed", status=409)
    new_token = (body.token or "").strip()
    previous_token = c.canvas_token() if new_token else None
    if new_token:
        c.secrets.set(CANVAS_TOKEN, new_token)  # if this fails, nothing has changed

    def mutate(s: AppSettings) -> None:
        if s.canvas.base_url != result["base_url"]:
            s.current_course_id = None
            s.general.default_course_id = None
        s.canvas.base_url = result["base_url"]
        s.canvas.identity = CanvasIdentity(**result["identity"])
        s.canvas.last_verified_at = datetime.now(UTC)

    try:
        c.settings.update(mutate)
    except Exception:
        if new_token:  # put the previous token back, so the old (working) connection is not half-replaced
            if previous_token:
                c.secrets.set(CANVAS_TOKEN, previous_token)
            else:
                c.secrets.delete(CANVAS_TOKEN)
        raise
    finally:
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


def _with_favorites(c: AppContainer, courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    favorites = set(c.settings.get().favorite_course_ids)
    return [{**course, "favorite": course["id"] in favorites} for course in courses]


@router.get("/courses")
async def list_courses(refresh: bool = False, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    cached, fetched_at = _cached_courses(c)
    if cached and not refresh:
        return {"courses": _with_favorites(c, cached), "fetched_at": fetched_at, "from_cache": True}
    await refresh_courses(c)
    courses, fetched_at = _cached_courses(c)
    return {"courses": _with_favorites(c, courses), "fetched_at": fetched_at, "from_cache": False}


class CourseFavorite(BaseModel):
    favorite: bool


@router.put("/courses/{course_id}/favorite")
async def set_favorite(course_id: str, body: CourseFavorite, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Mark or unmark a course as a favourite in the course selector. Stored in EmneKlar only – nothing is written to
    Canvas (Canvas' own course favourites are left as they are)."""
    course_id = require_course_id(course_id)

    def mutate(s: AppSettings) -> None:
        ids = [x for x in s.favorite_course_ids if x != course_id]
        s.favorite_course_ids = [*ids, course_id] if body.favorite else ids

    updated = c.settings.update(mutate)
    return {"course_id": course_id, "favorite": body.favorite, "favorite_course_ids": updated.favorite_course_ids}


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
    return await _course_capabilities(CanvasAPI(c.canvas()), course_id)


async def _course_capabilities(api: CanvasAPI, course_id: str) -> dict[str, Any]:
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


CAPABILITY_SAMPLE = 5


def _course_brief(course: dict[str, Any]) -> dict[str, Any]:
    """What the setup shows about a teaching course: its name, code and term (as in the course list)."""
    term = course.get("term") or {}
    return {"id": str(course["id"]), "name": course.get("name") or course.get("original_name") or "",
            "course_code": course.get("course_code"), "term_name": term.get("name") if isinstance(term, dict) else None}


async def _summarize_capabilities(api: CanvasAPI, course_ids: list[str]) -> dict[str, Any]:
    """Permissions in a sample of the teaching courses, counted per capability («i 3 av 5 kontrollerte emner») and with
    the courses (by id) where each one is missing – never generalised to all courses. Courses whose check failed are
    listed apart (unknown, not missing). Read-only; the same requests as before, only reported in more detail."""
    sample = course_ids[:CAPABILITY_SAMPLE]
    results = await asyncio.gather(*(_course_capabilities(api, course_id) for course_id in sample),
                                   return_exceptions=True)
    summary: dict[str, dict[str, Any]] = {key: {"granted": 0, "checked": 0, "missing_in": []} for key, _, _ in CAPABILITIES}
    checked_in: list[str] = []
    failed_in: list[str] = []
    for course_id, result in zip(sample, results, strict=True):
        if isinstance(result, BaseException):
            failed_in.append(course_id)
            continue
        checked_in.append(course_id)
        for cap in result["capabilities"]:
            entry = summary[cap["key"]]
            entry["checked"] += 1
            if cap["granted"]:
                entry["granted"] += 1
            else:
                entry["missing_in"].append(course_id)
    return {
        "teaching_courses": len(course_ids),
        "checked_courses": len(checked_in),
        "checked_in": checked_in,
        "failed_in": failed_in,
        "capabilities": [{"key": key, "label": label, **summary[key]} for key, label, _ in CAPABILITIES],
    }


@router.get("/canvas/capability-summary")
async def capability_summary(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Teaching courses and permissions in a sample of them, with the stored connection."""
    courses = await refresh_courses(c)
    return await _summarize_capabilities(CanvasAPI(c.canvas()), [x["id"] for x in courses])


@router.get("/canvas/image")
async def image_proxy(url: str, c: AppContainer = Depends(get_container)) -> Response:
    """Authenticated proxy for Canvas images in previews (Canvas origin only, images only, size-limited)."""
    client = c.canvas()
    parts = urlsplit(url)
    if not client.is_canvas_origin(url) or not re.match(r"^/(courses/\d+/)?files/\d+(/preview|/download)?$",
                                                        parts.path or ""):
        raise AppError("url_blocked", status=400)
    try:
        data, content_type = await CanvasAPI(client).file_bytes(url, max_bytes=8 * 1024 * 1024)
    except CanvasError as exc:
        raise AppError("not_found", status=404, detail=exc.code) from exc
    content_type = (content_type or "").split(";")[0].strip().lower()
    if not content_type.startswith("image/") or content_type == "image/svg+xml":
        raise AppError("file_unsupported", status=415)
    return Response(data, media_type=content_type, headers={"Cache-Control": "private, max-age=300"})


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
