"""The setup's Canvas connection: testing saves nothing, the stored token never goes to another address, only the
confirmed identity is saved, and a failed save keeps the previous working connection. Fake Canvas only."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.core.auth.secrets import CANVAS_TOKEN
from emneklar.core.container import AppContainer
from emneklar.main import create_app
from tests.conftest import CANVAS_BASE, FAKE_TOKEN, ORIGIN, login
from tests.fakes.fake_canvas import FakeCanvasState


@pytest.fixture
def setup_client(canvas_container: AppContainer) -> Iterator[TestClient]:
    """Logged in, nothing connected yet (a fresh setup)."""
    with TestClient(create_app(canvas_container), base_url=ORIGIN) as raw:
        yield login(raw)


def connect(client: TestClient, token: str = FAKE_TOKEN, **extra: object) -> httpx.Response:
    return client.put("/api/canvas/connection", json={"base_url": CANVAS_BASE, "token": token, **extra})


def test_a_test_reports_identity_and_access_but_saves_nothing(setup_client: TestClient,
                                                               fake_state: FakeCanvasState) -> None:
    response = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN,
                                                           "capabilities": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["identity"] == {"id": "42", "name": "Kari Lærer"}
    assert data["base_url"] == CANVAS_BASE and data["teaching_courses"] == 2
    names = {c["id"]: (c["name"], c["course_code"]) for c in data["courses"]}
    assert names == {"101": ("Digital kompetanse for lærere", "LA101IKT14-1 26H"), "102": ("Mal for digitale emner", "MAL-DIGITAL")}
    access = data["access"]
    assert access["checked_courses"] == 2
    assert all(c["granted"] == c["checked"] == 2 for c in access["capabilities"])
    session = setup_client.get("/api/session").json()
    assert session["canvas"]["base_url"] is None and session["canvas"]["token_configured"] is False
    assert fake_state.writes == [], "the setup never writes to Canvas"


def test_access_is_counted_per_course_and_never_generalised(setup_client: TestClient,
                                                            fake_state: FakeCanvasState) -> None:
    fake_state.courses["102"].permissions["manage_wiki_update"] = False
    access = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN,
                                                         "capabilities": True}).json()["access"]
    pages = next(c for c in access["capabilities"] if c["key"] == "pages")
    read = next(c for c in access["capabilities"] if c["key"] == "read")
    assert (pages["granted"], pages["checked"]) == (1, 2)
    assert (read["granted"], read["checked"]) == (2, 2)
    assert pages["missing_in"] == ["102"], "which course it is missing in (by id; the names come with the courses)"
    assert read["missing_in"] == []
    assert sorted(access["checked_in"]) == ["101", "102"] and access["failed_in"] == []


def test_a_course_that_cannot_be_checked_is_unknown_not_missing(setup_client: TestClient,
                                                                fake_state: FakeCanvasState) -> None:
    fake_state.fail = {"courses/102/permissions": 500}
    access = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN,
                                                         "capabilities": True}).json()["access"]
    assert access["checked_courses"] == 1 and access["failed_in"] == ["102"]
    assert all(c["checked"] == 1 and c["missing_in"] == [] for c in access["capabilities"])


def test_without_capabilities_the_test_is_as_before(setup_client: TestClient) -> None:
    data = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN}).json()
    assert "access" not in data


def test_wrong_token_and_bad_address_are_reported(setup_client: TestClient) -> None:
    wrong = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": "1~wrongtokenvalue1234567890"})
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "canvas_token_invalid"
    path = setup_client.post("/api/canvas/test", json={"base_url": f"{CANVAS_BASE}/courses/101", "token": FAKE_TOKEN})
    assert path.status_code == 400 and path.json()["error"]["code"] == "canvas_url_invalid"
    missing = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": ""})
    assert missing.json()["error"]["code"] == "canvas_token_missing"


def test_canvas_not_answering_is_reported_as_unavailable(setup_client: TestClient, fake_state: FakeCanvasState) -> None:
    fake_state.fail = {"users/self": 503}
    response = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN})
    assert response.json()["error"]["code"] == "canvas_unavailable"


def test_the_stored_token_is_never_sent_to_another_address(setup_client: TestClient,
                                                           fake_state: FakeCanvasState) -> None:
    assert connect(setup_client).status_code == 200
    before = len(fake_state.requests)
    other = setup_client.post("/api/canvas/test", json={"base_url": "http://annen-canvas.test", "token": None})
    assert other.status_code == 400 and other.json()["error"]["code"] == "canvas_token_other_url"
    assert len(fake_state.requests) == before, "no request with the stored token went anywhere"
    same = setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": None})
    assert same.status_code == 200, "the stored token is reused for its own address"


def test_only_the_confirmed_identity_is_saved(setup_client: TestClient, canvas_container: AppContainer,
                                              fake_state: FakeCanvasState) -> None:
    fake_state.user = {**fake_state.user, "id": "43", "name": "Ola Annen"}
    response = connect(setup_client, expected_user_id="42")
    assert response.status_code == 409 and response.json()["error"]["code"] == "canvas_identity_changed"
    assert canvas_container.secrets.get(CANVAS_TOKEN) is None
    assert canvas_container.settings.get().canvas.base_url is None


def test_a_failed_save_keeps_the_previous_connection(setup_client: TestClient, canvas_container: AppContainer,
                                                     fake_state: FakeCanvasState,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    assert connect(setup_client).status_code == 200
    new_token = "7~anotherFakeTokenForTests0987654321zyxwvu"
    fake_state.token = new_token

    def broken(_mutate: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(canvas_container.settings, "update", broken)
    with pytest.raises(OSError):  # the app answers 500; the test client re-raises it
        connect(setup_client, token=new_token, expected_user_id="42")
    assert canvas_container.secrets.get(CANVAS_TOKEN) == FAKE_TOKEN, "the old token is back"
    assert canvas_container.settings.get().canvas.base_url == CANVAS_BASE


def test_a_typed_token_is_masked_in_logs(setup_client: TestClient) -> None:
    from emneklar.core.security.redaction import known_secrets

    token = "1~neverSavedTokenValue1234567890"
    setup_client.post("/api/canvas/test", json={"base_url": CANVAS_BASE, "token": token})
    assert token in known_secrets()


def test_setup_completes_only_with_a_saved_connection(setup_client: TestClient) -> None:
    early = setup_client.post("/api/setup/complete", json={"default_course_id": None, "regulatory_profile": "no-offentlig-2023"})
    assert early.json()["error"]["code"] == "canvas_not_configured"
    assert setup_client.get("/api/session").json()["setup_completed"] is False
    assert connect(setup_client).status_code == 200
    done = setup_client.post("/api/setup/complete", json={"default_course_id": "101", "regulatory_profile": "no-privat-2013"})
    assert done.status_code == 200
    session = setup_client.get("/api/session").json()
    assert session["setup_completed"] is True and session["current_course_id"] == "101"
    assert session["regulatory_profile"] == "no-privat-2013"
