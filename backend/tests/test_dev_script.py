"""scripts/dev.py: set-up on a new machine, a development instance against a real Canvas, the demo and the checks.

Nothing here runs a command: the steps are inspected, and the instance's environment is checked to keep it apart from
an installed EmneKlar (its data folder, port 8770 and the service «EmneKlar» in the credential store).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from tests.script_loader import load_script

dev = load_script("dev")
package_release = load_script("package_release")


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A machine of its own: data folders under tmp_path, npm found, a working Python environment."""
    monkeypatch.setattr(dev, "user_data_dir", lambda name: tmp_path / "Local" / name)
    monkeypatch.setattr(dev, "tool", lambda name: name)
    monkeypatch.setattr(dev, "venv_python", lambda: Path(sys.executable))
    monkeypatch.setattr(dev, "require_node_modules", lambda: None)

    def no_commands(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("no command may run in these tests")

    monkeypatch.setattr(dev.subprocess, "run", no_commands)
    return tmp_path


def steps_of(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[Any]:
    seen: list[Any] = []
    monkeypatch.setattr(dev, "run_steps", lambda steps, **_kw: seen.extend(steps) or [])
    dev.main(argv)
    return seen


def test_start_is_a_development_instance_apart_from_the_ordinary_one(machine: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    build, run = steps_of(monkeypatch, ["start"])
    assert build.argv == ["npm", "run", "build"] and build.cwd == dev.FRONTEND, "the source code is built first"
    assert run.argv == [sys.executable, "-m", "emneklar"] and run.cwd == dev.BACKEND
    assert run.env == {"EMNEKLAR_DATA_DIR": str(machine / "Local" / "EmneKlar-dev"), "EMNEKLAR_PORT": "8771",
                       "EMNEKLAR_KEYRING_SERVICE": "EmneKlar-dev"}
    (only,) = steps_of(monkeypatch, ["start", "--no-build", "--no-browser", "--port", "8780", "--data-dir",
                                     str(machine / "egen")])
    assert only.argv[-1] == "--no-browser" and only.env["EMNEKLAR_PORT"] == "8780"
    assert only.env["EMNEKLAR_DATA_DIR"] == str(machine / "egen")


@pytest.mark.parametrize("argv", [["start", "--port", "8770"], ["demo", "--port", "8770"],
                                  ["demo", "--canvas-port", "8770"]])
def test_the_ordinary_port_is_refused(machine: Path, argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert dev.main([*argv, "--dry-run"]) == 2
    assert "Port 8770 er den vanlige EmneKlar sin" in capsys.readouterr().err


@pytest.mark.parametrize("folder", ["EmneKlar", "EmneKlar-Claude"])
def test_the_ordinary_data_folder_is_refused(machine: Path, folder: str, capsys: pytest.CaptureFixture[str]) -> None:
    ordinary = machine / "Local" / folder
    assert dev.main(["start", "--dry-run", "--data-dir", str(ordinary)]) == 2
    assert "er datamappen til den vanlige EmneKlar" in capsys.readouterr().err
    with pytest.raises(dev.DevError):
        dev.start_environment({}, data_dir=ordinary, port=8771)


def test_the_environment_keeps_everything_else(machine: Path) -> None:
    env = dev.start_environment({"PATH": "x", "EMNEKLAR_PORT": "8770"}, data_dir=machine / "d", port=8771)
    assert env["PATH"] == "x" and env["EMNEKLAR_PORT"] == "8771", "the instance's own values win"


def test_a_dry_run_shows_the_commands_and_runs_nothing(machine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert dev.main(["start", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "npm run build" in out and "-m emneklar" in out and "EmneKlar-dev" in out
    assert "http://127.0.0.1:8771" in out and "Ingenting skrives til Canvas før du publiserer" in out


def test_setup_installs_the_development_tools_like_ci(machine: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "python_version", lambda _python: (3, 14))
    monkeypatch.setattr(dev, "node_major", lambda: 22)
    steps = dev.setup_steps(playwright=False, dry_run=True)
    assert [s.label.split(" (")[0] for s in steps] == [
        "Installerer EmneKlar med utviklingsverktøyene", "Installerer pakkene til brukergrensesnittet",
        "Bygger brukergrensesnittet", "Kontrollerer at EmneKlar kan lastes"], "an existing environment is reused"
    pip = steps[0].argv
    assert pip[1:4] == ["-m", "pip", "install"] and pip[-4:] == ["-c", "backend/constraints.txt", "-e", "backend[dev]"]
    assert steps[1].argv == ["npm", "ci", "--no-audit", "--no-fund"] and steps[1].cwd == dev.FRONTEND
    with_browser = dev.setup_steps(playwright=True, dry_run=True)
    assert ["npx", "playwright", "install", "chromium"] in [s.argv for s in with_browser]

    monkeypatch.setattr(dev, "python_version", lambda _python: None)
    first = dev.setup_steps(playwright=False, dry_run=True)[0]
    assert first.argv[1:3] == ["-m", "venv"] and first.argv[3] == str(dev.BACKEND / ".venv")

    monkeypatch.setattr(dev, "node_major", lambda: 20)
    with pytest.raises(dev.DevError, match=r"Node\.js 20 er for gammel"):
        dev.setup_steps(playwright=False, dry_run=True)


def test_check_runs_what_ci_runs(machine: Path) -> None:
    steps = dev.check_steps(backend=True, frontend=True, e2e=False, dry_run=True)
    argv = [s.argv[1:] if s.cwd == dev.BACKEND else s.argv for s in steps]
    assert argv == [
        ["-m", "ruff", "check", "--config", "pyproject.toml", ".", "../scripts"],
        ["-m", "mypy", "--platform", "win32", "emneklar", "../scripts"],
        ["-m", "mypy", "--platform", "linux", "emneklar", "../scripts"],
        ["-m", "pytest", "-q"],
        ["npm", "run", "typecheck"], ["npm", "run", "lint"], ["npm", "test"],
    ]
    e2e = dev.check_steps(backend=False, frontend=True, e2e=True, dry_run=True)
    assert [s.argv for s in e2e][-2:] == [["npm", "run", "build"], ["npm", "run", "e2e"]]
    assert all(s.cwd == dev.BACKEND for s in dev.check_steps(backend=True, frontend=False, e2e=True, dry_run=True))


def test_a_missing_environment_says_what_to_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(dev, "user_data_dir", lambda name: tmp_path / "Local" / name)
    monkeypatch.setattr(dev, "venv_python", lambda: tmp_path / "finnes-ikke" / "python.exe")
    assert dev.main(["start", "--no-build"]) == 2
    assert "Kjør først: py scripts/dev.py setup" in capsys.readouterr().err


def test_the_script_is_never_part_of_a_release() -> None:
    assert package_release.classify("scripts/dev.py") == "development"
