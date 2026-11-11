"""Favourite courses in the course selector: stored in EmneKlar, never written to Canvas."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState


def courses(client: TestClient) -> dict[str, bool]:
    return {c["id"]: c["favorite"] for c in client.get("/api/courses").json()["courses"]}


def test_favorites_are_stored_locally_and_returned_with_the_courses(canvas_client: TestClient,
                                                                    fake_state: FakeCanvasState) -> None:
    assert courses(canvas_client)[COURSE_ID] is False
    before = len([r for r in fake_state.requests if r[0] != "GET"])
    answer = canvas_client.put(f"/api/courses/{COURSE_ID}/favorite", json={"favorite": True}).json()
    assert answer["favorite_course_ids"] == [COURSE_ID]
    assert courses(canvas_client)[COURSE_ID] is True
    assert canvas_client.put(f"/api/courses/{COURSE_ID}/favorite", json={"favorite": True}).json()[
        "favorite_course_ids"] == [COURSE_ID], "no duplicates"
    assert canvas_client.put(f"/api/courses/{COURSE_ID}/favorite", json={"favorite": False}).json()[
        "favorite_course_ids"] == []
    assert len([r for r in fake_state.requests if r[0] != "GET"]) == before, "nothing is written to Canvas"
    assert canvas_client.put("/api/courses/abc/favorite", json={"favorite": True}).status_code in (400, 422)
