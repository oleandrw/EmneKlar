"""EmneKlar started from the shortcut runs without a console window (pythonw.exe).

Then nothing that is printed can be seen: a start-up problem must be shown in a message box, the browser is only
opened on an address that answers, and the program is stopped with «Avslutt EmneKlar» – in the program
(``POST /api/system/shutdown``) or from the Start menu (``manage stop``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from emneklar import launcher, manage
from emneklar.core import logging_setup, system
from tests.test_coexistence import other_programs_database


@pytest.fixture
def no_console(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, bool]]:
    """The state under pythonw.exe once prepare_standard_streams() has run: there is no console to print in.
    Returns the message boxes that are shown. (pytest owns sys.stdout between the phases of a test, so the missing
    streams themselves are set inside the one test that is about them.)"""
    boxes: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(system, "_console_missing", True)
    monkeypatch.setattr(system, "_message_box", lambda title, text, *, error: boxes.append((title, text, error)))
    return boxes


def test_without_a_console_the_standard_streams_are_replaced_and_messages_go_to_a_box(
        monkeypatch: pytest.MonkeyPatch) -> None:
    boxes: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(system, "_message_box", lambda title, text, *, error: boxes.append((title, text, error)))
    monkeypatch.setattr(system, "_console_missing", False)  # restored after the test
    monkeypatch.setattr(system.sys, "stdout", None)  # as pythonw.exe starts
    monkeypatch.setattr(system.sys, "stderr", None)
    assert not system.has_console()
    system.prepare_standard_streams()
    assert system.sys.stdout is not None and system.sys.stderr is not None
    print("ingen ser dette", file=system.sys.stderr)  # code that writes directly must not fail
    assert not system.has_console(), "still no console: a message the user must read needs a box"
    system.tell_user("EmneKlar", "Noe gikk galt", error=True)
    assert boxes == [("EmneKlar", "Noe gikk galt", True)]


def test_with_a_console_nothing_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "_console_missing", False)
    before = (system.sys.stdout, system.sys.stderr)
    system.prepare_standard_streams()
    assert (system.sys.stdout, system.sys.stderr) == before and system.has_console()


def test_a_start_up_problem_is_shown_in_a_box_when_there_is_no_console(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_console: list[tuple[str, str, bool]]) -> None:
    folder = tmp_path / "EmneKlar"
    other_programs_database(folder)  # another program's data folder: EmneKlar must refuse to start in it
    monkeypatch.setenv("EMNEKLAR_DATA_DIR", str(folder))
    for name in ("EMNEKLAR_PORT", "EMNEKLAR_HOST", "EMNEKLAR_DEV"):
        monkeypatch.delenv(name, raising=False)
    assert launcher.main(["--no-browser"]) == 2
    assert len(no_console) == 1
    title, text, error = no_console[0]
    assert title == "EmneKlar" and error and "tilhører et annet program" in text


def test_the_browser_is_opened_only_when_emneklar_answers(monkeypatch: pytest.MonkeyPatch,
                                                         no_console: list[tuple[str, str, bool]]) -> None:
    opened: list[str] = []
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(launcher, "open_user_interface", lambda url: opened.append(url) or True)
    url = "http://127.0.0.1:8791/auth/launch?token=engangs"

    monkeypatch.setattr(launcher, "fetch_health", lambda origin, timeout=1: None)
    launcher._wait_and_open(url, "http://127.0.0.1:8791", True)
    assert opened == [] and no_console == [], "nothing answers: no window on a dead address"

    monkeypatch.setattr(launcher, "fetch_health", lambda origin, timeout=1: {"app": "EmneKlar"})
    launcher._wait_and_open(url, "http://127.0.0.1:8791", True)
    assert opened == [url] and no_console == []
    launcher._wait_and_open(url, "http://127.0.0.1:8791", False)  # --no-browser
    assert opened == [url]

    # No browser can be opened and there is no console to print the link in: the user gets it in a box.
    monkeypatch.setattr(launcher, "open_user_interface", lambda url: False)
    launcher._wait_and_open(url, "http://127.0.0.1:8791", True)
    assert len(no_console) == 1 and url in no_console[0][1] and not no_console[0][2]


def test_no_browser_can_be_chosen_with_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    """The shortcut and the updater start EmneKlar without arguments: EMNEKLAR_NO_BROWSER=1 is --no-browser."""
    opened: list[str] = []
    url = "http://127.0.0.1:8791/auth/launch?token=engangs"
    monkeypatch.setattr(launcher, "open_user_interface", lambda address: opened.append(address) or True)
    monkeypatch.setattr(launcher, "running_instance", lambda run_dir: {"origin": "http://127.0.0.1:8791"})
    monkeypatch.setattr(launcher, "request_launch_url", lambda info: url)
    for name in ("EMNEKLAR_PORT", "EMNEKLAR_HOST", "EMNEKLAR_DEV", "EMNEKLAR_NO_BROWSER"):
        monkeypatch.delenv(name, raising=False)
    assert launcher.main([]) == 0 and opened == [url], "already running: a new window with a fresh login link"
    monkeypatch.setenv("EMNEKLAR_NO_BROWSER", "1")
    assert launcher.main([]) == 0 and opened == [url]
    monkeypatch.delenv("EMNEKLAR_NO_BROWSER")
    assert launcher.main(["--no-browser"]) == 0 and opened == [url]
    assert "kjører allerede" in capsys.readouterr().out


def test_the_login_link_is_printed_only_in_a_console(monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(system, "_console_missing", False)
    monkeypatch.setattr(launcher, "open_user_interface", lambda url: True)
    launcher._announce("http://127.0.0.1:8791/auth/launch?token=engangs", True)
    out = capsys.readouterr().out
    assert "token=engangs" in out and "Lukk dette vinduet for å avslutte EmneKlar" in out


def test_stop_from_the_start_menu_answers_in_a_box(monkeypatch: pytest.MonkeyPatch,
                                                   no_console: list[tuple[str, str, bool]]) -> None:
    assert manage.main(["stop"]) == 0  # the data folder of this test has no running instance
    assert no_console == [("EmneKlar", "EmneKlar kjører ikke – ingenting å stoppe.", False)]
    monkeypatch.setattr(manage, "stop_instance", lambda run_dir, timeout=30.0: "stopped")
    assert manage.main(["stop"]) == 0
    assert no_console[-1] == ("EmneKlar", "EmneKlar er avsluttet.", False)
    monkeypatch.setattr(manage, "stop_instance", lambda run_dir, timeout=30.0: "timeout")
    assert manage.main(["stop", "--timeout", "2"]) == 1
    assert no_console[-1][2] and "avsluttet ikke innen 2 sekunder" in no_console[-1][1]


def test_no_console_handler_is_added_without_a_console(monkeypatch: pytest.MonkeyPatch,
                                                       no_console: list[tuple[str, str, bool]]) -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    monkeypatch.setattr(logging_setup, "_configured", False)
    try:
        logging_setup.configure_logging(None)
        added = [handler for handler in root.handlers if handler not in before]
        assert added == [], "only the log file is a log when nothing can be seen"
    finally:
        for handler in [handler for handler in root.handlers if handler not in before]:
            root.removeHandler(handler)


# -- «Avslutt EmneKlar» in the program ---------------------------------------------------------------------------------


def test_quitting_from_the_program_needs_a_session(raw_client: TestClient) -> None:
    stopped: list[int] = []
    raw_client.app.state.request_shutdown = lambda: stopped.append(1)  # type: ignore[attr-defined]
    response = raw_client.post("/api/system/shutdown", json={})
    assert response.status_code == 401 and stopped == []


def test_quitting_from_the_program_stops_the_server_and_warns_about_running_jobs(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    app: Any = client.app
    # Not started by the launcher (as here): there is nothing to stop, and the answer says so.
    refused = client.post("/api/system/shutdown", json={})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "unsupported"

    stopped: list[int] = []
    app.state.request_shutdown = lambda: stopped.append(1)
    container = app.state.container
    monkeypatch.setattr(container.jobs, "list", lambda **_kwargs: [object(), object()])
    busy = client.post("/api/system/shutdown", json={})
    assert busy.status_code == 409 and stopped == []
    error = busy.json()["error"]
    assert error["code"] == "jobs_running" and error["extra"] == {"jobs": 2} and "2 jobb(er) kjører" in error["message"]
    forced = client.post("/api/system/shutdown", json={"force": True})
    assert forced.status_code == 200 and forced.json() == {"ok": True} and stopped == [1]

    monkeypatch.setattr(container.jobs, "list", lambda **_kwargs: [])
    assert client.post("/api/system/shutdown", json={}).status_code == 200 and stopped == [1, 1]
    # A request from another site (no CSRF token, foreign Origin) never stops EmneKlar.
    foreign = client.post("/api/system/shutdown", json={}, headers={"Origin": "https://evil.example", "X-CSRF-Token": ""})
    assert foreign.status_code == 403 and stopped == [1, 1]


def test_messages_no_longer_assume_that_emneklar_is_started_with_start_bat(raw_client: TestClient) -> None:
    expired = raw_client.get("/auth/launch?token=feil")
    assert expired.status_code == 401 and "Start-menyen" in expired.text
    from emneklar.core.errors import MESSAGES

    assert "Start-menyen" in MESSAGES["session_required"]
