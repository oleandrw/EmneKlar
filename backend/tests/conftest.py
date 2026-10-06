"""Shared fixtures: isolated data folder, in-memory secrets, no real network."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.config import RuntimeConfig
from emneklar.core.auth.secrets import MemorySecretStore
from emneklar.core.container import AppContainer
from emneklar.main import create_app
from tests.fakes.fake_canvas import TOKEN as FAKE_TOKEN
from tests.fakes.fake_canvas import FakeCanvasState, create_fake_canvas, seed_state

ORIGIN = "http://127.0.0.1:8765"
LAUNCH_TOKEN = "test-launch-token"


@pytest.fixture
def config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        data_dir=tmp_path / "data",
        frontend_dist=None,
        secret_backend="memory",
        parser_isolation=False,
        dev_launch_token=LAUNCH_TOKEN,
        allow_insecure_canvas=True,
    )


@pytest.fixture
def container(config: RuntimeConfig) -> AppContainer:
    return AppContainer(config, secret_store=MemorySecretStore())


@pytest.fixture
def raw_client(container: AppContainer) -> Iterator[TestClient]:
    app = create_app(container)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client


def login(raw: TestClient) -> TestClient:
    response = raw.get(f"/auth/launch?token={LAUNCH_TOKEN}", follow_redirects=False)
    assert response.status_code == 303
    csrf = raw.get("/api/session").json()["csrf_token"]
    raw.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
    return raw


@pytest.fixture
def client(raw_client: TestClient) -> TestClient:
    """A logged-in client that sends Origin and CSRF headers like the real frontend."""
    return login(raw_client)


# -- Canvas-connected app (fake Canvas over ASGI) ------------------------------------------------

CANVAS_BASE = "http://canvas.test"


@pytest.fixture
def fake_state() -> FakeCanvasState:
    return seed_state(CANVAS_BASE)


@pytest.fixture
def canvas_container(config: RuntimeConfig, fake_state: FakeCanvasState) -> AppContainer:
    transport = httpx.ASGITransport(app=create_fake_canvas(fake_state))
    return AppContainer(config, secret_store=MemorySecretStore(), canvas_transport=transport)


@pytest.fixture
def canvas_client(canvas_container: AppContainer) -> Iterator[TestClient]:
    """Logged in, connected to the fake Canvas, course 101 selected."""
    app = create_app(canvas_container)
    with TestClient(app, base_url=ORIGIN) as raw:
        client = login(raw)
        response = client.put("/api/canvas/connection", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN})
        assert response.status_code == 200, response.text
        assert client.put("/api/context/course", json={"course_id": "101"}).status_code == 200
        yield client


def wait_for_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")
