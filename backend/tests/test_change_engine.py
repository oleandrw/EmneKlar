"""Change engine: stage → preview → approve → dry run / conflict / apply → backup → log → undo."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from emneklar.config import BACKEND_DIR
from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

pytestmark = pytest.mark.invariant


def analyse(client: TestClient) -> list[dict]:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["accessibility"]}).json()
    assert wait_for_job(client, job["id"])["status"] == "completed"
    return client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()["items"]


def finding(items: list[dict], rule: str, page: str | None = None) -> dict:
    return next(f for f in items if f["rule_id"] == rule and (page is None or f["object_id"] == page))


def apply(client: TestClient, ids: list[int], confirm: bool = False) -> dict:
    response = approve_and_apply(client, ids, confirm=confirm)
    assert response.status_code == 200, response.text
    return wait_for_job(client, response.json()["id"])


def test_fix_preview_stage_merge_and_apply(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    items = analyse(canvas_client)
    missing = finding(items, "UU-IMG-MISSING-ALT", "bildeformater")
    preview = canvas_client.post(f"/api/findings/{missing['id']}/fix/preview",
                                 json={"text": "Sammenligning av raster- og vektorgrafikk"}).json()
    assert 'alt="Sammenligning av raster- og vektorgrafikk"' in preview["after_display"]
    assert "/api/canvas/image?url=" in preview["preview_html"], "Canvas images go through the local proxy"
    assert fake_state.writes == [], "preview never writes"

    change = canvas_client.post(f"/api/findings/{missing['id']}/fix/stage",
                                json={"text": "Sammenligning av raster- og vektorgrafikk"}).json()
    assert change["status"] == "staged" and change["undo_capability"] == "full"
    fake_list = finding(items, "UU-LIST-FAKE", "bildeformater")
    merged = canvas_client.post(f"/api/findings/{fake_list['id']}/fix/stage", json={}).json()
    assert merged["id"] == change["id"], "two fixes on one page become one change"
    assert "<ul>" in merged["proposed"]["body"] and "Sammenligning" in merged["proposed"]["body"]
    assert canvas_client.get(f"/api/changes/summary?course_id={COURSE_ID}").json()["pending"] == 1

    job = apply(canvas_client, [change["id"]])
    assert job["result"]["results"][0]["status"] == "applied"
    page = fake_state.courses[COURSE_ID].pages["bildeformater"]
    assert "Sammenligning av raster- og vektorgrafikk" in page["body"] and "<ul>" in page["body"]
    log = canvas_client.get(f"/api/changelog?course_id={COURSE_ID}").json()["items"]
    assert log[0]["action"] == "apply" and log[0]["backup_id"] and log[0]["undoable"]
    backup = canvas_client.get(f"/api/backups/{log[0]['backup_id']}").json()
    assert "IMG" not in backup["content"]["state"]["body"] or backup["content"]["state"]["body"]
    refreshed = canvas_client.get(f"/api/findings/{missing['id']}").json()
    assert refreshed["status"] == "fixed"


def test_without_dry_run_analysis_preview_and_queue_never_write(canvas_client: TestClient,
                                                                fake_state: FakeCanvasState) -> None:
    """Dry run is gone: analyses, previews, staging and approval are read-only by design; only «Publiser» writes."""
    assert "dry_run" not in canvas_client.get("/api/session").json()
    assert canvas_client.put("/api/system/dry-run", json={"enabled": True}).status_code in (404, 405)
    job = canvas_client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": [
        "accessibility", "content_quality", "structure", "quiz"]}).json()
    assert wait_for_job(canvas_client, job["id"])["status"] == "completed"
    items = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()["items"]
    target = finding(items, "UU-IFRAME-NO-TITLE")
    canvas_client.post(f"/api/findings/{target['id']}/fix/preview", json={"text": "Video: Introduksjon"})
    change = canvas_client.post(f"/api/findings/{target['id']}/fix/approve", json={"text": "Video: Introduksjon"}).json()
    assert change["status"] == "approved"
    assert not [r for r in fake_state.requests if r[0] in ("PUT", "POST", "PATCH", "DELETE")], \
        "nothing but GET reaches Canvas before publishing"
    job = apply(canvas_client, [change["id"]])
    assert job["result"]["results"][0]["status"] == "applied"
    assert [r[0] for r in fake_state.requests if r[0] != "GET"] == ["PUT"]


def test_conflict_detection_blocks_write(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    items = analyse(canvas_client)
    target = finding(items, "UU-HEAD-H1", "velkommen")
    change = canvas_client.post(f"/api/findings/{target['id']}/fix/stage", json={}).json()
    # Someone edits the page in Canvas after the proposal was made.
    fake_state.courses[COURSE_ID].pages["velkommen"]["body"] += "<p>Ny tekst fra en kollega</p>"
    writes_before = len(fake_state.writes)
    job = apply(canvas_client, [change["id"]])
    assert job["result"]["results"][0]["status"] == "conflict"
    assert len(fake_state.writes) == writes_before
    assert canvas_client.get(f"/api/changes/{change['id']}").json()["status"] == "conflict"


def test_undo_restores_and_detects_later_edits(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    items = analyse(canvas_client)
    original = fake_state.courses[COURSE_ID].pages["velkommen"]["body"]
    target = finding(items, "UU-HEAD-H1", "velkommen")
    change = canvas_client.post(f"/api/findings/{target['id']}/fix/stage", json={}).json()
    apply(canvas_client, [change["id"]])
    assert "<h2>Velkommen</h2>" in fake_state.courses[COURSE_ID].pages["velkommen"]["body"]
    log_id = canvas_client.get("/api/changelog").json()["items"][0]["id"]
    undone = canvas_client.post(f"/api/changelog/{log_id}/undo")
    assert undone.status_code == 200, undone.text
    assert fake_state.courses[COURSE_ID].pages["velkommen"]["body"] == original
    again = canvas_client.post(f"/api/changelog/{log_id}/undo")
    assert again.status_code == 409

    # Undo after a later manual edit must refuse to overwrite newer work.
    items = analyse(canvas_client)
    target = finding(items, "UU-HEAD-H1", "velkommen")
    change = canvas_client.post(f"/api/findings/{target['id']}/fix/stage", json={}).json()
    apply(canvas_client, [change["id"]])
    log_id = canvas_client.get("/api/changelog").json()["items"][0]["id"]
    fake_state.courses[COURSE_ID].pages["velkommen"]["body"] += "<p>Endret senere</p>"
    conflict = canvas_client.post(f"/api/changelog/{log_id}/undo")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "undo_conflict"


def test_discard_reopens_findings(canvas_client: TestClient) -> None:
    items = analyse(canvas_client)
    target = finding(items, "UU-IFRAME-NO-TITLE")
    change = canvas_client.post(f"/api/findings/{target['id']}/fix/stage", json={"text": "Video"}).json()
    assert canvas_client.get(f"/api/findings/{target['id']}").json()["status"] == "staged"
    canvas_client.delete(f"/api/changes/{change['id']}")
    assert canvas_client.get(f"/api/findings/{target['id']}").json()["status"] == "open"


def test_fix_input_is_validated(canvas_client: TestClient) -> None:
    items = analyse(canvas_client)
    target = finding(items, "UU-IMG-MISSING-ALT")
    response = canvas_client.post(f"/api/findings/{target['id']}/fix/preview", json={"text": "  "})
    assert response.status_code == 400
    decorative = canvas_client.post(f"/api/findings/{target['id']}/fix/preview", json={"decorative": True}).json()
    assert 'alt=""' in decorative["after_display"] and 'role="presentation"' in decorative["after_display"]


def test_high_risk_requires_confirmation(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    change = canvas_container.changes.stage(
        course_id=COURSE_ID, domain="homepage", kind="front_page.replace", title="Ny forside",
        target={"object_type": "front_page", "object_id": "forside", "title": "Forside"},
        before={"body": "<h2>Velkommen</h2><p>Dette er forsiden.</p>", "title": "Forside", "url": "forside"},
        proposed={"body": "<h2>Ny forside</h2>"}, rationale="Test", risk="high")
    response = approve_and_apply(canvas_client, [change["id"]])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "change_requires_confirmation"
    job = apply(canvas_client, [change["id"]], confirm=True)
    assert job["result"]["results"][0]["status"] == "applied"


def test_completion_requirement_table_is_enforced(canvas_container) -> None:  # type: ignore[no-untyped-def]
    canvas_container.migrate()
    from emneklar.core.errors import AppError

    with pytest.raises(AppError):
        canvas_container.changes.stage(
            course_id=COURSE_ID, domain="canvas", kind="module_item.update", title="x",
            target={"object_type": "module_item", "object_id": "1021", "module_id": "203", "item_type": "File"},
            before={"completion_requirement": None}, proposed={"completion_requirement": {"type": "must_submit"}},
            rationale="test")


def test_only_the_change_engine_can_issue_write_permits() -> None:
    offenders = []
    for path in (BACKEND_DIR / "emneklar").rglob("*.py"):
        rel = path.relative_to(BACKEND_DIR / "emneklar").as_posix()
        text = path.read_text(encoding="utf-8")
        if rel.startswith("core/changes/") or rel == "core/canvas/client.py":
            continue
        if "issue_permit" in text or re.search(r"\bWritePermit\(", text):
            offenders.append(rel)
    assert offenders == [], f"Canvas writes must go through the change engine: {offenders}"


def test_no_feature_builds_its_own_http_client_for_canvas() -> None:
    offenders = []
    for path in Path(BACKEND_DIR / "emneklar" / "features").rglob("*.py"):
        if "CanvasClient(" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == []


def _stage_alt_fix(client: TestClient) -> dict:
    items = analyse(client)
    missing = finding(items, "UU-IMG-MISSING-ALT", "bildeformater")
    return client.post(f"/api/findings/{missing['id']}/fix/stage", json={"text": "Raster og vektor side om side"}).json()


def test_publishing_takes_approved_changes_only(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    change = _stage_alt_fix(canvas_client)
    assert change["status"] == "staged"
    refused = canvas_client.post("/api/changes/apply", json={"ids": [change["id"]]})
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "change_state_invalid" and "ikke godkjent" in error["message"]
    assert fake_state.writes == [], "a change that is not approved never reaches Canvas"

    assert canvas_client.post("/api/changes/approve", json={"ids": [change["id"]]}).json()["items"][0]["status"] == "approved"
    job = apply(canvas_client, [change["id"]])
    assert job["result"]["results"][0]["status"] == "applied"


def test_a_failed_change_must_be_approved_again(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    change = _stage_alt_fix(canvas_client)
    fake_state.fail["/pages/bildeformater"] = 500
    job = wait_for_job(canvas_client, approve_and_apply(canvas_client, [change["id"]]).json()["id"])
    assert job["result"]["results"][0]["status"] == "failed"
    fake_state.fail.clear()
    writes = list(fake_state.writes)

    retry = canvas_client.post("/api/changes/apply", json={"ids": [change["id"]]})
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "change_state_invalid"
    assert "Godkjenn den på nytt" in retry.json()["error"]["message"]
    assert fake_state.writes == writes, "nothing is written without a new approval"

    job = wait_for_job(canvas_client, approve_and_apply(canvas_client, [change["id"]]).json()["id"])
    assert job["result"]["results"][0]["status"] == "applied"


def test_the_write_step_checks_the_approval_again(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                                  fake_state: FakeCanvasState) -> None:
    """A change that lost its approval between «Publiser» and the write (e.g. «Angre godkjenning») is not sent."""
    import asyncio

    from emneklar.core.canvas.api import CanvasAPI

    change = _stage_alt_fix(canvas_client)
    data, row = canvas_container.changes._load(change["id"])
    outcome = asyncio.run(canvas_container.changes.apply_one(CanvasAPI(canvas_container.canvas()), data, row))
    assert outcome["status"] == "staged" and outcome["error_code"] == "change_state_invalid"
    assert fake_state.writes == []
    assert canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"][0]["status"] == "staged"
