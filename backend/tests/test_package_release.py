"""scripts/package_release.py builds exactly what scripts/update.py accepts (format contract), reproducibly."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from emneklar.config import REPO_DIR
from emneklar.core.updates.version import Version
from tests.script_loader import load_script

update = load_script("update")
package_release = load_script("package_release")

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git er ikke installert")

SOURCES = {
    "VERSION": "0.3.0\n",
    "CHANGELOG.md": "# Endringslogg\n\n## [Unreleased]\n\n## [0.3.0] – 2026-10-06\n\n### Lagt til\n- Noe nytt.\n",
    "README.md": "# EmneKlar\n",
    "backend/pyproject.toml": "[project]\nname = 'emneklar'\nversion = '0.3.0'\n",
    "backend/constraints.txt": "fastapi==0.162.0\n",
    "backend/alembic.ini": "[alembic]\n",
    "backend/emneklar/__init__.py": "",
    "backend/emneklar/features/help/Veiledning æøå.md": "Hei\n",
    "backend/migrations/versions/0001_initial.py": "# migration\n",
    "scripts/update.py": "# updater\n", "scripts/setup.py": "# setup\n",
    "start.bat": "@echo off\r\n", "update.bat": "@echo off\r\n", "setup.bat": "@echo off\r\n",
}
#: Followed by Git, but made for developing EmneKlar: none of it belongs in the package a teacher gets.
DEVELOPMENT = {
    "CLAUDE.md": "# rules\n", ".claude/launch.json": "{}\n", ".gitignore": "frontend/dist/\n*.db\n",
    ".gitattributes": "*.png binary\n",
    ".github/workflows/ci.yml": "name: CI\n", ".github/dependabot.yml": "version: 2\n",
    "backend/tests/test_noe.py": "def test_noe(): pass\n", "backend/tests/fakes/canvas.py": "",
    "docs/ARCHITECTURE.md": "# Arkitektur\n",
    "frontend/package.json": "{}\n", "frontend/src/main.tsx": "export {};\n", "frontend/src/app.test.tsx": "",
    "frontend/e2e/smoke.spec.ts": "", "scripts/package_release.py": "# packaging\n",
    "scripts/bump_version.py": "# bump\n",
}


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "kilde"
    for rel, text in {**SOURCES, **DEVELOPMENT}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode("utf-8"))
    (root / "frontend" / "dist" / "assets").mkdir(parents=True)
    (root / "frontend" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "frontend" / "dist" / "assets" / "app-1234.js").write_text("console.log(1)", encoding="utf-8")
    (root / "ikke-fulgt.txt").write_text("untracked files are not packaged", encoding="utf-8")
    assert GIT is not None
    subprocess.run([GIT, "init", "-q"], cwd=root, check=True)
    subprocess.run([GIT, "-c", "core.autocrlf=false", "add", *SOURCES, *DEVELOPMENT], cwd=root, check=True)
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
    assert (tree / "backend" / "emneklar" / "features" / "help" / "Veiledning æøå.md").read_text(
        encoding="utf-8") == "Hei\n"
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


def _packaged(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as archive:
        return {name.split("/", 1)[1] for name in archive.namelist()}


def test_the_package_has_the_program_and_nothing_made_for_developing_it(source: Path, tmp_path: Path) -> None:
    zip_path, _, _, _ = package_release.build(source, tmp_path / "out", repository="acme/EmneKlar", allow_dirty=True)
    names = _packaged(zip_path)
    assert names == {*SOURCES, "install.json", "frontend/dist/index.html", "frontend/dist/assets/app-1234.js"}
    assert not names & set(DEVELOPMENT), "development files leaked into the package"
    for forbidden in (".claude/", ".github/", "backend/tests/", "docs/", "frontend/src/", "frontend/e2e/"):
        assert not any(name.startswith(forbidden) for name in names), forbidden
    assert "CLAUDE.md" not in names and not any(name.endswith((".test.tsx", ".spec.ts")) for name in names)
    # Everything the updater and the fallback installation (setup.bat with your own Python) need is there.
    assert {"scripts/update.py", "scripts/setup.py", "backend/constraints.txt", "backend/alembic.ini",
            "backend/migrations/versions/0001_initial.py", *update.RELEASE_REQUIRED_FILES} <= names


def test_a_file_that_is_neither_program_nor_development_stops_the_build(source: Path, tmp_path: Path) -> None:
    assert GIT is not None
    (source / "verktoy").mkdir()
    (source / "verktoy" / "nytt.py").write_text("print(1)\n", encoding="utf-8")
    (source / "NOTES.txt").write_text("husk\n", encoding="utf-8")
    subprocess.run([GIT, "-c", "core.autocrlf=false", "add", "verktoy/nytt.py", "NOTES.txt"], cwd=source, check=True)
    with pytest.raises(package_release.PackageError, match=r"verken merket.*NOTES\.txt, verktoy/nytt\.py"):
        package_release.build(source, tmp_path / "out", repository=None, allow_dirty=True)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_every_file_in_this_repository_is_classified() -> None:
    """A new file must be placed on purpose: in the package, or among the development files."""
    names = package_release.tracked_files(REPO_DIR, working_tree=True)
    assert len(names) > 300
    unknown = [name for name in names if package_release.classify(name) == "unknown"]
    assert not unknown, f"classify these in scripts/package_release.py: {unknown}"
    packaged = {name for name in names if package_release.classify(name) == "package"}
    assert {"VERSION", "start.bat", "scripts/update.py", "backend/emneklar/main.py"} <= packaged
    for name in packaged:
        assert not name.startswith((".claude/", ".github/", "backend/tests/", "docs/", "frontend/")), name
    assert "CLAUDE.md" not in packaged
    assert package_release.classify("backend/tests/test_update_script.py") == "development"
    assert package_release.classify("frontend/src/main.tsx") == "development"


def test_the_working_tree_can_be_packaged_for_testing_before_a_commit(source: Path, tmp_path: Path) -> None:
    (source / "backend" / "emneklar" / "ny_modul.py").write_text("NY = 1\n", encoding="utf-8")  # not added to Git
    (source / "backend" / "emneklar" / "features" / "help" / "Veiledning æøå.md").unlink()  # deleted, not committed
    with pytest.raises(package_release.PackageError, match=r"verken merket.*ikke-fulgt\.txt"):
        # The same rule as for a release: a new file must be placed on purpose before it can be packaged.
        package_release.build(source, tmp_path / "a", repository=None, allow_dirty=False, working_tree=True)
    (source / "ikke-fulgt.txt").unlink()
    names = _packaged(package_release.build(source, tmp_path / "a", repository=None, allow_dirty=False,
                                            working_tree=True)[0])
    assert "backend/emneklar/ny_modul.py" in names
    assert "backend/emneklar/features/help/Veiledning æøå.md" not in names
    # Without --working-tree the folder is packaged as Git knows it: the new module is not there, and the deleted
    # file is an error.
    with pytest.raises(package_release.PackageError, match="finnes ikke som vanlig fil"):
        package_release.build(source, tmp_path / "b", repository=None, allow_dirty=True)


def fake_runtime(folder: Path, *, platform: str = "win-amd64", identifier: str = "cp314-0123456789ab",
                 name: str | None = None) -> Path:
    """A zip shaped like the output of scripts/build_runtime.py: files at the top level and a runtime.json."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name or update.runtime_asset_name(platform, identifier))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("python.exe", "python")
        archive.writestr("runtime.json", json.dumps({"id": identifier, "platform": platform, "python": "3.14.10"}))
    return path


def test_the_runtime_of_a_release_is_recorded_with_its_checksum(source: Path, tmp_path: Path) -> None:
    runtime = fake_runtime(tmp_path / "kjoretid")
    zip_path, _, _, _ = package_release.build(source, tmp_path / "out", repository="acme/EmneKlar", allow_dirty=True,
                                              runtimes=[runtime])
    tree = update.extract_release(zip_path, tmp_path / "staging")
    info = json.loads((tree / "install.json").read_text(encoding="utf-8"))
    assert info["runtimes"] == {"win-amd64": {
        "id": "cp314-0123456789ab", "python": "3.14.10", "asset": runtime.name,
        "sha256": update.sha256_file(runtime), "size": runtime.stat().st_size}}
    wanted = update.release_runtimes(info)["win-amd64"]  # exactly what the updater reads
    update.verify_runtime_archive(runtime, wanted)
    update.extract_runtime(runtime, tmp_path / "runtime", wanted)
    assert "runtime/python.exe" not in _packaged(zip_path), "the runtime is a file of its own, not part of the package"

    # Without a runtime the package is as before: usable with a Python environment made by setup.
    plain, _, _, _ = package_release.build(source, tmp_path / "plain", repository="acme/EmneKlar", allow_dirty=True)
    assert "runtimes" not in json.loads(
        (update.extract_release(plain, tmp_path / "staging2") / "install.json").read_text(encoding="utf-8"))


def test_a_runtime_that_is_not_what_its_name_says_is_refused(source: Path, tmp_path: Path) -> None:
    renamed = fake_runtime(tmp_path / "a", name="EmneKlar-runtime-win-amd64-cp314-ffffffffffff.zip")
    with pytest.raises(package_release.PackageError, match="heter ikke som innholdet sier"):
        package_release.build(source, tmp_path / "out", repository=None, allow_dirty=True, runtimes=[renamed])
    not_a_runtime = tmp_path / "EmneKlar-runtime-win-amd64-cp314-0123456789ab.zip"
    with zipfile.ZipFile(not_a_runtime, "w") as archive:
        archive.writestr("README.txt", "ikke en kjøretid")
    with pytest.raises(package_release.PackageError, match="ikke en kjøretid laget av"):
        package_release.build(source, tmp_path / "out", repository=None, allow_dirty=True, runtimes=[not_a_runtime])
    first, second = fake_runtime(tmp_path / "b"), fake_runtime(tmp_path / "c")
    with pytest.raises(package_release.PackageError, match="To kjøretider for samme plattform"):
        package_release.build(source, tmp_path / "out", repository=None, allow_dirty=True, runtimes=[first, second])
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_release_notes_come_from_the_changelog(source: Path) -> None:
    notes = package_release.release_notes(source, "0.3.0")
    assert notes.startswith("## EmneKlar 0.3.0 – 2026-10-06") and "Noe nytt." in notes
    assert "CHANGELOG.md" in package_release.release_notes(source, "9.9.9")


def test_a_pre_release_is_packaged_and_its_notes_are_what_is_not_released_yet(source: Path, tmp_path: Path) -> None:
    (source / "VERSION").write_text("0.4.0-rc.1\n", encoding="utf-8")
    (source / "CHANGELOG.md").write_text(
        "# Endringslogg\n\n## [Unreleased]\n\n### Lagt til\n- Kommer i 0.4.0.\n\n## [0.3.0] – 2026-10-06\n\n- Gammelt.\n",
        encoding="utf-8")
    zip_path, checksum, _, _ = package_release.build(source, tmp_path / "out", repository="acme/EmneKlar",
                                                     allow_dirty=True)
    assert zip_path.name == "EmneKlar-0.4.0-rc.1.zip" and checksum.name == "EmneKlar-0.4.0-rc.1.zip.sha256"
    tree = update.extract_release(zip_path, tmp_path / "staging")
    version = Version.parse("0.4.0-rc.1")
    assert version is not None
    update.validate_release_tree(tree, version)
    notes = package_release.release_notes(source, "0.4.0-rc.1")
    assert notes.startswith("## EmneKlar 0.4.0-rc.1 (forhåndsversjon)") and "Kommer i 0.4.0." in notes
    assert "Gammelt." not in notes
    # The updater offers it only on the pre-release channel, and the release replaces it for everyone.
    assert Version.parse("0.3.0") < version < Version.parse("0.4.0")  # type: ignore[operator]
