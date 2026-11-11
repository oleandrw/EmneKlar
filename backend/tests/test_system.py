"""core/system.py: the thin layer between EmneKlar and the machine it runs on."""

from __future__ import annotations

import io
import re
import sys
from collections.abc import Callable
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


EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"


def test_the_program_is_read_from_the_open_command_of_a_browser() -> None:
    assert system.executable_in_command(f'"{EDGE}" --single-argument %1') == EDGE
    assert system.executable_in_command(f"{CHROME} -- %1") == CHROME
    for nothing in (None, "", '"', "rundll32 url.dll,FileProtocolHandler %1"):
        assert system.executable_in_command(nothing) is None, nothing


def test_the_window_is_drawn_by_the_default_browser_when_it_can_and_by_edge_or_chrome_otherwise() -> None:
    installed = [Path(EDGE), Path(CHROME)]

    def on_machine(*paths: str) -> Callable[[Path], bool]:
        return lambda path: str(path) in paths

    choose = system.choose_app_window_browser
    assert str(choose(f'"{CHROME}" --single-argument %1', installed, exists=on_machine(EDGE, CHROME))) == CHROME
    firefox = '"C:\\Program Files\\Mozilla Firefox\\firefox.exe" -osint -url "%1"'
    assert str(choose(firefox, installed, exists=on_machine(EDGE, CHROME, "firefox"))) == EDGE, "no app window"
    assert str(choose(None, installed, exists=on_machine(CHROME))) == CHROME, "Edge removed"
    assert str(choose(f'"{CHROME}" %1', installed, exists=on_machine(EDGE))) == EDGE, "a stale default"
    assert choose(firefox, installed, exists=on_machine("firefox")) is None, "then a normal tab"


def test_emneklar_opens_in_a_window_of_its_own_and_in_a_tab_when_that_is_not_possible(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    url = "http://127.0.0.1:8770/auth/launch?token=engangs"
    browser = tmp_path / "Edge" / "msedge.exe"
    started: list[tuple[list[str], Path]] = []
    tabs: list[str] = []
    monkeypatch.setattr(system, "_start_detached", lambda command, cwd: started.append((command, cwd)))
    monkeypatch.setattr(system.webbrowser, "open", lambda address: tabs.append(address) or True)

    monkeypatch.setattr(system, "app_window_browser", lambda: browser)
    assert system.open_user_interface(url)
    assert started == [([str(browser), f"--app={url}"], browser.parent)] and tabs == [], \
        "app mode, started in the browser's own folder – never in the program folder"

    def gone(command: list[str], cwd: Path) -> None:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(system, "_start_detached", gone)
    assert system.open_user_interface(url) and tabs == [url], "the browser could not be started: a tab"
    monkeypatch.setattr(system, "app_window_browser", lambda: None)
    assert system.open_user_interface(url) and tabs == [url, url], "no Edge or Chrome: a tab"
    monkeypatch.setattr(system.webbrowser, "open", lambda address: False)
    assert not system.open_user_interface(url), "nothing could be opened: the caller tells the user"


def test_only_windows_looks_for_an_app_window(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("darwin", "linux"):
        monkeypatch.setattr(system.sys, "platform", name)
        assert system.app_window_browser() is None, "not built or tested there (docs/PLATFORMS.md): a tab"


@pytest.mark.skipif(sys.platform != "win32", reason="Edge and Chrome are looked up in the Windows registry")
def test_windows_has_a_browser_that_can_show_the_window() -> None:
    """Microsoft Edge comes with Windows 10 and 11 (and the Windows runners in CI)."""
    browser = system.app_window_browser()
    assert browser is not None and browser.is_file() and browser.name.lower() in system.APP_WINDOW_BROWSERS


def test_the_layer_uses_only_the_standard_library() -> None:
    """scripts/setup.py and scripts/update.py import it before any dependency is installed."""
    source = (REPO_DIR / "backend" / "emneklar" / "core" / "system.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([a-zA-Z_][\w.]*)", source, re.MULTILINE))
    assert imported <= {"__future__", "os", "platform", "subprocess", "sys", "sysconfig", "webbrowser",
                        "collections.abc", "pathlib", "ctypes", "winreg"}, imported


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
