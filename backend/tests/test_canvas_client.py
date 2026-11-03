"""Canvas client: auth, pagination, throttling, retries, timeouts, permissions, write guard."""

from __future__ import annotations

import httpx
import pytest

from emneklar.core.canvas.api import CanvasAPI, answer_is_correct, is_block_editor_page
from emneklar.core.canvas.client import CanvasClient, CanvasError, DryRunBlocked, WritePermit, parse_link_header
from tests.fakes.fake_canvas import COURSE_ID, TOKEN, create_fake_canvas, seed_state

BASE = "http://canvas.test"


async def _no_sleep(_: float) -> None:
    return None


def make_client(state=None, *, token: str = TOKEN, dry_run: bool = False, transport=None) -> CanvasClient:
    state = state or seed_state(BASE)
    http = httpx.AsyncClient(transport=transport or httpx.ASGITransport(app=create_fake_canvas(state)),
                             base_url=BASE)
    return CanvasClient(BASE, lambda: token, http=http, allow_http=True, sleep=_no_sleep, dry_run=lambda: dry_run)


async def test_users_self_and_invalid_token() -> None:
    api = CanvasAPI(make_client())
    me = await api.users_self()
    assert me["name"] == "Kari Lærer"
    bad = CanvasAPI(make_client(token="wrong"))
    with pytest.raises(CanvasError) as info:
        await bad.users_self()
    assert info.value.code == "canvas_token_invalid"


async def test_pagination_follows_link_header() -> None:
    state = seed_state(BASE)
    for i in range(25):
        state.courses[COURSE_ID].assignments[str(900 + i)] = {"id": str(900 + i), "name": f"Oppgave {i}"}
    client = make_client(state)
    items = await client.get_paginated(f"/api/v1/courses/{COURSE_ID}/assignments", [("per_page", 10)])
    assert len(items) == 28
    gets = [r for r in state.requests if r[1].endswith("/assignments")]
    assert len(gets) == 3


def test_parse_link_header() -> None:
    header = '<https://x/a?page=2>; rel="next",<https://x/a?page=1>; rel="first"'
    assert parse_link_header(header) == {"next": "https://x/a?page=2", "first": "https://x/a?page=1"}


@pytest.mark.parametrize("status", [429, 403])
async def test_rate_limit_is_retried(status: int) -> None:
    state = seed_state(BASE)
    state.rate_limit_failures = 2
    state.rate_limit_status = status
    me = await CanvasAPI(make_client(state)).users_self()
    assert me["id"] == "42"


async def test_rate_limit_gives_up_with_norwegian_error() -> None:
    state = seed_state(BASE)
    state.rate_limit_failures = 50
    with pytest.raises(CanvasError) as info:
        await CanvasAPI(make_client(state)).users_self()
    assert info.value.code == "canvas_rate_limited"
    assert "Canvas" in info.value.message


async def test_forbidden_is_not_confused_with_rate_limit() -> None:
    state = seed_state(BASE)
    state.fail["/settings"] = 403
    with pytest.raises(CanvasError) as info:
        await CanvasAPI(make_client(state)).course_settings(COURSE_ID)
    assert info.value.code == "canvas_forbidden"


async def test_timeout_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"id": "42", "name": "Kari"})

    client = make_client(transport=httpx.MockTransport(handler))
    assert (await client.get_json("/api/v1/users/self"))["id"] == "42"
    assert calls["n"] == 3


async def test_timeout_eventually_fails_cleanly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("down", request=request)

    with pytest.raises(CanvasError) as info:
        await make_client(transport=httpx.MockTransport(handler)).get_json("/api/v1/users/self")
    assert info.value.code == "canvas_unavailable"


async def test_server_error_is_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, json=[])

    assert await make_client(transport=httpx.MockTransport(handler)).get_paginated("/api/v1/courses") == []


@pytest.mark.invariant
async def test_write_without_permit_is_refused() -> None:
    state = seed_state(BASE)
    client = make_client(state)
    with pytest.raises(CanvasError) as info:
        await client.request("PUT", f"/api/v1/courses/{COURSE_ID}/pages/velkommen", json={"wiki_page": {"body": "x"}})
    assert info.value.code == "canvas_write_blocked"
    assert state.writes == []


@pytest.mark.invariant
async def test_dry_run_blocks_writes_even_with_permit() -> None:
    state = seed_state(BASE)
    api = CanvasAPI(make_client(state, dry_run=True))
    with pytest.raises(DryRunBlocked):
        await api.update_page(COURSE_ID, "velkommen", {"body": "<p>x</p>"}, permit=WritePermit(1, "test"))
    assert state.writes == []


@pytest.mark.invariant
async def test_token_never_sent_to_other_hosts() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "canvas.test":
            return httpx.Response(302, headers={"Location": "https://files.storage.example/blob?sig=abc"})
        return httpx.Response(200, content=b"%PDF-1.7 data")

    client = make_client(transport=httpx.MockTransport(handler))
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        size, _ = await client.download(f"{BASE}/files/9001/download", Path(tmp) / "f.bin", max_bytes=10_000)
    assert size == len(b"%PDF-1.7 data")
    assert seen[0][1] is not None and seen[0][1].startswith("Bearer ")
    assert seen[1][0] == "files.storage.example" and seen[1][1] is None


@pytest.mark.invariant
async def test_pagination_to_foreign_host_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 1}], headers={"Link": '<https://evil.example/x>; rel="next"'})

    with pytest.raises(CanvasError):
        await make_client(transport=httpx.MockTransport(handler)).get_paginated("/api/v1/courses")


async def test_user_agent_is_sent() -> None:
    agents: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers.get("user-agent"))
        return httpx.Response(200, json={"id": "1"})

    await make_client(transport=httpx.MockTransport(handler)).get_json("/api/v1/users/self")
    assert agents[0] and agents[0].startswith("EmneKlar/")


async def test_typed_api_shapes() -> None:
    api = CanvasAPI(make_client())
    courses = await api.list_courses()
    ids = {c["id"] for c in courses}
    assert COURSE_ID in ids and "103" not in ids, "student enrollments are not teaching courses"
    pages = await api.list_pages(COURSE_ID)
    block = next(p for p in pages if p["url"] == "blokkside")
    assert is_block_editor_page(block)
    modules = await api.list_modules(COURSE_ID)
    assert all("items" in m for m in modules)
    questions = await api.list_quiz_questions(COURSE_ID, "401")
    assert answer_is_correct(questions[0]["answers"][0]) and not answer_is_correct(questions[0]["answers"][1])
    assert await api.list_quiz_groups(COURSE_ID, "401") == []
    assert await api.blueprint_template(COURSE_ID) is None
    assert (await api.blueprint_template("102"))["associated_course_count"] == 3
    perms = await api.course_permissions(COURSE_ID)
    assert perms["manage_wiki_update"] is True
    assert await api.get_front_page(COURSE_ID) is not None


async def test_module_with_more_than_100_items_is_fetched_separately() -> None:
    state = seed_state(BASE)
    big = state.courses[COURSE_ID].modules[0]
    big["items"] = [{"id": str(70000 + i), "title": f"Element {i}", "type": "SubHeader", "position": i + 1}
                    for i in range(120)]
    modules = await CanvasAPI(make_client(state)).list_modules(COURSE_ID)
    assert len(modules[0]["items"]) == 120


async def test_module_publish_is_never_sent() -> None:
    api = CanvasAPI(make_client())
    with pytest.raises(CanvasError):
        await api.update_module(COURSE_ID, "201", {"published": False}, permit=WritePermit(1, "test"))
