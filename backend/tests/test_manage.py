"""python -m emneklar.manage: version, migrate, backup-db, health and stop (against a fake local instance)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from emneklar import __version__, manage
from emneklar.core.storage.db import Database


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "EmneKlar-data æøå"
    monkeypatch.setenv("EMNEKLAR_DATA_DIR", str(path))
    for name in ("EMNEKLAR_PORT", "EMNEKLAR_HOST", "EMNEKLAR_DEV"):
        monkeypatch.delenv(name, raising=False)
    return path


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert manage.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_usage_errors_exit_with_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert manage.main([]) == 1
    with pytest.raises(SystemExit) as exc:
        manage.main(["finnes-ikke"])
    assert exc.value.code == 1


def test_migrate_creates_and_then_keeps_the_database(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert manage.main(["migrate"]) == 0
    first = capsys.readouterr().out
    db = Database(data_dir / "database.db")
    try:
        head = db.head_revision()
        assert db.current_revision() == head
    finally:
        db.dispose()
    assert f"til {head}" in first
    assert manage.main(["migrate"]) == 0
    assert "allerede oppdatert" in capsys.readouterr().out
    log = (data_dir / "logs" / "emneklar.log").read_text(encoding="utf-8")
    assert "Database migrert" in log


def test_migrate_refuses_while_emneklar_runs(data_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(manage, "running_instance", lambda run_dir: {"origin": "http://127.0.0.1:8765"})
    assert manage.main(["migrate"]) == 1
    assert "EmneKlar kjører" in capsys.readouterr().err
    assert not (data_dir / "database.db").exists()


def test_backup_db_makes_a_consistent_copy(data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert manage.main(["backup-db", str(tmp_path / "kopi.db")]) == 1  # no database yet
    assert manage.main(["migrate"]) == 0
    target = tmp_path / "sikkerhetskopier æøå" / "kopi.db"
    assert manage.main(["backup-db", str(target)]) == 0
    connection = sqlite3.connect(str(target))
    try:
        assert connection.execute("SELECT count(*) FROM alembic_version").fetchone() == (1,)
    finally:
        connection.close()
    capsys.readouterr()
    assert manage.main(["backup-db", str(target)]) == 1  # never overwrites
    assert "finnes allerede" in capsys.readouterr().err
    folder = tmp_path / "mappe"
    folder.mkdir()
    assert manage.main(["backup-db", str(folder)]) == 0
    assert len(list(folder.glob("emneklar-database-*.db"))) == 1
    assert manage.main(["backup-db", str(data_dir / "database.db")]) == 1  # not onto itself


@pytest.mark.parametrize("origin", ["https://127.0.0.1:8765", "http://example.com:8765", "http://127.0.0.1",
                                    "http://127.0.0.1:8765/api", "http://user:pw@127.0.0.1:8765", "http://10.0.0.1:80"])
def test_only_local_origins_are_accepted(origin: str) -> None:
    with pytest.raises(ValueError):
        manage.check_local_origin(origin)


def test_local_origins_are_normalised() -> None:
    assert manage.check_local_origin("http://127.0.0.1:8765/") == "http://127.0.0.1:8765"
    assert manage.check_local_origin("http://localhost:9000") == "http://localhost:9000"
    assert manage.check_local_origin("http://[::1]:8765") == "http://[::1]:8765"


# -- health and stop against a fake EmneKlar ------------------------------------------------------

SECRET = "kontroll-hemmelighet-0123456789"


class FakeInstance:
    def __init__(self) -> None:
        self.shutdown_headers: list[str] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/api/health":
                    self._json(200, {"status": "ok", "app": "EmneKlar", "version": "9.8.7"})
                else:
                    self._json(404, {})

            def do_POST(self) -> None:
                supplied = self.headers.get("X-EmneKlar-Control", "")
                owner.shutdown_headers.append(supplied)
                if self.path != "/control/shutdown" or supplied != SECRET:
                    self._json(403, {"error": "control_rejected"})
                    return
                self._json(200, {"ok": True})
                threading.Thread(target=owner.server.shutdown, daemon=True).start()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def instance(data_dir: Path) -> Iterator[FakeInstance]:
    fake = FakeInstance()
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "instance.json").write_text(json.dumps({
        "pid": None, "port": 0, "origin": fake.origin, "version": "9.8.7", "control_secret": SECRET}), encoding="utf-8")
    try:
        yield fake
    finally:
        fake.close()


def test_health_and_stop(instance: FakeInstance, capsys: pytest.CaptureFixture[str]) -> None:
    assert manage.main(["health"]) == 0
    assert manage.main(["health", "--origin", instance.origin]) == 0
    assert "9.8.7" in capsys.readouterr().out
    assert manage.main(["stop", "--timeout", "10"]) == 0
    output = capsys.readouterr()
    assert "avsluttet" in output.out
    assert instance.shutdown_headers == [SECRET]
    assert SECRET not in output.out + output.err  # the control secret is never printed
    assert manage.main(["health"]) == 1
    assert manage.main(["stop"]) == 0  # nothing to stop is not an error
    assert "kjører ikke" in capsys.readouterr().out


def test_stop_reports_a_refused_shutdown(instance: FakeInstance, data_dir: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    info = json.loads((data_dir / "run" / "instance.json").read_text(encoding="utf-8"))
    info["control_secret"] = "feil-hemmelighet-0123456789"
    (data_dir / "run" / "instance.json").write_text(json.dumps(info), encoding="utf-8")
    assert manage.main(["stop", "--timeout", "2"]) == 1
    assert "avviste" in capsys.readouterr().err
    assert manage.main(["health"]) == 0  # still running


def test_instance_file_pointing_elsewhere_is_ignored(data_dir: Path) -> None:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "instance.json").write_text(json.dumps({"origin": "https://example.com:443", "control_secret": "x"}),
                                           encoding="utf-8")
    assert manage.read_instance(run_dir) is None
    assert manage.running_instance(run_dir) is None
    assert manage.stop_instance(run_dir) == "not_running"


def test_health_reports_when_nothing_runs(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert manage.main(["health"]) == 1
    assert "kjører ikke" in capsys.readouterr().err


def test_process_watcher_follows_a_real_process() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with manage.ProcessWatcher(process.pid) as watcher:
            assert watcher.exited() is False
            assert manage.process_alive(process.pid) is True
            process.kill()
            process.wait(timeout=30)
            assert watcher.wait(10) is True
    finally:
        if process.poll() is None:
            process.kill()
    assert manage.ProcessWatcher(None).wait(0) is None
    assert manage.ProcessWatcher(True).pid is None
