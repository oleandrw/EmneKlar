"""scripts/setup.py and scripts/update.py install the program's dependencies and nothing optional: they never ask
about, download or install local models, and no file that installs EmneKlar names those packages."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from emneklar.config import REPO_DIR
from tests.script_loader import load_script

setup = load_script("setup")
update = load_script("update")

LOCAL_MODEL_WORDS = ("sentence-transformers", "sentence_transformers", "faster-whisper", "faster_whisper", "torch",
                     "[rag]", "emneklar-extras", "--rag", "--no-rag")
#: Everything that installs or updates EmneKlar on a machine, and the workflows that build what is installed.
INSTALLING_FILES = ("scripts/setup.py", "scripts/update.py", "setup.bat", "update.bat", "start.bat",
                    "backend/constraints.txt", ".github/workflows/ci.yml", ".github/workflows/release.yml")


def test_setup_has_no_question_and_no_choice_for_local_models() -> None:
    assert not hasattr(setup, "wants_local_models") and not hasattr(setup, "LOCAL_MODELS_QUESTION")
    for flag in ("--rag", "--no-rag"):
        with pytest.raises(SystemExit) as stopped:  # argparse refuses the argument before anything is done
            setup.main([flag])
        assert stopped.value.code == 2


@pytest.mark.parametrize("rel", INSTALLING_FILES)
def test_nothing_that_installs_emneklar_names_the_local_model_packages(rel: str) -> None:
    text = (REPO_DIR / rel).read_text(encoding="utf-8").lower()
    found = [word for word in LOCAL_MODEL_WORDS if word in text]
    assert not found, f"{rel} mentions {found}"


def test_local_model_packages_are_not_dependencies_of_the_program() -> None:
    project = tomllib.loads((REPO_DIR / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    required = " ".join(project["dependencies"]).lower()
    for word in ("sentence-transformers", "faster-whisper", "torch"):
        assert word not in required
    # The developer-only extra still exists, so the support in the program code can be tried out by hand.
    assert any("sentence-transformers" in spec for spec in project["optional-dependencies"]["rag"])


def test_dependencies_are_installed_with_one_pinned_command_and_nothing_optional(tmp_path: Path,
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "EmneKlar"
    (root / "backend" / ".venv").mkdir(parents=True)
    (root / "backend" / "constraints.txt").write_text("fastapi==0.162.0\n", encoding="utf-8")
    # A choice an older setup remembered is ignored: there is nothing optional to install any more.
    (root / "backend" / ".venv" / "emneklar-extras.txt").write_text("rag\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(args: list[Any], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append([str(a) for a in args])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(update, "run", fake_run)
    update.install_python_dependencies(Path("python"), root, update.Reporter(None, total_steps=1, title="test"))
    assert len(commands) == 1, commands
    assert commands[0][-2:] == ["-e", str(root / "backend")] and "-c" in commands[0]
    assert not any("[" in word for word in commands[0]), "no extras"
    for name in ("chosen_extras", "remember_extra", "install_optional_extras", "KNOWN_EXTRAS", "EXTRAS_FILE"):
        assert not hasattr(update, name), name


# -- an installation with its own runtime (made by the installer) ---------------------------------------------------


def bundled_installation(root: Path, monkeypatch: pytest.MonkeyPatch, *, version: str = "0.3.0") -> list[list[str]]:
    """Point setup at ``root`` – a folder like the one the installer makes – and record the commands it runs."""
    (root / "VERSION").parent.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    python = update.bundled_python_path(root)
    python.parent.mkdir(parents=True)
    python.write_text("python", encoding="utf-8")
    (root / "runtime" / "runtime.json").write_text('{"id": "cp314-0123456789ab"}', encoding="utf-8")
    (root / "frontend" / "dist").mkdir(parents=True)
    (root / "frontend" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    for name, value in {"ROOT": root, "BACKEND": root / "backend", "FRONTEND": root / "frontend",
                        "VENV": root / "backend" / ".venv"}.items():
        monkeypatch.setattr(setup, name, value)
    commands: list[list[str]] = []

    def fake_run(args: list[Any], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = [str(a) for a in args]
        commands.append(command)
        output = version if "emneklar.main" in command[-1] else "3.14.10"
        return subprocess.CompletedProcess(args, 0, output + "\n", "")

    monkeypatch.setattr(update, "run", fake_run)
    return commands


def test_with_its_own_runtime_setup_checks_and_installs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "EmneKlar"
    commands = bundled_installation(root, monkeypatch)
    assert setup.main(["--no-pause"]) == 0
    out = capsys.readouterr().out
    assert "Steg 1 av 3" in out and "Steg 3 av 3" in out and "av 5" not in out
    assert "Ingen Python på maskinen brukes" in out and "Installasjonen er i orden – EmneKlar 0.3.0" in out
    assert "Start-menyen" in out
    python = str(update.bundled_python_path(root))
    assert len(commands) == 2 and all(command[0] == python for command in commands), "only the runtime's own Python"
    assert not any("pip" in word or "venv" in word for command in commands for word in command)
    assert not (root / "backend" / ".venv").exists(), "no virtual environment is made"


def test_a_broken_bundled_installation_is_repaired_with_the_installer_not_with_setup(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "EmneKlar"
    bundled_installation(root, monkeypatch)
    (root / "frontend" / "dist" / "index.html").unlink()
    assert setup.main(["--no-pause"]) == 1
    out = capsys.readouterr().out
    assert "Brukergrensesnittet mangler" in out and "installasjonsprogrammet" in out and "Dataene og innstillingene" in out
    assert "kjør setup.bat på nytt" not in out.lower()

    (root / "frontend" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(update, "run", lambda args, **_kwargs: subprocess.CompletedProcess(args, 1, "", "kan ikke starte"))
    assert setup.main(["--no-pause"]) == 1
    assert "lar seg ikke starte" in capsys.readouterr().out


def test_setup_finds_update_py_itself() -> None:
    """The bundled runtime runs isolated and does not put the script's folder on the search path."""
    source = (REPO_DIR / "scripts" / "setup.py").read_text(encoding="utf-8")
    assert source.index('sys.path.insert(0, str(ROOT / "scripts"))') < source.index("import update")
