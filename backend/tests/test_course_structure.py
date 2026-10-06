"""Course structure: suggestions with evidence, no silent moves, staged changes only."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

IMAGE_TEXT = ("Bilder lagres som raster eller vektor. Rasterbilder består av piksler, og oppløsningen avgjør hvor "
              "skarpt bildet blir. Vektorgrafikk beskriver former matematisk og kan skaleres uten tap. JPEG passer "
              "for foto med komprimering, PNG passer for grafikk med gjennomsiktighet, og SVG er et vektorformat. "
              "Piksler, oppløsning, komprimering og fargedybde er viktige begreper for bilder. ")
VIDEO_TEXT = ("Video krever teksting slik at døve og hørselshemmede kan følge med. Teksting av opptak skal "
              "korrekturleses, og automatisk teksting må kontrolleres. Opptak av forelesninger bør ha teksting, "
              "og videoen bør ha tydelig lyd. Teksting, opptak, lyd og video henger sammen i god videoproduksjon. ")


def run_structure(client: TestClient) -> list[dict]:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["structure"]}).json()
    assert wait_for_job(client, job["id"])["status"] == "completed"
    return client.get(f"/api/courses/{COURSE_ID}/findings?domain=structure&page_size=200").json()["items"]


def test_structure_suggestions(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    items = run_structure(canvas_client)
    rules = {(f["rule_id"], f["object_title"]) for f in items}
    assert ("ST-ORPHAN", "Oppsummering") in rules
    assert not any(r == "ST-ORPHAN" and t in ("Forside", "Gammelt utkast") for r, t in rules), \
        "front page and unpublished drafts are not orphans"
    naming = next(f for f in items if f["rule_id"] == "ST-NAMING")
    assert naming["evidence"]["suggestion"] == "Modul 3 – Video"
    assert ("ST-NO-INTRO", "Modul 2 – Bildebehandling") in rules
    assert ("ST-NO-INTRO", "Modul 1 – Introduksjon") not in rules
    assert all(f["confidence"] in ("high", "medium", "low") for f in items)
    assert all("impact" in f["evidence"] for f in items)
    assert fake_state.writes == [], "analysis never moves or renames anything"


def test_due_date_order(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    fake_state.courses[COURSE_ID].assignments["301"]["due_at"] = "2026-08-20T21:59:00Z"  # module 2, before module 1
    items = run_structure(canvas_client)
    order = [f for f in items if f["rule_id"] == "ST-ORDER-DUE"]
    assert order and order[0]["object_title"] == "Innlevering 1: Bildebehandling"


def test_misplaced_item_and_staged_move(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    course.pages["bildeformater"]["body"] = f"<p>{IMAGE_TEXT * 2}</p>"
    course.pages["fargelaere"]["body"] = f"<p>{IMAGE_TEXT}</p>"
    course.pages["video-og-medier"]["body"] = f"<p>{VIDEO_TEXT * 2}</p>"
    # A video page placed in the image module:
    course.pages["oppsummering"]["body"] = f"<p>{VIDEO_TEXT * 2}</p>"
    course.modules[1]["items"].append({"id": "1099", "title": "Teksting av video", "type": "Page",
                                       "page_url": "oppsummering", "position": 5, "published": True,
                                       "completion_requirement": None})
    course.modules[2]["items"].append({"id": "1098", "title": "Mer om opptak", "type": "Page", "page_url": "forside",
                                       "position": 6, "published": True, "completion_requirement": None})
    course.pages["forside"]["body"] = f"<p>{VIDEO_TEXT}</p>"
    items = run_structure(canvas_client)
    misplaced = next(f for f in items if f["rule_id"] == "ST-MISPLACED")
    assert misplaced["object_title"] == "Teksting av video"
    assert misplaced["evidence"]["suggested_module"] == "modul 3: video"
    assert misplaced["evidence"]["shared_terms"]

    change = canvas_client.post(f"/api/structure/findings/{misplaced['id']}/stage", json={}).json()
    assert change["kind"] == "module_item.update" and change["status"] == "staged"
    assert any(i["id"] == "1099" for i in course.modules[1]["items"]), "nothing moves before the change is applied"
    response = canvas_client.post("/api/changes/apply", json={"ids": [change["id"]]})
    job = wait_for_job(canvas_client, response.json()["id"])
    assert job["result"]["results"][0]["status"] == "applied"
    assert any(i["id"] == "1099" for i in course.modules[2]["items"])
    log_id = canvas_client.get("/api/changelog").json()["items"][0]["id"]
    assert canvas_client.post(f"/api/changelog/{log_id}/undo").status_code == 200
    assert any(i["id"] == "1099" for i in course.modules[1]["items"]), "undo moves the item back"


def test_rename_module_is_staged(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    items = run_structure(canvas_client)
    naming = next(f for f in items if f["rule_id"] == "ST-NAMING")
    change = canvas_client.post(f"/api/structure/findings/{naming['id']}/stage", json={}).json()
    assert change["proposed"] == {"name": "Modul 3 – Video"} and change["editable"] is True
    edited = canvas_client.patch(f"/api/changes/{change['id']}", json={"proposed": {"name": "Modul 3 – Video og lyd"}})
    assert edited.status_code == 200
    job = wait_for_job(canvas_client, canvas_client.post("/api/changes/apply", json={"ids": [change["id"]]}).json()["id"])
    assert job["result"]["results"][0]["status"] == "applied"
    assert fake_state.courses[COURSE_ID].modules[2]["name"] == "Modul 3 – Video og lyd"


def test_structure_view_and_journey(canvas_client: TestClient) -> None:
    run_structure(canvas_client)
    data = canvas_client.get(f"/api/courses/{COURSE_ID}/structure").json()
    assert [m["name"] for m in data["modules"]][:2] == ["Modul 1 – Introduksjon", "Modul 2 – Bildebehandling"]
    assert data["modules"][0]["journey"] == ["Les", "Diskusjon", "Innlevering"]
    assert data["modules"][1]["items"][0]["requirement"] == "Se på elementet"
