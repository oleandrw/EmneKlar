"""scripts/update.py (update.bat): version decision and major guard, checksums, database backup and restore,
release file swap and rollback, the Git safety checks, repository resolution and the rollback orchestration.

No network: GitHub, downloads, subprocesses and the running app are replaced by fakes.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from emneklar.core.updates.version import Version
from tests.script_loader import load_script

update = load_script("update")


# ------------------------------------------------------------------------------------------- helpers


def V(text: str) -> Version:
    version = Version.parse(text)
    assert version is not None
    return version


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_db(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany("INSERT OR REPLACE INTO settings VALUES (?, ?)", rows)
        connection.commit()
    finally:
        connection.close()


def db_state(path: Path) -> tuple[list[str], list[tuple[str, str]]]:
    connection = sqlite3.connect(str(path))
    try:
        tables = sorted(r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))
        rows = sorted(connection.execute("SELECT key, value FROM settings").fetchall())
    finally:
        connection.close()
    return tables, rows


def snapshot(root: Path) -> dict[str, str]:
    return {rel: (root / rel).read_text(encoding="utf-8") for rel in sorted(update.list_files(root))}


def quiet_reporter() -> Any:
    return update.Reporter(None, total_steps=update.TOTAL_STEPS, title="test")


# ------------------------------------------------------------------------------------- version decision


def candidate(version: str, *, newer: bool = True) -> Any:
    return update.Candidate(version=V(version), newer=newer, notes="- Ny funksjon\n- Feilretting")


def never_asked(_candidate: Any) -> bool:
    raise AssertionError("the user must not be asked")


@pytest.mark.parametrize(("current", "target", "newer", "expected"), [
    ("0.1.0", "0.1.1", True, True),     # patch: just do it
    ("1.2.3", "1.3.0", True, True),     # minor on 1.x is not major
    ("0.1.0", "0.1.0", False, False),   # nothing newer
])
def test_decide_without_major_guard(current: str, target: str, newer: bool, expected: bool) -> None:
    assert update.decide(V(current), candidate(target, newer=newer), allow_major=False, from_app=False,
                         confirm=never_asked) is expected


@pytest.mark.parametrize(("current", "target"), [("0.1.0", "0.2.0"), ("1.4.0", "2.0.0")])
def test_major_upgrade_needs_confirmation(current: str, target: str) -> None:
    assert V(current).is_major_upgrade_to(V(target))  # on 0.x a minor bump counts as major
    # --allow-major: no question
    assert update.decide(V(current), candidate(target), allow_major=True, from_app=False, confirm=never_asked)
    # interactive: the user sees the notes and types JA (or not)
    asked: list[Any] = []

    def says_ja(shown: Any) -> bool:
        asked.append(shown)
        return True

    assert update.decide(V(current), candidate(target), allow_major=False, from_app=False, confirm=says_ja)
    assert asked and "Ny funksjon" in asked[0].notes
    with pytest.raises(update.UpdateAborted) as refused:
        update.decide(V(current), candidate(target), allow_major=False, from_app=False, confirm=lambda c: False)
    assert refused.value.exit_code == update.EXIT_ABORTED
    # started from the app without --allow-major: abort, never ask
    with pytest.raises(update.UpdateAborted) as from_app:
        update.decide(V(current), candidate(target), allow_major=False, from_app=True, confirm=never_asked)
    assert "større oppdatering" in str(from_app.value)


def test_confirm_major_requires_ja(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    updater = update.Updater(update.Options(root=tmp_path), data_dir=tmp_path / "data", reporter=quiet_reporter())
    updater.current = V("0.1.0")
    for answer, accepted in (("JA", True), (" ja ", True), ("j", False), ("", False), ("nei", False)):
        monkeypatch.setattr(update, "ask", lambda _prompt, a=answer: a)
        assert updater._confirm_major(candidate("0.2.0")) is accepted


def test_no_console_means_no(monkeypatch: pytest.MonkeyPatch) -> None:
    def eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(update.UpdateAborted):
        update.ask("Skriv JA: ")


def test_select_release_respects_channel_and_ignores_drafts() -> None:
    releases = [
        {"tag_name": "v0.3.0-beta.1", "prerelease": True, "draft": False, "assets": []},
        {"tag_name": "v0.2.1", "prerelease": False, "draft": False, "body": "Rettelser", "assets": [
            {"name": "EmneKlar-0.2.1.zip", "browser_download_url": "https://github.com/a/b/releases/download/x.zip"}]},
        {"tag_name": "v9.9.9", "prerelease": False, "draft": True, "assets": []},
        {"tag_name": "ikke-en-versjon", "prerelease": False, "draft": False},
    ]
    stable = update.select_release(releases, include_prereleases=False)
    assert stable is not None and str(stable.version) == "0.2.1" and stable.notes == "Rettelser"
    assert stable.assets == {"EmneKlar-0.2.1.zip": "https://github.com/a/b/releases/download/x.zip"}
    beta = update.select_release(releases, include_prereleases=True)
    assert beta is not None and str(beta.version) == "0.3.0-beta.1"
    assert update.select_release({"tag_name": "v1.0.0", "draft": False}, include_prereleases=False) is not None
    assert update.select_release([], include_prereleases=True) is None


# ------------------------------------------------------------------------------------------- checksums


def test_checksum_verification_good_and_bad(tmp_path: Path) -> None:
    package = tmp_path / "EmneKlar-0.2.0.zip"
    package.write_bytes(b"innholdet i pakken")
    digest = hashlib.sha256(b"innholdet i pakken").hexdigest()
    assert update.verify_checksum(package, f"{digest}  EmneKlar-0.2.0.zip\n") == digest
    assert update.verify_checksum(package, f"{digest.upper()} *EmneKlar-0.2.0.zip") == digest  # binary marker
    assert update.verify_checksum(package, digest) == digest  # bare digest
    with pytest.raises(update.UpdateError, match="stemmer ikke"):
        update.verify_checksum(package, f"{'0' * 64}  EmneKlar-0.2.0.zip")
    with pytest.raises(update.UpdateError, match="gjelder"):
        update.verify_checksum(package, f"{digest}  EmneKlar-0.1.0.zip")
    with pytest.raises(update.UpdateError, match="format"):
        update.verify_checksum(package, "ikke en sjekksum")
    with pytest.raises(update.UpdateError, match="tom"):
        update.verify_checksum(package, "\n")


def make_release_zip(path: Path, files: dict[str, str], *, prefix: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(prefix + name, text)
    return path


def test_extract_release_finds_the_top_folder_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    good = make_release_zip(tmp_path / "ok.zip", {"VERSION": "0.2.0\n", "backend/x.py": "x"}, prefix="EmneKlar-0.2.0/")
    tree = update.extract_release(good, tmp_path / "staging")
    assert tree.name == "EmneKlar-0.2.0" and (tree / "backend" / "x.py").read_text() == "x"
    for evil in ("../utenfor.txt", "/abs.txt", "C:/windows.txt", "a\\..\\b.txt", "a/../../b.txt"):
        bad = make_release_zip(tmp_path / "bad.zip", {"VERSION": "1", evil: "x"})
        with pytest.raises(update.UpdateError, match="ugyldig sti"):
            update.extract_release(bad, tmp_path / "staging2")
        assert not (tmp_path / "utenfor.txt").exists()
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    with pytest.raises(update.UpdateError, match="gyldig zip"):
        update.extract_release(broken, tmp_path / "staging3")


# ------------------------------------------------------------------------------------- database backup


def test_database_backup_and_restore_after_failed_migration(tmp_path: Path) -> None:
    db = tmp_path / "data" / "database.db"
    make_db(db, [("app", '{"advanced": {}}'), ("update_status", "{}")])
    backup = update.backup_sqlite(db, tmp_path / "data" / "backups" / "database" / "for-oppdatering-0.1.0-x.db")
    before = db_state(db)
    assert db_state(backup) == before

    # A migration that fails half-way: new table, changed rows, and a reader still holding the WAL open.
    connection = sqlite3.connect(str(db))
    connection.execute("CREATE TABLE new_feature (id INTEGER)")
    connection.execute("UPDATE settings SET value = 'ødelagt' WHERE key = 'app'")
    connection.commit()
    connection.close()
    assert db_state(db) != before

    update.restore_database(backup, db, tmp_path / "data" / "backups" / "database")
    assert db_state(db) == before
    assert backup.exists()  # the backup itself is kept


def test_restore_moves_a_damaged_database_aside_instead_of_deleting_it(tmp_path: Path) -> None:
    db = tmp_path / "data" / "database.db"
    make_db(db, [("app", "{}")])
    backup = update.backup_sqlite(db, tmp_path / "backup.db")
    db.write_bytes(b"this is not a database" * 100)
    quarantine = tmp_path / "data" / "backups" / "database"
    update.restore_database(backup, db, quarantine)
    assert db_state(db) == db_state(backup)
    moved = list(quarantine.glob("etter-feilet-oppdatering-*.db"))
    assert len(moved) == 1 and moved[0].read_bytes().startswith(b"this is not a database")


# ----------------------------------------------------------------------------- release file swap


OLD_INSTALL = {
    "VERSION": "0.1.0\n",
    "install.json": '{"type": "release", "version": "0.1.0", "repository": "acme/EmneKlar"}',
    "start.bat": "old start", "update.bat": "old update",
    "backend/pyproject.toml": "old pyproject",
    "backend/emneklar/__init__.py": "old init",
    "backend/emneklar/removed_in_new.py": "stale module",
    "backend/migrations/versions/0001_initial.py": "migration 1",
    "frontend/dist/index.html": "old ui",
    "frontend/dist/assets/old-1234.js": "old bundle",
    "docs/gammel.md": "old doc that the new release dropped",
    "mine-notater.txt": "a file the user put here",
}
NEW_RELEASE = {
    "VERSION": "0.2.0\n",
    "install.json": '{"type": "release", "version": "0.2.0", "repository": "acme/EmneKlar"}',
    "start.bat": "new start", "update.bat": "new update",
    "backend/pyproject.toml": "new pyproject",
    "backend/emneklar/__init__.py": "new init",
    "backend/emneklar/features/ny/modul.py": "new module",
    "backend/migrations/versions/0001_initial.py": "migration 1",
    "backend/migrations/versions/0002_more.py": "migration 2",
    "frontend/dist/index.html": "new ui",
    "frontend/dist/assets/new-5678.js": "new bundle",
}
UNTOUCHABLE = {
    "backend/.venv/pyvenv.cfg": "home = C:\\Python",
    "frontend/node_modules/pkg/index.js": "dependency",
    ".update/previous-0.0.9/VERSION": "0.0.9",
    "backend/emneklar/__pycache__/x.cpython-314.pyc": "bytecode",
}


def make_install(root: Path) -> None:
    for rel, text in {**OLD_INSTALL, **UNTOUCHABLE}.items():
        write(root / rel, text)


def test_release_swap_and_rollback(tmp_path: Path) -> None:
    root = tmp_path / "EmneKlar (test) æøå & co"
    make_install(root)
    new_tree = tmp_path / "staging" / "EmneKlar-0.2.0"
    for rel, text in NEW_RELEASE.items():
        write(new_tree / rel, text)
    before = snapshot(root)
    assert not any(rel.startswith(("backend/.venv", "frontend/node_modules", ".update")) for rel in before)

    record = update.backup_program_files(root, new_tree, root / ".update" / "previous-0.1.0", old_version="0.1.0")
    update.apply_release(record, new_tree)

    after = snapshot(root)
    for rel, text in NEW_RELEASE.items():
        assert after[rel] == text
    # stale code is removed (it would be imported/discovered), other files are left alone
    assert "backend/emneklar/removed_in_new.py" not in after
    assert "frontend/dist/assets/old-1234.js" not in after
    assert after["docs/gammel.md"] == OLD_INSTALL["docs/gammel.md"]
    assert after["mine-notater.txt"] == OLD_INSTALL["mine-notater.txt"]
    for rel, text in UNTOUCHABLE.items():
        assert (root / rel).read_text(encoding="utf-8") == text
    backup = root / ".update" / "previous-0.1.0"
    assert (backup / "backend" / "emneklar" / "removed_in_new.py").read_text() == "stale module"
    manifest = json.loads((backup / ".emneklar-sikkerhetskopi.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.1.0" and "VERSION" in manifest["files"]

    update.rollback_release(record)
    assert snapshot(root) == before
    for rel, text in UNTOUCHABLE.items():
        assert (root / rel).read_text(encoding="utf-8") == text
    assert not (root / "backend" / "emneklar" / "features").exists()  # empty folders of the new release are gone


def test_a_swap_that_fails_half_way_can_be_rolled_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "install"
    make_install(root)
    new_tree = tmp_path / "new"
    for rel, text in NEW_RELEASE.items():
        write(new_tree / rel, text)
    before = snapshot(root)
    record = update.backup_program_files(root, new_tree, root / ".update" / "previous-0.1.0", old_version="0.1.0")
    real_copy = update._copy_file
    copied: list[Path] = []

    def flaky_copy(source: Path, target: Path) -> None:
        if len(copied) == 4:
            raise OSError("disken er full")
        copied.append(target)
        real_copy(source, target)

    monkeypatch.setattr(update, "_copy_file", flaky_copy)
    with pytest.raises(OSError):
        update.apply_release(record, new_tree)
    monkeypatch.setattr(update, "_copy_file", real_copy)
    assert snapshot(root) != before
    update.rollback_release(record)
    assert snapshot(root) == before


# ------------------------------------------------------------------------------ repository resolution


def test_repository_resolution_order(tmp_path: Path) -> None:
    root = tmp_path / "install"
    db = tmp_path / "data" / "database.db"
    write(root / ".git" / "config", '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/fra-git/EmneKlar.git\n'
                                    '\tfetch = +refs/heads/*:refs/remotes/origin/*\n')
    write(root / "install.json", json.dumps({"type": "release", "version": "0.1.0", "repository": "fra-install/EmneKlar"}))
    settings = {"advanced": {"update_repository": "fra-innstillinger/EmneKlar", "update_channel": "prerelease"}}
    make_db(db, [("app", json.dumps(settings))])

    assert update.resolve_repository(root, db)[:2] == ("fra-innstillinger/EmneKlar", "prerelease")
    make_db(db, [("app", json.dumps({"advanced": {"update_repository": None}}))])
    assert update.resolve_repository(root, db)[:2] == ("fra-git/EmneKlar", "stable")
    (root / ".git" / "config").unlink()
    assert update.resolve_repository(root, db)[:2] == ("fra-install/EmneKlar", "stable")
    write(root / "install.json", json.dumps({"type": "release", "repository": "ikke gyldig"}))
    assert update.resolve_repository(root, db)[0] is None
    # invalid values in the settings are ignored, a missing database is fine
    make_db(db, [("app", json.dumps({"advanced": {"update_repository": "../../evil"}}))])
    assert update.resolve_repository(root, db)[0] is None
    assert update.resolve_repository(root, tmp_path / "finnes-ikke.db")[0] is None
    write(root / ".git" / "config", '[remote "origin"]\n\turl = git@github.com:ssh-eier/EmneKlar.git\n')
    assert update.resolve_repository(root, db)[0] == "ssh-eier/EmneKlar"


def test_install_kind_matches_the_update_service(tmp_path: Path) -> None:
    assert update.install_kind(tmp_path) == "source"
    write(tmp_path / "install.json", "{}")
    assert update.install_kind(tmp_path) == "release"
    (tmp_path / ".git").mkdir()
    assert update.install_kind(tmp_path) == "git"


def test_npm_path_problem_is_explained_up_front(tmp_path: Path) -> None:
    # npm's .cmd shims run `SET dp0=%~dp0` unquoted, so "&" in the folder name breaks `npm run build` on Windows.
    problem = update.npm_path_problem(tmp_path / "Mine & dine")
    if os.name == "nt":
        assert problem is not None and "«&»" in problem and "EmneKlar-<versjon>.zip" in problem
    else:
        assert problem is None
    assert update.npm_path_problem(tmp_path / "Høgskolen (HVL) emner") is None


def test_pin_fallback_only_when_pins_do_not_exist() -> None:
    assert update.pins_unavailable("ERROR: No matching distribution found for pydantic-core==2.46.5")
    assert update.pins_unavailable("error: metadata-generation-failed")
    offline = ("WARNING: Retrying ... NewConnectionError('Failed to establish a new connection')\n"
               "ERROR: No matching distribution found for fastapi==0.142.2")
    assert not update.pins_unavailable(offline)
    assert not update.pins_unavailable("ERROR: some other failure")


def test_optional_extras_are_remembered_and_never_fail_the_install(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "EmneKlar"
    (root / "backend").mkdir(parents=True)
    write(root / "backend" / "constraints.txt", "fastapi==0.142.2\n")
    assert update.chosen_extras(root) == []
    update.remember_extra(root, "rag")
    update.remember_extra(root, "rag")
    assert update.chosen_extras(root) == ["rag"]
    write(root / "backend" / ".venv" / update.EXTRAS_FILE, "rag\nunknown\n")
    assert update.chosen_extras(root) == ["rag"]
    commands: list[list[str]] = []

    def fake_run(args: list[Any], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append([str(a) for a in args])
        failing = any(str(a).endswith("[rag]") for a in args)
        return subprocess.CompletedProcess(args, 1 if failing else 0, "", "")

    monkeypatch.setattr(update, "run", fake_run)
    reporter = update.Reporter(None, total_steps=1, title="test")
    update.install_python_dependencies(Path("python"), root, reporter)
    assert commands[0][-1].endswith("backend") and commands[1][-1].endswith("backend[rag]")
    assert "-c" in commands[1]


# ---------------------------------------------------------------------------- the whole update (faked)


class FakeEnvironment:
    """Stands in for GitHub, downloads, subprocesses, the running app and the health check."""

    def __init__(self, root: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch, *, running: bool = True) -> None:
        self.root = root
        self.data_dir = data_dir
        self.commands: list[list[str]] = []
        self.started = 0
        self.stopped = 0
        self.running = running
        self.fail_on: str | None = None
        self.on_migrate: Callable[[], None] | None = None
        self.release: Any = None
        self.files: dict[str, Path] = {}
        self.git: dict[str, str] = {}
        python = update.venv_python_path(root)
        write(python, "")  # validate_install only checks that it exists; commands are faked below
        mp = monkeypatch
        mp.setattr(update, "run", self.run)
        mp.setattr(update, "running_instance", self.running_instance)
        mp.setattr(update, "request_shutdown", self.request_shutdown)
        mp.setattr(update, "wait_until_stopped", lambda origin, watcher, timeout: True)
        mp.setattr(update, "fetch_latest_release", lambda repo, *, channel: self.release)
        mp.setattr(update, "download", self.download)
        mp.setattr(update.Updater, "start_app", lambda updater: self.start_app(updater))
        mp.setattr(update.Updater, "health_check", lambda updater: self.health_check(updater))

    def running_instance(self, run_dir: Path) -> dict[str, Any] | None:
        if not self.running:
            return None
        return {"origin": "http://127.0.0.1:8765", "version": "0.1.0", "pid": None, "control_secret": "hemmelig-123"}

    def request_shutdown(self, info: dict[str, Any]) -> bool:
        assert info["control_secret"] == "hemmelig-123"
        self.stopped += 1
        self.running = False
        return True

    def start_app(self, updater: Any) -> bool:
        self.started += 1
        return True

    def health_check(self, updater: Any) -> None:
        updater.step(9)
        if self.fail_on == "health":
            raise update.UpdateError("Den nye versjonen startet ikke.")
        assert (self.root / "VERSION").read_text().strip() == str(updater.target)

    def download(self, url: str, dest: Path, *, max_bytes: int) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[url.rsplit("/", 1)[-1]].read_bytes())

    def publish(self, version: str, files: dict[str, str]) -> None:
        name = f"EmneKlar-{version}.zip"
        package = make_release_zip(self.data_dir.parent / "github" / name, files, prefix=f"EmneKlar-{version}/")
        checksum = package.with_name(name + ".sha256")
        checksum.write_text(f"{hashlib.sha256(package.read_bytes()).hexdigest()}  {name}\n", encoding="utf-8")
        self.files = {name: package, f"{name}.sha256": checksum}
        base = f"https://github.com/acme/EmneKlar/releases/download/v{version}/"
        self.release = update.Release(version=V(version), tag=f"v{version}", name=f"EmneKlar {version}",
                                      notes="- Nytt", prerelease=False,
                                      assets={name: base + name, f"{name}.sha256": base + name + ".sha256"})

    def run(self, args: Any, *, cwd: Path, reporter: Any = None, capture: bool = False,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        command = [str(a) for a in args]
        self.commands.append(command)
        joined = " ".join(command)
        output = ""
        if "emneklar.manage version" in joined:
            output = (self.root / "VERSION").read_text().strip()
        elif "emneklar.manage migrate" in joined:
            if self.on_migrate is not None:
                self.on_migrate()
            if self.fail_on == "migrate":
                raise update.CommandFailed(command, 1, "alembic.util.exc.CommandError: noe gikk galt")
        elif command[0] == "git":
            output = self.git_command(command[1:])
        return subprocess.CompletedProcess(command, 0, output, "")

    def git_command(self, args: list[str]) -> str:
        key = " ".join(args)
        if key == "pull --ff-only":
            write(self.root / "VERSION", self.git["pulled_version"] + "\n")
            self.git["rev-parse HEAD"] = "bbbbbbb"
            return ""
        if key.startswith("reset --hard"):
            write(self.root / "VERSION", "0.1.0\n")
            self.git["rev-parse HEAD"] = args[-1]
            return ""
        return self.git.get(key, "")

    def count(self, needle: str) -> int:
        return sum(1 for command in self.commands if needle in " ".join(command))


def release_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, running: bool = True) -> tuple[Any, Path, Path]:
    root = tmp_path / "EmneKlar (test) æøå"
    data_dir = tmp_path / "data"
    make_install(root)
    make_db(data_dir / "database.db", [("app", "{}")])
    env = FakeEnvironment(root, data_dir, monkeypatch, running=running)
    return env, root, data_dir


def run_update(root: Path, data_dir: Path, **options: Any) -> int:
    reporter = update.Reporter(data_dir / "logs" / "update.log", total_steps=update.TOTAL_STEPS, title="test")
    try:
        return update.Updater(update.Options(root=root, **options), data_dir=data_dir, reporter=reporter).run()
    finally:
        reporter.close()


def test_successful_release_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch)
    env.publish("0.1.1", NEW_RELEASE | {"VERSION": "0.1.1\n"})
    assert run_update(root, data_dir, from_app=True) == update.EXIT_OK
    assert (root / "VERSION").read_text().strip() == "0.1.1"
    assert env.stopped == 1 and env.started == 1
    assert env.count("pip install") == 1 and env.count("emneklar.manage migrate") == 1
    backups = list((data_dir / "backups" / "database").glob("for-oppdatering-0.1.0-*.db"))
    assert len(backups) == 1
    assert (root / ".update" / "previous-0.1.0" / "VERSION").read_text().strip() == "0.1.0"
    assert not (root / ".update" / "staging").exists() and not (root / ".update" / "download").exists()
    assert not (root / ".update" / "update.lock").exists()
    log = (data_dir / "logs" / "update.log").read_text(encoding="utf-8")
    assert "Steg 10 av 10" in log and "hemmelig-123" not in log


def test_failed_migration_rolls_back_code_dependencies_and_database(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch)
    env.publish("0.1.1", NEW_RELEASE | {"VERSION": "0.1.1\n"})
    db = data_dir / "database.db"
    db_before = db_state(db)
    code_before = snapshot(root)

    def half_migration() -> None:
        connection = sqlite3.connect(str(db))
        connection.execute("CREATE TABLE half_done (id INTEGER)")
        connection.commit()
        connection.close()

    env.on_migrate = half_migration
    env.fail_on = "migrate"
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before
    assert db_state(db) == db_before
    assert env.count("pip install") == 2  # install for 0.1.1, then reinstall for 0.1.0
    assert env.started == 1  # the previous version is started again
    log = (data_dir / "logs" / "update.log").read_text(encoding="utf-8")
    assert "Steg 7 av 10" in log and "[OK] Databasen er hentet tilbake" in log


def test_failed_health_check_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch, running=False)
    env.publish("0.1.1", NEW_RELEASE | {"VERSION": "0.1.1\n"})
    code_before = snapshot(root)
    env.fail_on = "health"
    assert run_update(root, data_dir) == update.EXIT_FAILED
    assert snapshot(root) == code_before
    assert env.started == 1  # rollback tries to start the previous version


def test_tampered_package_is_never_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch)
    env.publish("0.1.1", NEW_RELEASE | {"VERSION": "0.1.1\n"})
    env.files["EmneKlar-0.1.1.zip.sha256"].write_text(f"{'a' * 64}  EmneKlar-0.1.1.zip\n", encoding="utf-8")
    code_before = snapshot(root)
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before
    assert env.count("pip install") == 0 and env.count("migrate") == 0


def test_nothing_newer_restarts_the_app_that_was_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch)
    env.publish("0.1.0", NEW_RELEASE | {"VERSION": "0.1.0\n"})
    code_before = snapshot(root)
    assert run_update(root, data_dir, from_app=True) == update.EXIT_OK
    assert env.stopped == 1 and env.started == 1
    assert snapshot(root) == code_before and env.count("pip install") == 0


def test_major_update_from_the_app_without_allow_major_is_refused(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch)
    env.publish("0.2.0", NEW_RELEASE)
    code_before = snapshot(root)
    assert run_update(root, data_dir, from_app=True) == update.EXIT_ABORTED
    assert snapshot(root) == code_before and env.count("pip install") == 0
    assert env.started == 1  # the app it stopped is started again
    assert run_update(root, data_dir, from_app=True, allow_major=True) == update.EXIT_OK
    assert (root / "VERSION").read_text().strip() == "0.2.0"


def test_interactive_user_can_cancel_while_the_app_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch)
    monkeypatch.setattr(update, "ask", lambda _prompt: "A")
    assert run_update(root, data_dir) == update.EXIT_ABORTED
    assert env.stopped == 0 and env.started == 0 and env.count("pip") == 0


def test_another_update_running_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch)
    write(root / ".update" / "update.lock", json.dumps({"pid": os.getpid()}))
    with pytest.raises(update.UpdateAborted, match="En annen oppdatering"):
        run_update(root, data_dir)
    assert env.stopped == 0
    # a lock left behind by a process that no longer exists is taken over
    write(root / ".update" / "update.lock", json.dumps({"pid": 2**31 - 7}))
    monkeypatch.setattr(update, "process_alive", lambda pid: False)
    env.publish("0.1.0", NEW_RELEASE | {"VERSION": "0.1.0\n"})
    assert run_update(root, data_dir, from_app=True) == update.EXIT_OK
    assert not (root / ".update" / "update.lock").exists()


# ------------------------------------------------------------------------------------- Git installations


def git_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path, Path]:
    env, root, data_dir = release_install(tmp_path, monkeypatch, running=False)
    (root / "install.json").unlink()
    (root / ".git").mkdir()
    env.git.update({
        "status --porcelain --untracked-files=no": "",
        "rev-parse --abbrev-ref HEAD": "main",
        "rev-parse --abbrev-ref --symbolic-full-name @{u}": "origin/main",
        "rev-list --count HEAD..@{u}": "2",
        "show @{u}:VERSION": "0.1.1",
        "log --oneline --no-decorate -n 30 HEAD..@{u}": "abc1234 Rett feil\ndef5678 Ny funksjon",
        "rev-parse HEAD": "aaaaaaa",
        "rev-parse --short HEAD": "bbbbbbb",
        "pulled_version": "0.1.1",
    })
    monkeypatch.setattr(update.shutil, "which", lambda name: name)
    return env, root, data_dir


def test_dirty_git_tree_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = git_install(tmp_path, monkeypatch)
    env.git["status --porcelain --untracked-files=no"] = " M backend/emneklar/main.py\nM  CHANGELOG.md"
    assert run_update(root, data_dir) == update.EXIT_ABORTED
    log = (data_dir / "logs" / "update.log").read_text(encoding="utf-8")
    assert "backend/emneklar/main.py" in log and "ikke er committet" in log
    assert env.count("git pull") == 0 and env.count("git fetch") == 0 and env.count("pip") == 0


def test_git_update_pulls_and_rolls_back_with_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = git_install(tmp_path, monkeypatch)
    env.fail_on = "migrate"
    assert run_update(root, data_dir) == update.EXIT_FAILED
    assert env.count("git pull --ff-only") == 1
    assert env.count("git reset --hard aaaaaaa") == 1  # back to the commit from before the update
    assert (root / "VERSION").read_text().strip() == "0.1.0"
    env.fail_on = None
    npm_runs: list[str] = []

    def fake_build(self: Any) -> None:
        self.step(8)
        npm_runs.append("npm ci && npm run build")

    monkeypatch.setattr(update.Updater, "build_frontend", fake_build)
    assert run_update(root, data_dir) == update.EXIT_OK
    assert (root / "VERSION").read_text().strip() == "0.1.1" and npm_runs


def test_git_major_update_needs_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = git_install(tmp_path, monkeypatch)
    env.git["show @{u}:VERSION"] = "0.2.0"
    monkeypatch.setattr(update, "ask", lambda _prompt: "nei")
    assert run_update(root, data_dir) == update.EXIT_ABORTED
    assert env.count("git pull") == 0


def test_git_without_new_commits_is_up_to_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = git_install(tmp_path, monkeypatch)
    env.git["rev-list --count HEAD..@{u}"] = "0"
    assert run_update(root, data_dir) == update.EXIT_OK
    assert env.count("git pull") == 0 and env.started == 0
