"""scripts/update.py and the bundled Python runtime of an installation (``runtime/``).

An installation made by the installer never runs pip. The runtime the new version needs is fetched when it differs
from the installed one (trusted through the SHA-256 in the release package's install.json), the folder is replaced
as a whole, and it is put back as a whole when a later step fails.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.script_loader import load_script
from tests.test_update_script import (
    NEW_RELEASE,
    make_release_zip,
    release_install,
    run_update,
    snapshot,
    write,
)

update = load_script("update")

TAG = "win-amd64"
OLD_RUNTIME, NEW_RUNTIME = "cp314-00000000000a", "cp314-00000000000b"
INTERPRETER = update.runtime_interpreter(Path()).as_posix()  # python.exe on Windows, bin/python3 elsewhere


def runtime_files(identifier: str, marker: str) -> dict[str, str]:
    return {INTERPRETER: "python", "runtime.json": json.dumps({"id": identifier, "platform": TAG, "python": "3.14.10"}),
            "Lib/site-packages/pakke.py": marker}


def runtime_state(root: Path) -> dict[str, str]:
    folder = root / "runtime"
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*"))
            if p.is_file()}


def bundled_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path, Path]:
    """An installation with its own runtime, as the installer makes it."""
    env, root, data_dir = release_install(tmp_path, monkeypatch, running=False)
    for rel, text in {**runtime_files(OLD_RUNTIME, "old package"), "bare-i-den-gamle.txt": "old only"}.items():
        write(root / "runtime" / rel, text)
    monkeypatch.setattr(update, "platform_tag", lambda: TAG)
    env.downloaded = []
    original = env.download

    def recording_download(url: str, dest: Path, *, max_bytes: int) -> None:
        env.downloaded.append(url.rsplit("/", 1)[-1])
        original(url, dest, max_bytes=max_bytes)

    monkeypatch.setattr(update, "download", recording_download)
    return env, root, data_dir


def publish(env: Any, version: str, identifier: str | None, *, tamper: bool = False, attach: bool = True) -> None:
    """A release whose install.json names the runtime ``identifier`` for this platform (None: no runtime at all)."""
    install: dict[str, Any] = {"type": "release", "version": version, "repository": "acme/EmneKlar"}
    archive: Path | None = None
    name = ""
    if identifier is not None:
        name = update.runtime_asset_name(TAG, identifier)
        archive = make_release_zip(env.data_dir.parent / "github" / name, runtime_files(identifier, "new package"))
        install["runtimes"] = {TAG: {"id": identifier, "python": "3.14.10", "asset": name,
                                     "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                     "size": archive.stat().st_size}}
    env.publish(version, NEW_RELEASE | {"VERSION": f"{version}\n", "install.json": json.dumps(install)})
    if archive is not None and attach:
        if tamper:  # same size, other content: only the checksum can tell
            data = bytearray(archive.read_bytes())
            data[-1] ^= 0xFF
            archive.write_bytes(bytes(data))
        env.files[name] = archive
        env.release.assets[name] = f"https://github.com/acme/EmneKlar/releases/download/v{version}/{name}"


def log_of(data_dir: Path) -> str:
    return (data_dir / "logs" / "update.log").read_text(encoding="utf-8")


def test_an_installation_with_its_own_runtime_uses_it_and_never_pip(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    assert update.has_bundled_runtime(root) and update.installation_python(root) == root / "runtime" / INTERPRETER
    assert update.installed_runtime_id(root) == OLD_RUNTIME
    before = runtime_state(root)
    publish(env, "0.1.1", OLD_RUNTIME)  # the new version needs the runtime that is installed
    assert run_update(root, data_dir, from_app=True) == update.EXIT_OK
    assert (root / "VERSION").read_text().strip() == "0.1.1"
    assert env.count("pip install") == 0 and env.count("emneklar.manage migrate") == 1
    assert runtime_state(root) == before, "the same runtime is not fetched or touched"
    assert env.downloaded == ["EmneKlar-0.1.1.zip.sha256", "EmneKlar-0.1.1.zip"]
    log = log_of(data_dir)
    assert "ingenting å hente" in log and "ingenting å installere" in log and f"Innebygd kjøretid: {OLD_RUNTIME}" in log
    version_check = next(c for c in env.commands if "emneklar.manage version" in " ".join(c))
    assert version_check[0] == str(root / "runtime" / INTERPRETER), "the installation's own Python, not a venv"


def test_a_new_runtime_replaces_the_old_folder_as_a_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    publish(env, "0.1.1", NEW_RUNTIME)
    assert run_update(root, data_dir, from_app=True) == update.EXIT_OK
    assert update.installed_runtime_id(root) == NEW_RUNTIME
    state = runtime_state(root)
    assert state["Lib/site-packages/pakke.py"] == "new package"
    assert "bare-i-den-gamle.txt" not in state, "nothing of the old runtime is left in the folder"
    assert env.downloaded[-1] == update.runtime_asset_name(TAG, NEW_RUNTIME)
    assert env.count("pip install") == 0
    for leftover in ("runtime-new", "runtime-previous", "runtime-failed", "download", "staging"):
        assert not (root / ".update" / leftover).exists(), leftover
    assert "runtime" not in "".join(snapshot(root)), "the runtime is not among the program files that are backed up"
    assert not (root / ".update" / "previous-0.1.0" / "runtime").exists()
    assert f"Kjøretiden er byttet ut ({NEW_RUNTIME}" in log_of(data_dir)


@pytest.mark.parametrize("fail_on", ["migrate", "health"])
def test_a_failure_after_the_swap_puts_the_previous_runtime_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                 fail_on: str) -> None:
    env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    publish(env, "0.1.1", NEW_RUNTIME)
    code_before, runtime_before = snapshot(root), runtime_state(root)
    env.fail_on = fail_on
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before
    assert runtime_state(root) == runtime_before and update.installed_runtime_id(root) == OLD_RUNTIME
    for leftover in ("runtime-new", "runtime-previous", "runtime-failed"):
        assert not (root / ".update" / leftover).exists(), leftover
    assert env.count("pip install") == 0, "nothing is installed with pip – not before, not while rolling back"
    assert "[OK] Den forrige kjøretiden er satt tilbake." in log_of(data_dir)


def test_a_runtime_that_does_not_match_the_release_is_never_installed(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    publish(env, "0.1.1", NEW_RUNTIME, tamper=True)
    code_before, runtime_before = snapshot(root), runtime_state(root)
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before and runtime_state(root) == runtime_before
    assert (root / "VERSION").read_text().strip() == "0.1.0"
    assert not (root / ".update" / "runtime-new").exists()
    assert env.count("emneklar.manage migrate") == 0
    assert "stemmer ikke med sjekksummen i utgivelsen" in log_of(data_dir)


def test_a_release_without_a_runtime_for_this_machine_is_refused(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    publish(env, "0.1.1", None)
    code_before, runtime_before = snapshot(root), runtime_state(root)
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before and runtime_state(root) == runtime_before
    assert "har ingen innebygd kjøretid for denne maskinen (win-amd64)" in log_of(data_dir)

    publish(env, "0.1.2", NEW_RUNTIME, attach=False)  # named in install.json, but the file is not in the release
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before and runtime_state(root) == runtime_before
    assert "mangler kjøretidfilen" in log_of(data_dir)


def test_a_swap_that_fails_half_way_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    publish(env, "0.1.1", NEW_RUNTIME)
    code_before, runtime_before = snapshot(root), runtime_state(root)
    real, calls = update._rename_folder, []

    def second_rename_fails(source: Path, target: Path, *, attempts: int = 20) -> None:
        calls.append(source.name)
        if len(calls) == 2:  # the old runtime is already moved away; the new one cannot be moved in
            raise PermissionError("i bruk")
        real(source, target, attempts=attempts)

    monkeypatch.setattr(update, "_rename_folder", second_rename_fails)
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before and runtime_state(root) == runtime_before
    assert not (root / ".update" / "runtime-previous").exists() and not (root / ".update" / "runtime-new").exists()


def test_the_runtime_is_only_replaced_by_an_interpreter_outside_it(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """update.bat runs the update with a copy of the interpreter. Run straight from runtime\\python.exe, the folder
    is in use and cannot be replaced: the update says so before anything is changed."""
    env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    publish(env, "0.1.1", NEW_RUNTIME)
    code_before, runtime_before = snapshot(root), runtime_state(root)
    monkeypatch.setattr(update.sys, "executable", str(root / "runtime" / INTERPRETER))
    assert run_update(root, data_dir, from_app=True) == update.EXIT_FAILED
    assert snapshot(root) == code_before and runtime_state(root) == runtime_before
    assert "må startes med update.bat" in log_of(data_dir)
    assert update.runtime_asset_name(TAG, NEW_RUNTIME) not in env.downloaded


def test_an_installation_without_a_runtime_keeps_its_venv_and_pip(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    env, root, data_dir = release_install(tmp_path, monkeypatch, running=False)
    monkeypatch.setattr(update, "platform_tag", lambda: TAG)
    assert not update.has_bundled_runtime(root) and update.installation_python(root) == update.venv_python_path(root)
    publish(env, "0.1.1", NEW_RUNTIME)  # the release has a runtime; this installation does not use one
    assert run_update(root, data_dir, from_app=True) == update.EXIT_OK
    assert env.count("pip install") == 1 and not (root / "runtime").exists()
    assert "Programmet starter i et eget vindu" in log_of(data_dir)


def test_the_runtime_folder_is_not_a_program_file_but_a_folder_called_runtime_deeper_down_is(tmp_path: Path) -> None:
    write(tmp_path / "VERSION", "0.1.0")
    write(tmp_path / "runtime" / "python.exe", "x")
    write(tmp_path / "backend" / "emneklar" / "runtime" / "modul.py", "x")
    assert update.list_files(tmp_path) == {"VERSION", "backend/emneklar/runtime/modul.py"}


GOOD = {"id": NEW_RUNTIME, "python": "3.14.10", "asset": f"EmneKlar-runtime-{TAG}-{NEW_RUNTIME}.zip",
        "sha256": "a" * 64, "size": 1000}


def test_runtimes_in_install_json_are_read_strictly() -> None:
    assert update.release_runtimes({"type": "release"}) == {}
    found = update.release_runtimes({"runtimes": {TAG: GOOD}})
    assert found[TAG] == update.RuntimeRef(platform=TAG, id=NEW_RUNTIME, python="3.14.10", asset=GOOD["asset"],
                                           sha256="a" * 64, size=1000)
    assert update.runtime_asset_name(TAG, NEW_RUNTIME) == GOOD["asset"]


@pytest.mark.parametrize("change", [
    {"id": "noe-annet"}, {"id": "../../cp314-00000000000b"}, {"python": "3.14"}, {"asset": "EmneKlar-0.2.0.zip"},
    {"asset": f"../EmneKlar-runtime-{TAG}-{NEW_RUNTIME}.zip"}, {"sha256": "A" * 64}, {"sha256": "abc"}, {"size": 0},
    {"size": "1000"}, {"size": True}, {"size": 10**12}, {"sha256": None},
])
def test_a_malformed_runtime_entry_is_an_error_never_a_silent_no_runtime(change: dict[str, Any]) -> None:
    with pytest.raises(update.UpdateError, match="ugyldig kjøretid"):
        update.release_runtimes({"runtimes": {TAG: {**GOOD, **change}}})


def test_other_malformed_runtime_sections_are_errors_too() -> None:
    with pytest.raises(update.UpdateError):
        update.release_runtimes({"runtimes": [GOOD]})
    with pytest.raises(update.UpdateError):
        update.release_runtimes({"runtimes": {TAG: "EmneKlar-runtime.zip"}})
    with pytest.raises(update.UpdateError):
        update.release_runtimes({"runtimes": {"../win": GOOD}})


def test_an_unpacked_runtime_must_be_the_one_the_release_asked_for(tmp_path: Path) -> None:
    wanted = update.RuntimeRef(platform=TAG, id=NEW_RUNTIME, python="3.14.10", asset=GOOD["asset"], sha256="a" * 64,
                               size=1)
    good = make_release_zip(tmp_path / "good.zip", runtime_files(NEW_RUNTIME, "x"))
    update.extract_runtime(good, tmp_path / "staged", wanted)
    assert (tmp_path / "staged" / INTERPRETER).is_file()
    other = make_release_zip(tmp_path / "other.zip", runtime_files(OLD_RUNTIME, "x"))
    with pytest.raises(update.UpdateError, match="ikke den utgivelsen ber om"):
        update.extract_runtime(other, tmp_path / "staged", wanted)
    files = runtime_files(NEW_RUNTIME, "x")
    del files[INTERPRETER]
    with pytest.raises(update.UpdateError, match="mangler Python"):
        update.extract_runtime(make_release_zip(tmp_path / "empty.zip", files), tmp_path / "staged", wanted)
    with pytest.raises(update.UpdateError, match="ugyldig sti"):
        update.extract_runtime(make_release_zip(tmp_path / "evil.zip", {"../utenfor.txt": "x"}), tmp_path / "staged",
                               wanted)
    assert not (tmp_path / "utenfor.txt").exists()


def test_the_start_and_repair_hints_fit_the_kind_of_installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env, root, data_dir = bundled_install(tmp_path, monkeypatch)
    reporter = update.Reporter(None, total_steps=update.TOTAL_STEPS, title="test")
    bundled = update.Updater(update.Options(root=root), data_dir=data_dir, reporter=reporter)
    assert bundled.bundled and "Start-menyen" in bundled.start_hint() and "start.bat" not in bundled.start_hint()
    assert "installasjonsprogrammet" in bundled.repair_hint() and "setup.bat" not in bundled.repair_hint()
    plain = tmp_path / "zip-installasjon"
    write(update.venv_python_path(plain), "")
    venv = update.Updater(update.Options(root=plain), data_dir=data_dir, reporter=reporter)
    assert not venv.bundled and "start.bat" in venv.start_hint() and "setup.bat" in venv.repair_hint()
