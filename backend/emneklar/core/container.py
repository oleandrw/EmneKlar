"""Wires the core services together. One instance per running application.

Features receive the container (via ``api.deps``) and use its shared services:
the Canvas client, the change engine, the job manager, the AI service and the
settings store. Features must not build their own HTTP clients for Canvas or
AI providers.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import delete, select

from emneklar import __version__
from emneklar.config import RuntimeConfig
from emneklar.core.auth.secrets import CANVAS_TOKEN, SecretStore, create_secret_store
from emneklar.core.canvas.client import CanvasClient
from emneklar.core.errors import AppError
from emneklar.core.jobs.manager import JobManager
from emneklar.core.security.web import SessionStore
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import WebSession
from emneklar.core.storage.settings import AppSettings, SettingsStore

if TYPE_CHECKING:
    from emneklar.core.ai.service import AIService
    from emneklar.core.changes.engine import ChangeEngine

log = logging.getLogger(__name__)


class DbSessionPersistence:
    def __init__(self, db: Database) -> None:
        self._db = db

    def load(self) -> list[tuple[str, str, float, float]]:
        with self._db.session() as session:
            return [(r.id_hash, r.csrf, r.created, r.last_seen) for r in session.scalars(select(WebSession)).all()]

    def save(self, id_hash: str, csrf: str, created: float, last_seen: float) -> None:
        with self._db.session() as session:
            row = session.get(WebSession, id_hash)
            if row is None:
                session.add(WebSession(id_hash=id_hash, csrf=csrf, created=created, last_seen=last_seen))
            else:
                row.last_seen = last_seen

    def delete(self, id_hash: str) -> None:
        with self._db.session() as session:
            session.execute(delete(WebSession).where(WebSession.id_hash == id_hash))


class AppContainer:
    def __init__(
        self,
        config: RuntimeConfig,
        *,
        secret_store: SecretStore | None = None,
        canvas_transport: httpx.AsyncBaseTransport | None = None,
        link_transport: httpx.AsyncBaseTransport | None = None,
        ai_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        config.ensure_dirs()
        self.config = config
        self.db = Database(config.db_path)
        self.secrets = secret_store or create_secret_store(config.secret_backend)
        self.settings = SettingsStore(self.db)
        self.jobs = JobManager(self.db)
        self.control_secret = secrets.token_urlsafe(32)
        # Test seams: tests inject httpx MockTransports instead of the network.
        self.canvas_transport = canvas_transport
        self.link_transport = link_transport
        self.ai_transport = ai_transport
        self._sessions: SessionStore | None = None
        self._canvas: CanvasClient | None = None
        self._canvas_key: tuple[str, int] | None = None
        self._changes: ChangeEngine | None = None
        self._ai: AIService | None = None
        self._parsers: Any = None
        self.started_at = datetime.now(UTC)

    # -- lifecycle ---------------------------------------------------------------------

    def migrate(self) -> None:
        self.db.migrate(self.config.backups_dir)

    @property
    def sessions(self) -> SessionStore:
        if self._sessions is None:
            self._sessions = SessionStore(self.config.dev_launch_token, persistence=DbSessionPersistence(self.db))
        return self._sessions

    def startup(self) -> None:
        self.migrate()
        interrupted = self.jobs.recover_after_restart()
        if interrupted:
            log.info("%s jobb(er) ble avbrutt ved forrige avslutning", interrupted)
        self._write_instance_file()

    async def aclose(self) -> None:
        await self.jobs.shutdown()
        if self._canvas is not None:
            await self._canvas.aclose()
            self._canvas = None
        if self._ai is not None:
            await self._ai.aclose()
        if self._parsers is not None:
            await self._parsers.close()
        self._remove_instance_file()
        self.db.dispose()

    def _instance_file(self) -> Any:
        return self.config.run_dir / "instance.json"

    def _write_instance_file(self) -> None:
        data = {"pid": os.getpid(), "port": self.config.port, "origin": self.config.origin, "version": __version__,
                "control_secret": self.control_secret, "started_at": self.started_at.isoformat()}
        path = self._instance_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)

    def _remove_instance_file(self) -> None:
        try:
            path = self._instance_file()
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("control_secret") == self.control_secret:
                path.unlink()
        except (OSError, ValueError):
            pass

    # -- settings shortcuts --------------------------------------------------------------

    def app_settings(self) -> AppSettings:
        return self.settings.get()

    def is_dry_run(self) -> bool:
        return self.settings.get().dry_run

    # -- Canvas --------------------------------------------------------------------------

    def canvas_token(self) -> str | None:
        return self.secrets.get(CANVAS_TOKEN)

    def canvas(self) -> CanvasClient:
        settings = self.settings.get()
        base_url = settings.canvas.base_url
        if not base_url:
            raise AppError("canvas_not_configured", status=400)
        if not self.secrets.has(CANVAS_TOKEN):
            raise AppError("canvas_token_missing", status=400)
        key = (base_url, settings.analysis.canvas_concurrency)
        if self._canvas is None or self._canvas_key != key:
            self._canvas = self.build_canvas_client(base_url, self.canvas_token,
                                                    max_concurrency=settings.analysis.canvas_concurrency)
            self._canvas_key = key
        return self._canvas

    def build_canvas_client(self, base_url: str, token_provider: Any, *, max_concurrency: int = 4) -> CanvasClient:
        http = None
        if self.canvas_transport is not None:
            http = httpx.AsyncClient(transport=self.canvas_transport, follow_redirects=False)
        return CanvasClient(base_url, token_provider, http=http, allow_http=self.config.allow_insecure_canvas,
                            max_concurrency=max_concurrency, dry_run=self.is_dry_run)

    def reset_canvas(self) -> None:
        """Drop the cached client (e.g. after the URL or token changed)."""
        self._canvas = None
        self._canvas_key = None

    # -- shared engines (created lazily to keep start-up fast) ----------------------------

    @property
    def parsers(self) -> Any:
        """Document parser runner: isolated worker processes, or inline in tests."""
        if self._parsers is None:
            from emneklar.core.security.isolation import InlineRunner, IsolatedWorkerPool

            self._parsers = IsolatedWorkerPool(size=2) if self.config.parser_isolation else InlineRunner()
        return self._parsers

    @property
    def changes(self) -> ChangeEngine:
        if self._changes is None:
            from emneklar.core.changes.engine import ChangeEngine

            self._changes = ChangeEngine(self)
        return self._changes

    @property
    def ai(self) -> AIService:
        if self._ai is None:
            from emneklar.core.ai.service import AIService

            self._ai = AIService(self)
        return self._ai
