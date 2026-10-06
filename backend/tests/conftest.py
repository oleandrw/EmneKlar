"""Shared fixtures: isolated data folder, in-memory secrets, no real network."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from emneklar.config import RuntimeConfig
from emneklar.core.auth.secrets import MemorySecretStore
from emneklar.core.container import AppContainer
from emneklar.main import create_app

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


@pytest.fixture
def client(raw_client: TestClient) -> TestClient:
    """A logged-in client that sends Origin and CSRF headers like the real frontend."""
    response = raw_client.get(f"/auth/launch?token={LAUNCH_TOKEN}", follow_redirects=False)
    assert response.status_code == 303
    csrf = raw_client.get("/api/session").json()["csrf_token"]
    raw_client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
    return raw_client
