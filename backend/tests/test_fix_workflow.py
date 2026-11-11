"""Analyse → find → context → fix → approve → publish: the workflow end to end against the fake Canvas.

Covers: Dry run is gone without analyses writing; targeted link and alt-text fixes (nothing else on the page
changes); one occurrence / all on the page / all in the course; direct Canvas links; Blueprint without application
blocks (Canvas decides, the fix can move to the Blueprint course, then sync); the single queue, «Godkjenn alle»,
publishing several changes to one page without losing content, partial failures, retries without duplicates; the
image endpoint; and the KI-forslag queue (async, limited concurrency, priority, cache).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import (
    BLUEPRINT_COURSE_ID,
    CHILD_COURSE_ID,
    COURSE_ID,
    PNG_1X1,
    FakeCanvasState,
    _page,
    add_blueprint_child,
    add_demo_data,
)

DEAD = "https://www.example.org/missing"
LINK_PAGE = ("<h2>Lenker</h2><p>Se <a href='https://www.example.org/missing' target=\"_blank\">gammel artikkel</a> og "
             "<a href=\"https://www.example.org/plan\">planen</a>.&nbsp;<br/>Mer:</p>"
             "<p><img src=\"/courses/101/files/9004/preview\" alt=\"Raster og vektor\"></p>"
             "<iframe src=\"https://www.youtube.com/embed/abc12345\" title=\"Video: Intro\"></iframe>"
             "<p>Igjen: <a href=\"https://www.example.org/missing\">artikkelen</a></p>")


def analyse(client: TestClient, course: str = COURSE_ID, domains: tuple[str, ...] = ("accessibility",)) -> None:
    job = client.post("/api/analysis", json={"course_id": course, "domains": list(domains)}).json()
    assert wait_for_job(client, job["id"], timeout=60)["status"] == "completed"


def findings(client: TestClient, domain: str, course: str = COURSE_ID) -> list[dict[str, Any]]:
    return client.get(f"/api/courses/{course}/findings?domain={domain}&page_size=200").json()["items"]


def one(items: list[dict[str, Any]], rule: str, page: str | None = None) -> dict[str, Any]:
    return next(f for f in items if f["rule_id"] == rule and (page is None or f["object_id"] == page))


def publish(client: TestClient, ids: list[int], confirm: bool = False) -> dict[str, Any]:
    response = approve_and_apply(client, ids, confirm=confirm)
    assert response.status_code == 200, response.text
    return wait_for_job(client, response.json()["id"])


def writes(state: FakeCanvasState) -> list[tuple[str, str]]:
    return [r for r in state.requests if r[0] in ("PUT", "POST", "PATCH", "DELETE")]


def add_link_page(state: FakeCanvasState) -> None:
    page = _page("lenker", "Lenker", LINK_PAGE)
    state.courses[COURSE_ID].pages["lenker"] = page
    state.courses[COURSE_ID].revisions["lenker"] = [{"revision_id": 1, "updated_at": page["updated_at"],
                                                    "latest": True, "title": "Lenker", "body": LINK_PAGE}]


# ------------------------------------------------------------------------------------------- 1. Dry run is gone


@pytest.mark.invariant
def test_dry_run_setting_and_log_column_are_gone(canvas_container) -> None:  # type: ignore[no-untyped-def]
    from emneklar.core.storage.settings import AppSettings

    assert not hasattr(AppSettings.model_validate({"dry_run": True}), "dry_run"), "an old stored value is ignored"
    canvas_container.migrate()
    with sqlite3.connect(canvas_container.config.db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(change_log)")}
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "dry_run" not in columns and "action" in columns
    assert "alt_text_suggestions" in tables


@pytest.mark.invariant
def test_analysis_of_every_domain_only_reads(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    add_link_page(fake_state)
    analyse(canvas_client, domains=("accessibility", "content_quality", "structure", "quiz"))
    for domain in ("accessibility", "content_quality"):
        for f in findings(canvas_client, domain)[:20]:
            if f["fix"] and f["fix"]["type"] in ("set_alt", "replace_link_href", "change_heading_level"):
                canvas_client.post(f"/api/findings/{f['id']}/fix/preview", json={"text": "x", "url": "https://a.no"})
    assert writes(fake_state) == [], "analysis and previews never write to Canvas"


# ------------------------------------------------------------------------------- 8. editing dead links (targeted)


def test_dead_link_fixes_change_only_the_link(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    add_link_page(fake_state)
    analyse(canvas_client, domains=("content_quality",))
    dead = one(findings(canvas_client, "content_quality"), "CQ-LINK-DEAD", "lenker")
    assert dead["fix"]["type"] == "replace_link_href" and dead["evidence"]["occurrences"] == 2
    url = f"/api/findings/{dead['id']}/fix/preview"

    def after(params: dict[str, Any]) -> str:
        response = canvas_client.post(url, json=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["targeted"] is True
        return "\n".join(c["after"] for c in data["changes"]), data

    # Replace the address of this occurrence only: every other byte (quotes, &nbsp;, <br/>, image, iframe) unchanged.
    changed, data = after({"url": "https://www.example.org/ny"})
    assert changed.startswith('<a href="https://www.example.org/ny" target="_blank">gammel artikkel</a>')
    assert data["occurrences"] == 2 and data["where"]["role"] == "course"
    staged = canvas_client.post(f"/api/findings/{dead['id']}/fix/stage", json={"url": "https://www.example.org/ny"})
    body = staged.json()["proposed"]["body"]
    assert body == LINK_PAGE.replace("href='https://www.example.org/missing'", 'href="https://www.example.org/ny"', 1)
    canvas_client.delete(f"/api/changes/{staged.json()['id']}")

    # Both occurrences on the page, with new link text.
    _, data = after({"url": "https://www.example.org/ny", "link_text": "Ny artikkel", "scope": "page"})
    assert data["count"] == 2 and all("Ny artikkel</a>" in c["after"] for c in data["changes"])
    # Remove the link, keep the text – and remove the whole link element.
    changed, _ = after({"link_action": "unlink"})
    assert changed == "gammel artikkel"
    changed, data = after({"link_action": "remove", "scope": "page"})
    assert data["count"] == 2 and all(c["after"] == "" for c in data["changes"])
    # Same address again is refused (nothing would change).
    assert canvas_client.post(url, json={"url": DEAD}).status_code == 400

    # Approve + publish: Canvas gets exactly the previewed page.
    approved = canvas_client.post(f"/api/findings/{dead['id']}/fix/approve",
                                  json={"link_action": "unlink"}).json()
    assert approved["status"] == "approved"
    job = publish(canvas_client, [approved["id"]])
    assert job["result"]["results"][0]["status"] == "applied"
    stored = fake_state.courses[COURSE_ID].pages["lenker"]["body"]
    assert stored == LINK_PAGE.replace("<a href='https://www.example.org/missing' target=\"_blank\">gammel artikkel</a>",
                                       "gammel artikkel")
    assert canvas_client.get(f"/api/findings/{dead['id']}").json()["status"] == "fixed"


def test_link_fix_for_every_place_in_the_course(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    add_link_page(fake_state)
    analyse(canvas_client, domains=("content_quality",))
    dead = one(findings(canvas_client, "content_quality"), "CQ-LINK-DEAD", "lenker")
    preview = canvas_client.post(f"/api/findings/{dead['id']}/fix/preview",
                                 json={"url": "https://www.example.org/ny", "scope": "course"}).json()
    assert {r["object_id"] for r in preview["related"]} == {"bildeformater"}
    result = canvas_client.post(f"/api/findings/{dead['id']}/fix/approve",
                                json={"url": "https://www.example.org/ny", "scope": "course"}).json()
    assert len(result["also_staged"]) == 1 and result["errors"] == []
    job = publish(canvas_client, [result["id"], result["also_staged"][0]["id"]])
    assert job["result"]["summary"] == {"applied": 2}
    pages = fake_state.courses[COURSE_ID].pages
    assert DEAD not in pages["lenker"]["body"] and DEAD not in pages["bildeformater"]["body"]
    assert '<a href="https://www.example.org/ny"></a>' in pages["bildeformater"]["body"]


EMPTY_LINK_PAGE = ("<h2>Pensum</h2><p>Last ned <a title=\"\" href=\"http://PDF-versjon%20https\" target=\"\"></a> før "
                   "første samling.</p>")


def test_empty_link_with_a_broken_address(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    page = _page("pensum", "Pensum", EMPTY_LINK_PAGE)
    fake_state.courses[COURSE_ID].pages["pensum"] = page
    analyse(canvas_client)
    empty = one(findings(canvas_client, "accessibility"), "UU-LINK-EMPTY", "pensum")
    assert empty["fix"]["type"] == "replace_link_href"
    assert empty["fix"]["params"]["empty"] is True and empty["fix"]["params"]["default_action"] == "remove"
    assert empty["fix"]["params"]["suggestion"] == "", "a broken address is not offered as a suggestion"
    assert "mellomrom" in empty["href_problem"] and "PDF-versjon https" in empty["href_problem"]
    assert empty["ready"] is None, "removing (or naming) an empty link is the teacher's choice"
    url = f"/api/findings/{empty['id']}/fix/preview"

    removed = canvas_client.post(url, json={"link_action": "remove"}).json()
    assert removed["changes"] == [{"before": '<a title="" href="http://PDF-versjon%20https" target=""></a>',
                                   "after": ""}]
    broken = canvas_client.post(url, json={"url": "http://PDF-versjon%20https", "link_text": "PDF"})
    assert broken.status_code == 400 and "ikke gyldig" in broken.json()["error"]["message"]
    no_text = canvas_client.post(url, json={"url": "https://www.uio.no/pensum.pdf"})
    assert no_text.status_code == 400 and "lenketekst" in no_text.json()["error"]["message"]
    named = canvas_client.post(url, json={"url": "https://www.uio.no/pensum.pdf", "link_text": "Pensumliste (PDF)"})
    assert named.json()["changes"][0]["after"] == \
        '<a title="" href="https://www.uio.no/pensum.pdf" target="">Pensumliste (PDF)</a>'

    change = canvas_client.post(f"/api/findings/{empty['id']}/fix/approve", json={"link_action": "remove"}).json()
    assert publish(canvas_client, [change["id"]])["result"]["results"][0]["status"] == "applied"
    assert fake_state.courses[COURSE_ID].pages["pensum"]["body"] == EMPTY_LINK_PAGE.replace(
        '<a title="" href="http://PDF-versjon%20https" target=""></a>', "")


def test_href_problem_explains_only_clear_cases() -> None:
    from emneklar.core.canvas.links import href_problem

    assert "mellomrom" in (href_problem("http://PDF-versjon%20https") or "")
    assert "«http» to ganger" in (href_problem("https://https://www.uio.no") or "")
    assert "mangler domene" in (href_problem("http://pensum") or "")
    assert "kjører kode" in (href_problem("javascript:alert(1)") or "")
    assert href_problem("") == "Lenken har ingen adresse."
    for fine in ("https://www.uio.no/pensum.pdf", "https://blåbær.no/", "http://127.0.0.1:8080/x", "/courses/1/pages/a",
                 "mailto:kari@example.org", "#seksjon", "http://localhost:3000"):
        assert href_problem(fine) is None, fine


def test_blueprint_course_lock_is_described_as_downstream() -> None:
    from emneklar.core.canvas.blueprint import describe

    where = describe({"is_blueprint": True, "associated_course_count": 21},
                     {"locked": True, "restrictions": {"content": True}})
    assert where["role"] == "blueprint" and where["locked"] is False and where["locked_downstream"] is True
    assert "du kan endre innholdet her" in where["message"]
    assert "låst i de tilknyttede emnene" in where["message"] and "de 21 tilknyttede emnene" in where["message"]
    child = describe({"is_child": True, "parent": {"id": "1", "name": "Mal"}},
                     {"locked": True, "restrictions": {"content": True}})
    assert child["role"] == "associated" and child["locked"] is True and "låst av Blueprint-emnet «Mal»" in child["message"]


# ------------------------------------------------------------------------------ 9. alt text, 2. image in the detail


def test_alt_text_fix_is_targeted_and_image_is_served(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    analyse(canvas_client)
    items = findings(canvas_client, "accessibility")
    missing = one(items, "UU-IMG-MISSING-ALT", "bildeformater")
    assert missing["image"] is True
    context = missing["evidence"]["image_context"]
    assert context["heading"] == "Raster og vektor", "the nearest heading is part of the context"

    image = canvas_client.get(f"/api/findings/{missing['id']}/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png" and image.content
    assert "authorization" not in {k.lower() for k in image.headers}
    assert fake_state.token not in image.text
    other = one(items, "UU-HEAD-H1")
    assert canvas_client.get(f"/api/findings/{other['id']}/image").status_code == 404

    original = fake_state.courses[COURSE_ID].pages["bildeformater"]["body"]
    data = canvas_client.post(f"/api/findings/{missing['id']}/fix/preview",
                              json={"text": "Raster- og vektorgrafikk side om side"}).json()
    assert data["changes"] == [{"before": '<img src="/courses/101/files/9004/preview">',
                                "after": '<img src="/courses/101/files/9004/preview" alt="Raster- og vektorgrafikk side '
                                         'om side">'}]
    change = canvas_client.post(f"/api/findings/{missing['id']}/fix/approve", json={"decorative": True}).json()
    assert change["proposed"]["body"] == original.replace('<img src="/courses/101/files/9004/preview">',
                                                          '<img src="/courses/101/files/9004/preview" alt="" '
                                                          'role="presentation">')


# ------------------------------------------------------------------------------------------- 6. Canvas links


def test_findings_link_to_the_right_canvas_resource(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    analyse(canvas_client, domains=("accessibility", "content_quality"))
    base = "http://canvas.test/courses/101"
    by_type = {}
    for f in findings(canvas_client, "accessibility") + findings(canvas_client, "content_quality"):
        by_type.setdefault(f["object_type"], f)
    page = one(findings(canvas_client, "accessibility"), "UU-LINK-VAGUE", "velkommen")
    assert page["canvas"]["view"] == f"{base}/pages/velkommen"
    assert page["canvas"]["edit"] == f"{base}/pages/velkommen/edit"
    assert page["canvas"]["module_item"] == f"{base}/modules/items/1001"
    assert page["canvas"]["highlight"] == f"{base}/pages/velkommen#:~:text=Klikk%20her"
    assert page["location"]["module"] == "Modul 1 – Introduksjon"
    assignment = next(f for f in findings(canvas_client, "content_quality") if f["object_type"] == "assignment")
    assert assignment["canvas"]["view"] == f"{base}/assignments/301"
    assert assignment["canvas"]["edit"] == f"{base}/assignments/301/edit"
    from emneklar.core.canvas.links import content_links

    syllabus = content_links("http://canvas.test", COURSE_ID, "syllabus", COURSE_ID)
    assert syllabus["view"] == f"{base}/assignments/syllabus" and syllabus["edit"] is None

    assert content_links("http://c", "1", "quiz", "4")["edit"] == "http://c/courses/1/quizzes/4/edit"
    assert content_links("http://c", "1", "discussion", "5")["view"] == "http://c/courses/1/discussion_topics/5"
    assert content_links("http://c", "1", "quiz_question", "9", evidence={"quiz_id": "4"})["view"] == \
        "http://c/courses/1/quizzes/4"
    assert content_links("http://c", "1", "module", "7")["view"] == "http://c/courses/1/modules#context_module_7"

    links = canvas_client.get(f"/api/courses/{COURSE_ID}/links").json()["links"]
    missing = next(row for row in links if row["url"] == DEAD)
    use = missing["uses"][0]
    assert use["title"] == "Bildeformater" and use["canvas"]["view"] == f"{base}/pages/bildeformater"
    assert use["module"] == "Modul 2 – Bildebehandling" and use["finding_id"]


# -------------------------------------------------------------------------------------------- 7. Blueprint


def test_blueprint_content_is_fixable_and_moves_to_the_blueprint_course(canvas_client: TestClient,
                                                                        fake_state: FakeCanvasState) -> None:
    add_blueprint_child(fake_state)
    assert canvas_client.put("/api/context/course", json={"course_id": CHILD_COURSE_ID}).status_code == 200
    analyse(canvas_client, course=CHILD_COURSE_ID, domains=("accessibility", "content_quality"))
    image = one(findings(canvas_client, "accessibility", CHILD_COURSE_ID), "UU-IMG-MISSING-ALT", "mal-ressurser")
    assert image["fix"] is not None, "Blueprint-locked content is not blocked by EmneKlar"
    assert image["evidence"]["blueprint"]["locked"] is True
    preview = canvas_client.post(f"/api/findings/{image['id']}/fix/preview", json={"text": "Samlingsplan"}).json()
    assert preview["where"]["role"] == "associated" and preview["where"]["locked"] is True
    assert "Mal for digitale emner" in preview["where"]["message"]

    # Canvas refuses the locked page in the associated course – EmneKlar explains and offers the alternative.
    change = canvas_client.post(f"/api/findings/{image['id']}/fix/approve", json={"text": "Samlingsplan"}).json()
    result = publish(canvas_client, [change["id"]])["result"]["results"][0]
    assert result["status"] == "failed" and result["error_category"] == "blueprint"
    assert "Blueprint-emnet «Mal for digitale emner»" in result["message"]
    assert fake_state.courses[CHILD_COURSE_ID].pages["mal-ressurser"]["body"].count("alt=") == 0

    plan = canvas_client.get(f"/api/changes/{change['id']}/blueprint-move").json()
    assert plan["parent"]["id"] == BLUEPRINT_COURSE_ID and plan["associated_course_count"] == 1
    assert 'alt="Samlingsplan"' in plan["after_display"] and "/courses/102/files/9104" in plan["after_display"]
    moved = canvas_client.post(f"/api/changes/{change['id']}/blueprint-move").json()
    assert moved["moved"]["course_id"] == BLUEPRINT_COURSE_ID and moved["sync"]["kind"] == "blueprint.sync"
    assert canvas_client.get(f"/api/changes/{change['id']}").json()["status"] == "discarded"
    queue = canvas_client.get("/api/changes").json()
    assert {c["course_id"] for c in queue["courses"]} >= {BLUEPRINT_COURSE_ID}

    ids = [moved["moved"]["id"], moved["sync"]["id"]]
    assert approve_and_apply(canvas_client, ids).status_code == 409, "the sync needs confirming"
    job = publish(canvas_client, ids, confirm=True)
    results = {r["change_id"]: r for r in job["result"]["results"]}
    assert results[moved["moved"]["id"]]["status"] == "applied"
    assert results[moved["moved"]["id"]]["blueprint"]["sync_needed"] is True
    assert results[moved["sync"]["id"]]["status"] == "applied"
    assert [r["change_id"] for r in job["result"]["results"]] == ids, "content first, then the sync"
    assert 'alt="Samlingsplan"' in fake_state.courses[BLUEPRINT_COURSE_ID].pages["mal-ressurser"]["body"]
    assert 'alt="Samlingsplan"' in fake_state.courses[CHILD_COURSE_ID].pages["mal-ressurser"]["body"], "synced"
    migration = canvas_client.get(f"/api/changes/{moved['sync']['id']}").json()["result"]["after"]["migration_id"]
    status = canvas_client.get(f"/api/courses/{BLUEPRINT_COURSE_ID}/blueprint/migrations/{migration}").json()
    assert status["finished"] is True and status["failed"] is False

    # Unlocked content in the associated course is changed right there.
    local = one(findings(canvas_client, "content_quality", CHILD_COURSE_ID), "CQ-LINK-DEAD", "lokal-side")
    change = canvas_client.post(f"/api/findings/{local['id']}/fix/approve", json={"link_action": "unlink"}).json()
    assert publish(canvas_client, [change["id"]])["result"]["results"][0]["status"] == "applied"


def test_blueprint_course_change_says_where_it_lands(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    add_blueprint_child(fake_state)
    assert canvas_client.put("/api/context/course", json={"course_id": BLUEPRINT_COURSE_ID}).status_code == 200
    analyse(canvas_client, course=BLUEPRINT_COURSE_ID)
    image = one(findings(canvas_client, "accessibility", BLUEPRINT_COURSE_ID), "UU-IMG-MISSING-ALT")
    where = canvas_client.post(f"/api/findings/{image['id']}/fix/preview", json={"text": "Plan"}).json()["where"]
    assert where["role"] == "blueprint" and where["sync_needed"] is True and "synkroniseres" in where["message"]
    sync = canvas_client.get(f"/api/courses/{BLUEPRINT_COURSE_ID}/blueprint/sync").json()
    assert [c["id"] for c in sync["associated_courses"]] == [CHILD_COURSE_ID]


# ------------------------------------------------------------------------- 10/11. one queue and «Godkjenn alle»


def test_queue_groups_by_course_and_bulk_approval(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    analyse(canvas_client)
    items = findings(canvas_client, "accessibility")
    ready = [f for f in items if f["ready"] == "automatic"]
    assert ready and all(f["fix"]["type"] not in ("set_alt", "replace_link_href") for f in ready)
    assert not any(f["ready"] == "automatic" and f["rule_id"] == "UU-LINK-EMPTY" for f in items), \
        "removing a link is never approved in bulk"
    response = canvas_client.post("/api/findings/fix/bulk", json={"course_id": COURSE_ID,
                                                                  "finding_ids": [f["id"] for f in items]})
    assert response.status_code == 200, response.text
    job = wait_for_job(canvas_client, response.json()["job"]["id"])
    assert job["status"] == "completed" and not job["result"]["failed"]
    assert set(job["result"]["approved"]) == {f["id"] for f in ready}
    queue = canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()
    pages = [c["target"]["object_id"] for c in queue["items"]]
    assert len(pages) == len(set(pages)), "one change per page"
    assert all(c["status"] == "approved" for c in queue["items"])
    assert queue["summary"]["approved"] == len(queue["items"])
    assert queue["courses"][0]["name"] == "Digital kompetanse for lærere"
    assert writes(fake_state) == [], "approving never writes"


# ------------------------------------------------------- 12/13. several changes to one page, partial failure, retry


def test_two_changes_to_one_page_keep_both(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                           fake_state: FakeCanvasState) -> None:
    analyse(canvas_client)
    fix = canvas_client.post(f"/api/findings/{one(findings(canvas_client, 'accessibility'), 'UU-HEAD-H1')['id']}"
                             "/fix/approve", json={}).json()
    page = fake_state.courses[COURSE_ID].pages["velkommen"]
    other = canvas_container.changes.stage(
        course_id=COURSE_ID, domain="homepage", kind="page.update_body", title="Tillegg",
        target={"object_type": "page", "object_id": "velkommen", "title": "Velkommen"},
        before={"body": page["body"]}, proposed={"body": page["body"] + "<p>Tillegg fra en annen funksjon</p>"},
        rationale="Test", source={"feature": "other"})
    assert other["id"] != fix["id"]
    canvas_client.post("/api/changes/approve", json={"ids": [other["id"]]})
    job = publish(canvas_client, [fix["id"], other["id"]])
    assert job["result"]["summary"] == {"applied": 2}
    body = page["body"]
    assert "<h2>Velkommen</h2>" in body and "Tillegg fra en annen funksjon" in body, "neither change was lost"


def test_partial_failure_retry_and_no_double_write(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    analyse(canvas_client)
    items = findings(canvas_client, "accessibility")
    a = canvas_client.post(f"/api/findings/{one(items, 'UU-HEAD-H1')['id']}/fix/approve", json={}).json()
    b = canvas_client.post(f"/api/findings/{one(items, 'UU-TABLE-NO-HEADERS')['id']}/fix/approve", json={}).json()
    fake_state.fail = {"/pages/fargelaere": 403}
    job = publish(canvas_client, [a["id"], b["id"]])
    results = {r["change_id"]: r for r in job["result"]["results"]}
    assert results[a["id"]]["status"] == "applied" and results[b["id"]]["status"] == "failed"
    assert results[b["id"]]["error_category"] == "permission" and "rettighet" in results[b["id"]]["message"]
    fake_state.fail = {}
    # Retrying an applied change is refused; the failed one is retried and written once.
    assert approve_and_apply(canvas_client, [a["id"]]).status_code == 409
    before = len(writes(fake_state))
    job = publish(canvas_client, [b["id"]])
    assert job["result"]["results"][0]["status"] == "applied"
    assert len(writes(fake_state)) == before + 1


def test_change_already_in_canvas_is_not_written_again(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    analyse(canvas_client)
    change = canvas_client.post(f"/api/findings/{one(findings(canvas_client, 'accessibility'), 'UU-HEAD-H1')['id']}"
                                "/fix/approve", json={}).json()
    # The write reached Canvas, but the answer was lost (timeout): Canvas already holds the proposal.
    fake_state.courses[COURSE_ID].pages["velkommen"]["body"] = change["proposed"]["body"]
    before = len(writes(fake_state))
    result = publish(canvas_client, [change["id"]])["result"]["results"][0]
    assert result["status"] == "applied" and "allerede lagret" in result["message"]
    assert len(writes(fake_state)) == before


def test_conflict_with_newer_work_can_be_rebuilt(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    analyse(canvas_client)
    change = canvas_client.post(f"/api/findings/{one(findings(canvas_client, 'accessibility'), 'UU-HEAD-H1')['id']}"
                                "/fix/approve", json={}).json()
    fake_state.courses[COURSE_ID].pages["velkommen"]["body"] += "<p>Kollegaen skrev dette</p>"
    assert publish(canvas_client, [change["id"]])["result"]["results"][0]["status"] == "conflict"
    rebuilt = canvas_client.post(f"/api/changes/{change['id']}/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert "Kollegaen skrev dette" in rebuilt.json()["proposed"]["body"]
    canvas_client.post("/api/changes/approve", json={"ids": [change["id"]]})
    assert publish(canvas_client, [change["id"]])["result"]["results"][0]["status"] == "applied"
    body = fake_state.courses[COURSE_ID].pages["velkommen"]["body"]
    assert "<h2>Velkommen</h2>" in body and "Kollegaen skrev dette" in body


# ------------------------------------------------------------------ 3/4/5. KI-forslag: async, priority, cache


class CountingAI:
    """Fake Anthropic endpoint that records what it was asked and how many requests ran at once."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.prompts: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def transport(self) -> httpx.MockTransport:
        import asyncio

        async def handler(request: httpx.Request) -> httpx.Response:
            data = json.loads(request.content)
            text = json.dumps(data["messages"], ensure_ascii=False)
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.prompts.append(text)
            await asyncio.sleep(self.delay)
            with self.lock:
                self.active -= 1
            answer = {"alt_text": f"Forslag {len(self.prompts)}", "decorative": False, "image_kind": "informative",
                      "confidence": "medium", "notes": ""}
            return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(answer)}],
                                             "stop_reason": "end_turn", "usage": {}})

        return httpx.MockTransport(handler)


def enable_ai(client: TestClient, container, ai: CountingAI) -> None:  # type: ignore[no-untyped-def]
    container.ai_transport = ai.transport()
    assert client.put("/api/ai/providers/anthropic", json={"enabled": True,
                                                           "api_key": "sk-ant-api-test-1234567890"}).status_code == 200
    container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))


def wait_ready(client: TestClient, ids: list[int], timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/courses/{COURSE_ID}/alt-text/status", params={"ids": ids}).json()
        if all(v["status"] in ("ready", "failed") for v in status["items"].values()) and not status["queue"]["queued"] \
                and not status["queue"]["running"]:
            return status
        time.sleep(0.05)
    raise AssertionError(f"suggestions not ready: {status}")


def test_alt_text_queue_is_consented_limited_prioritised_and_cached(canvas_container,  # type: ignore[no-untyped-def]
                                                                    canvas_client: TestClient,
                                                                    fake_state: FakeCanvasState) -> None:
    add_demo_data(fake_state, images=12, links=0)
    analyse(canvas_client)
    ai = CountingAI(delay=0.08)
    enable_ai(canvas_client, canvas_container, ai)
    images = [f for f in findings(canvas_client, "accessibility") if f["image"] and f["status"] == "open"
              and f["object_id"] == "bildegalleri"]
    ids = [f["id"] for f in images]
    assert len(images) == 12

    plan = canvas_client.post("/api/ai/tasks/alt-text/batch/prepare",
                              json={"course_id": COURSE_ID, "finding_ids": ids}).json()
    assert plan["available"] and plan["needs_confirmation"] and plan["to_send"] == len(images)
    assert "Ingen studentdata" in plan["payload_summary"]
    # Nothing is sent without consent – not even when the teacher opens an image.
    refused = canvas_client.post("/api/ai/tasks/alt-text/batch/start", json={"course_id": COURSE_ID, "finding_ids": ids})
    assert refused.status_code == 409
    assert canvas_client.post("/api/ai/tasks/alt-text/prioritize",
                              json={"course_id": COURSE_ID, "finding_ids": ids[:2]}).json()["allowed"] is False
    assert ai.prompts == []

    last = images[-1]
    start = canvas_client.post("/api/ai/tasks/alt-text/batch/start",
                               json={"course_id": COURSE_ID, "confirmed": True, "finding_ids": ids})
    assert start.json()["added"] == len(images)
    canvas_client.post("/api/ai/tasks/alt-text/prioritize", json={"course_id": COURSE_ID, "finding_ids": [last["id"]]})
    status = wait_ready(canvas_client, ids)
    assert all(v["status"] == "ready" for v in status["items"].values())
    assert len(ai.prompts) == len(images), "every image exactly once"
    assert ai.max_active <= 3, "at most three at a time"
    heading = last["evidence"]["image_context"]["heading"]
    assert any(heading in p for p in ai.prompts[:5]), "the image being viewed is moved to the front"

    # Cached: starting again, prioritising, or reading the list sends nothing.
    assert canvas_client.post("/api/ai/tasks/alt-text/batch/start",
                              json={"course_id": COURSE_ID, "confirmed": True, "finding_ids": ids}).json()["added"] == 0
    canvas_client.post("/api/ai/tasks/alt-text/prioritize", json={"course_id": COURSE_ID, "finding_ids": ids[:3]})
    listed = {f["id"]: f for f in findings(canvas_client, "accessibility")}
    assert listed[last["id"]]["alt_suggestion"]["status"] == "ready"
    assert listed[last["id"]]["ready"] is None, "a KI-forslag is reviewed in the finding, never «klar» for bulk approval"
    assert len(ai.prompts) == len(images)

    # A suggestion is a suggestion: the teacher's own text wins, and the approved fix uses it.
    change = canvas_client.post(f"/api/findings/{last['id']}/fix/approve", json={"text": "Min egen tekst"}).json()
    assert 'alt="Min egen tekst"' in change["proposed"]["body"]

    # A changed context (new analysis after an edit in Canvas) gets a new suggestion; unchanged ones are reused.
    gallery = fake_state.courses[COURSE_ID].pages["bildegalleri"]
    gallery["body"] = gallery["body"].replace("Eksempel 1 viser", "Eksempel 1 viser nå")
    analyse(canvas_client)
    fresh = [f for f in findings(canvas_client, "accessibility") if f["image"] and f["status"] == "open"
             and f["object_id"] == "bildegalleri"]
    sent = len(ai.prompts)
    canvas_client.post("/api/ai/tasks/alt-text/batch/start",
                       json={"course_id": COURSE_ID, "confirmed": True, "finding_ids": [f["id"] for f in fresh]})
    wait_ready(canvas_client, [f["id"] for f in fresh])
    assert len(ai.prompts) - sent == 1, "only the image whose context changed is sent again"
    assert "Eksempel 1 viser nå" in ai.prompts[-1]


def test_alt_text_failure_is_shown_and_retried_on_request(canvas_container,  # type: ignore[no-untyped-def]
                                                          canvas_client: TestClient,
                                                          fake_state: FakeCanvasState) -> None:
    analyse(canvas_client)
    ai = CountingAI()
    enable_ai(canvas_client, canvas_container, ai)
    target = one(findings(canvas_client, "accessibility"), "UU-IMG-MISSING-ALT", "bildeformater")
    fake_state.file_bytes["9004"] = (b"not an image", "text/plain")
    canvas_client.post("/api/ai/tasks/alt-text/batch/start",
                       json={"course_id": COURSE_ID, "confirmed": True, "finding_ids": [target["id"]]})
    status = wait_ready(canvas_client, [target["id"]])
    assert status["items"][str(target["id"])]["status"] == "failed" and status["items"][str(target["id"])]["error"]
    assert ai.prompts == [], "nothing is sent for an image that could not be read"
    canvas_client.post("/api/ai/tasks/alt-text/prioritize", json={"course_id": COURSE_ID, "finding_ids": [target["id"]]})
    assert wait_ready(canvas_client, [target["id"]])["items"][str(target["id"])]["status"] == "failed"
    fake_state.file_bytes["9004"] = (PNG_1X1, "image/png")
    canvas_client.post("/api/ai/tasks/alt-text/retry", json={"finding_id": target["id"]})
    assert wait_ready(canvas_client, [target["id"]])["items"][str(target["id"])]["status"] == "ready"
    assert len(ai.prompts) == 1
