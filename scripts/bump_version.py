"""Set a new EmneKlar version everywhere it is recorded.

    python scripts/bump_version.py 0.2.0 [--date 2026-10-06] [--root <repo>]
    python scripts/bump_version.py 0.2.0-rc.1          (a pre-release: alpha, beta or rc, with a number)

Updates
  * VERSION (the single source of truth),
  * backend/pyproject.toml ([project] version),
  * frontend/package.json and frontend/package-lock.json (top-level "version" and packages[""].version),
  * CHANGELOG.md: the content of "## [Unreleased]" moves under a new "## [0.2.0] – 2026-10-06" heading and
    an empty [Unreleased] section is left on top (compare links at the bottom are updated if present).

A pre-release (``0.2.0-rc.1``) gets the same version in every file, but CHANGELOG.md is left as it is: the changes
stay under [Unreleased] until the real release, and the release notes of the pre-release are that section
(scripts/package_release.py). The tag ``v0.2.0-rc.1`` is published as a pre-release on GitHub, so only installations
on the channel «Også forhåndsversjoner» are offered it.

The new version must be MAJOR.MINOR.PATCH, optionally followed by -alpha.N, -beta.N or -rc.N, and greater than the
current one (0.2.0-rc.1 < 0.2.0-rc.2 < 0.2.0, the order the updater uses). Every file is checked and prepared first;
nothing is written unless all of them can be updated.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # emneklar.core.updates.version uses only the standard library

from emneklar.core.updates.version import Version  # noqa: E402 - the same ordering as the updater

# alpha, beta and rc are the pre-release names that are valid both as SemVer and as a Python package version.
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?$")
UNRELEASED = re.compile(r"^## \[Unreleased\][ \t]*$", re.IGNORECASE | re.MULTILINE)


class BumpError(Exception):
    pass


def parse_version(text: str) -> Version:
    version = Version.parse(text.strip()) if VERSION_RE.match(text.strip()) else None
    if version is None:
        raise BumpError(f"«{text.strip()}» er ikke en gyldig versjon. Bruk formen MAJOR.MINOR.PATCH, f.eks. 1.4.2 – "
                        "eller en forhåndsversjon som 1.5.0-rc.1 (alpha, beta eller rc med et nummer).")
    return version


def bump_pyproject(text: str, old: str, new: str) -> str:
    section = re.search(r"(?ms)^\[project\][ \t]*\n(.*?)(?=^\[|\Z)", text)
    if section is None:
        raise BumpError("Fant ikke [project] i backend/pyproject.toml.")
    pattern = re.compile(r'(?m)^(version\s*=\s*")([^"]*)(")')
    found = pattern.search(section.group(1))
    if found is None:
        raise BumpError("Fant ikke version = \"…\" under [project] i backend/pyproject.toml.")
    if found.group(2) != old:
        raise BumpError(f"backend/pyproject.toml har versjon {found.group(2)}, men VERSION sier {old}. Rett dette først.")
    body = pattern.sub(lambda m: f"{m.group(1)}{new}{m.group(3)}", section.group(1), count=1)
    result = text[:section.start(1)] + body + text[section.end(1):]
    if tomllib.loads(result)["project"]["version"] != new:
        raise BumpError("Kontrollen av backend/pyproject.toml feilet etter endringen.")
    return result


def bump_package_json(text: str, new: str, *, name: str) -> str:
    """Set the top-level "version" (and packages[""].version in a lock file) without reformatting the file."""
    data = json.loads(text)
    expected = copy.deepcopy(data)
    expected["version"] = new
    result, count = re.subn(r'(?m)^(  "version": ")([^"]*)(")', lambda m: f"{m.group(1)}{new}{m.group(3)}", text,
                            count=1)
    if count != 1:
        raise BumpError(f"Fant ikke \"version\" øverst i {name}.")
    root_package = (data.get("packages") or {}).get("") if isinstance(data.get("packages"), dict) else None
    if isinstance(root_package, dict) and "version" in root_package:
        expected["packages"][""]["version"] = new
        block = re.search(r'(?m)^    "": \{\n(.*?)^    \}', result, re.DOTALL)
        if block is None:
            raise BumpError(f"Fant ikke packages[\"\"] i {name}.")
        inner, count = re.subn(r'(?m)^(      "version": ")([^"]*)(")', lambda m: f"{m.group(1)}{new}{m.group(3)}",
                               block.group(1), count=1)
        if count != 1:
            raise BumpError(f"Fant ikke packages[\"\"].version i {name}.")
        result = result[:block.start(1)] + inner + result[block.end(1):]
    if json.loads(result) != expected:
        raise BumpError(f"Kontrollen av {name} feilet etter endringen (uventet format).")
    return result


def bump_changelog(text: str, old: str, new: str, day: str) -> tuple[str, bool]:
    """Returns (new text, whether [Unreleased] had any content)."""
    heading = UNRELEASED.search(text)
    if heading is None:
        raise BumpError("CHANGELOG.md mangler overskriften «## [Unreleased]».")
    if re.search(rf"^## \[{re.escape(new)}\]", text, re.MULTILINE):
        raise BumpError(f"CHANGELOG.md har allerede en seksjon for {new}.")
    following = re.compile(r"^## \[", re.MULTILINE).search(text, heading.end())
    links = re.compile(r"^\[[^\]]+\]:\s", re.MULTILINE).search(text, heading.end())
    end = min(m.start() for m in (following, links) if m is not None) if (following or links) else len(text)
    content = text[heading.end():end].strip("\n")
    section = f"## [{new}] – {day}\n\n" + (f"{content}\n\n" if content else "")
    result = text[:heading.end()] + "\n\n" + section + text[end:]
    # Keep a Changelog compare links, if the file uses them.
    link = re.search(r"(?mi)^\[unreleased\]:\s*(\S+)/compare/(\S+)\.\.\.HEAD[ \t]*$", result)
    if link:
        base = link.group(1)
        result = (result[:link.start()] + f"[Unreleased]: {base}/compare/v{new}...HEAD\n"
                  f"[{new}]: {base}/compare/v{old}...v{new}" + result[link.end():])
    return result.rstrip("\n") + "\n", bool(content)


def _write(path: Path, text: str, newline: str) -> None:
    partial = path.with_name(path.name + ".bump")
    partial.write_bytes(text.replace("\n", newline).encode("utf-8"))
    os.replace(partial, path)


def _read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), newline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Setter ny versjon av EmneKlar i alle filer som har versjonsnummer.")
    parser.add_argument("version", help="ny versjon, f.eks. 0.2.0")
    parser.add_argument("--date", help="utgivelsesdato i CHANGELOG.md (ÅÅÅÅ-MM-DD, standard: i dag)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root: Path = args.root
    try:
        new = args.version.strip().removeprefix("v")
        new_version = parse_version(new)
        prerelease = new_version.pre is not None
        day = args.date or date.today().isoformat()
        try:
            date.fromisoformat(day)
        except ValueError as exc:
            raise BumpError(f"Ugyldig dato «{day}». Bruk formen ÅÅÅÅ-MM-DD.") from exc
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise BumpError(f"Ugyldig dato «{day}». Bruk formen ÅÅÅÅ-MM-DD.")
        version_file = root / "VERSION"
        old = version_file.read_text(encoding="utf-8").strip()
        if not parse_version(old) < new_version:
            raise BumpError(f"Ny versjon ({new}) må være høyere enn nåværende versjon ({old}).")

        changes: list[tuple[Path, str, str]] = [(version_file, f"{new}\n", "\n")]
        text, newline = _read(root / "backend" / "pyproject.toml")
        changes.append((root / "backend" / "pyproject.toml", bump_pyproject(text, old, new), newline))
        for name in ("package.json", "package-lock.json"):
            path = root / "frontend" / name
            if path.is_file():
                text, newline = _read(path)
                changes.append((path, bump_package_json(text, new, name=f"frontend/{name}"), newline))
        text, newline = _read(root / "CHANGELOG.md")
        if prerelease:
            # The changes stay under [Unreleased] until the real release; they are the pre-release's release notes.
            if UNRELEASED.search(text) is None:
                raise BumpError("CHANGELOG.md mangler overskriften «## [Unreleased]».")
            had_content = True
        else:
            changelog, had_content = bump_changelog(text, old, new, day)
            changes.append((root / "CHANGELOG.md", changelog, newline))
    except (BumpError, OSError, ValueError, KeyError) as exc:
        print(f"Feil: {exc}", file=sys.stderr)
        print("Ingen filer er endret.", file=sys.stderr)
        return 1

    for path, content, newline in changes:
        _write(path, content, newline)
    print(f"Versjon {old} → {new}")
    for path, _content, _newline in changes:
        print(f"  oppdatert: {path.relative_to(root).as_posix()}")
    if prerelease:
        print("Forhåndsversjon: CHANGELOG.md er ikke endret. Endringene står fortsatt under [Unreleased] og blir "
              "utgivelsesnotatene. Taggen publiseres som forhåndsversjon på GitHub.")
    elif not had_content:
        print("Advarsel: [Unreleased] i CHANGELOG.md var tom – skriv inn endringene under "
              f"«## [{new}] – {day}» før utgivelsen.")
    print(f"Neste steg: se over endringene (git diff), commit dem og lag taggen v{new}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
