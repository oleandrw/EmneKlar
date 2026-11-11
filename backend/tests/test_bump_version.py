"""scripts/bump_version.py on temporary copies of VERSION, pyproject.toml, package(-lock).json and CHANGELOG.md."""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from emneklar.config import REPO_DIR
from emneklar.core.updates.version import changelog_sections
from tests.script_loader import load_script

bump = load_script("bump_version")

CHANGELOG = """# Endringslogg

Alle merkbare endringer i EmneKlar dokumenteres her.

## [Unreleased]

### Lagt til
- Oppdatering fra appen.

### Rettet
- Lenkesjekk med omdirigering.

## [0.1.0] – 2026-10-01

### Lagt til
- Første versjon.
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir()
    shutil.copy(REPO_DIR / "VERSION", root / "VERSION")
    shutil.copy(REPO_DIR / "backend" / "pyproject.toml", root / "backend" / "pyproject.toml")
    shutil.copy(REPO_DIR / "frontend" / "package.json", root / "frontend" / "package.json")
    if (REPO_DIR / "frontend" / "package-lock.json").is_file():
        shutil.copy(REPO_DIR / "frontend" / "package-lock.json", root / "frontend" / "package-lock.json")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    return root


def current(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def next_minor(version: str) -> str:
    major, minor, _patch = (int(p) for p in version.split("."))
    return f"{major}.{minor + 1}.0"


def test_bump_updates_every_file(repo: Path) -> None:
    old = current(repo)
    new = next_minor(old)
    lock_before = json.loads((repo / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert bump.main([new, "--date", "2026-10-06", "--root", str(repo)]) == 0

    assert (repo / "VERSION").read_text(encoding="utf-8") == f"{new}\n"
    assert tomllib.loads((repo / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == new
    assert json.loads((repo / "frontend" / "package.json").read_text(encoding="utf-8"))["version"] == new
    lock = json.loads((repo / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == new and lock["packages"][""]["version"] == new
    lock["version"], lock["packages"][""]["version"] = lock_before["version"], lock_before["packages"][""]["version"]
    assert lock == lock_before  # nothing else in the lock file changed

    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = changelog_sections(repo / "CHANGELOG.md", limit=10)
    assert [s["version"] for s in sections] == [new, "0.1.0"]  # [Unreleased] is empty again (and hidden)
    assert sections[0]["title"] == "2026-10-06"
    assert "Oppdatering fra appen." in sections[0]["body"] and "Lenkesjekk" in sections[0]["body"]
    assert text.index("## [Unreleased]") < text.index(f"## [{new}] – 2026-10-06") < text.index("## [0.1.0]")
    assert text.count("Oppdatering fra appen.") == 1


def test_pyproject_formatting_and_comments_are_kept(repo: Path) -> None:
    before = (repo / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    new = next_minor(current(repo))
    assert bump.main([new, "--date", "2026-10-06", "--root", str(repo)]) == 0
    after = (repo / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert changed == [(f'version = "{current_version_line(before)}"', f'version = "{new}"')]


def current_version_line(pyproject: str) -> str:
    return tomllib.loads(pyproject)["project"]["version"]


@pytest.mark.parametrize("version", ["0.0.1", "0.1.0", "1.2", "v", "1.2.3.4", "01.2.3", "1.2.3-beta", "abc"])
def test_invalid_or_not_greater_versions_change_nothing(repo: Path, version: str,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert bump.main([version, "--root", str(repo)]) == 1
    assert "Ingen filer er endret" in capsys.readouterr().err
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()} == before


def test_a_pre_release_sets_the_version_everywhere_and_leaves_the_changelog(repo: Path,
                                                                             capsys: pytest.CaptureFixture[str]) -> None:
    old = current(repo)
    final = next_minor(old)
    changelog_before = (repo / "CHANGELOG.md").read_bytes()
    assert bump.main([f"{final}-rc.1", "--root", str(repo)]) == 0
    assert "Forhåndsversjon: CHANGELOG.md er ikke endret" in capsys.readouterr().out
    assert current(repo) == f"{final}-rc.1"
    assert tomllib.loads((repo / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] \
        == f"{final}-rc.1"
    assert json.loads((repo / "frontend" / "package.json").read_text(encoding="utf-8"))["version"] == f"{final}-rc.1"
    assert (repo / "CHANGELOG.md").read_bytes() == changelog_before, "the changes stay under [Unreleased]"

    # The order the updater uses: rc.1 < rc.2 < the release. Going back is refused.
    assert bump.main([f"{final}-rc.1", "--root", str(repo)]) == 1
    assert bump.main([f"{final}-beta.9", "--root", str(repo)]) == 1
    assert bump.main([f"{final}-rc.2", "--root", str(repo)]) == 0
    assert bump.main([final, "--date", "2026-10-06", "--root", str(repo)]) == 0
    assert current(repo) == final
    sections = changelog_sections(repo / "CHANGELOG.md", limit=10)
    assert [s["version"] for s in sections] == [final, "0.1.0"]
    assert "Oppdatering fra appen." in sections[0]["body"], "everything since the last release is in the release"
    assert bump.main([f"{final}-rc.3", "--root", str(repo)]) == 1, "a pre-release of a version that is released"


@pytest.mark.parametrize("version", ["9.0.0-rc", "9.0.0-rc1", "9.0.0-test.1", "9.0.0-rc.01", "9.0.0-RC.1", "9.0.0+build"])
def test_only_alpha_beta_and_rc_with_a_number_are_pre_releases(repo: Path, version: str) -> None:
    before = current(repo)
    assert bump.main([version, "--root", str(repo)]) == 1
    assert current(repo) == before


def test_inconsistent_pyproject_is_refused(repo: Path) -> None:
    pyproject = repo / "backend" / "pyproject.toml"
    old = current(repo)
    pyproject.write_text(pyproject.read_text(encoding="utf-8").replace(f'version = "{old}"', 'version = "0.0.9"'),
                         encoding="utf-8")
    assert bump.main([next_minor(old), "--root", str(repo)]) == 1
    assert current(repo) == old


def test_bad_date_and_existing_section_are_refused(repo: Path) -> None:
    new = next_minor(current(repo))
    assert bump.main([new, "--date", "6.10.2026", "--root", str(repo)]) == 1
    (repo / "CHANGELOG.md").write_text(CHANGELOG.replace("## [0.1.0]", f"## [{new}]"), encoding="utf-8")
    assert bump.main([new, "--root", str(repo)]) == 1


def test_compare_links_are_updated() -> None:
    text = ("# Endringslogg\n\n## [Unreleased]\n- Ny ting\n\n## [1.0.0] – 2026-01-01\n- Start\n\n"
            "[Unreleased]: https://github.com/acme/EmneKlar/compare/v1.0.0...HEAD\n"
            "[1.0.0]: https://github.com/acme/EmneKlar/releases/tag/v1.0.0\n")
    result, had_content = bump.bump_changelog(text, "1.0.0", "1.1.0", "2026-10-06")
    assert had_content
    assert "[Unreleased]: https://github.com/acme/EmneKlar/compare/v1.1.0...HEAD" in result
    assert "[1.1.0]: https://github.com/acme/EmneKlar/compare/v1.0.0...v1.1.0" in result
    assert result.index("## [1.1.0] – 2026-10-06\n\n- Ny ting") < result.index("## [1.0.0]")


def test_empty_unreleased_section_still_bumps_with_a_warning(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "CHANGELOG.md").write_text("# Endringslogg\n\n## [Unreleased]\n\n## [0.1.0] – 2026-10-01\n- X\n",
                                       encoding="utf-8")
    new = next_minor(current(repo))
    assert bump.main([new, "--date", "2026-10-06", "--root", str(repo)]) == 0
    assert "var tom" in capsys.readouterr().out
    assert f"## [Unreleased]\n\n## [{new}] – 2026-10-06\n\n## [0.1.0]" in (repo / "CHANGELOG.md").read_text(
        encoding="utf-8")
