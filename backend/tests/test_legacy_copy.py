"""The one-time copy of the data from before EmneKlar got its final name (core/storage/legacy.py).

The old folder («EmneKlar-Claude») is copied into the new one («EmneKlar») the first time the new names are used,
and the secrets follow. The old folder and the old entries are never changed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from emneklar import launcher, manage
from emneklar.config import ConfigError, RuntimeConfig
from emneklar.core.auth.secrets import CANVAS_TOKEN, MemorySecretStore, ai_key_name
from emneklar.core.container import AppContainer
from emneklar.core.storage import legacy
from emneklar.core.storage.db import Database, database_owner
from tests.test_coexistence import files_in, other_programs_database

pytestmark = pytest.mark.invariant


def sql(path: Path, statement: str) -> list[tuple[object, ...]]:
    """Run one statement and close the connection again (an open connection keeps -wal/-shm files alive)."""
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(statement).fetchall()
        connection.commit()
        return rows
    finally:
        connection.close()


def old_installation(folder: Path) -> Path:
    """A data folder as an earlier version left it: a migrated database with a setting, and the usual sub-folders."""
    folder.mkdir(parents=True)
    db = Database(folder / "database.db")
    db.migrate()
    db.dispose()
    sql(folder / "database.db", "INSERT INTO settings (key, value, updated_at) VALUES "
                                "('gammel', '{\"a\": 1}', '2026-11-01 10:00:00')")
    for rel, text in {"backups/objects/a.json": "{}", "reports/rapport æøå.html": "<p>hei</p>", "logs/emneklar.log": "linje",
                      "rag/course-104.sqlite": "indeks", "illustrations/104/bilde.png": "png",
                      "run/instance.json": "{}", "tmp/x.tmp": "x", "cache/c.bin": "c", "models/stor.bin": "modell"}.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


def test_the_old_folder_is_copied_once_and_never_changed(tmp_path: Path) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    new = tmp_path / "EmneKlar"
    before = files_in(old)
    assert sorted(name for name in before if name.startswith("database")) == ["database.db"], "closed cleanly"

    result = legacy.copy_legacy_data(new, old)
    assert result is not None and result.entries[-1] == "database.db", "the database is copied last"
    assert files_in(old) == before, "nothing in the old folder was changed – not even -wal/-shm files"
    assert (new / "reports" / "rapport æøå.html").read_text(encoding="utf-8") == "<p>hei</p>"
    assert (new / "backups" / "objects" / "a.json").is_file() and (new / "rag" / "course-104.sqlite").is_file()
    assert (new / "illustrations" / "104" / "bilde.png").is_file() and (new / "logs" / "emneklar.log").is_file()
    for skipped in ("run", "tmp", "cache", "models"):
        assert not (new / skipped).exists(), f"{skipped} is not copied"
    assert database_owner(new / "database.db") == "emneklar"
    assert sql(new / "database.db", "SELECT value FROM settings WHERE key = 'gammel'") == [('{"a": 1}',)]
    marker = json.loads((new / legacy.MARKER).read_text(encoding="utf-8"))
    assert marker["source"] == str(old) and marker["secrets_copied"] is False and "database.db" in marker["entries"]
    assert not list(new.glob(f"*{legacy.PARTIAL}"))

    # Once only: later changes in the old folder never reach the new one, and nothing is copied twice.
    (old / "reports" / "ny.html").write_text("senere", encoding="utf-8")
    assert legacy.copy_legacy_data(new, old) is None
    assert not (new / "reports" / "ny.html").exists()


def test_nothing_is_copied_into_a_folder_that_already_has_a_database(tmp_path: Path) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    ours = tmp_path / "ny"
    ours.mkdir()
    db = Database(ours / "database.db")
    db.migrate()
    db.dispose()
    before = files_in(ours)
    assert legacy.copy_legacy_data(ours, old) is None and files_in(ours) == before

    # Another program's database in the new folder: nothing is copied, and the start is refused as before.
    theirs = tmp_path / "EmneKlar"
    other_programs_database(theirs)
    before = files_in(theirs)
    assert legacy.copy_legacy_data(theirs, old) is None and files_in(theirs) == before


def test_no_old_folder_or_an_old_folder_that_is_not_emneklars_means_no_copy(tmp_path: Path) -> None:
    new = tmp_path / "EmneKlar"
    assert legacy.copy_legacy_data(new, tmp_path / "EmneKlar-Claude") is None and not new.exists()
    other_programs_database(tmp_path / "fremmed")
    assert legacy.copy_legacy_data(new, tmp_path / "fremmed") is None and not new.exists()


def test_files_written_by_the_new_version_are_kept_and_an_interrupted_copy_is_finished(tmp_path: Path) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    new = tmp_path / "EmneKlar"
    (new / "logs").mkdir(parents=True)
    (new / "logs" / "setup.log").write_text("installert", encoding="utf-8")  # e.g. written by the installer
    (new / f"reports{legacy.PARTIAL}").mkdir()  # left behind by a copy that was interrupted
    (new / f"reports{legacy.PARTIAL}" / "halv.html").write_text("halv", encoding="utf-8")
    result = legacy.copy_legacy_data(new, old)
    assert result is not None and "logs" not in result.entries and "reports" in result.entries
    assert sorted(p.name for p in (new / "logs").iterdir()) == ["setup.log"], "an existing folder is never overwritten"
    assert sorted(p.name for p in (new / "reports").iterdir()) == ["rapport æøå.html"]
    assert not list(new.glob(f"*{legacy.PARTIAL}"))


def test_too_little_disk_space_stops_the_start_instead_of_starting_empty(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    new = tmp_path / "EmneKlar"
    monkeypatch.setattr(legacy, "FREE_SPACE_MARGIN", 10**18)
    with pytest.raises(ConfigError, match="for lite ledig diskplass"):
        legacy.copy_legacy_data(new, old)
    assert not new.exists()


def test_only_the_default_location_is_copied_into(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    monkeypatch.setattr(legacy, "legacy_data_dir", lambda: old)
    config = RuntimeConfig(data_dir=tmp_path / "EmneKlar", frontend_dist=None, secret_backend="memory",
                           parser_isolation=False)
    # EMNEKLAR_DATA_DIR is set (as in every test): the user chose the folder, nothing is copied.
    assert legacy.prepare_data_dir(config) is None and not config.data_dir.exists()
    # An installation with a data folder of its own (emneklar.local.json): nothing is copied either.
    monkeypatch.delenv("EMNEKLAR_DATA_DIR")
    monkeypatch.setattr(legacy, "uses_standard_data_dir", lambda: False)
    assert legacy.prepare_data_dir(config) is None and not config.data_dir.exists()
    # The standard folder: the old data is copied.
    monkeypatch.setattr(legacy, "uses_standard_data_dir", lambda: True)
    assert legacy.prepare_data_dir(config) is not None and (config.data_dir / "database.db").is_file()


def test_start_and_migrate_copy_before_they_use_the_data_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    new = tmp_path / "EmneKlar"
    monkeypatch.setattr(legacy, "legacy_data_dir", lambda: old)
    monkeypatch.setattr(legacy, "uses_standard_data_dir", lambda: True)  # as when started from the shortcut
    monkeypatch.setattr(manage, "default_data_dir", lambda: new)
    monkeypatch.setattr("emneklar.config.default_data_dir", lambda: new)
    monkeypatch.delenv("EMNEKLAR_DATA_DIR")
    for name in ("EMNEKLAR_PORT", "EMNEKLAR_HOST", "EMNEKLAR_DEV"):
        monkeypatch.delenv(name, raising=False)
    assert manage.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "er kopiert til" in out and "ikke endret" in out and "allerede oppdatert" in out
    assert sql(new / "database.db", "SELECT count(*) FROM settings WHERE key = 'gammel'") == [(1,)]

    # The launcher does the same before it creates anything: a full disk is reported, not hidden behind an empty start.
    another = tmp_path / "EmneKlar-2"
    monkeypatch.setattr("emneklar.config.default_data_dir", lambda: another)
    monkeypatch.setattr(legacy, "FREE_SPACE_MARGIN", 10**18)
    assert launcher.main(["--no-browser"]) == 2
    assert "for lite ledig diskplass" in capsys.readouterr().err and not another.exists()


def test_secrets_follow_once_and_a_secret_deleted_later_does_not_come_back(tmp_path: Path) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    config = RuntimeConfig(data_dir=tmp_path / "EmneKlar", frontend_dist=None, secret_backend="memory",
                           parser_isolation=False)
    names = [CANVAS_TOKEN, ai_key_name("openai"), ai_key_name("anthropic")]
    old_store, new_store = MemorySecretStore(), MemorySecretStore()
    old_store.set(CANVAS_TOKEN, "gammelt-token-1234567890")
    old_store.set(ai_key_name("openai"), "sk-gammel-0987654321")
    new_store.set(ai_key_name("openai"), "sk-ny-1122334455")  # already entered under the new name: kept

    # Without a copy of the data there is nothing to bring along.
    assert legacy.finish_legacy_copy(config, new_store, names, old_store) == []
    assert not new_store.has(CANVAS_TOKEN)

    assert legacy.copy_legacy_data(config.data_dir, old) is not None
    assert legacy.finish_legacy_copy(config, new_store, names, old_store) == [CANVAS_TOKEN]
    assert new_store.get(CANVAS_TOKEN) == "gammelt-token-1234567890"
    assert new_store.get(ai_key_name("openai")) == "sk-ny-1122334455"
    assert old_store.get(CANVAS_TOKEN) == "gammelt-token-1234567890", "the old entries are left alone"
    marker = json.loads((config.data_dir / legacy.MARKER).read_text(encoding="utf-8"))
    assert marker["secrets_copied"] is True and marker["secrets"] == [CANVAS_TOKEN]
    assert "gammelt-token" not in json.dumps(marker), "names only – never a value"

    new_store.delete(CANVAS_TOKEN)
    assert legacy.finish_legacy_copy(config, new_store, names, old_store) == []
    assert not new_store.has(CANVAS_TOKEN)


def test_the_app_starts_on_the_copied_data(tmp_path: Path) -> None:
    old = old_installation(tmp_path / "EmneKlar-Claude")
    config = RuntimeConfig(data_dir=tmp_path / "EmneKlar", frontend_dist=None, secret_backend="memory",
                           parser_isolation=False)
    assert legacy.copy_legacy_data(config.data_dir, old) is not None
    container = AppContainer(config, secret_store=MemorySecretStore())
    try:
        container.startup()
        assert sql(config.db_path, "SELECT count(*) FROM settings WHERE key = 'gammel'") == [(1,)]
        # The memory store (tests) has no old service to read from: the copy of secrets is left for the keyring.
        assert json.loads((config.data_dir / legacy.MARKER).read_text(encoding="utf-8"))["secrets_copied"] is False
    finally:
        container.db.dispose()
