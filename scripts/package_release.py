"""Build the release package that update.bat (scripts/update.py) installs.

    python scripts/package_release.py [--repository eier/repo] [--out dist-release] [--notes-out FIL]
                                      [--runtime KJØRETID.zip ...] [--allow-dirty | --working-tree]

Creates ``dist-release/EmneKlar-<versjon>.zip`` with
  * the program files Git follows (see PACKAGED_FILES and PACKAGED_PREFIXES below) – what is needed to run and
    update EmneKlar, and nothing made for developing it (no tests, no ``.github``, no ``.claude``, no ``CLAUDE.md``,
    no frontend sources, no developer documentation),
  * the built user interface ``frontend/dist`` (run ``npm ci && npm run build`` in frontend first), and
  * a generated ``install.json`` = {"type": "release", "version": ..., "repository": "eier/repo" or null,
    "runtimes": {...}},
all inside one top-level folder ``EmneKlar-<versjon>/``, plus ``EmneKlar-<versjon>.zip.sha256``
(``<sha256>  <filnavn>``, the sha256sum format). Entries are sorted and time-stamped with the commit time
(or SOURCE_DATE_EPOCH), so the same commit and the same build give the same zip.

The package is the same for every platform. The Python runtime an installation runs on is a separate file per
platform (scripts/build_runtime.py). ``--runtime`` names the runtime zips that belong to this release: for each,
``install.json`` records ``runtimes[<plattform>] = {id, python, asset, sha256, size}``. That SHA-256 is how the
updater trusts the runtime it downloads – the checksum (and, when used, the signature) of this package covers it.

Every file Git follows must be classified as a program file or a development file: a file that is neither stops
the build, so a new file is never packaged – or left out – by accident.

``--working-tree`` is for testing a package before anything is committed: it packages the folder as it stands
(uncommitted changes and new files Git does not ignore; deleted files are left out). A release is always built
from a clean commit.

The repository defaults to $GITHUB_REPOSITORY (set in GitHub Actions), then the ``origin`` remote.
``--notes-out`` writes the CHANGELOG.md section for the version (used as the GitHub release notes).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # emneklar.* helpers below use only the standard library

import update  # noqa: E402 - scripts/update.py: the format of a release package is defined there

from emneklar.core.updates.version import Version, changelog_sections  # noqa: E402


class PackageError(Exception):
    pass


#: The installed program: what a teacher's installation needs to run and to update itself.
PACKAGED_FILES = frozenset({
    "VERSION", "CHANGELOG.md", "README.md", "setup.bat", "start.bat", "update.bat",
    "backend/pyproject.toml", "backend/constraints.txt", "backend/alembic.ini",
    "scripts/setup.py", "scripts/update.py",
})
PACKAGED_PREFIXES = ("backend/emneklar/", "backend/migrations/")
#: Followed by Git, but only used to develop, test and release EmneKlar – never part of the package.
DEVELOPMENT_FILES = frozenset({
    "CLAUDE.md", ".gitignore", ".gitattributes", "scripts/package_release.py", "scripts/bump_version.py",
    "scripts/build_runtime.py", "scripts/build_installer.py", "scripts/local_update_test.py",
    "scripts/sign_release.py", "scripts/verify_windows_installer.py",
})
DEVELOPMENT_PREFIXES = (".claude/", ".github/", "backend/tests/", "docs/", "frontend/", "packaging/")


def classify(name: str) -> str:
    """``package`` (goes into the zip), ``development`` (never does) or ``unknown`` (the build stops)."""
    if name in PACKAGED_FILES or name.startswith(PACKAGED_PREFIXES):
        return "package"
    if name in DEVELOPMENT_FILES or name.startswith(DEVELOPMENT_PREFIXES):
        return "development"
    return "unknown"


def git(root: Path, *args: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise PackageError("Fant ikke git. Utgivelsespakken lages fra filene Git følger.")
    try:
        done = subprocess.run([executable, *args], cwd=root, capture_output=True, check=False)
    except OSError as exc:
        raise PackageError(f"Klarte ikke å kjøre git: {exc}") from exc
    if done.returncode != 0:
        raise PackageError(f"git {' '.join(args)} feilet: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def _names(output: bytes) -> set[str]:
    return {name for name in output.decode("utf-8").split("\0") if name}


def tracked_files(root: Path, *, working_tree: bool = False) -> list[str]:
    """The files Git follows. With ``working_tree`` also new files Git does not ignore, minus deleted ones."""
    if not working_tree:
        return sorted(_names(git(root, "ls-files", "-z")))
    present = _names(git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    return sorted(present - _names(git(root, "ls-files", "-z", "--deleted")))


def default_repository(root: Path) -> str | None:
    env = os.environ.get("GITHUB_REPOSITORY", "")
    if update.REPO_RE.match(env):
        return env
    return update.git_remote_repository(root)


def zip_timestamp(root: Path) -> tuple[int, int, int, int, int, int]:
    raw = os.environ.get("SOURCE_DATE_EPOCH") or git(root, "log", "-1", "--format=%ct").decode().strip()
    try:
        epoch = int(raw)
    except ValueError:
        epoch = int(time.time())
    stamp = time.gmtime(max(epoch, 315532800))  # zip timestamps start in 1980
    return stamp.tm_year, stamp.tm_mon, stamp.tm_mday, stamp.tm_hour, stamp.tm_min, stamp.tm_sec


def release_notes(root: Path, version: str) -> str:
    sections = changelog_sections(root / "CHANGELOG.md", limit=1000)
    for section in sections:
        if section["version"] == version:
            title = f"EmneKlar {version}" + (f" – {section['title']}" if section["title"] else "")
            return f"## {title}\n\n{section['body'].strip() or 'Ingen endringsnotater.'}\n"
    parsed = Version.parse(version)
    if parsed is not None and parsed.pre is not None:
        # A pre-release has no section of its own (scripts/bump_version.py): its notes are what is not released yet.
        for section in sections:
            if section["version"].lower() == "unreleased" and section["body"].strip():
                return (f"## EmneKlar {version} (forhåndsversjon)\n\nEndringer siden forrige utgivelse – ennå ikke "
                        f"endelig utgitt:\n\n{section['body'].strip()}\n")
    return f"## EmneKlar {version}\n\nSe CHANGELOG.md for endringer.\n"


def describe_runtime(path: Path) -> tuple[str, dict[str, object]]:
    """``(platform, install.json entry)`` for a runtime zip built by scripts/build_runtime.py."""
    try:
        with zipfile.ZipFile(path) as archive:
            info = json.loads(archive.read(update.RUNTIME_INFO).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise PackageError(f"{path} er ikke en kjøretid laget av scripts/build_runtime.py ({exc}).") from exc
    platform, identifier = str(info.get("platform", "")), str(info.get("id", ""))
    if path.name != update.runtime_asset_name(platform, identifier):
        raise PackageError(f"{path.name} heter ikke som innholdet sier ({update.runtime_asset_name(platform, identifier)}).")
    return platform, {"id": identifier, "python": str(info.get("python", "")), "asset": path.name,
                      "sha256": update.sha256_file(path), "size": path.stat().st_size}


def build(root: Path, out_dir: Path, *, repository: str | None, allow_dirty: bool, working_tree: bool = False,
          runtimes: Sequence[Path] = ()) -> tuple[Path, Path, str, int]:
    raw_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    version = Version.parse(raw_version)
    if version is None or str(version) != raw_version:
        raise PackageError(f"VERSION inneholder ikke en gyldig versjon: {raw_version!r}")
    dist = root / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise PackageError("frontend/dist/index.html mangler. Bygg brukergrensesnittet først: "
                           "cd frontend && npm ci && npm run build")
    if repository is not None and not update.REPO_RE.match(repository):
        raise PackageError(f"Ugyldig repository {repository!r}; bruk formen eier/repo.")
    dirty = git(root, "status", "--porcelain", "--untracked-files=no").decode("utf-8", "replace").strip()
    if dirty and not (allow_dirty or working_tree):
        raise PackageError("Arbeidskatalogen har endringer som ikke er committet. En utgivelse skal bygges fra en ren "
                           "commit (bruk --allow-dirty eller --working-tree bare til testing).\n" + dirty)

    files: dict[str, Path] = {}
    unknown: list[str] = []
    for name in tracked_files(root, working_tree=working_tree):
        path = root / name
        if name.startswith("frontend/dist/") or name == "install.json":
            raise PackageError(f"{name} skal ikke være i Git; den lages når pakken bygges.")
        kind = classify(name)
        if kind == "unknown":
            unknown.append(name)
        if kind != "package":
            continue
        if path.is_symlink() or not path.is_file():
            raise PackageError(f"{name} følges av Git, men finnes ikke som vanlig fil i arbeidskatalogen.")
        files[name] = path
    if unknown:
        raise PackageError("Disse filene er verken merket som programfil eller som utviklingsfil: "
                           f"{', '.join(unknown[:10])}{' …' if len(unknown) > 10 else ''}. Legg dem til i "
                           "PACKAGED_* (skal være med i pakken) eller DEVELOPMENT_* (skal ikke) i "
                           "scripts/package_release.py.")
    for path in sorted(p for p in dist.rglob("*") if p.is_file()):
        files[path.relative_to(root).as_posix()] = path
    install_info: dict[str, object] = {"type": "release", "version": raw_version, "repository": repository}
    bundled: dict[str, dict[str, object]] = {}
    for runtime in runtimes:
        platform, described = describe_runtime(runtime)
        if platform in bundled:
            raise PackageError(f"To kjøretider for samme plattform ({platform}).")
        bundled[platform] = described
    if bundled:
        install_info["runtimes"] = dict(sorted(bundled.items()))
        try:
            update.release_runtimes(install_info)  # exactly what the updater will accept
        except update.UpdateError as exc:
            raise PackageError(str(exc)) from exc

    prefix = f"EmneKlar-{raw_version}/"
    stamp = zip_timestamp(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"EmneKlar-{raw_version}.zip"
    partial = zip_path.with_name(zip_path.name + ".partial")

    def entry(name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(prefix + name, date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        return info

    with zipfile.ZipFile(partial, "w", compresslevel=9) as archive:
        for name in sorted(files):
            archive.writestr(entry(name), files[name].read_bytes())
        archive.writestr(entry("install.json"), json.dumps(install_info, indent=2) + "\n")
    with zipfile.ZipFile(partial) as archive:
        names = set(archive.namelist())
    missing = [name for name in update.RELEASE_REQUIRED_FILES if prefix + name not in names]
    if missing:
        partial.unlink()
        raise PackageError(f"Pakken mangler filer som oppdateringen krever: {', '.join(missing)}")
    os.replace(partial, zip_path)

    digest = update.sha256_file(zip_path)
    checksum_path = out_dir / f"{zip_path.name}.sha256"
    checksum_path.write_bytes(f"{digest}  {zip_path.name}\n".encode("ascii"))
    return zip_path, checksum_path, digest, len(files) + 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lager utgivelsespakken EmneKlar-<versjon>.zip med sjekksum.")
    parser.add_argument("--repository", help="GitHub-repositoriet (eier/repo) som skrives i install.json")
    parser.add_argument("--out", type=Path, default=None, help="målmappe (standard: dist-release)")
    parser.add_argument("--notes-out", type=Path, help="skriv endringsnotatene for versjonen til denne filen")
    parser.add_argument("--runtime", type=Path, action="append", default=[], metavar="ZIP",
                        help="kjøretid som hører til utgivelsen (fra scripts/build_runtime.py); kan gjentas, én per "
                             "plattform")
    parser.add_argument("--allow-dirty", action="store_true", help="tillat ucommittede endringer (bare til testing)")
    parser.add_argument("--working-tree", action="store_true",
                        help="pakk mappen slik den står: ucommittede endringer og nye filer Git ikke ignorerer er med, "
                             "slettede filer er ikke (bare til testing)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    update.configure_stdio()
    root: Path = args.root.resolve()
    out_dir: Path = args.out or root / "dist-release"
    repository = args.repository or default_repository(root)
    try:
        zip_path, checksum_path, digest, count = build(root, out_dir, repository=repository,
                                                       allow_dirty=args.allow_dirty, working_tree=args.working_tree,
                                                       runtimes=args.runtime)
        if args.notes_out is not None:
            version = (root / "VERSION").read_text(encoding="utf-8").strip()
            args.notes_out.parent.mkdir(parents=True, exist_ok=True)
            args.notes_out.write_text(release_notes(root, version), encoding="utf-8")
    except (PackageError, OSError) as exc:
        print(f"Feil: {exc}", file=sys.stderr)
        return 1
    print(f"Utgivelsespakke: {zip_path} ({zip_path.stat().st_size / 1_048_576:.1f} MB, {count} filer)")
    print(f"Sjekksum:        {checksum_path}")
    print(f"SHA-256:         {digest}")
    print(f"Repository i install.json: {repository or '(ikke satt – oppdateringskilden må angis i appen)'}")
    for runtime in args.runtime:
        print(f"Kjøretid i install.json:   {runtime.name}")
    if not args.runtime:
        print("Kjøretid i install.json:   (ingen – pakken kan bare brukes med et Python-miljø laget av setup.bat)")
    if args.notes_out is not None:
        print(f"Endringsnotater: {args.notes_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
