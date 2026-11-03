"""End-to-end: setup → course context → analysis job → findings (fake Canvas)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import FakeCanvasState


def test_connection_status_and_courses(canvas_client: TestClient) -> None:
    status = canvas_client.get("/api/canvas/status").json()
    assert status["token_configured"] is True and status["identity"]["name"] == "Kari Lærer"
    courses = canvas_client.get("/api/courses").json()["courses"]
    assert {c["id"] for c in courses} == {"101", "102"}
    assert any(c["is_blueprint"] for c in courses)
    session = canvas_client.get("/api/session").json()
    assert session["current_course_id"] == "101"


def test_wrong_token_is_reported_in_norwegian(canvas_client: TestClient) -> None:
    response = canvas_client.post("/api/canvas/test", json={"base_url": "http://canvas.test", "token": "1~wrongtokenvalue12345678901234"})
    assert response.status_code == 401
    assert "tokenet" in response.json()["error"]["message"]


def test_capabilities(canvas_client: TestClient) -> None:
    caps = canvas_client.get("/api/courses/101/capabilities").json()
    assert all(c["granted"] for c in caps["capabilities"])
    assert caps["blueprint"]["is_blueprint"] is False
    assert canvas_client.get("/api/courses/102/capabilities").json()["blueprint"]["is_blueprint"] is True
    summary = canvas_client.get("/api/canvas/capability-summary").json()
    assert summary["teaching_courses"] == 2


def test_accessibility_analysis_end_to_end(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    started = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": ["accessibility"]})
    assert started.status_code == 200, started.text
    job = wait_for_job(canvas_client, started.json()["id"])
    assert job["status"] == "completed", job
    progress = job["progress"]
    assert progress["percent"] == 100 and progress["done"] == progress["total"]
    assert {"page", "document"} <= set(progress["types"])

    result = canvas_client.get("/api/courses/101/findings?domain=accessibility&page_size=200").json()
    rules = {f["rule_id"] for f in result["items"]}
    for expected in ("UU-IMG-MISSING-ALT", "UU-IMG-FILENAME-ALT", "UU-HEAD-H1", "UU-HEAD-FAKE", "UU-LIST-FAKE",
                     "UU-LINK-VAGUE", "UU-CONTRAST", "UU-IFRAME-NO-TITLE", "UU-MEDIA-EXTERNAL-CAPTIONS",
                     "UU-MEDIA-CANVAS-CAPTIONS", "UU-BLOCK-EDITOR", "UU-DOC-PDF-NO-TEXT", "UU-DOC-IMG-ALT",
                     "UU-LANG-PARTS", "UU-SENSORY"):
        assert expected in rules, expected
    finding = next(f for f in result["items"] if f["rule_id"] == "UU-IMG-MISSING-ALT")
    assert finding["legal"]["status"] == "required"
    assert finding["rule"]["sources"] and finding["location"]["module"]
    old_ppt = next(f for f in result["items"] if f["object_title"] == "Lysbilder uke 1.pptx")
    assert "exemption_hint" in old_ppt["evidence"]
    assert result["runs"][0]["limitations"], "limitations are always reported"
    # The analysis never writes to Canvas.
    assert fake_state.writes == []


def test_ignore_survives_reanalysis(canvas_client: TestClient) -> None:
    job = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": ["accessibility"]}).json()
    wait_for_job(canvas_client, job["id"])
    items = canvas_client.get("/api/courses/101/findings?domain=accessibility").json()["items"]
    target = next(f for f in items if f["rule_id"] == "UU-LINK-VAGUE")
    assert canvas_client.post(f"/api/findings/{target['id']}/ignore", json={"note": "Bevisst valg"}).status_code == 200
    job = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": ["accessibility"]}).json()
    wait_for_job(canvas_client, job["id"])
    ignored = canvas_client.get("/api/courses/101/findings?domain=accessibility&status=ignored").json()["items"]
    assert any(f["fingerprint"] == target["fingerprint"] for f in ignored)


def test_partial_scope_merges_with_full_run(canvas_client: TestClient) -> None:
    full = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": ["accessibility"]}).json()
    wait_for_job(canvas_client, full["id"])
    total_before = canvas_client.get("/api/courses/101/findings?domain=accessibility").json()["total"]
    partial = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": ["accessibility"],
                                                        "scope": "modules", "module_ids": ["201"]}).json()
    assert wait_for_job(canvas_client, partial["id"])["status"] == "completed"
    after = canvas_client.get("/api/courses/101/findings?domain=accessibility").json()
    assert after["total"] == total_before, "a module re-scan must not hide findings from other modules"
    assert len(after["runs"]) == 2


def test_partial_failure_is_a_limitation(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    fake_state.fail["/quizzes"] = 403
    job = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": ["accessibility"]}).json()
    done = wait_for_job(canvas_client, job["id"])
    assert done["status"] == "completed"
    assert done["result"]["status"] == "partial"
    assert any("Quizer" in item for item in done["result"]["limitations"])


def test_sse_stream_delivers_progress(canvas_client: TestClient) -> None:
    job = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": ["accessibility"]}).json()
    events = []
    with canvas_client.stream("GET", f"/api/jobs/{job['id']}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(line)
            if '"status": "completed"' in line or '"status":"completed"' in line:
                break
    assert events, "at least one progress event"


def test_analysis_requires_a_domain(canvas_client: TestClient) -> None:
    response = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": []})
    assert response.status_code == 400
