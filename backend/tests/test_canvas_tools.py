"""Canvas-verktøy: automatic module requirements, Blueprint locking and Canvas settings analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from emneklar.features.canvas_settings.analysis import analyze
from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import BLUEPRINT_COURSE_ID, COURSE_ID, FakeCanvasState

pytestmark = pytest.mark.invariant


def apply(client: TestClient, ids: list[int], confirm: bool = False) -> dict:
    response = approve_and_apply(client, ids, confirm=confirm)
    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    return job["result"]


def rows(preview: dict) -> dict[str, dict]:
    return {r["item_id"]: r for m in preview["modules"] for r in m["items"]}


def item(fake_state: FakeCanvasState, item_id: str) -> dict:
    return next(i for m in fake_state.courses[COURSE_ID].modules for i in m["items"] if i["id"] == item_id)


# ---------------------------------------------------------------------------------- module requirements


def test_requirement_options_follow_the_verified_table(canvas_client: TestClient) -> None:
    types = {t["type"]: t for t in canvas_client.get("/api/module-requirements/options").json()["item_types"]}
    assert [a["value"] for a in types["Page"]["allowed"]] == ["must_view", "must_contribute", "must_mark_done"]
    assert types["SubHeader"]["allowed"] == [] and types["SubHeader"]["default"] is None
    assert "must_submit" not in [a["value"] for a in types["File"]["allowed"]]


def test_preview_keeps_existing_requirements_by_default(canvas_client: TestClient) -> None:
    preview = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/preview", json={}).json()
    r = rows(preview)
    assert r["1010"]["status"] == "unchanged" and r["1010"]["current_label"] == "Se på elementet"
    assert (r["1001"]["status"], r["1001"]["proposed"]) == ("add", {"type": "must_view"})
    assert r["1002"]["proposed"] == {"type": "must_contribute"}, "discussions: contribute"
    assert r["1011"]["proposed"] == {"type": "must_submit"} and r["1012"]["proposed"] == {"type": "must_submit"}
    assert r["1023"]["proposed"] == {"type": "must_view"} and r["1021"]["type_label"] == "Fil"

    keep = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/preview",
                              json={"policy": {"Page": "must_mark_done"}}).json()
    assert rows(keep)["1010"]["status"] == "keep", "existing requirements are preserved unless replace is chosen"
    replace = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/preview",
                                 json={"policy": {"Page": "must_mark_done"}, "existing": "replace"}).json()
    assert rows(replace)["1010"]["status"] == "replace"
    assert rows(replace)["1010"]["proposed"] == {"type": "must_mark_done"}


def test_invalid_combinations_are_rejected(canvas_client: TestClient) -> None:
    for policy in ({"File": "must_submit"}, {"SubHeader": "must_view"}, {"Page": "made_up"}):
        response = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/preview", json={"policy": policy})
        assert response.status_code == 422, policy


def test_stage_apply_and_undo_requirements_for_selected_module(canvas_client: TestClient,
                                                               fake_state: FakeCanvasState) -> None:
    body = {"module_ids": ["201"], "require_sequential_progress": True}
    preview = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/preview", json=body).json()
    assert [m["id"] for m in preview["modules"]] == ["201"]
    assert preview["modules"][0]["settings"]["changed"] == {"require_sequential_progress": True}
    staged = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/stage", json=body).json()
    assert staged["staged"] == 4  # three items + module settings
    writes = len(fake_state.writes)
    result = apply(canvas_client, staged["change_ids"])
    assert result["summary"] == {"applied": 4}
    assert item(fake_state, "1001")["completion_requirement"]["type"] == "must_view"
    assert item(fake_state, "1002")["completion_requirement"]["type"] == "must_contribute"
    module = next(m for m in fake_state.courses[COURSE_ID].modules if m["id"] == "201")
    assert module["require_sequential_progress"] is True
    assert len(fake_state.writes) > writes
    again = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/preview", json=body).json()
    assert again["changes"] == 0, "after applying, nothing is left to change"

    log = canvas_client.get(f"/api/changelog?course_id={COURSE_ID}").json()["items"]
    entry = next(e for e in log if e["object_id"] == "1001" and e["action"] == "apply")
    assert canvas_client.post(f"/api/changelog/{entry['id']}/undo").json()["status"] == "undone"
    assert item(fake_state, "1001")["completion_requirement"] is None


def test_staged_requirements_are_not_written_before_publishing(canvas_client: TestClient,
                                                               fake_state: FakeCanvasState) -> None:
    writes = len(fake_state.writes)
    staged = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/stage",
                                json={"module_ids": ["203"]}).json()
    assert staged["change_ids"] and len(fake_state.writes) == writes
    assert item(fake_state, "1021")["completion_requirement"] is None


# ------------------------------------------------------------------------------------------ blueprint


def test_blueprint_is_unavailable_with_explanation_for_normal_course(canvas_client: TestClient) -> None:
    data = canvas_client.get(f"/api/courses/{COURSE_ID}/blueprint").json()
    assert data["available"] is False and "ikke et Blueprint-emne" in data["reason"]
    staged = canvas_client.post(f"/api/courses/{COURSE_ID}/blueprint/stage", json={"action": "lock"})
    assert staged.status_code == 409


def test_blueprint_preview_lock_apply_and_undo(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    data = canvas_client.get(f"/api/courses/{BLUEPRINT_COURSE_ID}/blueprint").json()
    assert data["available"] is True and data["template"]["associated_course_count"] == 3
    items = {(i["content_type"], i["title"]): i for i in data["items"]}
    assert items[("assignment", "Malinnlevering")]["restricted"] is True
    assert items[("wiki_page", "Malforside")]["restricted"] is False
    assert items[("wiki_page", "Malforside")]["modules"] == ["Malmodul"]

    scoped = canvas_client.post(f"/api/courses/{BLUEPRINT_COURSE_ID}/blueprint/preview",
                                json={"action": "lock", "module_ids": ["291"]}).json()
    assert {r["title"] for r in scoped["rows"]} == {"Malforside", "Malinnlevering"}
    assert {r["title"]: r["status"] for r in scoped["rows"]}["Malinnlevering"] == "unchanged"

    body = {"action": "lock", "content_types": ["wiki_page", "discussion_topic", "assignment"],
            "restrictions": {"content": True}}
    change = canvas_client.post(f"/api/courses/{BLUEPRINT_COURSE_ID}/blueprint/stage", json=body).json()
    assert change["risk"] == "high" and change["requires_confirmation"] is True
    assert len(change["proposed"]["items"]) == 4  # two pages, the discussion and the assignment (other restrictions)
    blocked = approve_and_apply(canvas_client, [change["id"]])
    assert blocked.status_code == 409, "high-impact locking needs explicit confirmation"
    assert apply(canvas_client, [change["id"]], confirm=True)["summary"] == {"applied": 1}
    locks = fake_state.courses[BLUEPRINT_COURSE_ID].restrictions
    page_id = fake_state.courses[BLUEPRINT_COURSE_ID].pages["mal-forside"]["page_id"]
    assert locks[("wiki_page", str(page_id))] == {"restricted": True, "restrictions": {"content": True}}
    assert locks[("discussion_topic", "591")]["restricted"] is True

    log_id = canvas_client.get(f"/api/changelog?course_id={BLUEPRINT_COURSE_ID}").json()["items"][0]["id"]
    assert canvas_client.post(f"/api/changelog/{log_id}/undo").json()["status"] == "undone"
    assert locks[("wiki_page", str(page_id))]["restricted"] is False
    assert locks[("assignment", "391")] == {"restricted": True, "restrictions": {"content": True, "points": True}}


def test_blueprint_rejects_unknown_restrictions(canvas_client: TestClient) -> None:
    response = canvas_client.post(f"/api/courses/{BLUEPRINT_COURSE_ID}/blueprint/preview",
                                  json={"action": "lock", "restrictions": {"everything": True}})
    assert response.status_code == 422


# ------------------------------------------------------------------------------------ canvas settings


def test_settings_analysis_categorises_findings(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    course.course["default_view"] = "feed"
    course.course["is_public"] = True
    course.pages["fargelaere"]["editing_roles"] = "teachers,students"
    course.assignments["301"]["lock_at"] = "2026-09-10T21:59:00Z"  # before the due date (15.9)
    course.quizzes["401"]["time_limit"] = 30
    course.tabs.append({"id": "modules", "label": "Moduler", "hidden": True, "position": 4, "type": "internal"})
    data = canvas_client.get(f"/api/courses/{COURSE_ID}/canvas-settings").json()
    found = {i["rule_id"]: i for i in data["items"]}
    assert found["CS-HOME-FEED"]["category"] == "recommendation" and found["CS-HOME-FEED"]["fix"]["options"]
    assert found["CS-ASSIGN-LOCK-BEFORE-DUE"]["category"] == "technical"
    assert found["CS-COURSE-PUBLIC"]["category"] == "security_accessibility"
    assert found["CS-PAGE-EDIT-STUDENTS"]["object"]["title"] == "Fargelære"
    assert "CS-QUIZ-TIME-LIMIT" not in found, "a time limit is the teacher's choice, not a problem"
    assert data["category_labels"]["security_accessibility"] == "Sikkerhet"
    assert "CS-TAB-MODULES-HIDDEN" in found
    assert "CS-QUIZ-ANSWERS-UNLIMITED" not in found, "a practice quiz may show answers"
    assert data["counts"]["technical"] >= 1
    assert all(p["key"] in fake_state.courses[COURSE_ID].settings for p in data["preferences"])
    assert not any(i["category"] == "preference" and i["fix"] for i in data["items"]), \
        "preferences are never offered as automatic fixes"


NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
COURSE = {"id": 1, "name": "Emne", "workflow_state": "available", "blueprint": False, "default_view": "modules"}


def assignment(id_: int, **fields: Any) -> dict[str, Any]:
    return {"id": id_, "name": f"Oppgave {id_}", "published": True, "points_possible": 10,
            "submission_types": ["online_upload"], "due_at": "2026-11-20T22:59:00Z", **fields}


def settings_items(course: dict[str, Any], assignments: list[dict[str, Any]],
                   quizzes: list[dict[str, Any]] | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    result = analyze(course=course, settings={}, tabs=[], front_page=None, pages=[], assignments=assignments,
                     quizzes=quizzes or [], modules=[], now=NOW)
    return {(i["rule_id"], i["object"]["id"]): i for i in result["items"]}


def test_settings_report_what_stops_students_from_doing_and_handing_in_work() -> None:
    found = settings_items(COURSE, [
        assignment(1, submission_types=["on_paper"]),
        assignment(2, published=False, due_at="2026-11-12T22:59:00Z"),
        assignment(3, published=False, due_at="2027-01-12T22:59:00Z"),  # far ahead: nothing to report yet
        assignment(4, only_visible_to_overrides=True, has_overrides=False),
        assignment(5, due_at=None, unlock_at="2026-11-10T08:00:00Z", lock_at="2026-11-09T08:00:00Z"),
        assignment(6, points_possible=0, submission_types=["none"]),  # ungraded without submission: intended
        assignment(7, only_visible_to_overrides=True, has_overrides=True),  # assigned to a section
    ], [{"id": 9, "title": "Quiz", "published": True, "question_count": 3, "quiz_type": "assignment",
         "time_limit": 20, "cant_go_back": True}])
    assert found[("CS-ASSIGN-NO-SUBMISSION", "1")]["current"] == "På papir"
    assert found[("CS-ASSIGN-NO-SUBMISSION", "1")]["category"] == "recommendation"
    soon = found[("CS-ASSIGN-UNPUBLISHED-DUE-SOON", "2")]
    assert soon["category"] == "technical" and "kl." in soon["current"] and "T22:59" not in soon["current"]
    assert ("CS-ASSIGN-UNPUBLISHED-DUE-SOON", "3") not in found
    assert found[("CS-ASSIGN-NO-ASSIGNEES", "4")]["category"] == "technical"
    assert ("CS-ASSIGN-NO-ASSIGNEES", "7") not in found
    assert found[("CS-ASSIGN-LOCK-BEFORE-UNLOCK", "5")]["title"] == "Stenges før den åpner"
    assert not any(obj == "6" for _, obj in found)
    assert not {rule for rule, _ in found} & {"CS-QUIZ-TIME-LIMIT", "CS-QUIZ-NO-BACK"}, \
        "quiz design choices are not reported"


@pytest.mark.parametrize("course", [{**COURSE, "blueprint": True}, {**COURSE, "workflow_state": "unpublished"}])
def test_unpublished_work_is_only_reported_where_students_take_the_course(course: dict[str, Any]) -> None:
    found = settings_items(course, [assignment(2, published=False, due_at="2026-11-12T22:59:00Z")])
    assert ("CS-ASSIGN-UNPUBLISHED-DUE-SOON", "2") not in found


def test_stage_default_view_and_explicit_preference(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    course.course["default_view"] = "feed"
    view = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                              json={"kind": "default_view", "value": "modules"}).json()
    pref = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                              json={"kind": "setting", "key": "allow_student_forum_attachments", "value": False}).json()
    assert view["kind"] == "course.update" and pref["kind"] == "course.update_settings"
    assert pref["rationale"].startswith("Preferanse valgt av deg")
    assert apply(canvas_client, [view["id"], pref["id"]])["summary"] == {"applied": 2}
    assert course.course["default_view"] == "modules"
    assert course.settings["allow_student_forum_attachments"] is False
    bad = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                             json={"kind": "setting", "key": "is_public", "value": False})
    assert bad.status_code == 400
    same = canvas_client.post(f"/api/courses/{COURSE_ID}/canvas-settings/stage",
                              json={"kind": "default_view", "value": "modules"})
    assert same.status_code == 400


def test_min_score_requires_a_value(canvas_client: TestClient) -> None:
    response = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/preview",
                                  json={"policy": {"Quiz": "min_score"}, "existing": "replace"})
    assert response.status_code == 422, "no silent «Fjernes» when the minimum score is missing"


def test_a_write_canvas_ignores_is_reported_as_failed(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    fake_state.ignored_fields.add("require_sequential_progress")
    staged = canvas_client.post(f"/api/courses/{COURSE_ID}/module-requirements/stage",
                                json={"module_ids": ["202"], "require_sequential_progress": True,
                                      "policy": {"Page": None, "File": None, "ExternalUrl": None, "ExternalTool": None,
                                                 "Discussion": None, "Assignment": None, "Quiz": None}}).json()
    assert staged["staged"] == 1
    result = apply(canvas_client, staged["change_ids"])
    assert result["summary"] == {"failed": 1}
    change = canvas_client.get(f"/api/changes/{staged['change_ids'][0]}").json()
    assert change["status"] == "failed" and "krav om rekkefølge" in change["error"]
