"""The built frontend: hashed files are cached for good and compressed; the entry page and the API stay fresh."""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from emneklar.config import RuntimeConfig
from emneklar.core.auth.secrets import MemorySecretStore
from emneklar.core.container import AppContainer
from emneklar.main import IMMUTABLE, create_app
from tests.conftest import LAUNCH_TOKEN, ORIGIN, login

SCRIPT = "export const hello = () => 'hei';\n" * 200


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><script type="module" src="/assets/index-a1b2c3.js"></script>',
                                     encoding="utf-8")
    (dist / "assets" / "index-a1b2c3.js").write_bytes(SCRIPT.encode("utf-8"))  # exact bytes, also on Windows
    (dist / "assets" / "tiny-d4e5f6.css").write_text("a{}", encoding="utf-8")
    config = RuntimeConfig(data_dir=tmp_path / "data", frontend_dist=dist, secret_backend="memory",
                           parser_isolation=False, dev_launch_token=LAUNCH_TOKEN, allow_insecure_canvas=True)
    app = create_app(AppContainer(config, secret_store=MemorySecretStore()))
    with TestClient(app, base_url=ORIGIN) as client:
        yield login(client)


def test_hashed_assets_are_cached_for_good_and_compressed(app_client: TestClient) -> None:
    response = app_client.get("/assets/index-a1b2c3.js", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE == "public, max-age=31536000, immutable"
    assert response.headers["content-encoding"] == "gzip"
    assert response.text == SCRIPT, "the client unpacks it to the same file"
    assert "content-security-policy" in response.headers, "the security headers still apply"
    raw = app_client.get("/assets/index-a1b2c3.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in raw.headers and raw.text == SCRIPT
    assert len(gzip.compress(SCRIPT.encode())) < len(SCRIPT)
    small = app_client.get("/assets/tiny-d4e5f6.css", headers={"Accept-Encoding": "gzip"})
    assert small.headers["cache-control"] == IMMUTABLE and "content-encoding" not in small.headers, "too small to pack"


def test_a_cached_asset_revalidates_with_304_and_keeps_the_cache_header(app_client: TestClient) -> None:
    first = app_client.get("/assets/index-a1b2c3.js")
    again = app_client.get("/assets/index-a1b2c3.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == IMMUTABLE


def test_the_entry_page_and_the_api_are_never_cached_for_good(app_client: TestClient) -> None:
    page = app_client.get("/oversikt")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    api = app_client.get("/api/session", headers={"Accept-Encoding": "gzip"})
    assert api.headers["cache-control"] == "no-store" and "content-encoding" not in api.headers
    missing = app_client.get("/assets/finnes-ikke-123.js")
    assert missing.status_code == 404 and missing.headers.get("cache-control") != IMMUTABLE
