"""Build the release package that update.bat (scripts/update.py) installs.

    python scripts/package_release.py [--repository eier/repo] [--out dist-release] [--notes-out FIL] [--allow-dirty]

Creates ``dist-release/EmneKlar-<versjon>.zip`` with
  * every file tracked by Git (``git ls-files``),
  * the built user interface ``frontend/dist`` (run ``npm ci && npm run build`` in frontend first), and
  * a generated ``install.json`` = {"type": "release", "version": ..., "repository": "eier/repo" or null},
all inside one top-level folder ``EmneKlar-<versjon>/``, plus ``EmneKlar-<versjon>.zip.sha256``
(``<sha256>  <filnavn>``, the sha256sum format). Entries are sorted and time-stamped with the commit time
(or SOURCE_DATE_EPOCH), so the same commit and the same build give the same zip.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # emneklar.* helpers below use only the standard library

import update  # noqa: E402 - scripts/update.py: the format of a release package is defined there

from emneklar.core.updates.version import Version, changelog_sections  # noqa: E402


class PackageError(Exception):
    pass


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


def tracked_files(root: Path) -> list[str]:
    return sorted(name for name in git(root, "ls-files", "-z").decode("utf-8").split("\0") if name)


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
    for section in changelog_sections(root / "CHANGELOG.md", limit=1000):
        if section["version"] == version:
            title = f"EmneKlar {version}" + (f" – {section['title']}" if section["title"] else "")
            return f"## {title}\n\n{section['body'].strip() or 'Ingen endringsnotater.'}\n"
    return f"## EmneKlar {version}\n\nSe CHANGELOG.md for endringer.\n"


def build(root: Path, out_dir: Path, *, repository: str | None, allow_dirty: bool) -> tuple[Path, Path, str, int]:
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
    if dirty and not allow_dirty:
        raise PackageError("Arbeidskatalogen har endringer som ikke er committet. En utgivelse skal bygges fra en ren "
                           "commit (bruk --allow-dirty bare til testing).\n" + dirty)

    files: dict[str, Path] = {}
    for name in tracked_files(root):
        path = root / name
        if name.startswith("frontend/dist/") or name == "install.json":
            raise PackageError(f"{name} skal ikke være i Git; den lages når pakken bygges.")
        if path.is_symlink() or not path.is_file():
            raise PackageError(f"{name} følges av Git, men finnes ikke som vanlig fil i arbeidskatalogen.")
        files[name] = path
    for path in sorted(p for p in dist.rglob("*") if p.is_file()):
        files[path.relative_to(root).as_posix()] = path
    install_info = {"type": "release", "version": raw_version, "repository": repository}

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
    parser.add_argument("--allow-dirty", action="store_true", help="tillat ucommittede endringer (bare til testing)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    update.configure_stdio()
    root: Path = args.root.resolve()
    out_dir: Path = args.out or root / "dist-release"
    repository = args.repository or default_repository(root)
    try:
        zip_path, checksum_path, digest, count = build(root, out_dir, repository=repository,
                                                       allow_dirty=args.allow_dirty)
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
    if args.notes_out is not None:
        print(f"Endringsnotater: {args.notes_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
