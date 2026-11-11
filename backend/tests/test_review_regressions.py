"""Regression tests for defects found in code review (undo safety, merges, quiz edits, bank, generation)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from emneklar.core.container import AppContainer
from emneklar.core.storage.models import QuestionBankItem
from emneklar.features.quiz_assistant.bank import generation_plan
from emneklar.features.quiz_assistant.retrieval import Chunk
from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState
from tests.test_quiz_assistant import QUIZ, block, detail, enable_ai, quote_from, review, snapshot, sources_in

pytestmark = pytest.mark.invariant


def apply(client: TestClient, ids: list[int], confirm: bool = False) -> dict:
    response = approve_and_apply(client, ids, confirm=confirm)
    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    return job["result"]


def last_log(client: TestClient) -> dict:
    return client.get(f"/api/changelog?course_id={COURSE_ID}").json()["items"][0]


# ------------------------------------------------------------------------- 1. undo never deletes newer work


def stage_new_page(container: AppContainer, title: str, body: str = "<h2>Velkommen</h2><p>Utkast.</p>") -> dict:
    """A queued «page.create» – kept for changes queued or applied before Emneforside was removed (undo needs it)."""
    return container.changes.stage(
        course_id=COURSE_ID, domain="homepage", kind="page.create", title=f"Ny side: {title}",
        target={"object_type": "page", "object_id": "", "title": title},
        before={}, proposed={"title": title, "body": body, "published": False},
        rationale="Oppretter en ny, upublisert side.", risk="low", source={"feature": "homepage"})


def create_page(container: AppContainer, client: TestClient, title: str) -> dict:
    change = stage_new_page(container, title)
    assert apply(client, [change["id"]])["summary"] == {"applied": 1}
    return change


def test_undo_of_a_created_page_is_blocked_when_the_page_was_edited(canvas_client: TestClient,
                                                                     canvas_container: AppContainer,
                                                                     fake_state: FakeCanvasState) -> None:
    create_page(canvas_container, canvas_client, "Utkast A")
    page = fake_state.courses[COURSE_ID].pages["utkast-a"]
    page["body"] += "<p>Lagt til av læreren etterpå.</p>"
    entry = last_log(canvas_client)
    response = canvas_client.post(f"/api/changelog/{entry['id']}/undo")
    assert response.status_code == 409 and response.json()["error"]["code"] == "undo_conflict"
    assert "utkast-a" in fake_state.courses[COURSE_ID].pages, "the edited page was not deleted"


def test_undo_of_an_unchanged_created_page_backs_it_up_first(canvas_client: TestClient,
                                                             canvas_container: AppContainer,
                                                             fake_state: FakeCanvasState) -> None:
    create_page(canvas_container, canvas_client, "Utkast B")
    body = fake_state.courses[COURSE_ID].pages["utkast-b"]["body"]
    entry = last_log(canvas_client)
    assert canvas_client.post(f"/api/changelog/{entry['id']}/undo").json()["status"] == "undone"
    assert "utkast-b" not in fake_state.courses[COURSE_ID].pages
    undo_entry = last_log(canvas_client)
    backup = canvas_client.get(f"/api/backups/{undo_entry['backup_id']}").json()
    assert backup["content"]["state"]["body"] == body, "the deleted page can be recovered from the backup"


def test_undo_of_a_created_quiz_is_blocked_when_questions_were_added(canvas_client: TestClient,
                                                                     fake_state: FakeCanvasState) -> None:
    ids = []
    for n in range(2):
        item = canvas_client.post(f"/api/courses/{COURSE_ID}/bank", json={
            "question_type": "single_choice", "stem": f"Spørsmål {n} om formater?", "review_status": "approved",
            "answers": [{"text": "JPEG", "correct": True}, {"text": "SVG"}, {"text": "TXT"}]}).json()
        ids.append(item["id"])
    change = canvas_client.post(f"/api/courses/{COURSE_ID}/quiz-builder/stage",
                                json={"title": "Quiz som utvides", "question_ids": ids}).json()
    apply(canvas_client, [change["id"]])
    course = fake_state.courses[COURSE_ID]
    quiz_id = next(q["id"] for q in course.quizzes.values() if q["title"] == "Quiz som utvides")
    course.questions[quiz_id].append({"id": "99999", "quiz_id": quiz_id, "position": 3, "question_name": "Ekstra",
                                      "question_type": "essay_question", "question_text": "<p>Lærerens eget</p>",
                                      "points_possible": 1, "quiz_group_id": None, "answers": []})
    entry = last_log(canvas_client)
    assert canvas_client.post(f"/api/changelog/{entry['id']}/undo").status_code == 409
    assert quiz_id in course.quizzes


# ----------------------------------------------------------------------------- 2./3. quiz suggestions


def _review_with(client: TestClient, container: AppContainer, entry_for_603: dict[str, Any]) -> list[dict]:
    snapshot(client)

    def answer(prompt: str) -> dict:
        sources = sources_in(prompt)
        questions = block(prompt, "SPØRSMÅL")
        out = []
        for q in questions:
            entry: dict[str, Any] = {"question_id": q["question_id"], "key_assessment": "supported",
                                     "correct_answer_ids": [], "issues": [], "evidence": [],
                                     "suggestion": {"stem": "", "answers": [], "explanation": ""}}
            if q["question_id"] == "603":
                entry.update(entry_for_603)
                for e in entry.get("evidence", []):
                    if e.get("quote") == "VERIFIED":
                        e.update(chunk_id=sources[0]["chunk_id"], quote=quote_from(sources[0]))
            out.append(entry)
        return {"questions": out}

    enable_ai(client, container, answer)
    return [review(client, use_ai=True, confirmed=True)["result"], detail(client)["findings"]]  # type: ignore[list-item]


SUGGESTION = {"stem": "PNG støtter gjennomsiktighet.", "explanation": "",
              "answers": [{"text": "Sant", "correct": False}, {"text": "Usant", "correct": True}]}


def test_a_key_change_without_a_verified_source_is_never_offered(canvas_client: TestClient,
                                                                  canvas_container: AppContainer) -> None:
    result, findings = _review_with(canvas_client, canvas_container, {
        "issues": [{"type": "ambiguous", "explanation": "Uklart."}], "suggestion": SUGGESTION})
    ambiguous = next(f for f in findings if f["rule_id"] == "QZ-AI-AMBIGUOUS")
    assert ambiguous["fix"] is None, "the ambiguity finding must not carry an unverified key change"
    assert result["discarded_unverified"] == 1


def test_applying_a_suggestion_keeps_points_and_feedback_changed_after_queuing(
        canvas_client: TestClient, canvas_container: AppContainer, fake_state: FakeCanvasState) -> None:
    _, findings = _review_with(canvas_client, canvas_container, {
        "key_assessment": "wrong_key", "evidence": [{"chunk_id": "x", "quote": "VERIFIED"}], "suggestion": SUGGESTION})
    key = next(f for f in findings if f["rule_id"] == "QZ-AI-KEY")
    change = canvas_client.post(f"/api/quiz/findings/{key['id']}/stage", json={}).json()
    question = next(q for q in fake_state.courses[COURSE_ID].questions[QUIZ] if q["id"] == "603")
    question["points_possible"] = 3
    question["neutral_comments"] = "Ny tilbakemelding fra læreren."
    assert apply(canvas_client, [change["id"]], confirm=True)["summary"] == {"applied": 1}
    assert question["points_possible"] == 3 and question["neutral_comments"] == "Ny tilbakemelding fra læreren."
    assert [(a["text"], a["weight"]) for a in question["answers"]] == [("Sant", 0.0), ("Usant", 100.0)]


# ---------------------------------------------------------------------------------- 4. merging staged changes


def stage(container: AppContainer, **kwargs: Any) -> dict:
    base = {"course_id": COURSE_ID, "domain": "canvas", "rationale": "test", "risk": "low"}
    return container.changes.stage(**{**base, **kwargs})


def test_changes_from_different_features_to_different_fields_stay_separate(canvas_client: TestClient,
                                                                             canvas_container: AppContainer) -> None:
    target = {"object_type": "module", "object_id": "203", "title": "modul 3: video"}
    rename = stage(canvas_container, kind="module.update", title="Nytt navn på modul", target=target,
                   before={"name": "modul 3: video"}, proposed={"name": "Modul 3: Video"},
                   source={"feature": "structure"}, merge=False)
    sequential = stage(canvas_container, kind="module.update", title="Modulinnstillinger", target=target,
                       before={"require_sequential_progress": False}, proposed={"require_sequential_progress": True},
                       source={"feature": "module_requirements"}, merge=True)
    assert rename["id"] != sequential["id"]
    assert canvas_client.get(f"/api/changes/{rename['id']}").json()["proposed"] == {"name": "Modul 3: Video"}


def test_a_new_choice_replaces_the_queued_one_and_its_title(canvas_client: TestClient) -> None:
    first = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                               json={"kind": "default_view", "value": "assignments"}).json()
    second = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                                json={"kind": "default_view", "value": "syllabus"}).json()
    assert first["id"] == second["id"]
    assert second["proposed"] == {"default_view": "syllabus"} and second["title"] == "Startside: Emneplan"


def test_restaging_after_a_conflict_uses_the_current_canvas_state(canvas_client: TestClient,
                                                                  fake_state: FakeCanvasState) -> None:
    first = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                               json={"kind": "default_view", "value": "assignments"}).json()
    fake_state.courses[COURSE_ID].course["default_view"] = "syllabus"  # changed in Canvas meanwhile
    checked = canvas_client.post("/api/changes/check-conflicts", json={"ids": [first["id"]]}).json()["items"][0]
    assert checked["status"] == "conflict"
    again = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                               json={"kind": "default_view", "value": "assignments"}).json()
    assert again["id"] == first["id"] and again["before"] == {"default_view": "syllabus"}
    assert again["status"] == "staged"
    assert apply(canvas_client, [again["id"]])["summary"] == {"applied": 1}


# ------------------------------------------------------------------------- 5. failed quiz creation cleans up


def test_a_failed_quiz_creation_removes_the_partial_quiz(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    item = canvas_client.post(f"/api/courses/{COURSE_ID}/bank", json={
        "question_type": "true_false", "stem": "JPEG er tapsfritt?", "review_status": "approved",
        "answers": [{"text": "Sant"}, {"text": "Usant", "correct": True}]}).json()
    change = canvas_client.post(f"/api/courses/{COURSE_ID}/quiz-builder/stage",
                                json={"title": "Halvferdig", "question_ids": [item["id"]]}).json()
    fake_state.fail["/questions"] = 422
    result = apply(canvas_client, [change["id"]])
    fake_state.fail.clear()
    assert result["summary"] == {"failed": 1}
    assert not any(q["title"] == "Halvferdig" for q in fake_state.courses[COURSE_ID].quizzes.values())
    stored = canvas_client.get(f"/api/changes/{change['id']}").json()
    assert "slettet igjen" in stored["error"]


# ------------------------------------------------------------------------------------- 8./9. question bank


def test_editing_a_bank_question_saves_module_and_type_and_marks_the_source_check(canvas_client: TestClient,
                                                                                canvas_container: AppContainer) -> None:
    with canvas_container.db.session() as session:
        row = QuestionBankItem(course_id=COURSE_ID, question_type="single_choice", stem="Hva er JPEG?",
                               answers=[{"text": "Bildeformat", "correct": True}, {"text": "Lyd", "correct": False},
                                        {"text": "Tekst", "correct": False}], origin="ai", grounding="verified",
                               sources=[{"quote": "JPEG er et bildeformat"}])
        session.add(row)
        session.flush()
        item_id = row.id
    moved = canvas_client.patch(f"/api/bank/{item_id}", json={"module_name": "Modul 2 – Bildebehandling"}).json()
    assert moved["module_name"] == "Modul 2 – Bildebehandling" and moved["grounding"] == "verified"
    retyped = canvas_client.patch(f"/api/bank/{item_id}", json={
        "question_type": "multiple_answers",
        "answers": [{"text": "Bildeformat", "correct": True}, {"text": "Komprimert", "correct": True},
                    {"text": "Tekst", "correct": False}]})
    assert retyped.status_code == 200, retyped.text
    assert retyped.json()["question_type"] == "multiple_answers"
    assert retyped.json()["grounding"] == "partial", "an edited question is no longer the one the quote verified"
    cleared = canvas_client.patch(f"/api/bank/{item_id}", json={"module_name": None}).json()
    assert cleared["module_name"] is None


def test_bank_counts_cover_the_whole_bank_regardless_of_filter(canvas_client: TestClient) -> None:
    for status in ("approved", "draft"):
        canvas_client.post(f"/api/courses/{COURSE_ID}/bank", json={
            "question_type": "true_false", "stem": f"Påstand {status}?", "review_status": status,
            "answers": [{"text": "Sant", "correct": True}, {"text": "Usant"}]})
    filtered = canvas_client.get(f"/api/courses/{COURSE_ID}/bank?status=approved").json()
    assert len(filtered["items"]) == 1 and filtered["counts"] == {"draft": 1, "approved": 1, "rejected": 0}


def test_generation_spreads_excerpts_over_all_selected_content() -> None:
    chunks = [Chunk(id=f"K{i}", object_ref=f"page:{i // 10}", title=f"Side {i // 10}", module=f"Modul {i // 25}",
                    text="ord " * 50) for i in range(100)]
    plan = generation_plan(chunks, 20)
    used = [c for batch in plan for c in batch]
    assert len(plan) == 3 and len(used) == 12
    assert {c.module for c in used} == {"Modul 0", "Modul 1", "Modul 2", "Modul 3"}, "not only the first module"
    small = generation_plan(chunks[:2], 40)
    assert all(batch for batch in small) and {c.id for batch in small for c in batch} == {"K0", "K1"}


def test_generation_consent_states_what_is_actually_sent(canvas_client: TestClient,
                                                        canvas_container: AppContainer) -> None:
    snapshot(canvas_client)
    enable_ai(canvas_client, canvas_container, lambda prompt: {"questions": []})
    plan = canvas_client.post(f"/api/courses/{COURSE_ID}/bank/generate/prepare", json={"count": 8}).json()
    summary = plan["payload_summary"]
    assert plan["available"] and "utdrag" in summary and "i én forespørsel" in summary, summary
    assert "Ingen studentdata" in summary and plan["characters"] > 0
    many = canvas_client.post(f"/api/courses/{COURSE_ID}/bank/generate/prepare", json={"count": 40}).json()
    assert "forespørsler" in many["payload_summary"] and "1 forespørsler" not in many["payload_summary"]


# --------------------------------------------------------------------------------------- smaller findings


def test_the_default_course_is_selected_at_start(container: AppContainer) -> None:
    container.migrate()
    container.settings.update(lambda s: setattr(s.general, "default_course_id", "101"))
    container.startup()
    assert container.settings.get().current_course_id == "101"


def test_queued_html_changes_preview_canvas_images_through_the_proxy(canvas_client: TestClient,
                                                                    canvas_container: AppContainer) -> None:
    change = stage_new_page(canvas_container, "Med logo", '<p><img src="/courses/101/files/9004/preview" alt="Logo"></p>')
    preview = canvas_client.get(f"/api/changes/{change['id']}/preview").json()
    assert "/api/canvas/image?url=" in preview["html"]


def test_copying_settings_from_a_long_quiz_is_supported(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    fake_state.courses[COURSE_ID].quizzes[QUIZ].update(time_limit=720, allowed_attempts=99)
    copied = canvas_client.get(f"/api/courses/{COURSE_ID}/quizzes/{QUIZ}/settings")
    assert copied.status_code == 200 and copied.json()["settings"]["time_limit"] == 720
