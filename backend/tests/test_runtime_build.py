"""scripts/build_runtime.py: the bundled Python runtime is built from pinned, hashed inputs.

The build itself (downloads from python.org and PyPI) runs in the release workflow and is verified there by
installing and starting the result. These tests cover what must hold in the repository: the lock agrees with
backend/constraints.txt, every file has a hash, no local-model package is in it, and the id follows the inputs.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from emneklar.config import REPO_DIR
from tests.script_loader import load_script

update = load_script("update")
build_runtime = load_script("build_runtime")

PLATFORM = "win-amd64"
LOCAL_MODEL_PACKAGES = {"torch", "sentence-transformers", "transformers", "faster-whisper", "ctranslate2",
                        "tokenizers", "huggingface-hub", "onnxruntime"}


def constraints() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (REPO_DIR / "backend" / "constraints.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==(\S+)", line.strip())
        if match:
            pins[build_runtime.canonical(match.group(1))] = match.group(2)
    return pins


def test_the_spec_names_an_exact_python_from_python_org_with_its_hash() -> None:
    spec = build_runtime.load_spec(REPO_DIR, PLATFORM)
    assert re.fullmatch(r"3\.\d+\.\d+", spec.python)
    assert spec.python_url == (f"https://www.python.org/ftp/python/{spec.python}/"
                               f"python-{spec.python}-embed-amd64.zip")
    assert re.fullmatch(r"[0-9a-f]{64}", spec.python_sha256)
    assert spec.lock == REPO_DIR / "packaging" / f"runtime-{PLATFORM}.txt" and spec.lock.is_file()
    major, minor = spec.python.split(".")[:2]
    assert spec.tag == f"cp{major}{minor}" and spec.pth_name == f"python{major}{minor}._pth"
    with pytest.raises(build_runtime.RuntimeBuildError, match="ingen kjøretid for «plan9-mips»"):
        build_runtime.load_spec(REPO_DIR, "plan9-mips")


def test_the_lock_agrees_with_the_constraints_and_every_file_has_a_hash() -> None:
    spec = build_runtime.load_spec(REPO_DIR, PLATFORM)
    locked = build_runtime.read_lock(spec)
    pinned = constraints()
    different = {name: (version, pinned.get(name)) for name, version in locked.items() if pinned.get(name) != version}
    assert not different, ("the runtime lock and backend/constraints.txt disagree – run "
                           f"«python scripts/build_runtime.py lock»: {different}")
    text = spec.lock.read_text(encoding="utf-8")
    assert text.count("--hash=sha256:") == len(locked), "exactly one hashed file per package"
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}\b", text)) == len(locked)
    assert not re.search(r"\.tar\.gz|\.zip\b", text), "only ready-built wheels – nothing is built on the build machine"
    for wheel in re.findall(r"#\s+(\S+\.whl)", text):
        assert wheel.endswith(("-none-any.whl", "-win_amd64.whl")), wheel


def test_every_dependency_of_the_program_is_in_the_lock_and_no_local_model_package_is() -> None:
    spec = build_runtime.load_spec(REPO_DIR, PLATFORM)
    locked = build_runtime.read_lock(spec)
    project = tomllib.loads((REPO_DIR / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    direct = {build_runtime.canonical(re.split(r"[<>=!~\[; ]", spec_text, maxsplit=1)[0])
              for spec_text in project["dependencies"]}
    assert direct <= set(locked), direct - set(locked)
    assert build_runtime.runtime_requirements(REPO_DIR) == project["dependencies"]
    assert not LOCAL_MODEL_PACKAGES & set(locked), "local models are not part of the Windows package"
    assert not {"pytest", "ruff", "mypy", "pip-audit", "pip", "setuptools"} & set(locked), "no development tools"


def test_the_id_follows_the_inputs_and_is_what_the_updater_accepts(tmp_path: Path) -> None:
    spec = build_runtime.load_spec(REPO_DIR, PLATFORM)
    identifier = build_runtime.runtime_id(spec)
    assert identifier == build_runtime.runtime_id(spec), "the same inputs give the same id"
    assert update.RUNTIME_ID_RE.match(identifier) and build_runtime.ID_RE.match(identifier)
    assert identifier.startswith(spec.tag + "-")
    assert build_runtime.asset_name(PLATFORM, identifier) == update.runtime_asset_name(PLATFORM, identifier)

    # Another lock, another Python download or another platform: another id (and so a new download for the user).
    other_lock = tmp_path / "lock.txt"
    other_lock.write_text(spec.lock.read_text(encoding="utf-8") + "ekstra==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n",
                          encoding="utf-8")
    changed = [
        build_runtime.Spec(spec.platform, spec.python, spec.python_url, spec.python_sha256, other_lock),
        build_runtime.Spec(spec.platform, spec.python, spec.python_url, "f" * 64, spec.lock),
        build_runtime.Spec("win-arm64", spec.python, spec.python_url, spec.python_sha256, spec.lock),
    ]
    assert len({identifier, *(build_runtime.runtime_id(item) for item in changed)}) == 4
    # Line endings do not matter (the file is text in Git).
    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes(spec.lock.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert build_runtime.runtime_id(
        build_runtime.Spec(spec.platform, spec.python, spec.python_url, spec.python_sha256, crlf)) == identifier


def test_the_runtime_is_isolated_from_the_machine_and_finds_emneklar_next_to_it() -> None:
    lines = build_runtime.pth_lines()
    assert lines == ["{zip}", ".", "Lib\\site-packages", "..\\backend"]
    assert "import site" not in lines, "no site module: no user site-packages and no .pth files from elsewhere"
    assert not any(Path(line).is_absolute() for line in lines), "the installation can be put in any folder"


def test_a_lock_is_written_only_from_ready_built_files_with_hashes() -> None:
    report = {"install": [
        {"metadata": {"name": "Pillow", "version": "13.0.0"},
         "download_info": {"url": "https://files.pythonhosted.org/packages/x/pillow-13.0.0-cp314-cp314-win_amd64.whl",
                           "archive_info": {"hashes": {"sha256": "a" * 64}}}},
        {"metadata": {"name": "annotated_types", "version": "0.8.0"},
         "download_info": {"url": "https://files.pythonhosted.org/packages/y/annotated_types-0.8.0-py3-none-any.whl",
                           "archive_info": {"hashes": {"sha256": "b" * 64}}}},
    ]}
    lines = build_runtime.lock_lines(report)
    assert lines == [
        "annotated-types==0.8.0 \\\n    --hash=sha256:" + "b" * 64 + "  # annotated_types-0.8.0-py3-none-any.whl",
        "pillow==13.0.0 \\\n    --hash=sha256:" + "a" * 64 + "  # pillow-13.0.0-cp314-cp314-win_amd64.whl",
    ]
    source = json.loads(json.dumps(report))
    source["install"][0]["download_info"]["url"] = "https://files.pythonhosted.org/packages/x/pillow-13.0.0.tar.gz"
    with pytest.raises(build_runtime.RuntimeBuildError, match="ferdigbygd fil"):
        build_runtime.lock_lines(source)
    unhashed = json.loads(json.dumps(report))
    unhashed["install"][1]["download_info"]["archive_info"] = {}
    with pytest.raises(build_runtime.RuntimeBuildError):
        build_runtime.lock_lines(unhashed)
    with pytest.raises(build_runtime.RuntimeBuildError, match="ingen pakker"):
        build_runtime.lock_lines({"install": []})


def test_removed_console_scripts_are_not_left_in_the_package_records(tmp_path: Path) -> None:
    """The scripts are removed from the runtime; their lines would name missing files, and their hashes change from
    build to build. Without them two builds of the same inputs are identical."""
    site_packages = tmp_path / "Lib" / "site-packages"
    record = site_packages / "alembic-1.20.1.dist-info" / "RECORD"
    record.parent.mkdir(parents=True)
    record.write_bytes(b"../../bin/alembic.exe,sha256=8zr0_DciRbUDpZfqvb1SGNwpMgLEJLHCkMoIp6F_DiE,108356\n"
                       b"alembic/__init__.py,sha256=abc,63\n"
                       b"alembic-1.20.1.dist-info/RECORD,,\n")
    untouched = site_packages / "idna-3.20.dist-info" / "RECORD"
    untouched.parent.mkdir(parents=True)
    untouched.write_bytes(b"idna/__init__.py,sha256=def,868\r\nidna-3.20.dist-info/RECORD,,\r\n")
    build_runtime.forget_removed_scripts(site_packages)
    assert record.read_bytes() == b"alembic/__init__.py,sha256=abc,63\nalembic-1.20.1.dist-info/RECORD,,\n"
    assert untouched.read_bytes() == b"idna/__init__.py,sha256=def,868\r\nidna-3.20.dist-info/RECORD,,\r\n"
    assert build_runtime.RECIPE >= 2, "the id changed with the way the runtime is put together"


def test_lock_and_build_refuse_another_python_or_platform_than_the_runtime_is_for(
        monkeypatch: pytest.MonkeyPatch) -> None:
    spec = build_runtime.load_spec(REPO_DIR, PLATFORM)
    monkeypatch.setattr(build_runtime, "platform_tag", lambda: "linux-x86_64")
    with pytest.raises(build_runtime.RuntimeBuildError, match="på samme plattform"):
        build_runtime.require_matching_host(spec)
    monkeypatch.setattr(build_runtime, "platform_tag", lambda: PLATFORM)
    monkeypatch.setattr(build_runtime.sys, "version_info", (3, 12, 0, "final", 0))
    with pytest.raises(build_runtime.RuntimeBuildError, match=r"Python 3\.12"):
        build_runtime.require_matching_host(spec)


def test_a_python_download_with_another_hash_is_not_used(tmp_path: Path) -> None:
    spec = build_runtime.load_spec(REPO_DIR, PLATFORM)
    fake = tmp_path / "python-embed.zip"
    fake.write_bytes(b"ikke python")
    with pytest.raises(build_runtime.RuntimeBuildError, match="Filen brukes ikke"):
        build_runtime.fetch_python(spec, tmp_path / "cache", fake)
