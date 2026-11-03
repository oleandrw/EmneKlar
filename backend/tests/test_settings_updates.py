"""Innstillinger (sections, flags, local data) and the update service (version check, major guard)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.core.container import AppContainer
from emneklar.core.updates import service as update_service
from emneklar.core.updates.service import (
    UpdateService,
    git_remote_repository,
    install_json_repository,
    update_command,
)
from emneklar.core.updates.version import Version, changelog_sections
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID

# ------------------------------------------------------------------------------------- settings


def test_settings_payload_has_no_secrets(canvas_client: TestClient) -> None:
    data = canvas_client.get("/api/settings").json()
    assert data["version"] and {f["key"] for f in data["flags"]} >= {"quiz_assistant", "homepage_builder"}
    text = json.dumps(data).lower()
    assert "fakecanvastoken" not in text and "api_key" not in text and "ai" not in data["settings"]


def test_patch_settings_validates_sections_and_fields(canvas_client: TestClient) -> None:
    ok = canvas_client.patch("/api/settings/general", json={"theme": "dark", "page_size": 50})
    assert ok.status_code == 200 and ok.json()["settings"]["general"]["theme"] == "dark"
    assert canvas_client.patch("/api/settings/general", json={"page_size": 5}).status_code == 400
    assert canvas_client.patch("/api/settings/general", json={"dry_run": True}).status_code == 400
    assert canvas_client.patch("/api/settings/canvas", json={"base_url": "https://x"}).status_code == 404
    assert canvas_client.patch("/api/settings/analysis", json={"regulatory_profile": "nope"}).status_code == 400
    assert canvas_client.patch("/api/settings/advanced", json={"update_repository": "ikke gyldig"}).status_code == 400
    repo = canvas_client.patch("/api/settings/advanced", json={"update_repository": "acme/EmneKlar"}).json()
    assert repo["settings"]["advanced"]["update_repository"] == "acme/EmneKlar"
    cleared = canvas_client.patch("/api/settings/advanced", json={"update_repository": ""}).json()
    assert cleared["settings"]["advanced"]["update_repository"] is None


def test_feature_flags_can_be_overridden_and_reset(canvas_client: TestClient) -> None:
    off = canvas_client.put("/api/flags/quiz_assistant", json={"enabled": False}).json()["flags"]
    assert next(f for f in off if f["key"] == "quiz_assistant")["enabled"] is False
    assert canvas_client.get(f"/api/courses/{COURSE_ID}/quizzes").status_code == 403
    reset = canvas_client.put("/api/flags/quiz_assistant", json={"enabled": None}).json()["flags"]
    flag = next(f for f in reset if f["key"] == "quiz_assistant")
    assert flag["enabled"] is True and flag["overridden"] is False
    assert canvas_client.put("/api/flags/finnes_ikke", json={"enabled": True}).status_code == 404


def test_storage_overview_and_clearing_analysis_data(canvas_client: TestClient) -> None:
    job = canvas_client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["structure"]}).json()
    wait_for_job(canvas_client, job["id"])
    before = canvas_client.get("/api/system/storage").json()
    assert before["counts"]["snapshots"] >= 1 and before["data_dir"]
    result = canvas_client.post("/api/system/storage/clear", json={"target": "analysis"}).json()
    assert result["counts"]["snapshots"] == 0 and result["counts"]["findings"] == 0
    assert canvas_client.post("/api/system/storage/clear", json={"target": "everything"}).status_code == 422


def test_unpublished_content_can_be_left_out_of_analysis(canvas_client: TestClient) -> None:
    def pages_total() -> int:
        job = canvas_client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["accessibility"]}).json()
        done = wait_for_job(canvas_client, job["id"])
        return sum(1 for f in canvas_client.get(
            f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()["items"]
            if f["object_id"] == "gammelt-utkast") + done["progress"]["total"]

    with_unpublished = pages_total()
    canvas_client.patch("/api/settings/analysis", json={"include_unpublished": False})
    assert pages_total() < with_unpublished


# -------------------------------------------------------------------------------------- versions


def test_semver_ordering_and_major_detection() -> None:
    parse = Version.parse
    assert parse("v1.2.3") == Version(1, 2, 3) and parse("1.0") is None and parse("x") is None
    assert parse("1.0.0-beta.2") < parse("1.0.0-beta.10") < parse("1.0.0") < parse("1.0.1") < parse("1.1.0")
    v = parse("0.1.0")
    assert v and v.is_major_upgrade_to(Version(0, 2, 0)), "on 0.x a minor bump may break things"
    assert v and not v.is_major_upgrade_to(Version(0, 1, 5))
    assert Version(1, 4, 0).is_major_upgrade_to(Version(2, 0, 0))
    assert not Version(1, 4, 0).is_major_upgrade_to(Version(1, 9, 0))


def test_changelog_sections(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Endringslogg\n\n## [Unreleased]\n\n## [0.2.0] – 2026-11-01\n### Lagt til\n- Ny ting\n\n"
                    "## [0.1.0] – 2026-10-06\n- Første\n", encoding="utf-8")
    sections = changelog_sections(path)
    assert [s["version"] for s in sections] == ["0.2.0", "0.1.0"] and "Ny ting" in sections[0]["body"]


@pytest.mark.parametrize("url", ["https://github.com/acme/EmneKlar.git", "git@github.com:acme/EmneKlar.git",
                                 "https://github.com/acme/EmneKlar"])
def test_repository_from_git_remote(tmp_path: Path, url: str) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text(f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {url}\n',
                                              encoding="utf-8")
    assert git_remote_repository(tmp_path) == "acme/EmneKlar"


def test_repository_from_a_release_package(container: AppContainer, tmp_path: Path) -> None:
    (tmp_path / "install.json").write_text('{"type": "release", "version": "0.1.0", "repository": "acme/EmneKlar"}',
                                           encoding="utf-8")
    assert install_json_repository(tmp_path) == "acme/EmneKlar"
    container.migrate()
    assert UpdateService(container, repo_dir=tmp_path).repository() == "acme/EmneKlar"
    (tmp_path / "install.json").write_text('{"repository": "https://evil.example/x"}', encoding="utf-8")
    assert install_json_repository(tmp_path) is None


def test_update_command_survives_spaces_in_the_install_path() -> None:
    bat = Path(r"C:\Users\Ola Nordmann\EmneKlar\update.bat")
    command = update_command(bat, allow_major=False, comspec=r"C:\Windows\system32\cmd.exe")
    assert command == r'"C:\Windows\system32\cmd.exe" /d /s /c ""C:\Users\Ola Nordmann\EmneKlar\update.bat" --from-app"'
    assert update_command(bat, allow_major=True, comspec="cmd.exe").endswith('--from-app --allow-major"')


@pytest.mark.skipif(os.name != "nt", reason="needs cmd.exe")
def test_update_command_really_starts_a_bat_file_in_a_folder_with_spaces(tmp_path: Path) -> None:
    folder = tmp_path / "Ola Nordmann" / "EmneKlar"
    folder.mkdir(parents=True)
    (folder / "update.bat").write_text('@echo off\r\necho %*> "%~dp0args.txt"\r\n', encoding="ascii")
    subprocess.run(update_command(folder / "update.bat", allow_major=True), check=True, timeout=60)
    assert (folder / "args.txt").read_text(encoding="ascii").strip() == "--from-app --allow-major"


def github(release: dict[str, Any] | None, status: int = 200) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=release or {"message": "Not Found"})

    return seen, httpx.MockTransport(handler)


async def test_update_check_reports_new_version(container: AppContainer, tmp_path: Path) -> None:
    container.migrate()
    container.settings.update(lambda s: setattr(s.advanced, "update_repository", "acme/EmneKlar"))
    seen, container.update_transport = github({"tag_name": "v9.0.0", "name": "EmneKlar 9", "body": "Nytt",
                                               "html_url": "https://github.com/acme/EmneKlar/releases/tag/v9.0.0",
                                               "prerelease": False, "draft": False})
    service = UpdateService(container, repo_dir=tmp_path)
    status = await service.check()
    assert seen[0].url.path == "/repos/acme/EmneKlar/releases/latest"
    assert "EmneKlar/" in seen[0].headers["user-agent"]
    assert status["update_available"] and status["is_major"] and status["latest"]["version"] == "9.0.0"
    assert status["install"]["type"] == "source"


async def test_update_check_failures_are_stored(container: AppContainer, tmp_path: Path) -> None:
    from emneklar.core.errors import AppError

    container.migrate()
    service = UpdateService(container, repo_dir=tmp_path)
    with pytest.raises(AppError):
        await service.check()  # no repository configured
    container.settings.update(lambda s: setattr(s.advanced, "update_repository", "acme/EmneKlar"))
    _, container.update_transport = github(None, status=404)
    with pytest.raises(AppError):
        await service.check()
    assert "Fant ingen utgivelser" in service.status()["last_error"]


def test_start_refuses_major_without_confirmation(canvas_client: TestClient, canvas_container: AppContainer,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[str] = []
    monkeypatch.setattr(update_service.subprocess, "Popen", lambda args, **_: launched.append(args))
    monkeypatch.setattr(UpdateService, "install_info", lambda self: {"type": "release", "can_start_from_app": True})
    canvas_client.patch("/api/settings/advanced", json={"update_repository": "acme/EmneKlar"})
    _, canvas_container.update_transport = github({"tag_name": "v9.0.0", "prerelease": False, "draft": False})
    assert canvas_client.post("/api/updates/check").json()["is_major"] is True
    refused = canvas_client.post("/api/updates/start", json={})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "confirmation_required"
    assert launched == [], "nothing is started without confirmation"
    started = canvas_client.post("/api/updates/start", json={"confirm_major": True}).json()
    assert started["started"] is True and launched and "--allow-major" in launched[0]


def test_only_the_newest_database_copies_are_kept(tmp_path: Path) -> None:
    from emneklar.core.storage.maintenance import prune_database_copies

    folder = tmp_path / "database"
    folder.mkdir()
    for n in range(8):
        for prefix in ("for-oppdatering-0.1.0", "for-migrering-abc"):
            path = folder / f"{prefix}-{n}.db"
            path.write_bytes(b"x")
            os.utime(path, (1_700_000_000 + n, 1_700_000_000 + n))
    (folder / "min-egen-kopi.db").write_bytes(b"x")
    assert prune_database_copies(tmp_path, keep=5) == 6
    left = sorted(p.name for p in folder.iterdir())
    assert "min-egen-kopi.db" in left, "files EmneKlar did not make are never touched"
    assert [n for n in left if n.startswith("for-oppdatering")] == [f"for-oppdatering-0.1.0-{n}.db" for n in range(3, 8)]
