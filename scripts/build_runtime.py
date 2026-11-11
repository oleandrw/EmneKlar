"""Build the Python runtime that is bundled with an EmneKlar installation.

    python scripts/build_runtime.py lock  [--platform win-amd64]
    python scripts/build_runtime.py id    [--platform win-amd64]
    python scripts/build_runtime.py build [--platform win-amd64] [--out dist-release] [--python-zip FIL]

A teacher's installation does not use a Python installed on the machine, and it never runs pip. It contains a
*runtime*: the official "embeddable package" of CPython from python.org with EmneKlar's dependencies already
installed in ``Lib\\site-packages``. The runtime is built here, once per release, and is the same for everyone.

``packaging/runtime.json`` names the Python version and, per platform, the download and its SHA-256.
``packaging/runtime-<platform>.txt`` is the *lock*: every dependency with its exact version and the SHA-256 of the
one file that is installed (``lock`` writes it from backend/constraints.txt with pip's own resolver).

``build`` verifies the Python download against its SHA-256, installs the lock with ``pip --require-hashes`` (nothing
that is not in the lock, nothing with another hash, no source builds), writes ``python<XY>._pth`` so the runtime
ignores environment variables, the registry and packages in the user's profile, compiles the packages, checks that
they can be imported with the runtime's own interpreter, and writes

    <out>/EmneKlar-runtime-<platform>-<id>.zip      (python.exe … at the top level, plus runtime.json)
    <out>/EmneKlar-runtime-<platform>-<id>.zip.sha256

The id is a hash of everything that decides the content (Python download, lock, recipe), so the same inputs give
the same id: an installation fetches a new runtime only when the id changes. ``scripts/package_release.py --runtime``
records the zip's SHA-256 in install.json, which is how ``scripts/update.py`` trusts it.

``lock`` and ``build`` must run with the Python version and on the platform the runtime is for (the files pip
selects are the ones for the interpreter that runs it). Only Windows (win-amd64) is built and tested today.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # emneklar.core.system uses only the standard library

from emneklar.core.system import platform_tag  # noqa: E402 - the same platform names as the program and the updater

SPEC_FILE = "packaging/runtime.json"
#: Changing how the runtime is put together (not just what goes into it) must give a new id.
#: 2: the removed console scripts are no longer listed in the RECORD files (reproducible builds).
RECIPE = 2
MAX_PYTHON_BYTES = 100 * 1024 * 1024
ZIP_TIME = (2020, 1, 1, 0, 0, 0)  # fixed: the same content gives the same zip
ID_RE = re.compile(r"^cp\d{2,3}-[0-9a-f]{12}$")
PLATFORM_RE = re.compile(r"^[a-z0-9]+-[a-z0-9_]+$")
#: Imported with the built runtime before it is packaged: every direct dependency and the standard-library parts
#: with native code that EmneKlar and the updater need.
IMPORT_CHECK = ("fastapi", "uvicorn", "pydantic", "sqlalchemy", "alembic", "httpx", "certifi", "keyring",
                "keyring.backends.Windows", "bs4", "defusedxml", "pypdf", "nh3", "numpy", "av", "PIL.Image",
                "pypdfium2", "fpdf", "youtube_transcript_api", "ssl", "sqlite3", "ctypes", "multiprocessing",
                "zipfile", "lzma", "bz2")


class RuntimeBuildError(Exception):
    pass


@dataclass(frozen=True)
class Spec:
    platform: str
    python: str  # "3.14.10"
    python_url: str
    python_sha256: str
    lock: Path

    @property
    def tag(self) -> str:
        major, minor = self.python.split(".")[:2]
        return f"cp{major}{minor}"

    @property
    def pth_name(self) -> str:
        major, minor = self.python.split(".")[:2]
        return f"python{major}{minor}._pth"


def load_spec(root: Path, platform: str) -> Spec:
    try:
        data = json.loads((root / SPEC_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeBuildError(f"Kan ikke lese {SPEC_FILE}: {exc}") from exc
    entry = (data.get("platforms") or {}).get(platform)
    if not isinstance(entry, dict):
        known = ", ".join(sorted(data.get("platforms") or {})) or "ingen"
        raise RuntimeBuildError(f"{SPEC_FILE} har ingen kjøretid for «{platform}» (finnes: {known}).")
    python = str(data.get("python", ""))
    url, digest = str(entry.get("python_url", "")), str(entry.get("python_sha256", "")).lower()
    if not re.fullmatch(r"\d+\.\d+\.\d+", python) or not url.startswith("https://") \
            or not re.fullmatch(r"[0-9a-f]{64}", digest) or not PLATFORM_RE.match(platform):
        raise RuntimeBuildError(f"{SPEC_FILE} er ugyldig for «{platform}».")
    return Spec(platform=platform, python=python, python_url=url, python_sha256=digest,
                lock=root / str(entry.get("lock", f"packaging/runtime-{platform}.txt")))


def require_matching_host(spec: Spec) -> None:
    wanted = tuple(int(part) for part in spec.python.split(".")[:2])
    if sys.version_info[:2] != wanted or platform_tag() != spec.platform:
        raise RuntimeBuildError(
            f"Kjøretiden for {spec.platform} lages med Python {wanted[0]}.{wanted[1]} på samme plattform. Dette er "
            f"Python {sys.version_info[0]}.{sys.version_info[1]} på {platform_tag()}.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args: list[str | Path], *, cwd: Path | None = None) -> str:
    command = [str(a) for a in args]
    env = {**os.environ, "PYTHONUTF8": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"}
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, stdin=subprocess.DEVNULL, check=False)
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-25:])
        raise RuntimeBuildError(f"Kommandoen feilet ({done.returncode}): {' '.join(command[:6])} …\n{tail}")
    return done.stdout


# -- the lock -------------------------------------------------------------------------------------------------------


def runtime_requirements(root: Path) -> list[str]:
    project = tomllib.loads((root / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return [str(item) for item in project["dependencies"]]


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_lines(report: dict[str, object]) -> list[str]:
    """``name==version --hash=sha256:…`` for every file pip would install, from ``pip install --report``."""
    lines: list[str] = []
    items = report.get("install")
    if not isinstance(items, list) or not items:
        raise RuntimeBuildError("pip ga ingen pakker i rapporten.")
    for item in items:
        metadata, info = item.get("metadata") or {}, item.get("download_info") or {}
        name, version = metadata.get("name"), metadata.get("version")
        digest = ((info.get("archive_info") or {}).get("hashes") or {}).get("sha256")
        url = str(info.get("url", ""))
        if not name or not version or not digest or not url.endswith(".whl"):
            raise RuntimeBuildError(f"Kan ikke låse {name or '?'}: pip valgte ikke en ferdigbygd fil med hash ({url}).")
        lines.append(f"{canonical(str(name))}=={version} \\\n    --hash=sha256:{digest}  # {url.rsplit('/', 1)[-1]}")
    return sorted(lines)


def write_lock(root: Path, spec: Spec) -> Path:
    require_matching_host(spec)
    with tempfile.TemporaryDirectory(prefix="emneklar-lock-") as temp:
        requirements = Path(temp) / "requirements.txt"
        requirements.write_text("\n".join(runtime_requirements(root)) + "\n", encoding="utf-8")
        report = Path(temp) / "report.json"
        run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet", "--only-binary=:all:",
             "--report", report, "-c", root / "backend" / "constraints.txt", "-r", requirements], cwd=root)
        lines = lock_lines(json.loads(report.read_text(encoding="utf-8")))
    series = ".".join(spec.python.split(".")[:2])
    header = (
        f"# The dependencies of the bundled runtime for {spec.platform} (CPython {series}): exact\n"
        "# versions and the SHA-256 of the one file that is installed. Generated – do not edit:\n"
        f"#   python scripts/build_runtime.py lock --platform {spec.platform}\n"
        "# The versions come from backend/constraints.txt (tests/test_runtime_build.py checks that they agree).\n"
        "# Installed with: pip install --require-hashes --no-deps --only-binary=:all: -r <this file>\n\n")
    spec.lock.parent.mkdir(parents=True, exist_ok=True)
    spec.lock.write_bytes((header + "\n".join(lines) + "\n").encode("utf-8"))
    return spec.lock


def read_lock(spec: Spec) -> dict[str, str]:
    """``{package: version}`` in the lock (every entry must carry a hash)."""
    try:
        text = spec.lock.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeBuildError(f"Låsefilen {spec.lock} mangler. Lag den med: python scripts/build_runtime.py lock") \
            from exc
    pins: dict[str, str] = {}
    for block in re.split(r"\n(?=\S)", text):
        if not block.strip() or block.lstrip().startswith("#"):
            continue
        match = re.match(r"([A-Za-z0-9._-]+)==(\S+)", block)
        if not match or "--hash=sha256:" not in block:
            raise RuntimeBuildError(f"Ugyldig linje i {spec.lock.name}: {block.splitlines()[0]}")
        pins[canonical(match.group(1))] = match.group(2)
    if not pins:
        raise RuntimeBuildError(f"{spec.lock.name} er tom.")
    return pins


def runtime_id(spec: Spec) -> str:
    lock = spec.lock.read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(b"\n".join([spec.platform.encode(), spec.python_sha256.encode(), lock,
                                        str(RECIPE).encode()])).hexdigest()
    return f"{spec.tag}-{digest[:12]}"


def asset_name(platform: str, identifier: str) -> str:
    return f"EmneKlar-runtime-{platform}-{identifier}.zip"


# -- building -------------------------------------------------------------------------------------------------------


def fetch_python(spec: Spec, cache: Path, given: Path | None) -> Path:
    """The embeddable package, verified against the SHA-256 in packaging/runtime.json."""
    archive = given or cache / spec.python_url.rsplit("/", 1)[-1]
    if not archive.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        partial = archive.with_name(archive.name + ".partial")
        request = urllib.request.Request(spec.python_url, headers={"User-Agent": "EmneKlar-build"})  # noqa: S310 - https
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:  # noqa: S310
            if not response.geturl().startswith("https://"):
                raise RuntimeBuildError("Nedlastingen av Python ble sendt videre til en adresse uten HTTPS.")
            received = 0
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > MAX_PYTHON_BYTES:
                    raise RuntimeBuildError("Python-pakken er større enn forventet.")
                out.write(chunk)
        os.replace(partial, archive)
    actual = sha256_file(archive)
    if actual != spec.python_sha256:
        raise RuntimeBuildError(f"{archive.name} har SHA-256 {actual}, men {SPEC_FILE} sier {spec.python_sha256}. "
                                "Filen brukes ikke.")
    return archive


def pth_lines() -> list[str]:
    """Search path of the runtime, relative to the runtime folder. With a ._pth file Python is isolated: PYTHONPATH,
    PYTHONHOME, the registry and the user's site-packages are ignored. ``..\\backend`` is EmneKlar itself."""
    return ["{zip}", ".", "Lib\\site-packages", "..\\backend"]


def forget_removed_scripts(site_packages: Path) -> None:
    """Take the console scripts pip made out of the packages' RECORD files.

    The scripts themselves are removed (EmneKlar starts everything with ``python -m``), so the lines name files that
    are not there. Their hashes also differ from build to build – a script launcher holds the path of the build
    folder – and without them two builds of the same inputs are identical byte for byte.
    """
    for record in site_packages.glob("*.dist-info/RECORD"):
        lines = record.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [line for line in lines if not line.startswith("../../bin/")]
        if kept != lines:
            record.write_bytes("".join(kept).encode("utf-8"))


def build(root: Path, out_dir: Path, *, platform: str, python_zip: Path | None = None) -> tuple[Path, Path, str]:
    spec = load_spec(root, platform)
    require_matching_host(spec)
    read_lock(spec)
    identifier = runtime_id(spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = fetch_python(spec, out_dir / ".cache", python_zip)
    with tempfile.TemporaryDirectory(prefix="emneklar-runtime-") as temp:
        runtime = Path(temp) / "runtime"
        runtime.mkdir()
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                target = (runtime / member.filename).resolve()
                if runtime.resolve() not in target.parents and target != runtime.resolve():
                    raise RuntimeBuildError(f"Python-pakken har en ugyldig sti: {member.filename}")
            source.extractall(runtime)  # members checked above, and the archive's hash is pinned
        python = runtime / ("python.exe" if os.name == "nt" else "bin/python3")
        stdlib_zip = spec.pth_name.replace("._pth", ".zip")
        if not python.is_file() or not (runtime / stdlib_zip).is_file():
            raise RuntimeBuildError("Python-pakken har ikke det ventede innholdet (python.exe og standardbiblioteket).")
        (runtime / spec.pth_name).write_bytes(
            ("\n".join(line.replace("{zip}", stdlib_zip) for line in pth_lines()) + "\n").encode("ascii"))

        site_packages = runtime / "Lib" / "site-packages"
        site_packages.mkdir(parents=True)
        run([sys.executable, "-m", "pip", "install", "--require-hashes", "--no-deps", "--only-binary=:all:",
             "--no-compile", "--quiet", "--target", site_packages, "-r", spec.lock], cwd=root)
        shutil.rmtree(site_packages / "bin", ignore_errors=True)  # console scripts: not used by EmneKlar
        forget_removed_scripts(site_packages)
        for cache in list(site_packages.rglob("__pycache__")):
            shutil.rmtree(cache, ignore_errors=True)

        # Compile with the runtime's own interpreter. unchecked-hash: valid whatever the file times become when the
        # runtime is unpacked; -s keeps the build folder out of the compiled files.
        run([python, "-m", "compileall", "-q", "-s", str(runtime), "--invalidation-mode", "unchecked-hash",
             str(site_packages)])
        check = "import importlib, sys\nfor name in sys.argv[1:]:\n    importlib.import_module(name)\n" \
                "assert sys.flags.isolated, 'the ._pth file is not in use'\nprint(sys.version.split()[0])"
        modules = [name for name in IMPORT_CHECK if os.name == "nt" or name != "keyring.backends.Windows"]
        version = run([python, "-c", check, *modules]).strip()
        if version != spec.python:
            raise RuntimeBuildError(f"Kjøretiden svarer med Python {version}, ventet {spec.python}.")

        info = {"id": identifier, "platform": spec.platform, "python": spec.python, "recipe": RECIPE,
                "packages": read_lock(spec)}
        (runtime / "runtime.json").write_bytes((json.dumps(info, indent=2, sort_keys=True) + "\n").encode("utf-8"))

        zip_path = out_dir / asset_name(spec.platform, identifier)
        partial = zip_path.with_name(zip_path.name + ".partial")
        files = sorted(path for path in runtime.rglob("*") if path.is_file())
        with zipfile.ZipFile(partial, "w", compresslevel=9) as target_zip:
            for path in files:
                entry = zipfile.ZipInfo(path.relative_to(runtime).as_posix(), date_time=ZIP_TIME)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                target_zip.writestr(entry, path.read_bytes())
        os.replace(partial, zip_path)
    digest = sha256_file(zip_path)
    checksum = out_dir / f"{zip_path.name}.sha256"
    checksum.write_bytes(f"{digest}  {zip_path.name}\n".encode("ascii"))
    return zip_path, checksum, identifier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lager Python-kjøretiden som følger med en EmneKlar-installasjon.")
    parser.add_argument("command", choices=("lock", "id", "build"))
    parser.add_argument("--platform", default="win-amd64", help="plattformen kjøretiden er for (standard: win-amd64)")
    parser.add_argument("--out", type=Path, default=None, help="målmappe for build (standard: dist-release)")
    parser.add_argument("--python-zip", type=Path, default=None,
                        help="bruk denne nedlastede Python-pakken i stedet for å laste den ned (hashen kontrolleres)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    root: Path = args.root.resolve()
    try:
        spec = load_spec(root, args.platform)
        if args.command == "lock":
            path = write_lock(root, spec)
            print(f"Låsefil: {path} ({len(read_lock(spec))} pakker)")
            print(f"Kjøretid-id: {runtime_id(spec)}")
        elif args.command == "id":
            read_lock(spec)
            print(runtime_id(spec))
        else:
            zip_path, checksum, identifier = build(root, args.out or root / "dist-release", platform=args.platform,
                                                   python_zip=args.python_zip)
            print(f"Kjøretid:  {zip_path} ({zip_path.stat().st_size / 1_048_576:.1f} MB)")
            print(f"Sjekksum:  {checksum}")
            print(f"Id:        {identifier}")
    except (RuntimeBuildError, OSError) as exc:
        print(f"Feil: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
