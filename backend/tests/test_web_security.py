"""Local web security: Host check, session, CSRF, Origin, control channel, headers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import LAUNCH_TOKEN, ORIGIN

pytestmark = pytest.mark.invariant


def test_health_is_public_and_identifies_app(raw_client: TestClient) -> None:
    response = raw_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["app"] == "EmneKlar"


def test_dns_rebinding_host_is_rejected(raw_client: TestClient) -> None:
    response = raw_client.get("/api/health", headers={"Host": "evil.example:8765"})
    assert response.status_code == 421


def test_api_requires_session(raw_client: TestClient) -> None:
    response = raw_client.get("/api/session")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_required"


def test_launch_token_creates_strict_httponly_cookie(raw_client: TestClient) -> None:
    response = raw_client.get(f"/auth/launch?token={LAUNCH_TOKEN}", follow_redirects=False)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_invalid_launch_token_is_rejected(raw_client: TestClient) -> None:
    response = raw_client.get("/auth/launch?token=wrong", follow_redirects=False)
    assert response.status_code == 401


def test_unsafe_request_needs_origin_and_csrf(client: TestClient) -> None:
    ok = client.patch("/api/settings/general", json={"page_size": 50})
    assert ok.status_code == 200
    no_csrf = client.patch("/api/settings/general", json={"page_size": 25}, headers={"X-CSRF-Token": "nope"})
    assert no_csrf.status_code == 403
    assert no_csrf.json()["error"]["code"] == "csrf_failed"
    evil_origin = client.patch("/api/settings/general", json={"page_size": 25}, headers={"Origin": "https://evil.example"})
    assert evil_origin.status_code == 403
    assert evil_origin.json()["error"]["code"] == "origin_rejected"


def test_cors_preflight_is_never_approved(client: TestClient) -> None:
    response = client.options("/api/session", headers={"Origin": "https://evil.example",
                                                       "Access-Control-Request-Method": "PUT"})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_security_headers_present(client: TestClient) -> None:
    response = client.get("/api/session")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_the_csp_keeps_its_strict_directives_and_the_comment_matches() -> None:
    from emneklar.core.security import web

    directives = dict(part.strip().split(" ", 1) for part in web.CSP.split(";"))
    assert directives["script-src"] == "'self'", "no inline scripts, no eval"
    assert directives["object-src"] == "'none'" and directives["base-uri"] == "'none'"
    assert directives["default-src"] == "'self'" and directives["connect-src"] == "'self'"
    # Only EmneKlar may frame its pages (the illustration preview is shown in a frame); the docs say the same.
    assert directives["frame-ancestors"] == "'self'"
    assert "frame-ancestors 'self'" in (web.__doc__ or "") and "frame-ancestors 'none'" not in (web.__doc__ or "")
    assert (b"x-frame-options", b"SAMEORIGIN") in web.SECURITY_HEADERS


def test_a_wrong_method_is_reported_as_such_not_as_an_internal_error(client: TestClient) -> None:
    response = client.delete("/api/session")
    assert response.status_code == 405
    error = response.json()["error"]
    assert error["code"] == "method_not_allowed" and error["message"] == "Denne handlingen støttes ikke på denne adressen."
    assert "GET" in response.headers["allow"]
    missing = client.get("/api/finnes-ikke")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_control_channel_requires_instance_secret(raw_client: TestClient) -> None:
    container = raw_client.app.state.container  # type: ignore[attr-defined]
    denied = raw_client.post("/control/launch-url", headers={"X-EmneKlar-Control": "wrong"})
    assert denied.status_code == 403
    browser_like = raw_client.post("/control/launch-url",
                                   headers={"X-EmneKlar-Control": container.control_secret, "Origin": ORIGIN})
    assert browser_like.status_code == 403, "requests from a browser page must never reach the control channel"
    allowed = raw_client.post("/control/launch-url", headers={"X-EmneKlar-Control": container.control_secret})
    assert allowed.status_code == 200
    assert "/auth/launch?token=" in allowed.json()["url"]


def test_session_never_exposes_secrets(client: TestClient) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    container.secrets.set("canvas_token", "1234~" + "a" * 40)
    body = client.get("/api/session").text
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in body
    assert '"token_configured":true' in body


def test_instance_file_written_and_removed(config, container) -> None:  # type: ignore[no-untyped-def]
    from emneklar.main import create_app

    instance = config.run_dir / "instance.json"
    with TestClient(create_app(container), base_url=ORIGIN):
        assert instance.exists()
    assert not instance.exists()
