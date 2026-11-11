"""EmneKlar stops by itself when its last window has been closed (core/presence.py, GET /api/system/presence)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from emneklar.core.presence import WindowPresence


def armed(jobs: list[int] | None = None) -> tuple[WindowPresence, list[str]]:
    """A presence as the launcher arms it, with short waits; ``jobs[0]`` is the number of running jobs."""
    running = jobs if jobs is not None else [0]
    presence = WindowPresence(running_jobs=lambda: running[0], grace=0.05, poll=0.01)
    stops: list[str] = []
    presence.stop = lambda: stops.append("stop")
    return presence, stops


async def test_emneklar_stops_when_the_last_window_has_been_closed_for_a_while() -> None:
    presence, stops = armed()
    presence.opened()
    presence.opened()
    presence.closed()
    await asyncio.sleep(0.15)
    assert stops == [], "one window is still open"
    presence.closed()
    await asyncio.sleep(0.02)
    assert stops == [], "not at once: a reload comes back within the wait"
    await asyncio.sleep(0.15)
    assert stops == ["stop"]


async def test_a_reload_within_the_wait_keeps_emneklar_running() -> None:
    presence, stops = armed()
    presence.opened()
    presence.closed()
    await asyncio.sleep(0.02)
    presence.opened()  # the same window, reloaded
    await asyncio.sleep(0.15)
    assert stops == []
    presence.closed()
    await asyncio.sleep(0.15)
    assert stops == ["stop"], "closed for good later: then it stops"


async def test_running_jobs_are_finished_first() -> None:
    jobs = [2]
    presence, stops = armed(jobs)
    presence.opened()
    presence.closed()
    await asyncio.sleep(0.15)
    assert stops == [], "an analysis or a publication to Canvas is never cut off by closing the window"
    jobs[0] = 0
    await asyncio.sleep(0.1)
    assert stops == ["stop"]


async def test_a_window_opened_while_jobs_finish_keeps_emneklar_running() -> None:
    jobs = [1]
    presence, stops = armed(jobs)
    presence.opened()
    presence.closed()
    await asyncio.sleep(0.1)
    presence.opened()  # the shortcut was used again
    jobs[0] = 0
    await asyncio.sleep(0.1)
    assert stops == []


async def test_it_never_stops_by_itself_unless_the_launcher_armed_it() -> None:
    presence = WindowPresence(running_jobs=lambda: 0, grace=0.01, poll=0.01)
    presence.opened()
    presence.closed()
    await asyncio.sleep(0.05)
    assert presence.stop is None and presence.open_windows == 0, "--no-browser, tests, CI and the e2e server"


async def test_nothing_more_happens_once_emneklar_is_stopping() -> None:
    presence, stops = armed()
    presence.opened()
    presence.stopping.set()  # «Avslutt EmneKlar», the Start menu or an update: the connections end
    presence.closed()
    await asyncio.sleep(0.1)
    assert stops == []


def test_the_window_connection_needs_the_session(raw_client: TestClient) -> None:
    assert raw_client.get("/api/system/presence").status_code == 401
    assert raw_client.app.state.presence.stop is None, "the app alone never stops by itself; the launcher arms it"  # type: ignore[attr-defined]


def test_a_window_is_counted_while_its_connection_is_open(client: TestClient) -> None:
    presence: WindowPresence = client.app.state.presence  # type: ignore[attr-defined]
    presence.stopping.set()  # the test client reads a response to its end: let this one end after its first event
    response = client.get("/api/system/presence")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "retry: 2000\n\n" and response.headers["cache-control"] == "no-store"
    assert presence.open_windows == 0, "opened and closed again"
