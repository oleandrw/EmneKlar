"""EmneKlar shares nothing with other programs: database, data folder, session cookie, keyring service, port.

Regression for a real collision: an independent implementation of the same specification used
%LOCALAPPDATA%\\EmneKlar\\database.db with Alembic revision "0001" – EmneKlar took that for its own, fully
migrated database and failed at start-up ("no such table: jobs"). It must never use or change such a file.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from emneklar import launcher, manage
from emneklar.config import DEFAULT_PORT, RuntimeConfig, default_data_dir
from emneklar.core.auth.secrets import KEYRING_SERVICE, MemorySecretStore
from emneklar.core.container import AppContainer
from emneklar.core.storage.db import APPLICATION_ID, Database, ForeignDatabaseError, database_owner
from tests.conftest import LAUNCH_TOKEN

pytestmark = pytest.mark.invariant


def other_programs_database(folder: Path) -> Path:
    """A database like the other implementation's: WAL, its own tables, Alembic revision "0001"."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "database.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
    connection.execute("INSERT INTO alembic_version VALUES ('0001')")
    connection.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data JSON)")
    connection.execute("INSERT INTO records VALUES ('a', 'change', '{}')")
    connection.commit()
    connection.close()
    return path


def files_in(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() if p.is_file() else b"<dir>" for p in folder.rglob("*")}


def test_a_database_of_another_program_is_never_used_or_changed(tmp_path: Path) -> None:
    folder = tmp_path / "EmneKlar æøå #1"
    path = other_programs_database(folder)
    before = files_in(folder)
    assert sorted(before) == ["database.db"], "closed cleanly: no -wal/-shm files"
    assert database_owner(path) == "foreign"
    with pytest.raises(ForeignDatabaseError, match="tilhører et annet program"):
        Database(path)
    config = RuntimeConfig(data_dir=folder, frontend_dist=None, secret_backend="memory", parser_isolation=False)
    with pytest.raises(ForeignDatabaseError):
        AppContainer(config, secret_store=MemorySecretStore())
    assert files_in(folder) == before, "no file or folder was created or changed (not even -wal/-shm files)"


def test_the_check_works_while_the_other_program_has_its_database_open(tmp_path: Path) -> None:
    path = other_programs_database(tmp_path / "EmneKlar")
    other = sqlite3.connect(path)  # the other program, running
    try:
        other.execute("INSERT INTO records VALUES ('b', 'change', '{}')")
        other.commit()
        names = sorted(p.name for p in path.parent.iterdir())
        assert database_owner(path) == "foreign"
        assert sorted(p.name for p in path.parent.iterdir()) == names
    finally:
        other.close()


def test_emneklar_marks_its_database_and_recognises_older_ones(tmp_path: Path) -> None:
    path = tmp_path / "database.db"
    assert database_owner(path) == "new"
    db = Database(path)
    db.migrate()
    db.dispose()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        connection.execute("PRAGMA application_id = 0")  # as created before the id was introduced
    assert database_owner(path) == "emneklar", "recognised by its tables"
    db = Database(path)
    db.migrate()
    db.dispose()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID


def test_a_file_that_is_not_a_database_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "database.db"
    path.write_bytes(b"ikke en database")
    assert database_owner(path) == "foreign"


def test_start_and_migrate_refuse_another_programs_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "EmneKlar"
    other_programs_database(folder)
    before = files_in(folder)
    monkeypatch.setenv("EMNEKLAR_DATA_DIR", str(folder))
    for name in ("EMNEKLAR_PORT", "EMNEKLAR_HOST", "EMNEKLAR_DEV"):
        monkeypatch.delenv(name, raising=False)
    assert launcher.main(["--no-browser"]) == 2
    assert "tilhører et annet program" in capsys.readouterr().err
    assert manage.main(["migrate"]) == 1
    assert "tilhører et annet program" in capsys.readouterr().err
    assert files_in(folder) == before


def test_the_session_cookie_is_specific_to_the_port(raw_client: TestClient) -> None:
    launch = raw_client.get(f"/auth/launch?token={LAUNCH_TOKEN}", follow_redirects=False)
    assert launch.headers["set-cookie"].startswith(f"emneklar_session_{DEFAULT_PORT}=")
    value = launch.cookies[f"emneklar_session_{DEFAULT_PORT}"]
    raw_client.cookies.clear()
    # Another local program's cookie on 127.0.0.1 (cookies are not separated by port) is not ours.
    other = raw_client.get("/api/session", headers={"Cookie": f"emneklar_session={value}"})
    assert other.status_code == 401
    ours = raw_client.get("/api/session", headers={"Cookie": f"emneklar_session_{DEFAULT_PORT}={value}"})
    assert ours.status_code == 200


def test_defaults_differ_from_the_other_implementation() -> None:
    assert default_data_dir().name.lower() != "emneklar"
    assert KEYRING_SERVICE != "EmneKlar"
    assert DEFAULT_PORT != 8765
