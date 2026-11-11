"""The link overview (Innholdskvalitet → Lenker): honest categories, unique places vs occurrences, re-checking that
updates the stored result, changing chosen places only, and «Finn alternativ lenke med KI» from real candidates.
Web pages, the Internet Archive, the provider's web search and the KI answers are simulated."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.core.ai.providers.openai_compat import OpenAICompatibleProvider
from emneklar.core.changes.appliers import ChangeData
from emneklar.core.container import AppContainer
from emneklar.features.accessibility import link_target
from emneklar.features.content_quality.link_replace import rebase, replace_links
from tests.conftest import fake_internet, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

PAGE = ('<p>Les <a href="https://www.example.org/pensum-gammel">Pensumliste for emnet</a> og igjen '
        '<a href="https://www.example.org/pensum-gammel" target="_blank">Pensumliste for emnet</a>.</p>'
        '<p><a href="https://www.example.org/pensum-gammel"><img src="/courses/101/files/9004/preview" alt="Pensum"></a></p>'
        '<p><a href="https://www.example.org/ressurs">Ressurs</a> <a href="https://www.example.org/treg">Treg</a> '
        '<a href="https://www.example.org/lukket">Lukket</a></p>')


@pytest.fixture(autouse=True)
def _fresh() -> None:
    link_target.clear_cache()


def web(extra: dict[str, Any] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, answer in (extra or {}).items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        if url.startswith("https://www.example.org/pensum-gammel"):
            return httpx.Response(404)
        if url.startswith("https://www.example.org/treg"):
            raise httpx.ReadTimeout("slow", request=request)
        if url.startswith("https://www.example.org/lukket"):
            return httpx.Response(401)
        return fake_internet(request)
    return httpx.MockTransport(handler)


def setup(client: TestClient, container: AppContainer, state: FakeCanvasState, extra: dict[str, Any] | None = None) -> None:
    course = state.courses[COURSE_ID]
    course.pages["oppsummering"]["body"] = PAGE
    course.pages["fargelaere"]["body"] += '<p><a href="https://www.example.org/pensum-gammel">Pensumliste for emnet</a></p>'
    container.link_transport = web(extra)
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["content_quality"]}).json()
    assert wait_for_job(client, job["id"], timeout=60)["status"] == "completed"


def overview(client: TestClient) -> dict[str, Any]:
    return client.get(f"/api/courses/{COURSE_ID}/links").json()


def row(data: dict[str, Any], url: str) -> dict[str, Any]:
    return next(x for x in data["links"] if x["url"] == url)


# ----------------------------------------------------------------------------------------------- overview


def test_categories_separate_proven_errors_from_uncertain_checks(canvas_client: TestClient,
                                                                 canvas_container: AppContainer,
                                                                 fake_state: FakeCanvasState) -> None:
    setup(canvas_client, canvas_container, fake_state)
    data = overview(canvas_client)
    missing = row(data, "https://www.example.org/pensum-gammel")
    assert missing["category"] == "broken" and missing["category_label"] == "Fungerer ikke"
    assert missing["title"] == "Pensumliste for emnet", "the title comes from the link text in the content"
    assert missing["places"] == 2 and missing["occurrences"] == 4, "two content items, four links"
    assert "HEAD" in missing["method"] and missing["http_status"] == 404
    assert row(data, "https://www.example.org/ressurs")["category"] == "unchecked", "403 is not proof of anything"
    assert row(data, "https://www.example.org/treg")["category"] == "unchecked", "a timeout is not a broken link"
    assert row(data, "https://www.example.org/lukket")["category"] == "login"
    assert row(data, "https://www.example.org/plan")["title"] is None, "«Klikk her» is no title – the address is shown"
    assert data["summary"]["broken"] >= 1 and data["summary"]["unchecked"] >= 2 and data["summary"]["login"] >= 1
    order = ["broken", "login", "unchecked", "working"]
    categories = [x["category"] for x in data["links"]]
    assert categories == sorted(categories, key=order.index), "proven errors first, then login, uncertain, working"


def test_recheck_updates_the_row_and_the_totals(canvas_client: TestClient, canvas_container: AppContainer,
                                                fake_state: FakeCanvasState) -> None:
    setup(canvas_client, canvas_container, fake_state)
    before = overview(canvas_client)
    canvas_container.link_transport = web({"https://www.example.org/pensum-gammel": httpx.Response(200)})
    result = canvas_client.post("/api/content-quality/recheck",
                                json={"url": "https://www.example.org/pensum-gammel", "course_id": COURSE_ID}).json()
    assert result["category"] == "working" and result["summary"]["broken"] == before["summary"]["broken"] - 1
    after = overview(canvas_client)
    assert row(after, "https://www.example.org/pensum-gammel")["category"] == "working"
    assert after["checked_at"] == before["checked_at"], "the time of the full check is kept apart from the row's"
    assert row(after, "https://www.example.org/pensum-gammel")["checked_at"] != row(before, "https://www.example.org/pensum-gammel")["checked_at"]


# ----------------------------------------------------------------------------------- changing chosen places


def test_only_the_chosen_places_change_and_link_content_is_kept(canvas_client: TestClient,
                                                                canvas_container: AppContainer,
                                                                fake_state: FakeCanvasState) -> None:
    setup(canvas_client, canvas_container, fake_state)
    body = {"old_url": "https://www.example.org/pensum-gammel", "new_url": "https://www.example.org/pensum-2026",
            "places": [{"object_type": "page", "object_id": "oppsummering", "title": "Oppsummering"}]}
    preview = canvas_client.post(f"/api/courses/{COURSE_ID}/links/replace/preview", json=body).json()
    (place,) = preview["places"]
    assert place["count"] == 3 and len(place["changes"]) == 3
    assert all("pensum-2026" in ch["after"] and "pensum-gammel" in ch["before"] for ch in place["changes"])
    result = canvas_client.post(f"/api/courses/{COURSE_ID}/links/replace/approve", json=body).json()
    (change_id,) = result["approved"]
    change = next(c for c in canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"] if c["id"] == change_id)
    html = change["proposed"]["body"]
    assert html.count("https://www.example.org/pensum-2026") == 3 and "example.org/missing" not in html
    assert html.count(">Pensumliste for emnet</a>") == 2 and 'target="_blank"' in html and 'alt="Pensum"' in html
    assert change["status"] == "approved" and change["ai_generated"] is False
    assert not [r for r in fake_state.requests if r[0] in ("PUT", "POST")], "approving never writes to Canvas"
    others = canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"]
    assert not any(c["target"]["object_id"] == "fargelaere" for c in others), "places not chosen are not changed"


def test_a_new_link_text_is_only_used_when_chosen(canvas_client: TestClient) -> None:
    html, count, _ = replace_links(PAGE, "https://www.example.org/pensum-gammel", "https://ny.example.org/p", "Pensum 2026")
    assert count == 3 and html.count(">Pensum 2026</a>") == 2
    assert 'aria-label="Pensum 2026"' in html and 'alt="Pensum"' in html, "an image link keeps its image"
    same, _, _ = replace_links(PAGE, "https://www.example.org/pensum-gammel", "https://ny.example.org/p")
    assert same.count(">Pensumliste for emnet</a>") == 2


def test_a_queued_change_is_rebuilt_on_newer_content() -> None:
    data = ChangeData(1, COURSE_ID, "page.update_body", {"object_type": "page", "object_id": "x"}, {"body": "gammel"},
                      {"body": "x"})
    source = {"fixes": [{"old": "https://www.example.org/pensum-gammel", "new": "https://ny.example.org/p", "text": None}]}
    newer = '<p>Ny tekst fra læreren.</p><a href="https://www.example.org/pensum-gammel">Pensum</a>'
    rebuilt = rebase(data, source, {"body": newer})
    assert rebuilt == {"body": '<p>Ny tekst fra læreren.</p><a href="https://ny.example.org/p">Pensum</a>'}


def test_invalid_or_unchanged_addresses_are_refused(canvas_client: TestClient, canvas_container: AppContainer,
                                                    fake_state: FakeCanvasState) -> None:
    setup(canvas_client, canvas_container, fake_state)
    place = [{"object_type": "page", "object_id": "oppsummering"}]
    for new in ("javascript:alert(1)", "www.example.org/x", "https://www.example.org/pensum-gammel"):
        response = canvas_client.post(f"/api/courses/{COURSE_ID}/links/replace/preview",
                                      json={"old_url": "https://www.example.org/pensum-gammel", "new_url": new, "places": place})
        assert response.status_code == 400, new


# --------------------------------------------------------------------------------- alternatives with KI


SEARCH_HITS = [{"type": "web_search_result", "url": "https://www.example.org/pensum-2026", "title": "Pensumliste 2026",
                "page_age": "2026"},
               {"type": "web_search_result", "url": "https://andre.example.org/pensum", "title": "Annen pensumliste"},
               {"type": "web_search_result", "url": "https://www.example.org/pensum-gammel", "title": "Den gamle"}]
ARCHIVE = {"archived_snapshots": {"closest": {"available": True, "status": "200", "timestamp": "20240115120000",
                                              "url": "http://web.archive.org/web/20240115120000/https://www.example.org/pensum-gammel"}}}


def ai(container: AppContainer, client: TestClient, choices: list[dict[str, Any]], sent: list[dict[str, Any]],
       hits: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Anthropic, simulated (search and assessment). Returns the state – change it between requests, since the
    provider is reused."""
    state: dict[str, Any] = {"choices": choices, "hits": SEARCH_HITS if hits is None else hits}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        if any(t.get("type") == "web_search_20250305" for t in body.get("tools") or []):
            return httpx.Response(200, json={"content": [
                {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "pensum"}},
                {"type": "web_search_tool_result", "tool_use_id": "s1", "content": state["hits"]},
                {"type": "text", "text": "ferdig – se også https://oppdiktet.example.org/fake"}],
                "stop_reason": "end_turn", "usage": {"server_tool_use": {"web_search_requests": 1}}})
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(
            {"choices": state["choices"], "note": "Vurdert."})}], "stop_reason": "end_turn", "usage": {}})

    container.ai_transport = httpx.MockTransport(handler)
    assert client.put("/api/ai/providers/anthropic", json={"enabled": True, "api_key": "sk-ant-api-test-1234567890"}
                      ).status_code == 200
    container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    return state


def page(title: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html"}, text=f"<title>{title}</title><main>{title}</main>")


ALT_WEB = {"https://www.example.org/pensum-2026": page("Pensumliste 2026"),
           "https://andre.example.org/pensum": page("Annen pensumliste"),
           "https://archive.org/wayback/available": httpx.Response(200, json=ARCHIVE),
           "https://web.archive.org/": page("Arkivert pensumliste")}


def alternatives(client: TestClient, **body: Any) -> httpx.Response:
    return client.post(f"/api/courses/{COURSE_ID}/links/alternatives", json={
        "url": "https://www.example.org/pensum-gammel?session=abc", "link_text": "Pensumliste for emnet",
        "page_title": "Oppsummering", **body})


def test_alternatives_come_only_from_real_candidates(canvas_client: TestClient, canvas_container: AppContainer,
                                                     fake_state: FakeCanvasState) -> None:
    setup(canvas_client, canvas_container, fake_state, ALT_WEB)
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, [
        {"id": "k1", "relation": "same", "publisher": "Example", "reason": "Samme liste for 2026.", "limitations": []},
        {"id": "k99", "relation": "same", "publisher": "Oppdiktet", "reason": "x", "limitations": []},
        {"id": "k3", "relation": "same", "publisher": "Internet Archive", "reason": "Kopi fra 2024.",
         "limitations": ["Innholdet kan være utdatert."]}], sent)
    plan = canvas_client.post(f"/api/courses/{COURSE_ID}/links/alternatives/prepare",
                              json={"url": "https://www.example.org/pensum-gammel"}).json()
    assert plan["available"] and plan["search"]["available"] and "søker på nettet" in plan["payload_summary"]
    assert "Internet Archive" in plan["payload_summary"]  # the archive lookup is an external service too
    assert alternatives(canvas_client).status_code == 409 and sent == [], "nothing is sent before consent"

    answer = alternatives(canvas_client, confirmed=True).json()
    urls = [s["url"] for s in answer["suggestions"]]
    assert urls == ["https://www.example.org/pensum-2026",
                    "https://web.archive.org/web/20240115120000/https://www.example.org/pensum-gammel"]
    assert "oppdiktet" not in json.dumps(answer), "an address the model made up is never shown"
    first, archived = answer["suggestions"]
    assert first["relation_label"] == "Samme ressurs, ny adresse" and first["check"]["label"] == "Fungerer"
    assert first["title"] == "Pensumliste 2026" and first["reason"] == "Samme liste for 2026." and first["check"]["checked_at"]
    assert archived["relation"] == "archive" and archived["archived_at"] == "15.01.2024"
    assert answer["searched"] is True and answer["label"] == "KI-forslag – må vurderes"
    search = next(b for b in sent if b.get("tools") and b["tools"][0].get("type") == "web_search_20250305")
    assert "site:www.example.org" in json.dumps(search, ensure_ascii=False)
    assert "session=abc" not in json.dumps(sent, ensure_ascii=False), "no sensitive parameters are sent"
    assessment = json.dumps(sent[-1], ensure_ascii=False)
    assert "[k1] search" in assessment
    assert "search: https://www.example.org/pensum-gammel" not in assessment, "the old address is never a candidate"
    assert canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"] == [], "nothing is queued"


def test_without_web_search_the_limits_are_explained(canvas_client: TestClient, canvas_container: AppContainer,
                                                     fake_state: FakeCanvasState, monkeypatch: pytest.MonkeyPatch) -> None:
    setup(canvas_client, canvas_container, fake_state, ALT_WEB)
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, [{"id": "k1", "relation": "archive", "publisher": "Internet Archive",
                                          "reason": "Arkivert kopi.", "limitations": []}], sent)
    monkeypatch.setattr(canvas_container.ai, "search_route", lambda task: None)
    answer = alternatives(canvas_client, confirmed=True).json()
    assert answer["searched"] is False and "Nettsøk krever" in answer["search_note"]
    assert [s["origin"] for s in answer["suggestions"]] == ["archive"]
    assert not any(b.get("tools") for b in sent), "no search was attempted"


def test_no_good_candidates_is_said_plainly(canvas_client: TestClient, canvas_container: AppContainer,
                                            fake_state: FakeCanvasState) -> None:
    setup(canvas_client, canvas_container, fake_state, {**ALT_WEB, "https://archive.org/wayback/available":
                                                        httpx.Response(200, json={"archived_snapshots": {}})})
    sent: list[dict[str, Any]] = []
    state = ai(canvas_container, canvas_client, [], sent, hits=[])
    answer = alternatives(canvas_client, confirmed=True).json()
    assert answer["none_found"] is True and answer["suggestions"] == [] and "Fant ingen kandidater" in answer["note"]
    assert len(sent) == 1, "no assessment without candidates"

    sent.clear()
    state["hits"] = SEARCH_HITS
    answer = alternatives(canvas_client, confirmed=True).json()
    assert answer["none_found"] is True and answer["considered"] >= 1, "the model may decide that none fits"


async def test_openai_web_search_returns_only_the_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/responses") and body["tools"] == [{"type": "web_search"}]
        assert body["include"] == ["web_search_call.action.sources"]
        return httpx.Response(200, json={"output": [
            {"type": "web_search_call", "action": {"type": "search", "sources": [
                {"type": "url", "url": "https://a.example.org/1"}]}},
            {"type": "message", "content": [{"type": "output_text", "text": "Se https://oppdiktet.example.org",
                                             "annotations": [{"type": "url_citation", "url": "https://b.example.org/2",
                                                              "title": "B", "start_index": 0, "end_index": 3}]}]}]})

    provider = OpenAICompatibleProvider("openai", base_url="https://api.openai.com/v1", api_key="sk-test-123",
                                        local=False, transport=httpx.MockTransport(handler))
    hits = await provider.web_search("gpt-test", "pensum")
    assert [h.url for h in hits] == ["https://a.example.org/1", "https://b.example.org/2"]
