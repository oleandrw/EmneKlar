"""Database access (SQLite via SQLAlchemy) and migrations (Alembic).

* WAL journal, foreign keys on, busy timeout – safe for the web threads and
  the background jobs of one local process.
* :meth:`Database.migrate` upgrades to the newest schema at start-up. Before
  any pending migration is applied, the database file is copied to
  ``backups/`` with SQLite's online backup API, so a failed upgrade can be
  rolled back by restoring that copy.
* EmneKlar only ever opens its *own* database. The file is marked with
  :data:`APPLICATION_ID` (``PRAGMA application_id``), and before anything is
  opened for writing, :func:`database_owner` checks the file read-only. A
  database that belongs to another program is never migrated or changed –
  not even by the journal-mode pragma below.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from emneklar.config import BACKEND_DIR, ConfigError

log = logging.getLogger(__name__)

MIGRATIONS_DIR = BACKEND_DIR / "migrations"
#: Written into every EmneKlar database file (``PRAGMA application_id``): the bytes "EmKl".
APPLICATION_ID = 0x456D4B6C
#: Tables every EmneKlar database has. Recognises databases created before the application id was written.
CORE_TABLES = frozenset({"alembic_version", "settings", "jobs", "staged_changes", "change_log", "backups"})


class ForeignDatabaseError(ConfigError):
    """The database file belongs to another program. EmneKlar does not open it for writing."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"Databasen {path} tilhører et annet program, ikke EmneKlar. EmneKlar har ikke endret den og bruker den "
            "ikke. Et annet program bruker denne datamappen: flytt eller fjern det programmets mappe, eller gi "
            "EmneKlar en egen datamappe med miljøvariabelen EMNEKLAR_DATA_DIR.")
        self.path = path


def database_owner(path: Path) -> Literal["new", "emneklar", "foreign"]:
    """Who a database file belongs to – decided before EmneKlar opens it, without writing anything.

    The application id is read straight from the 100-byte SQLite header. Only an unmarked file needs a
    look at its tables (see :func:`_table_names`).
    """
    try:
        if path.stat().st_size == 0:
            return "new"
    except FileNotFoundError:
        return "new"
    with path.open("rb") as file:
        header = file.read(100)
    if len(header) < 100 or not header.startswith(b"SQLite format 3\x00"):
        return "foreign"  # not an SQLite database at all
    application_id = int.from_bytes(header[68:72], "big")
    if application_id == APPLICATION_ID:
        return "emneklar"
    if application_id != 0:
        return "foreign"
    tables = _table_names(path, wal=2 in header[18:20])
    if not tables:
        return "new"
    return "emneklar" if CORE_TABLES.issubset(tables) else "foreign"  # older EmneKlar databases have no id yet


def _table_names(path: Path, *, wal: bool) -> set[str]:
    # A read-only connection to a WAL database creates its -wal/-shm files when they are missing. Missing files
    # mean the database is closed and complete in the main file, so it is read as immutable instead.
    open_elsewhere = any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm"))
    mode = "ro&immutable=1" if wal and not open_elsewhere else "ro"
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode={mode}", uri=True, timeout=30)
    try:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        connection.close()


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
        if database_owner(path) == "foreign":
            raise ForeignDatabaseError(path)
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
        with self.engine.begin() as connection:  # ownership was checked when this object was created
            if connection.exec_driver_sql("PRAGMA application_id").scalar() != APPLICATION_ID:
                connection.exec_driver_sql(f"PRAGMA application_id = {APPLICATION_ID}")
        return MigrationResult(previous=previous, current=head, backup_path=backup)

    def dispose(self) -> None:
        self.engine.dispose()
