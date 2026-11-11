"""Health, launch/session and the local control channel."""

from __future__ import annotations

import asyncio
import platform
import sys
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from emneklar import APP_NAME, __version__
from emneklar.api.deps import get_container
from emneklar.core import flags
from emneklar.core.auth.secrets import CANVAS_TOKEN
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.presence import WindowPresence
from emneklar.core.security.web import session_cookie_from_scope, session_cookie_header

router = APIRouter()

EXPIRED_PAGE = """<!doctype html><html lang="nb"><head><meta charset="utf-8"><title>Lenken er utløpt – EmneKlar</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
<h1>Lenken er utløpt</h1>
<p>Innloggingslenken kan bare brukes én gang og er gyldig i fem minutter.</p>
<p>Start EmneKlar på nytt fra <strong>Start-menyen</strong> (eller med start.bat i programmappen). EmneKlar
åpnes da automatisk.</p></body></html>"""

#: A window's connection says something this often, so that a closed window is noticed also where the server learns
#: of it only when it writes.
KEEPALIVE_SECONDS = 10.0


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME, "version": __version__}


@router.get("/auth/launch")
async def launch(request: Request, token: str = "", c: AppContainer = Depends(get_container)) -> object:
    redeemed = c.sessions.redeem(token)
    if redeemed is None:
        if c.sessions.get(session_cookie_from_scope(request.scope, c.sessions.cookie_name)):
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(EXPIRED_PAGE, status_code=401)
    cookie_value, _session = redeemed
    response = RedirectResponse("/", status_code=303)
    key, value = session_cookie_header(c.sessions.cookie_name, cookie_value)
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
        "analysis": {"default_domains": s.analysis.default_domains},
    }


@router.post("/api/session/logout")
async def logout(request: Request, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    c.sessions.drop(session_cookie_from_scope(request.scope, c.sessions.cookie_name))
    return {"ok": True}


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


class ShutdownBody(BaseModel):
    #: Stop although jobs are running (they are interrupted and marked as such at the next start).
    force: bool = False


@router.post("/api/system/shutdown")
async def shutdown(body: ShutdownBody, request: Request, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    """«Avslutt EmneKlar» in the program: stops it at once (closing the last window stops it too, after a short wait –
    ``/api/system/presence``). Like every changing request it needs the session and the CSRF token; the local control
    channel (``/control/shutdown``) is for the start and update scripts."""
    active = c.jobs.list(active_only=True)
    if active and not body.force:
        raise AppError("jobs_running", status=409, extra={"jobs": len(active)},
                       message=f"{len(active)} jobb(er) kjører fortsatt. De blir avbrutt hvis du avslutter nå.")
    callback = getattr(request.app.state, "request_shutdown", None)
    if callback is None:
        raise AppError("unsupported", status=409, message="Denne instansen av EmneKlar kan ikke avsluttes herfra.")
    callback()
    return {"ok": True}


@router.get("/api/system/presence")
async def presence(request: Request) -> StreamingResponse:
    """Held open by every EmneKlar window for as long as it is open (an event stream that only says it is alive).
    When the last one has closed, EmneKlar stops by itself (``core/presence.py``). Needs the session, like the rest
    of the API."""
    windows: WindowPresence = request.app.state.presence

    async def alive() -> AsyncIterator[str]:
        windows.opened()
        try:
            yield "retry: 2000\n\n"  # after a reload or a short break the window is back within two seconds
            while not windows.stopping.is_set():
                try:
                    await asyncio.wait_for(windows.stopping.wait(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": i live\n\n"
        finally:
            windows.closed()

    return StreamingResponse(alive(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


# -- local control channel (start.bat / update.bat / the Start-menu shortcuts) -------------------


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
