"""scripts/package_release.py builds exactly what scripts/update.py accepts (format contract), reproducibly."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from emneklar.core.updates.version import Version
from tests.script_loader import load_script

update = load_script("update")
package_release = load_script("package_release")

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git er ikke installert")

SOURCES = {
    "VERSION": "0.3.0\n",
    "CHANGELOG.md": "# Endringslogg\n\n## [Unreleased]\n\n## [0.3.0] – 2026-10-06\n\n### Lagt til\n- Noe nytt.\n",
    "backend/pyproject.toml": "[project]\nname = 'emneklar'\nversion = '0.3.0'\n",
    "backend/emneklar/__init__.py": "",
    "scripts/update.py": "# updater\n",
    "start.bat": "@echo off\r\n", "update.bat": "@echo off\r\n", "setup.bat": "@echo off\r\n",
    "docs/Brukerveiledning æøå.md": "Hei\n",
}


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "kilde"
    for rel, text in SOURCES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode("utf-8"))
    (root / "frontend" / "dist" / "assets").mkdir(parents=True)
    (root / "frontend" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "frontend" / "dist" / "assets" / "app-1234.js").write_text("console.log(1)", encoding="utf-8")
    (root / "ikke-fulgt.txt").write_text("untracked files are not packaged", encoding="utf-8")
    assert GIT is not None
    subprocess.run([GIT, "init", "-q"], cwd=root, check=True)
    subprocess.run([GIT, "-c", "core.autocrlf=false", "add", *SOURCES], cwd=root, check=True)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1791244800")  # no commit needed for the timestamps
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    return root


def test_package_is_accepted_by_the_updater(source: Path, tmp_path: Path) -> None:
    out = tmp_path / "dist-release"
    zip_path, checksum_path, digest, count = package_release.build(source, out, repository="acme/EmneKlar",
                                                                   allow_dirty=True)
    assert zip_path.name == "EmneKlar-0.3.0.zip" and count == len(SOURCES) + 3  # + 2 dist files + install.json
    assert checksum_path.read_text(encoding="ascii") == f"{digest}  EmneKlar-0.3.0.zip\n"

    assert update.verify_checksum(zip_path, checksum_path.read_text(encoding="ascii")) == digest
    tree = update.extract_release(zip_path, tmp_path / "staging")
    update.validate_release_tree(tree, Version(0, 3, 0))
    assert json.loads((tree / "install.json").read_text(encoding="utf-8")) == {
        "type": "release", "version": "0.3.0", "repository": "acme/EmneKlar"}
    assert (tree / "frontend" / "dist" / "assets" / "app-1234.js").is_file()
    assert (tree / "docs" / "Brukerveiledning æøå.md").read_text(encoding="utf-8") == "Hei\n"
    assert (tree / "start.bat").read_bytes() == b"@echo off\r\n"  # batch files keep CRLF
    assert not (tree / "ikke-fulgt.txt").exists()

    again, _, digest_again, _ = package_release.build(source, tmp_path / "again", repository="acme/EmneKlar",
                                                      allow_dirty=True)
    assert digest_again == digest and again.read_bytes() == zip_path.read_bytes()  # reproducible


def test_uncommitted_changes_and_missing_ui_are_refused(source: Path, tmp_path: Path) -> None:
    with pytest.raises(package_release.PackageError, match="ikke er committet"):
        package_release.build(source, tmp_path / "out", repository=None, allow_dirty=False)
    with pytest.raises(package_release.PackageError, match="Ugyldig repository"):
        package_release.build(source, tmp_path / "out", repository="ikke gyldig", allow_dirty=True)
    shutil.rmtree(source / "frontend" / "dist")
    with pytest.raises(package_release.PackageError, match="npm run build"):
        package_release.build(source, tmp_path / "out", repository=None, allow_dirty=True)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_release_notes_come_from_the_changelog(source: Path) -> None:
    notes = package_release.release_notes(source, "0.3.0")
    assert notes.startswith("## EmneKlar 0.3.0 – 2026-10-06") and "Noe nytt." in notes
    assert "CHANGELOG.md" in package_release.release_notes(source, "9.9.9")
