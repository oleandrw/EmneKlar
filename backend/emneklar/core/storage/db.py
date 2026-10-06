"""Database access (SQLite via SQLAlchemy) and migrations (Alembic).

* WAL journal, foreign keys on, busy timeout – safe for the web threads and
  the background jobs of one local process.
* :meth:`Database.migrate` upgrades to the newest schema at start-up. Before
  any pending migration is applied, the database file is copied to
  ``backups/`` with SQLite's online backup API, so a failed upgrade can be
  rolled back by restoring that copy.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from emneklar.config import BACKEND_DIR

log = logging.getLogger(__name__)

MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@dataclass(frozen=True)
class MigrationResult:
    previous: str | None
    current: str | None
    backup_path: Path | None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.url = f"sqlite:///{path.as_posix()}"
        self.engine: Engine = create_engine(self.url, connect_args={"check_same_thread": False, "timeout": 30})
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def current_revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def head_revision(self) -> str | None:
        return ScriptDirectory.from_config(alembic_config(self.url)).get_current_head()

    def backup_to(self, target: Path) -> Path:
        """Consistent copy of the live database using SQLite's online backup API."""
        target.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(self.path))
        try:
            dest = sqlite3.connect(str(target))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        return target

    def migrate(self, backups_dir: Path | None = None) -> MigrationResult:
        previous = self.current_revision()
        head = self.head_revision()
        backup: Path | None = None
        if previous != head:
            if previous is not None and backups_dir is not None and self.path.exists():
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                backup = self.backup_to(backups_dir / "database" / f"for-migrering-{previous}-{stamp}.db")
                log.info("Sikkerhetskopi av databasen før migrering: %s", backup.name)
            cfg = alembic_config(self.url)
            with self.engine.begin() as connection:
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, "head")
            log.info("Database migrert fra %s til %s", previous or "tom", head)
        return MigrationResult(previous=previous, current=head, backup_path=backup)

    def dispose(self) -> None:
        self.engine.dispose()
