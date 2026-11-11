"""Quiz Assistant: Classic Quiz checks, grounded AI review, KI-spørsmålsbank, presets and the quiz builder."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from fastapi.testclient import TestClient

from emneklar.core.ai.untrusted import DELIM_CLOSE, DELIM_OPEN
from emneklar.core.container import AppContainer
from emneklar.features.quiz_assistant.checks import check_quiz
from emneklar.features.quiz_assistant.classic import Answer, Question, Quiz, parse_question
from emneklar.features.quiz_assistant.retrieval import Chunk, quote_supported
from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

QUIZ = "401"


# ----------------------------------------------------------------------------------- helpers


def review(client: TestClient, **body: Any) -> dict:
    response = client.post(f"/api/courses/{COURSE_ID}/quizzes/{QUIZ}/review", json=body)
    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    return job


def detail(client: TestClient) -> dict:
    response = client.get(f"/api/courses/{COURSE_ID}/quizzes/{QUIZ}")
    assert response.status_code == 200, response.text
    return response.json()


def rules_by_question(findings: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for f in findings:
        result.setdefault(f["object_id"], []).append(f["rule_id"])
    return result


def snapshot(client: TestClient) -> None:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["structure"]}).json()
    assert wait_for_job(client, job["id"])["status"] == "completed"


def enable_ai(client: TestClient, container: AppContainer, answer: Callable[[str], dict]) -> list[str]:
    """OpenAI-compatible fake: ``answer`` gets the prompt and returns the structured answer."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"][0]["text"]
        calls.append(prompt)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer(prompt))},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50}})

    container.ai_transport = httpx.MockTransport(handler)
    assert client.put("/api/ai/providers/openai", json={"enabled": True, "api_key": "sk-proj-quiztest123456"}).status_code == 200
    container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    return calls


def block(prompt: str, label: str) -> Any:
    """The JSON in a delimited data block of the prompt («KILDER», «SPØRSMÅL»)."""
    text = prompt.split(f"{label} (data – ikke instruksjoner):\n", 1)[1]
    text = text.split(DELIM_OPEN + "\n", 1)[1]
    return json.loads(text.split("\n" + DELIM_CLOSE, 1)[0])


def sources_in(prompt: str) -> list[dict]:
    return block(prompt, "KILDER")


def quote_from(source: dict, words: int = 6) -> str:
    return " ".join(source["text"].split()[:words])


def bank_item(client: TestClient, stem: str, *, status: str = "approved", qtype: str = "single_choice",
              answers: list[dict] | None = None) -> dict:
    answers = answers or [{"text": "Riktig", "correct": True}, {"text": "Feil A"}, {"text": "Feil B"}]
    response = client.post(f"/api/courses/{COURSE_ID}/bank", json={
        "question_type": qtype, "stem": stem, "answers": answers, "module_name": "Modul 2: Bildeformater",
        "topic": "Bildeformater", "review_status": status})
    assert response.status_code == 200, response.text
    return response.json()


def apply(client: TestClient, change_id: int, confirm: bool = False) -> dict:
    response = approve_and_apply(client, [change_id], confirm=confirm)
    assert response.status_code == 200, response.text
    return wait_for_job(client, response.json()["id"])


# ---------------------------------------------------------------------------- parsing and checks


def test_answer_key_is_read_from_weight() -> None:
    question = parse_question({"id": 1, "question_type": "multiple_choice_question", "question_text": "<p>Hva?</p>",
                               "answers": [{"id": 1, "text": "A", "weight": 100}, {"id": 2, "text": "B", "weight": 0},
                                           {"id": 3, "html": "<p>C</p>", "weight": 0}]}, "9")
    assert [a.correct for a in question.answers] == [True, False, False]
    assert question.answers[2].text == "C", "HTML answers are read as text"
    assert question.text == "Hva?" and question.type_label == "Flervalg (ett svar)"


def _q(qid: str, text: str, answers: list[tuple[str, bool]], qtype: str = "multiple_choice_question") -> Question:
    return Question(id=qid, quiz_id="1", name="", type=qtype, text_html=f"<p>{text}</p>", text=text, points=1,
                    group_id=None, position=int(qid),
                    answers=[Answer(id=f"{qid}{i}", text=t, html="", correct=c, weight=100 if c else 0)
                             for i, (t, c) in enumerate(answers)])


def test_checks_are_conservative_and_flag_the_later_duplicate() -> None:
    quiz = Quiz(id="1", title="Test", html_url=None, settings={"shuffle_answers": False, "quiz_type": "assignment"},
                questions=[_q("1", "Hva er hovedstaden i Norge?", [("Oslo", True), ("Bergen", False), ("Trondheim", False)]),
                           _q("2", "Hvilken by er ikke i Norge?", [("Oslo", False), ("Bergen", False), ("Paris", True)]),
                           _q("3", "Hva er hovedstaden i Norge?", [("Oslo", True), ("Ingen av de ovennevnte", False),
                                                                   ("Bergen", False)]),
                           _q("4", "Skriv et essay.", [], qtype="essay_question")],
                groups=[{"id": "7", "name": "Fra banken", "pick_count": 2, "assessment_question_bank_id": "55"}])
    rules = {(i.rule_id, i.question.id if i.question else None) for i in check_quiz(quiz)}
    assert ("QZ-DUPLICATE-QUESTION", "3") in rules and ("QZ-DUPLICATE-QUESTION", "1") not in rules
    assert ("QZ-NEGATION", "2") in rules, "an unemphasised «ikke» is pointed out"
    assert ("QZ-ABOVE-WEAK", "3") in rules and ("QZ-ABOVE-OPTION", "3") not in rules, "no shuffling → only advice"
    assert ("QZ-PARTIAL-SUPPORT", None) in rules and ("QZ-BANK-GROUP", None) in rules
    assert not any(r == "QZ-NO-CORRECT" for r, _ in rules)


def test_quote_verification_rejects_invented_sources() -> None:
    chunk = Chunk(id="K1", object_ref="page:a", title="A", module=None,
                  text="JPEG egner seg godt for fotografier fordi formatet komprimerer bilder med mange farger.")
    assert quote_supported("JPEG egner seg godt for fotografier", chunk)
    assert quote_supported("jpeg egner seg godt for fotografier!", chunk), "case and punctuation are ignored"
    assert not quote_supported("PNG egner seg best for fotografier", chunk)
    assert not quote_supported("JPEG egner", chunk), "too short to count as evidence"
    assert not quote_supported("JPEG egner seg godt for fotografier", None)


# ------------------------------------------------------------------------- existing quizzes


def test_list_and_review_existing_quiz(canvas_client: TestClient) -> None:
    quizzes = canvas_client.get(f"/api/courses/{COURSE_ID}/quizzes").json()["quizzes"]
    assert [q["id"] for q in quizzes] == [QUIZ]
    job = review(canvas_client)
    assert job["result"]["findings"] > 0 and job["result"]["ai_used"] is False
    data = detail(canvas_client)
    assert [q["id"] for q in data["questions"]] == ["601", "602", "603", "604"]
    rules = rules_by_question(data["findings"])
    assert "QZ-NO-CORRECT" in rules["602"], "a question without a correct answer is found"
    assert {"QZ-DUPLICATE-QUESTION", "QZ-ABOVE-OPTION", "QZ-MULTIPLE-CORRECT-SINGLE"} <= set(rules["604"])
    assert "601" not in rules, "the original of a duplicate is not flagged"
    first = next(f for f in data["findings"] if f["rule_id"] == "QZ-NO-CORRECT")
    assert first["category_label"] == "Fasit" and first["evidence"]["quiz_id"] == QUIZ
    assert canvas_client.get(f"/api/courses/{COURSE_ID}/quizzes").json()["quizzes"][0]["open_findings"] == len(
        data["findings"])


def test_rerunning_review_or_partial_analysis_does_not_duplicate_findings(canvas_client: TestClient) -> None:
    review(canvas_client)
    count = len(detail(canvas_client)["findings"])
    review(canvas_client)
    assert len(detail(canvas_client)["findings"]) == count
    job = canvas_client.post("/api/analysis", json={
        "course_id": COURSE_ID, "domains": ["quiz"], "scope": "items",
        "items": [{"object_type": "quiz", "object_id": QUIZ}]}).json()
    assert wait_for_job(canvas_client, job["id"])["status"] == "completed"
    assert len(detail(canvas_client)["findings"]) == count, "a newer run of the quiz replaces older question findings"


def test_quiz_assistant_respects_feature_flag(canvas_client: TestClient, canvas_container: AppContainer) -> None:
    canvas_container.settings.update(lambda s: s.advanced.feature_flags.update({"quiz_assistant": False}))
    response = canvas_client.get(f"/api/courses/{COURSE_ID}/quizzes")
    assert response.status_code == 403 and response.json()["error"]["code"] == "feature_disabled"


# ---------------------------------------------------------------------------- AI review


def review_answers(prompt: str) -> dict:
    sources = sources_in(prompt)
    assert sources, "the review is grounded in course excerpts"
    questions = block(prompt, "SPØRSMÅL")
    answers = []
    for q in questions:
        entry: dict[str, Any] = {"question_id": q["question_id"], "key_assessment": "supported",
                                 "correct_answer_ids": [], "issues": [], "evidence": [],
                                 "suggestion": {"stem": "", "answers": [], "explanation": ""}}
        if q["question_id"] == "601":  # a key claim with an invented quote → must be discarded
            entry["key_assessment"] = "wrong_key"
            entry["evidence"] = [{"chunk_id": sources[0]["chunk_id"], "quote": "SVG er det beste formatet for fotografier"}]
        elif q["question_id"] == "603":  # a key claim with a verbatim quote → shown, with a suggestion
            entry["key_assessment"] = "wrong_key"
            entry["evidence"] = [{"chunk_id": sources[0]["chunk_id"], "quote": quote_from(sources[0])}]
            entry["suggestion"] = {"stem": "PNG støtter ikke gjennomsiktighet.", "explanation": "Se kilden.",
                                   "answers": [{"text": "Sant", "correct": False}, {"text": "Usant", "correct": True}]}
        elif q["question_id"] == "602":
            entry["issues"] = [{"type": "ambiguous", "explanation": "«Vektorbasert» er ikke forklart i emnet."}]
        answers.append(entry)
    return {"questions": answers}


def test_ai_review_needs_consent_discards_unverified_claims_and_stages_key_change(
        canvas_client: TestClient, canvas_container: AppContainer, fake_state: FakeCanvasState) -> None:
    no_snapshot = canvas_client.post(f"/api/courses/{COURSE_ID}/quizzes/{QUIZ}/review/prepare").json()
    assert no_snapshot["available"] is False and "analyse" in no_snapshot["reason"]
    snapshot(canvas_client)
    calls = enable_ai(canvas_client, canvas_container, review_answers)

    plan = canvas_client.post(f"/api/courses/{COURSE_ID}/quizzes/{QUIZ}/review/prepare").json()
    assert plan["available"] and plan["needs_confirmation"] and "Ingen studentdata" in plan["payload_summary"]
    refused = canvas_client.post(f"/api/courses/{COURSE_ID}/quizzes/{QUIZ}/review", json={"use_ai": True})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ai_consent_required"
    assert calls == [], "nothing is sent before consent"

    job = review(canvas_client, use_ai=True, confirmed=True)
    assert job["result"]["discarded_unverified"] == 1 and job["result"]["ai_used"] is True
    assert len(calls) == 1 and "PNG støtter gjennomsiktighet" in calls[0]
    findings = detail(canvas_client)["findings"]
    ai = {(f["rule_id"], f["object_id"]): f for f in findings if f["test_method"] == "ai"}
    assert ("QZ-AI-KEY", "603") in ai and ("QZ-AI-KEY", "601") not in ai
    assert ("QZ-AI-AMBIGUOUS", "602") in ai
    key = ai[("QZ-AI-KEY", "603")]
    assert key["evidence"]["label"] == "KI-forslag – må vurderes" and key["evidence"]["sources"][0]["quote"]
    assert key["fix"]["params"]["changes_key"] is True

    change = canvas_client.post(f"/api/quiz/findings/{key['id']}/stage", json={}).json()
    assert change["risk"] == "high" and change["requires_confirmation"] and change["ai_generated"]
    assert change["rationale"].startswith("KI-forslag – må vurderes") and "ENDRER FASITEN" in change["rationale"]
    blocked = approve_and_apply(canvas_client, [change["id"]])
    assert blocked.status_code == 409, "a key change is never applied without explicit confirmation"
    assert apply(canvas_client, change["id"], confirm=True)["result"]["summary"] == {"applied": 1}
    question = next(q for q in fake_state.courses[COURSE_ID].questions[QUIZ] if q["id"] == "603")
    assert [(a["text"], a["weight"]) for a in question["answers"]] == [("Sant", 0.0), ("Usant", 100.0)]
    assert "ikke" in question["question_text"]

    log_id = canvas_client.get("/api/changelog").json()["items"][0]["id"]
    assert canvas_client.post(f"/api/changelog/{log_id}/undo").json()["status"] == "undone"
    question = next(q for q in fake_state.courses[COURSE_ID].questions[QUIZ] if q["id"] == "603")
    assert [(a["text"], a["weight"]) for a in question["answers"]] == [("Sant", 100.0), ("Usant", 0.0)]

    review(canvas_client)  # deterministic re-check keeps the (costly) AI review results
    assert any(f["rule_id"] == "QZ-AI-KEY" for f in detail(canvas_client)["findings"])
    usage = json.dumps(canvas_client.get("/api/ai/usage").json())
    assert "gjennomsiktighet" not in usage, "the usage log holds metadata only"


# ------------------------------------------------------------------------------ question bank


def test_bank_crud_and_answer_validation(canvas_client: TestClient) -> None:
    bad = canvas_client.post(f"/api/courses/{COURSE_ID}/bank", json={
        "question_type": "single_choice", "stem": "Hva er 2 + 2?", "answers": [{"text": "4", "correct": True},
                                                                             {"text": "5"}]})
    assert bad.status_code == 400 and "minst tre" in bad.json()["error"]["message"]
    item = bank_item(canvas_client, "Hva står JPEG for?", status="draft")
    assert item["origin"] == "manual" and item["grounding"] == "unverified" and item["review_status"] == "draft"
    approved = canvas_client.patch(f"/api/bank/{item['id']}", json={"review_status": "approved"}).json()
    assert approved["review_status"] == "approved"
    no_key = canvas_client.patch(f"/api/bank/{item['id']}", json={"answers": [
        {"text": "A", "correct": False}, {"text": "B", "correct": False}, {"text": "C", "correct": False}]})
    assert no_key.status_code == 400
    listing = canvas_client.get(f"/api/courses/{COURSE_ID}/bank").json()
    assert listing["counts"] == {"draft": 0, "approved": 1, "rejected": 0}
    assert canvas_client.delete(f"/api/bank/{item['id']}").json() == {"ok": True}
    assert canvas_client.get(f"/api/courses/{COURSE_ID}/bank").json()["items"] == []


def generation_answers(prompt: str) -> dict:
    source = sources_in(prompt)[0]
    good = {"type": "single_choice", "stem": "Hvilket format passer for fotografier ifølge emnet?",
            "answers": [{"text": "JPEG", "correct": True}, {"text": "SVG", "correct": False},
                        {"text": "TXT", "correct": False}],
            "explanation": "Står i emnet.", "chunk_id": source["chunk_id"], "quote": quote_from(source),
            "topic": "Bildeformater", "difficulty": "easy"}
    return {"questions": [
        good,
        {**good, "stem": "Hvilket format er best for logoer?", "quote": "Logoer bør alltid lagres som BMP-filer"},
        {**good, "stem": "Hvilket format passer for fotografier ifølge emnet?"},  # duplicate
        {**good, "type": "true_false", "stem": "JPEG er et vektorformat.",
         "answers": [{"text": "Sant", "correct": False}, {"text": "Usant", "correct": True},
                     {"text": "Vet ikke", "correct": False}]},  # invalid true/false
    ]}


def test_generated_questions_must_be_grounded(canvas_client: TestClient, canvas_container: AppContainer) -> None:
    snapshot(canvas_client)
    calls = enable_ai(canvas_client, canvas_container, generation_answers)
    plan = canvas_client.post(f"/api/courses/{COURSE_ID}/bank/generate/prepare", json={"count": 8}).json()
    assert plan["available"] and plan["chunks"] > 0 and plan["needs_confirmation"]
    refused = canvas_client.post(f"/api/courses/{COURSE_ID}/bank/generate", json={"count": 8})
    assert refused.status_code == 409 and calls == []
    response = canvas_client.post(f"/api/courses/{COURSE_ID}/bank/generate", json={"count": 8, "confirmed": True})
    job = wait_for_job(canvas_client, response.json()["id"])
    assert job["status"] == "completed", job
    assert job["result"]["kept"] == 1 and job["result"]["discarded_unverified"] == 2
    assert job["result"]["duplicates"] == 1
    items = canvas_client.get(f"/api/courses/{COURSE_ID}/bank").json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["origin"] == "ai" and item["grounding"] == "verified" and item["review_status"] == "draft"
    assert item["sources"][0]["quote"] and item["generator"]["model"]
    coverage = canvas_client.get(f"/api/courses/{COURSE_ID}/bank/coverage").json()
    assert coverage["total"]["draft"] == 1 and coverage["modules"]


# ------------------------------------------------------------------------- presets and builder


def test_presets_and_copy_settings(canvas_client: TestClient) -> None:
    presets = canvas_client.get("/api/quiz/presets").json()["presets"]
    assert {p["name"] for p in presets if p["builtin"]} == {"Øvingsquiz", "Avsluttende test", "Egenvurdering"}
    copied = canvas_client.get(f"/api/courses/{COURSE_ID}/quizzes/{QUIZ}/settings").json()
    assert copied["settings"]["allowed_attempts"] == -1 and copied["settings"]["shuffle_answers"] is True
    assert copied["settings"]["published"] is False, "copied settings never publish a new quiz"
    custom = canvas_client.post("/api/quiz/presets", json={"name": "Min mal", "settings": copied["settings"]}).json()
    default = canvas_client.post(f"/api/quiz/presets/{custom['id']}/default").json()
    assert default["is_default"] is True
    presets = canvas_client.get("/api/quiz/presets").json()["presets"]
    assert [p["name"] for p in presets if p["is_default"]] == ["Min mal"]
    assert canvas_client.post("/api/quiz/presets", json={"name": "Øvingsquiz", "settings": {}}).status_code == 400
    builtin = next(p for p in presets if p["builtin"])
    assert canvas_client.delete(f"/api/quiz/presets/{builtin['id']}").status_code == 409
    assert canvas_client.delete(f"/api/quiz/presets/{custom['id']}").json() == {"ok": True}


def test_builder_creates_unpublished_quiz_with_question_group_and_undo(
        canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    ids = [bank_item(canvas_client, f"Spørsmål nummer {n} om bildeformater?")["id"] for n in range(3)]
    draft = bank_item(canvas_client, "Et utkast som ikke er godkjent?", status="draft")
    request = {"title": "Ukequiz 1", "question_ids": ids, "pick_count": 2, "points_per_question": 2,
               "settings": {"quiz_type": "assignment", "allowed_attempts": 1, "scoring_policy": "keep_latest"}}
    preview = canvas_client.post(f"/api/courses/{COURSE_ID}/quiz-builder/preview", json=request).json()
    assert preview["summary"] == {"questions_total": 3, "questions_asked": 2, "points_possible": 4.0,
                                  "published": False}
    assert any("Poengregel" in w for w in preview["warnings"]), "settings Canvas would ignore are explained"
    rejected = canvas_client.post(f"/api/courses/{COURSE_ID}/quiz-builder/preview",
                                  json={**request, "question_ids": [*ids, draft["id"]]})
    assert rejected.status_code == 400 and "godkjente" in rejected.json()["error"]["message"]

    change = canvas_client.post(f"/api/courses/{COURSE_ID}/quiz-builder/stage", json=request).json()
    assert change["kind"] == "quiz.create" and change["risk"] == "low" and "upublisert" in change["rationale"]
    writes_before = len(fake_state.writes)
    assert apply(canvas_client, change["id"])["result"]["summary"] == {"applied": 1}
    course = fake_state.courses[COURSE_ID]
    quiz = next(q for q in course.quizzes.values() if q["title"] == "Ukequiz 1")
    assert quiz["published"] is False and quiz["points_possible"] == 4.0
    assert course.groups[quiz["id"]][0]["pick_count"] == 2
    questions = course.questions[quiz["id"]]
    assert len(questions) == 3 and all(q["quiz_group_id"] for q in questions)
    assert all([a["weight"] for a in q["answers"]] == [100.0, 0.0, 0.0] for q in questions), "explicit answer key"
    assert len(fake_state.writes) > writes_before
    stored = canvas_client.get(f"/api/changes/{change['id']}").json()
    assert stored["result"]["after"]["quiz_id"] == quiz["id"] and "_created" not in stored["proposed"]
    used = canvas_client.get(f"/api/courses/{COURSE_ID}/bank?status=approved").json()["items"]
    assert all(i["used_in"] and i["used_in"][0]["title"] == "Ukequiz 1" for i in used)

    log_id = canvas_client.get("/api/changelog").json()["items"][0]["id"]
    assert canvas_client.post(f"/api/changelog/{log_id}/undo").json()["status"] == "undone"
    assert quiz["id"] not in course.quizzes, "undo deletes the unpublished quiz EmneKlar created"
    used = canvas_client.get(f"/api/courses/{COURSE_ID}/bank?status=approved").json()["items"]
    assert all(i["used_in"] == [] for i in used)


def test_builder_creates_nothing_before_publishing(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    ids = [bank_item(canvas_client, f"Kø-spørsmål {n}?")["id"] for n in range(2)]
    writes = len(fake_state.writes)
    change = canvas_client.post(f"/api/courses/{COURSE_ID}/quiz-builder/stage",
                                json={"title": "Prøvequiz", "question_ids": ids}).json()
    assert change["status"] == "staged" and len(fake_state.writes) == writes
    assert not any(q["title"] == "Prøvequiz" for q in fake_state.courses[COURSE_ID].quizzes.values())


def _ai_key_finding(client: TestClient, container: AppContainer, suggestion_stem: str) -> dict:
    snapshot(client)

    def answer(prompt: str) -> dict:
        sources = sources_in(prompt)
        questions = block(prompt, "SPØRSMÅL")
        out = []
        for q in questions:
            entry: dict[str, Any] = {"question_id": q["question_id"], "key_assessment": "supported", "correct_answer_ids": [],
                                     "issues": [], "evidence": [], "suggestion": {"stem": "", "answers": [], "explanation": ""}}
            if q["question_id"] == "603":
                entry.update(key_assessment="wrong_key", evidence=[{"chunk_id": sources[0]["chunk_id"], "quote": quote_from(sources[0])}],
                             suggestion={"stem": suggestion_stem, "explanation": "",
                                         "answers": [{"text": "Sant", "correct": False}, {"text": "Usant", "correct": True}]})
            out.append(entry)
        return {"questions": out}

    enable_ai(client, container, answer)
    review(client, use_ai=True, confirmed=True)
    return next(f for f in detail(client)["findings"] if f["rule_id"] == "QZ-AI-KEY")


def test_approving_a_suggestion_keeps_formatting_and_feedback(canvas_client: TestClient, canvas_container: AppContainer,
                                                             fake_state: FakeCanvasState) -> None:
    question = next(q for q in fake_state.courses[COURSE_ID].questions[QUIZ] if q["id"] == "603")
    question["question_text"] = "<p><strong>PNG</strong> støtter gjennomsiktighet.</p>"
    question["neutral_comments"] = "Se kapittel 2."
    question["answers"][1]["comments"] = "Les om alfakanalen."
    finding = _ai_key_finding(canvas_client, canvas_container, "PNG støtter gjennomsiktighet.")
    change = canvas_client.post(f"/api/quiz/findings/{finding['id']}/stage", json={}).json()
    assert change["proposed"]["question_text"] == question["question_text"], "unchanged wording keeps the original HTML"
    assert apply(canvas_client, change["id"], confirm=True)["result"]["summary"] == {"applied": 1}
    assert question["question_text"] == "<p><strong>PNG</strong> støtter gjennomsiktighet.</p>"
    assert question["neutral_comments"] == "Se kapittel 2."
    assert [(a["text"], a["weight"], a["comments"]) for a in question["answers"]] == [
        ("Sant", 0.0, ""), ("Usant", 100.0, "Les om alfakanalen.")]


def test_rich_question_text_is_never_replaced_by_plain_text(canvas_client: TestClient, canvas_container: AppContainer,
                                                           fake_state: FakeCanvasState) -> None:
    question = next(q for q in fake_state.courses[COURSE_ID].questions[QUIZ] if q["id"] == "603")
    question["question_text"] = '<p>PNG støtter gjennomsiktighet.</p><p><img src="/courses/101/files/9004/preview" alt="Logo"></p>'
    finding = _ai_key_finding(canvas_client, canvas_container, "Støtter PNG-formatet gjennomsiktighet?")
    response = canvas_client.post(f"/api/quiz/findings/{finding['id']}/stage", json={})
    assert response.status_code == 400 and "bilder" in response.json()["error"]["message"]
    kept = canvas_client.post(f"/api/quiz/findings/{finding['id']}/stage", json={"stem": "PNG støtter gjennomsiktighet."})
    assert kept.status_code == 200, kept.text
    assert "<img" in kept.json()["proposed"]["question_text"], "keeping the wording keeps the image"


def test_requeuing_a_quiz_suggestion_replaces_the_earlier_version(canvas_client: TestClient,
                                                                 canvas_container: AppContainer) -> None:
    finding = _ai_key_finding(canvas_client, canvas_container, "PNG støtter ikke gjennomsiktighet.")
    first = canvas_client.post(f"/api/quiz/findings/{finding['id']}/stage", json={}).json()
    second = canvas_client.post(f"/api/quiz/findings/{finding['id']}/stage", json={
        "stem": "PNG støtter ikke gjennomsiktighet.", "answers": [{"text": "Sant", "correct": True}, {"text": "Usant"}]}).json()
    assert first["id"] == second["id"], "no duplicate changes for the same question"
    pending = canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"]
    assert len([c for c in pending if c["kind"] == "quiz_question.update"]) == 1
    assert second["proposed"]["answers"][0] == {"text": "Sant", "correct": True}
