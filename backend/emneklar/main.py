"""FastAPI application factory.

The built frontend (``frontend/dist``) is served by the same process, so the
user only ever starts one program.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response as StarletteResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from emneklar import APP_NAME, __version__
from emneklar.api.router import api_routers
from emneklar.config import RuntimeConfig
from emneklar.core.container import AppContainer
from emneklar.core.errors import MESSAGES, AppError
from emneklar.core.presence import WindowPresence
from emneklar.core.security.web import SecurityMiddleware

log = logging.getLogger(__name__)
#: Starlette's own HTTP errors with a message of their own (405 keeps its «Allow» header).
HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}

NO_FRONTEND_PAGE = """<!doctype html><html lang="nb"><head><meta charset="utf-8"><title>EmneKlar</title>
</head><body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
<h1>Brukergrensesnittet er ikke bygget</h1>
<p>Installer EmneKlar på nytt (dataene dine beholdes), eller kjør <strong>setup.bat</strong> i programmappen.
Utviklere: kjør <code>npm ci</code> og <code>npm run build</code> i mappen <code>frontend</code>, eller start
Vite-serveren med <code>npm run dev</code>.</p></body></html>"""


def create_app(container: AppContainer | None = None, *, config: RuntimeConfig | None = None) -> FastAPI:
    config = config or (container.config if container else RuntimeConfig.from_env())
    container = container or AppContainer(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container.startup()
        log.info("%s %s kjører på %s (data: %s)", APP_NAME, __version__, config.origin, config.data_dir)
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if config.dev_mode else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.dev_mode else None,
    )
    app.state.container = container
    # Counts the open windows; the launcher arms it (core/presence.py), everything else leaves it unarmed.
    app.state.presence = WindowPresence(running_jobs=lambda: len(container.jobs.list(active_only=True)))

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.to_payload(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        return JSONResponse({"error": {"code": "validation_error", "message": MESSAGES["validation_error"],
                                       "details": detail[:1000]}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 404 and 405 are the client asking for something that is not there; anything else is unexpected here.
        code = HTTP_ERROR_CODES.get(exc.status_code, "internal_error")
        return JSONResponse({"error": {"code": code, "message": MESSAGES[code]}}, status_code=exc.status_code,
                            headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        reference = secrets.token_hex(4)
        log.exception("Uventet feil (referanse %s)", reference)
        return JSONResponse({"error": {"code": "internal_error", "message": MESSAGES["internal_error"],
                                       "details": f"Referanse {reference}: {type(exc).__name__}"}}, status_code=500)

    for router in api_routers():
        app.include_router(router)

    _mount_frontend(app, config.frontend_dist)
    app.add_middleware(SecurityMiddleware, config=config, sessions=container.sessions,
                       control_secret=lambda: container.control_secret)
    return app


#: Every file under /assets has a content hash in its name (Vite): a new build gives new names, so a browser may keep
#: a file for good. index.html (no-cache) decides which names are current.
IMMUTABLE = "public, max-age=31536000, immutable"


class HashedAssets(StaticFiles):
    """The built frontend's hashed files: cached for good, and compressed (see _mount_frontend)."""

    async def get_response(self, path: str, scope: Scope) -> StarletteResponse:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def _mount_frontend(app: FastAPI, dist: Path | None) -> None:
    index = dist / "index.html" if dist else None
    if dist and (dist / "assets").is_dir():
        # Compression only here: the scripts and styles are large and static. API responses (and the event stream)
        # are left as they are.
        app.mount("/assets", GZipMiddleware(HashedAssets(directory=dist / "assets"), minimum_size=1024), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "control/", "auth/")):
            return JSONResponse({"error": {"code": "not_found", "message": MESSAGES["not_found"]}}, status_code=404)
        if dist is not None and path and "/" not in path and not path.startswith("."):
            candidate = (dist / path).resolve()
            if candidate.is_file() and candidate.parent == dist.resolve():
                return FileResponse(candidate)
        if index is not None and index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return Response(NO_FRONTEND_PAGE, media_type="text/html; charset=utf-8", status_code=503)
