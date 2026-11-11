"""The one-time copy of the data from before EmneKlar got its final name.

Until the first public release the data folder and the credential-store service were called «EmneKlar-Claude».
The first time a version with the final names starts, the old data folder is *copied* into the new one, and the
Canvas token and the AI keys are copied to the new service name. Nothing in the old folder and none of the old
entries is moved, changed or deleted: they stay as a reserve until the user removes them.

* Only the standard location is handled. With ``EMNEKLAR_DATA_DIR`` the user has chosen the folder, and an
  installation with a data folder of its own (the test build of the installer) never touches the user's real data:
  nothing is copied.
* The copy happens only into a folder without a database. A folder that already holds a database – EmneKlar's own, or
  another program's (see ``core/storage/db.py``) – is never filled from the old one.
* The database is copied last, with SQLite's backup API from a read-only connection. A copy that was interrupted
  therefore leaves no database behind and is simply done again at the next start.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from emneklar.config import ConfigError, RuntimeConfig, legacy_data_dir, uses_standard_data_dir
from emneklar.core.auth.secrets import LEGACY_KEYRING_SERVICE, KeyringSecretStore, SecretStore
from emneklar.core.storage.db import database_owner

log = logging.getLogger(__name__)

#: Written into the new folder when the copy is complete. Its presence means: never copy again.
MARKER = "kopiert-fra-EmneKlar-Claude.json"
#: Not copied: the files of a running instance, scratch files, caches, and downloaded model files (several GB that
#: can be downloaded again and are not part of an installation).
SKIPPED = frozenset({"run", "tmp", "cache", "models"})
DATABASE = "database.db"
DATABASE_FILES = frozenset({DATABASE, f"{DATABASE}-wal", f"{DATABASE}-shm", f"{DATABASE}-journal"})
PARTIAL = ".kopieres"
FREE_SPACE_MARGIN = 200 * 1024 * 1024


@dataclass(frozen=True)
class LegacyCopy:
    source: Path
    target: Path
    entries: tuple[str, ...]


def copy_pending(target: Path, source: Path) -> bool:
    """True when the new folder has no database and no earlier copy, and the old folder has an EmneKlar database."""
    if (target / MARKER).exists() or database_owner(target / DATABASE) != "new":
        return False
    return database_owner(source / DATABASE) == "emneklar"


def _entries(source: Path) -> list[Path]:
    return sorted((entry for entry in source.iterdir() if entry.name not in SKIPPED and entry.name not in DATABASE_FILES
                   and not entry.name.endswith(PARTIAL) and not entry.is_symlink()), key=lambda entry: entry.name)


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file() and not file.is_symlink())


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _copy_database(source: Path, target: Path) -> None:
    """A consistent copy that never writes to the old folder: a closed WAL database is read as immutable, so SQLite
    creates no -wal/-shm files next to it; a database that is open elsewhere is read through its existing files."""
    open_elsewhere = any(source.with_name(source.name + suffix).exists() for suffix in ("-wal", "-shm"))
    mode = "ro" if open_elsewhere else "ro&immutable=1"
    partial = target.with_name(target.name + PARTIAL)
    partial.unlink(missing_ok=True)
    reader = sqlite3.connect(f"{source.resolve().as_uri()}?mode={mode}", uri=True, timeout=30)
    try:
        writer = sqlite3.connect(str(partial))
        try:
            reader.backup(writer)
            row = writer.execute("PRAGMA quick_check").fetchone()
            if row is None or row[0] != "ok":
                raise sqlite3.DatabaseError("kopien besto ikke integritetskontrollen")
        finally:
            writer.close()
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        reader.close()
    os.replace(partial, target)


def copy_legacy_data(target: Path, source: Path) -> LegacyCopy | None:
    """Copy the old data folder into the new one if that is still to be done. Returns what was copied, else None."""
    if not copy_pending(target, source):
        return None
    entries = _entries(source)
    needed = sum(_size(entry) for entry in entries) + (source / DATABASE).stat().st_size
    probe = target
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if free < needed + FREE_SPACE_MARGIN:
        raise ConfigError(
            f"Det er for lite ledig diskplass til å kopiere dataene dine fra {source} til {target} "
            f"({needed // 2**20} MB trengs, {free // 2**20} MB er ledig). Ingenting er endret. Frigjør plass og start "
            "EmneKlar på nytt.")
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    try:
        for entry in entries:
            destination = target / entry.name
            if destination.exists():
                continue  # already there (an earlier, interrupted copy – or written by this version): never overwritten
            partial = target / (entry.name + PARTIAL)
            _remove(partial)
            if entry.is_dir():
                shutil.copytree(entry, partial)
            else:
                shutil.copy2(entry, partial)
            os.replace(partial, destination)
            copied.append(entry.name)
        _copy_database(source / DATABASE, target / DATABASE)  # last: a database means the copy is complete
    except (OSError, sqlite3.Error) as exc:
        raise ConfigError(f"Klarte ikke å kopiere dataene dine fra {source} til {target} ({exc}). Den gamle mappen er "
                          "ikke endret. Start EmneKlar på nytt for å prøve igjen.") from exc
    copied.append(DATABASE)
    _write_marker(target, {"source": str(source), "copied_at": datetime.now(UTC).isoformat(timespec="seconds"),
                           "entries": copied, "secrets_copied": False})
    return LegacyCopy(source=source, target=target, entries=tuple(copied))


def _read_marker(target: Path) -> dict[str, object] | None:
    try:
        data = json.loads((target / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_marker(target: Path, data: dict[str, object]) -> None:
    partial = target / (MARKER + PARTIAL)
    partial.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(partial, target / MARKER)


def prepare_data_dir(config: RuntimeConfig, *, custom_location: bool | None = None) -> LegacyCopy | None:
    """Called before the data folder is used for the first time (start and ``manage migrate``)."""
    if custom_location is None:
        custom_location = not uses_standard_data_dir()
    if custom_location:
        return None
    return copy_legacy_data(config.data_dir, legacy_data_dir())


# -- secrets ------------------------------------------------------------------------------------------------------


def copy_secrets(old: SecretStore, new: SecretStore, names: Iterable[str]) -> list[str]:
    """Copy each secret that exists in ``old`` and not in ``new``. Returns the names that were copied (never values)."""
    copied: list[str] = []
    for name in names:
        if new.has(name):
            continue
        value = old.get(name)
        if value:
            new.set(name, value)
            copied.append(name)
    return copied


def finish_legacy_copy(config: RuntimeConfig, secrets: SecretStore, names: Iterable[str],
                       old_store: SecretStore | None = None) -> list[str]:
    """After the data was copied: copy the Canvas token and the AI keys from the old service name, once.

    A secret the user later deletes under the new name is therefore not brought back from the old entries.
    """
    marker = _read_marker(config.data_dir)
    if marker is None or marker.get("secrets_copied"):
        return []
    if old_store is None:
        if config.secret_backend != "keyring":
            return []
        old_store = KeyringSecretStore(LEGACY_KEYRING_SERVICE)
    copied = copy_secrets(old_store, secrets, names)
    _write_marker(config.data_dir, {**marker, "secrets_copied": True, "secrets": copied})
    if copied:
        log.info("Hemmeligheter kopiert fra %s: %s", LEGACY_KEYRING_SERVICE, ", ".join(copied))
    return copied
