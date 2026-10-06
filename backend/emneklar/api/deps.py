"""FastAPI dependencies shared by all routers."""

from __future__ import annotations

from fastapi import Request

from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.security.web import Session


def get_container(request: Request) -> AppContainer:
    return request.app.state.container  # type: ignore[no-any-return]


def get_session(request: Request) -> Session:
    session = request.scope.get("state", {}).get("emneklar_session")
    if session is None:
        raise AppError("session_required", status=401)
    return session  # type: ignore[no-any-return]


def require_course_id(course_id: str) -> str:
    course_id = (course_id or "").strip()
    if not course_id.isdigit() or len(course_id) > 20:
        raise AppError("validation_error", detail="Ugyldig emne-id")
    return course_id
