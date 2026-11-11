"""core/system.py: the thin layer between EmneKlar and the machine it runs on."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from emneklar.config import REPO_DIR
from emneklar.core import system


def test_the_data_folder_follows_the_conventions_of_each_platform(monkeypatch: pytest.MonkeyPatch,
                                                                  tmp_path: Path) -> None:
    monkeypatch.setattr(system.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert system.user_data_dir("EmneKlar") == tmp_path / "Local" / "EmneKlar"
    monkeypatch.delenv("LOCALAPPDATA")
    assert system.user_data_dir("EmneKlar") == Path.home() / "AppData" / "Local" / "EmneKlar"

    monkeypatch.setattr(system.sys, "platform", "darwin")
    assert system.user_data_dir("EmneKlar") == Path.home() / "Library" / "Application Support" / "EmneKlar"

    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert system.user_data_dir("EmneKlar") == tmp_path / "xdg" / "emneklar"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert system.user_data_dir("EmneKlar") == Path.home() / ".local" / "share" / "emneklar"


def test_the_platform_tag_names_the_runtime_for_the_running_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    assert re.fullmatch(r"[a-z0-9]+-[a-z0-9_]+", system.platform_tag()), "the form install.json and the updater use"
    monkeypatch.setattr(system.sys, "platform", "win32")
    monkeypatch.setattr(system.sysconfig, "get_platform", lambda: "win-amd64")
    assert system.platform_tag() == "win-amd64"
    monkeypatch.setattr(system.sys, "platform", "darwin")
    monkeypatch.setattr(system.platform, "machine", lambda: "arm64")
    assert system.platform_tag() == "macos-arm64"
    monkeypatch.setattr(system.platform, "machine", lambda: "x86_64")
    assert system.platform_tag() == "macos-x86_64"
    monkeypatch.setattr(system.sys, "platform", "linux")
    assert system.platform_tag() == "linux-x86_64"
    monkeypatch.setattr(system.platform, "machine", lambda: "aarch64")
    assert system.platform_tag() == "linux-aarch64"


def test_a_message_is_printed_with_a_console_and_shown_in_a_box_without_one(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(system.sys, "stdout", out)
    monkeypatch.setattr(system.sys, "stderr", err)
    boxes: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(system, "_message_box", lambda title, text, *, error: boxes.append((title, text, error)))
    assert system.has_console()
    system.tell_user("EmneKlar", "Alt i orden")
    system.tell_user("EmneKlar", "Noe gikk galt", error=True)
    assert out.getvalue() == "Alt i orden\n" and err.getvalue() == "Noe gikk galt\n" and boxes == []

    # Started from the shortcut (pythonw.exe): there is nowhere to print.
    monkeypatch.setattr(system.sys, "stdout", None)
    monkeypatch.setattr(system.sys, "stderr", None)
    assert not system.has_console()
    system.tell_user("EmneKlar", "Noe gikk galt", error=True)
    assert boxes == [("EmneKlar", "Noe gikk galt", True)]


def test_where_no_message_box_is_implemented_nothing_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system.sys, "platform", "linux")
    assert system._message_box("EmneKlar", "Ingen vindusmelding her", error=True) is None


def test_opening_a_folder_is_windows_only_and_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(system.sys, "platform", "win32")
    monkeypatch.setattr(system.os, "startfile", lambda path: opened.append(path), raising=False)
    system.open_folder(tmp_path)
    assert opened == [tmp_path]
    monkeypatch.setattr(system.sys, "platform", "darwin")
    with pytest.raises(system.UnsupportedOnThisPlatform, match="bare på Windows"):
        system.open_folder(tmp_path)
    assert opened == [tmp_path]


def test_the_layer_uses_only_the_standard_library() -> None:
    """scripts/setup.py and scripts/update.py import it before any dependency is installed."""
    source = (REPO_DIR / "backend" / "emneklar" / "core" / "system.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([a-zA-Z_][\w.]*)", source, re.MULTILINE))
    assert imported <= {"__future__", "os", "platform", "sys", "sysconfig", "pathlib", "ctypes"}, imported


def test_platform_checks_stay_in_the_thin_layer() -> None:
    """New code asks core/system.py instead of testing the platform itself. The files below are the known places
    where the platform is part of what the module does (process handles, job objects, worker start-up)."""
    allowed = {"core/system.py", "manage.py", "core/security/isolation.py", "core/ai/local/whisper.py",
               "core/updates/service.py"}
    found = set()
    package = REPO_DIR / "backend" / "emneklar"
    for path in package.rglob("*.py"):
        if re.search(r"sys\.platform|os\.name\b|platform\.system\(", path.read_text(encoding="utf-8")):
            found.add(path.relative_to(package).as_posix())
    assert found <= allowed, f"move the platform check into core/system.py: {sorted(found - allowed)}"
