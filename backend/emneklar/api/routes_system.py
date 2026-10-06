"""Health, launch/session, Dry run and the local control channel."""

from __future__ import annotations

import platform
import sys

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from emneklar import APP_NAME, __version__
from emneklar.api.deps import get_container
from emneklar.core import flags
from emneklar.core.auth.secrets import CANVAS_TOKEN
from emneklar.core.container import AppContainer
from emneklar.core.security.web import session_cookie_from_scope, session_cookie_header
from emneklar.core.storage.settings import AppSettings

router = APIRouter()

EXPIRED_PAGE = """<!doctype html><html lang="nb"><head><meta charset="utf-8"><title>Lenken er utløpt – EmneKlar</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
<h1>Lenken er utløpt</h1>
<p>Innloggingslenken kan bare brukes én gang og er gyldig i fem minutter.</p>
<p>Start EmneKlar på nytt med <strong>start.bat</strong>. Nettleseren åpnes da automatisk.</p></body></html>"""


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME, "version": __version__}


@router.get("/auth/launch")
async def launch(request: Request, token: str = "", c: AppContainer = Depends(get_container)) -> object:
    redeemed = c.sessions.redeem(token)
    if redeemed is None:
        if c.sessions.get(session_cookie_from_scope(request.scope)):
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(EXPIRED_PAGE, status_code=401)
    cookie_value, _session = redeemed
    response = RedirectResponse("/", status_code=303)
    key, value = session_cookie_header(cookie_value)
    response.raw_headers.append((key, value))
    return response


@router.get("/api/session")
async def session_info(request: Request, c: AppContainer = Depends(get_container)) -> dict[str, object]:
    session = request.scope["state"]["emneklar_session"]
    s = c.settings.get()
    return {
        "csrf_token": session.csrf,
        "app": {"name": APP_NAME, "version": __version__},
        "setup_completed": s.setup_completed,
        "dry_run": s.dry_run,
        "current_course_id": s.current_course_id,
        "canvas": {
            "base_url": s.canvas.base_url,
            "token_configured": c.secrets.has(CANVAS_TOKEN),
            "identity": s.canvas.identity.model_dump() if s.canvas.identity else None,
        },
        "general": s.general.model_dump(mode="json"),
        "appearance": s.appearance.model_dump(mode="json"),
        "notifications": s.notifications.model_dump(mode="json"),
        "flags": {f["key"]: f["enabled"] for f in flags.describe(s)},
        "ai": {
            "external_allowed": s.privacy.allow_external_ai,
            "confirm_before_send": s.privacy.confirm_before_send,
            "providers_enabled": [p.id for p in s.ai.providers if p.enabled],
        },
        "regulatory_profile": s.analysis.regulatory_profile,
    }


@router.post("/api/session/logout")
async def logout(request: Request, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    c.sessions.drop(session_cookie_from_scope(request.scope))
    return {"ok": True}


class DryRunBody(BaseModel):
    enabled: bool


@router.put("/api/system/dry-run")
async def set_dry_run(body: DryRunBody, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    def mutate(s: AppSettings) -> None:
        s.dry_run = body.enabled

    settings = c.settings.update(mutate)
    return {"dry_run": settings.dry_run}


@router.get("/api/system/info")
async def system_info(c: AppContainer = Depends(get_container)) -> dict[str, object]:
    backend_name = getattr(c.secrets, "backend_name", lambda: "ukjent")()
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(terse=True),
        "data_dir": str(c.config.data_dir),
        "database": str(c.config.db_path),
        "secret_backend": backend_name,
        "started_at": c.started_at.isoformat(),
        "db_revision": c.db.current_revision(),
    }


# -- local control channel (start.bat / update.bat) ------------------------------------------


@router.post("/control/launch-url")
async def control_launch_url(c: AppContainer = Depends(get_container)) -> dict[str, str]:
    token = c.sessions.new_launch_token()
    return {"url": f"{c.config.origin}/auth/launch?token={token}"}


@router.post("/control/shutdown")
async def control_shutdown(request: Request) -> dict[str, bool]:
    callback = getattr(request.app.state, "request_shutdown", None)
    if callback is not None:
        callback()
    return {"ok": callback is not None}
