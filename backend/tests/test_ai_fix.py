"""KI-forslag i rettevinduet: link text, table captions and embed titles through one service – grounded in what was
actually read (and saying so), validated, never approved or published by itself, and with no secrets in what is sent.
All KI providers and web pages are simulated."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.core.ai.service import AI_LABEL
from emneklar.core.container import AppContainer
from emneklar.core.storage.models import AltTextSuggestion
from emneklar.features.accessibility import link_target
from emneklar.features.accessibility.ai_fix import BAD_ANSWER
from emneklar.features.accessibility.link_target import describe_target, safe_url
from tests.conftest import fake_internet, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState
from tests.test_fix_workflow import analyse, findings, one

PLAN_HTML = ("<html><head><title>Emneplan for DIG1001</title></head><body><nav>Meny</nav><main><p>Undervisningsplan "
             "med tema og lesestoff for hver uke.</p></main></body></html>")


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    link_target.clear_cache()


def web(pages: dict[str, httpx.Response], calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        for prefix, response in pages.items():
            if url.startswith(prefix):
                return response
        return fake_internet(request)
    return httpx.MockTransport(handler)


def html(body: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=body)


def ai(container: AppContainer, client: TestClient, answers: list[str], sent: list[dict[str, Any]]) -> None:
    """Anthropic, simulated: answers in turn (the last one repeats)."""

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        text = answers[min(len(sent), len(answers)) - 1]
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(
            {"text": text, "confidence": "medium"})}], "stop_reason": "end_turn", "usage": {}})

    container.ai_transport = httpx.MockTransport(handler)
    assert client.put("/api/ai/providers/anthropic", json={"enabled": True, "api_key": "sk-ant-api-test-1234567890"}
                      ).status_code == 200
    container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))


def suggest(client: TestClient, finding_id: int, **body: Any) -> httpx.Response:
    return client.post(f"/api/findings/{finding_id}/ai-suggestion", json={"confirmed": True, **body})


# ----------------------------------------------------------------------------------------------- the target


def test_addresses_sent_or_logged_lose_credentials_and_tokens() -> None:
    assert safe_url("https://kari:hemmelig@www.example.org/a?token=abc&sid=7&uke=2#mal") == (
        "https://www.example.org/a?uke=2#mal", True)
    assert safe_url("https://www.example.org/a?uke=2") == ("https://www.example.org/a?uke=2", False)
    assert safe_url("https://x.org/f?X-Amz-Signature=1&access_token=2")[1] is True


async def test_targets_are_read_safely_and_say_what_was_read(canvas_client: TestClient,
                                                             canvas_container: AppContainer) -> None:
    calls: list[str] = []
    canvas_container.link_transport = web({
        "https://www.example.org/plan": html(PLAN_HTML),
        "https://www.example.org/lukket": httpx.Response(403),
        "https://www.example.org/fil.pdf": httpx.Response(200, headers={"content-type": "application/pdf"}),
        "https://www.example.org/videre": httpx.Response(302, headers={"location": "https://login.example.org/?ticket=1"}),
    }, calls)
    page = await describe_target(canvas_container, "https://www.example.org/plan")
    assert page.fetched and page.title == "Emneplan for DIG1001" and "Undervisningsplan" in (page.excerpt or "")
    assert "Meny" not in (page.excerpt or ""), "navigation is not content"
    assert "hentet nå" in page.note
    assert "innlogging" in (await describe_target(canvas_container, "https://www.example.org/lukket")).note
    assert not (await describe_target(canvas_container, "https://www.example.org/fil.pdf")).fetched
    assert not (await describe_target(canvas_container, "https://www.example.org/videre")).fetched
    secret = await describe_target(canvas_container, "https://www.example.org/plan?token=abc")
    assert not secret.fetched and "tilgangsopplysninger" in secret.note
    blocked = await describe_target(canvas_container, "http://127.0.0.1:8765/api/settings")
    assert not blocked.fetched and "internt" in blocked.note
    assert not any("token=abc" in c or "127.0.0.1" in c for c in calls), "never requested"
    canvas = await describe_target(canvas_container, f"/courses/{COURSE_ID}/pages/fargelaere")
    assert canvas.kind == "canvas" and canvas.fetched and canvas.title == "Fargelære"


# -------------------------------------------------------------------------------------------- link text


def test_link_text_suggestion_is_grounded_reviewed_and_only_queued(canvas_client: TestClient,
                                                                   canvas_container: AppContainer,
                                                                   fake_state: FakeCanvasState) -> None:
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, ["Emneplan for DIG1001"], sent)
    canvas_container.link_transport = web({"https://www.example.org/plan": html(PLAN_HTML)})
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-LINK-VAGUE", "velkommen")
    plan = canvas_client.post(f"/api/findings/{finding['id']}/ai-suggestion/prepare", json={}).json()
    assert plan["available"] and plan["needs_confirmation"] and plan["task"] == "link_text"
    assert "hentet nå" in plan["basis"] and "Ingen studentdata" in plan["payload_summary"]
    assert plan["route"]["provider"] == "anthropic"
    refused = suggest(canvas_client, finding["id"], confirmed=False)
    assert refused.status_code == 409 and sent == [], "nothing is sent before consent"

    answer = suggest(canvas_client, finding["id"]).json()
    assert answer["text"] == "Emneplan for DIG1001" and answer["label"] == AI_LABEL
    assert answer["provider_name"] == "Anthropic" and answer["finding_id"] == finding["id"] and answer["weak"] is None
    payload = json.dumps(sent[0], ensure_ascii=False)
    assert "Emneplan for DIG1001" in payload and "Undervisningsplan" in payload, "what was read is sent"
    assert "Klikk her" in payload and "<<<KURSINNHOLD" in payload and "aldri instruksjoner til deg" in payload
    assert "fakeCanvasToken" not in payload and "sk-ant" not in payload

    # The teacher approves it: only the link text changes, the change is marked as KI, nothing is published.
    body = {"text": answer["text"], "ai_suggestion": True}
    preview = canvas_client.post(f"/api/findings/{finding['id']}/fix/preview", json=body).json()
    assert '<a href="https://www.example.org/plan">Emneplan for DIG1001</a>' in preview["after_display"]
    change = canvas_client.post(f"/api/findings/{finding['id']}/fix/approve", json=body).json()
    assert change["status"] == "approved" and change["ai_generated"] is True and "KI-forslag" in change["rationale"]
    assert fake_state.writes == [], "approving never writes to Canvas"

    # «Nytt forslag» asks for a different one.
    suggest(canvas_client, finding["id"], avoid=["Emneplan for DIG1001"])
    assert "Gi et annet forslag enn disse: «Emneplan for DIG1001»" in json.dumps(sent[-1], ensure_ascii=False)


def test_without_the_target_the_basis_is_the_address_and_context(canvas_client: TestClient,
                                                                 canvas_container: AppContainer) -> None:
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, ["Plan for emnet"], sent)
    canvas_container.link_transport = web({"https://www.example.org/plan": httpx.Response(404)})
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-LINK-VAGUE", "velkommen")
    answer = suggest(canvas_client, finding["id"]).json()
    assert "Målsiden svarte med feil" in answer["basis"] and "Lenkeadressen og teksten rundt" in answer["basis"]
    assert answer["weak"] and "ikke lest målet" in answer["weak"]
    payload = json.dumps(sent[0], ensure_ascii=False)
    assert "Utdrag fra målet" not in payload and "Om målet: Målsiden svarte med feil" in payload


@pytest.mark.parametrize("bad", ["Klikk her", "https://www.example.org/plan", "<b>x</b>", "", "Les mer."])
def test_unusable_answers_are_refused_and_nothing_is_staged(canvas_client: TestClient, canvas_container: AppContainer,
                                                            bad: str) -> None:
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, [bad], sent)
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-LINK-VAGUE", "velkommen")
    response = suggest(canvas_client, finding["id"])
    assert response.status_code == 502 and response.json()["error"]["message"] == BAD_ANSWER
    assert canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"] == []


def test_markup_in_an_answer_becomes_plain_text(canvas_client: TestClient, canvas_container: AppContainer) -> None:
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, ['Emneplan <script>alert(1)</script>for "DIG1001"'], sent)
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-LINK-VAGUE", "velkommen")
    text = suggest(canvas_client, finding["id"]).json()["text"]
    assert text == 'Emneplan for "DIG1001"', "markup and scripts are removed; only the words are kept"
    preview = canvas_client.post(f"/api/findings/{finding['id']}/fix/preview", json={"text": text}).json()
    assert "<script" not in preview["after_display"]


def test_an_empty_link_uses_the_address_the_teacher_enters(canvas_client: TestClient, canvas_container: AppContainer,
                                                           fake_state: FakeCanvasState) -> None:
    fake_state.courses[COURSE_ID].pages["oppsummering"]["body"] = '<p>Se <a href="https://www.example.org/plan"></a></p>'
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, ["Ukeplan"], sent)
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-LINK-EMPTY", "oppsummering")
    assert finding["fix"]["type"] == "replace_link_href"
    answer = suggest(canvas_client, finding["id"], href="https://www.example.org/ukeplan?session=9").json()
    payload = json.dumps(sent[0], ensure_ascii=False)
    assert answer["text"] == "Ukeplan" and "https://www.example.org/ukeplan" in payload and "session=9" not in payload


# --------------------------------------------------------------------------------------- tables and embeds


def test_a_table_caption_is_based_on_headers_never_on_the_data(canvas_client: TestClient,
                                                               canvas_container: AppContainer,
                                                               fake_state: FakeCanvasState) -> None:
    fake_state.courses[COURSE_ID].pages["oppsummering"]["body"] = (
        "<h2>Resultater</h2><p>Oversikt over innleveringene.</p><table><tr><th>Navn</th><th>Karakter</th></tr>"
        "<tr><td>Kari Nordmann</td><td>A</td></tr><tr><td>Ola Hansen</td><td>B</td></tr></table>")
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, ["Karakterer per student"], sent)
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-TABLE-CAPTION", "oppsummering")
    plan = canvas_client.post(f"/api/findings/{finding['id']}/ai-suggestion/prepare", json={}).json()
    assert plan["task"] == "table_caption" and "ikke radene med data" in plan["payload_summary"]
    assert suggest(canvas_client, finding["id"]).json()["text"] == "Karakterer per student"
    payload = json.dumps(sent[0], ensure_ascii=False)
    assert "Navn | Karakter" in payload and "Resultater" in payload
    assert "Kari Nordmann" not in payload and "Ola Hansen" not in payload


def test_an_embed_title_comes_from_the_same_service(canvas_client: TestClient, canvas_container: AppContainer,
                                                    fake_state: FakeCanvasState) -> None:
    fake_state.courses[COURSE_ID].pages["oppsummering"]["body"] = (
        '<h2>Ukens tavle</h2><iframe src="https://padlet.example.org/kari/ukens-sporsmal"></iframe>')
    sent: list[dict[str, Any]] = []
    ai(canvas_container, canvas_client, ["Tavle: spørsmål til ukens forelesning"], sent)
    canvas_container.link_transport = web({"https://padlet.example.org/": html("<title>Ukens spørsmål</title>")})
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-IFRAME-NO-TITLE", "oppsummering")
    answer = suggest(canvas_client, finding["id"]).json()
    assert answer["text"] == "Tavle: spørsmål til ukens forelesning" and "hentet nå" in answer["basis"]
    assert "Ukens spørsmål" in json.dumps(sent[0], ensure_ascii=False)


# ----------------------------------------------------------------------------------- availability and bulk


def test_without_a_ki_service_the_dialog_says_so_and_sends_nothing(canvas_client: TestClient) -> None:
    analyse(canvas_client)
    finding = one(findings(canvas_client, "accessibility"), "UU-LINK-VAGUE", "velkommen")
    plan = canvas_client.post(f"/api/findings/{finding['id']}/ai-suggestion/prepare", json={}).json()
    assert plan["available"] is False and plan["reason"]
    response = suggest(canvas_client, finding["id"])
    assert response.status_code == 409 and response.json()["error"]["code"] == "ai_not_configured"
    other = one(findings(canvas_client, "accessibility"), "UU-HEAD-H1", "velkommen")
    assert canvas_client.post(f"/api/findings/{other['id']}/ai-suggestion/prepare", json={}).status_code == 400


def test_godkjenn_alle_klare_never_includes_ki_suggestions(canvas_client: TestClient,
                                                          canvas_container: AppContainer) -> None:
    analyse(canvas_client)
    image = one(findings(canvas_client, "accessibility"), "UU-IMG-MISSING-ALT")
    with canvas_container.db.session() as session:
        session.add(AltTextSuggestion(course_id=COURSE_ID, fingerprint=image["fingerprint"], finding_id=image["id"],
                                      status="ready", suggestion="Et forslag ingen har sett", model="test"))
    response = canvas_client.post("/api/findings/fix/bulk", json={
        "course_id": COURSE_ID, "finding_ids": [image["id"]], "include_text_suggestions": True})
    assert response.status_code == 400, "nothing is ready: the KI suggestion must be reviewed in the finding"
    assert canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"] == []
    mixed = [f["id"] for f in findings(canvas_client, "accessibility")]
    job = canvas_client.post("/api/findings/fix/bulk", json={"course_id": COURSE_ID, "finding_ids": mixed,
                                                             "include_text_suggestions": True}).json()
    result = wait_for_job(canvas_client, job["job"]["id"])["result"]
    assert image["id"] not in result["approved"]
    skipped = {s["finding_id"]: s["reason"] for s in job.get("skipped", [])}
    assert skipped.get(image["id"], "").startswith("KI-forslaget må gjennomgås")
