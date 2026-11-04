"""EmneKlar – oppdatering. Started by update.bat (also from Innstillinger → Generelt in the app).

The update runs in ten steps, each announced as "Steg N av 10 – …":

     1  detect a running EmneKlar and stop it      6  update Python dependencies (pinned versions)
     2  validate the installation                  7  migrate the database
     3  back up the database                       8  build the user interface (Git installations)
     4  check for a newer version on GitHub        9  health check of the new version
     5  fetch the new version                     10  start EmneKlar again

If anything in steps 5–9 fails, the program files, the dependencies and the database are rolled back and the
previous version is started again. User data (``%LOCALAPPDATA%\\EmneKlar-Claude``) is never deleted; the database is
backed up before anything changes.

Installation types (same rule as ``emneklar.core.updates.service``): ``git`` if ``.git`` exists (updated with
``git pull --ff-only``; refused if tracked files have uncommitted changes), ``release`` if ``install.json``
exists, otherwise ``source``. Release and source installations are updated with the release package
``EmneKlar-<versjon>.zip`` (verified against ``EmneKlar-<versjon>.zip.sha256``).

Exit codes: 0 = updated, or already up to date
            1 = the update failed (changes were rolled back, or nothing had been changed yet)
            2 = not started: the user cancelled, or a safety check stopped it (major version without
                confirmation, uncommitted Git changes, EmneKlar could not be stopped, …)

update.bat runs a temporary copy of this file, so the update may safely replace ``scripts/``.
``scripts/setup.py`` reuses the helpers in the first half of this file.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TextIO

try:
    import emneklar  # noqa: F401 - normally importable through the venv's editable install
except ModuleNotFoundError:  # run by another Python: use the installation's own package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from emneklar import __version__
from emneklar.core.security.redaction import redact, register_secret
from emneklar.core.updates.version import Version
from emneklar.manage import (
    ProcessWatcher,
    backup_sqlite,
    data_dir_from_env,
    fetch_health,
    process_alive,
    read_instance,
    request_shutdown,
    running_instance,
    utc_stamp,
    wait_until_stopped,
)

TOTAL_STEPS = 10
EXIT_OK, EXIT_FAILED, EXIT_ABORTED = 0, 1, 2

GITHUB_API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
REMOTE_RE = re.compile(r"github\.com[:/]+([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$")
# Never backed up, replaced or removed by a release update.
EXCLUDED_DIRS = frozenset({".git", ".venv", "node_modules", ".update", "__pycache__", ".pytest_cache",
                           ".mypy_cache", ".ruff_cache"})
# Files of the old version that the new release no longer contains are removed only here (code that is
# discovered dynamically, e.g. Alembic migrations, and the built UI). They stay in the code backup.
STALE_CLEANUP_PREFIXES = ("backend/emneklar/", "backend/migrations/", "frontend/dist/", "scripts/")
RELEASE_REQUIRED_FILES = ("VERSION", "install.json", "backend/pyproject.toml", "backend/emneklar/__init__.py",
                          "frontend/dist/index.html", "start.bat", "update.bat")
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
MAX_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ZIP_ENTRIES = 50_000
MIN_FREE_BYTES = 300 * 1024 * 1024
HEALTH_TIMEOUT = 60.0
STOP_TIMEOUT = 30.0
KEEP_CODE_BACKUPS = 3
STALE_LOCK_SECONDS = 2 * 3600
# pip output meaning "the pinned versions cannot be installed on this Python version" ...
PINS_UNAVAILABLE_MARKERS = ("No matching distribution found", "Could not find a version that satisfies",
                            "ResolutionImpossible", "Failed to build", "metadata-generation-failed",
                            "Failed building wheel")
# ... unless the real cause was the network (then installing unpinned versions would be wrong).
NETWORK_ERROR_MARKERS = ("NewConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "Connection broken",
                         "Max retries exceeded", "ProxyError", "SSLError", "getaddrinfo failed",
                         "Temporary failure in name resolution", "Network is unreachable")


class UpdateError(Exception):
    """The update failed (exit code 1)."""

    exit_code = EXIT_FAILED


class UpdateAborted(UpdateError):
    """The user or a safety check stopped the update before anything was changed (exit code 2)."""

    exit_code = EXIT_ABORTED


class CommandFailed(UpdateError):
    def __init__(self, args: Sequence[str], returncode: int, output: str) -> None:
        self.command = list(args)
        self.returncode = returncode
        self.output = output
        name = Path(self.command[0]).name if self.command else "?"
        words = " ".join(word for word in self.command[1:4] if not Path(word).is_absolute())
        super().__init__(f"Kommandoen «{name} {words}» feilet (kode {returncode}).")


# -- console and log ----------------------------------------------------------------------------


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # UTF-8 also when redirected; consoles are Unicode anyway
            reconfigure(encoding="utf-8", errors="replace")


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _scrub(text: str) -> str:
    """Redact credentials (incl. user:password@ in URLs) and drop terminal colour codes before output/logging."""
    return re.sub(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1[SKJULT]@", redact(ANSI_ESCAPE.sub("", text)))


class Reporter:
    """Prints progress in Norwegian and appends everything (timestamped, redacted) to a log file."""

    def __init__(self, log_path: Path | None, *, total_steps: int, title: str) -> None:
        self.total_steps = total_steps
        self.log_path = log_path
        self._file: TextIO | None = None
        if log_path is not None:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._file = log_path.open("a", encoding="utf-8", newline="\n")
            except OSError:
                self._file = None
        self.log(f"===== {title} – {datetime.now().astimezone().isoformat(timespec='seconds')} =====")

    def _print(self, text: str) -> None:
        print(_scrub(text), flush=True)

    def log(self, text: str) -> None:
        if self._file is not None:
            stamp = datetime.now().strftime("%H:%M:%S")
            for line in _scrub(text).splitlines() or [""]:
                self._file.write(f"{stamp} {line}\n")
            self._file.flush()

    def step(self, number: int, title: str) -> None:
        text = f"Steg {number} av {self.total_steps} – {title}"
        self._print(f"\n{text}")
        self.log(text)

    def info(self, text: str = "") -> None:
        self._print(f"  {text}" if text else "")
        self.log(text)

    def warn(self, text: str) -> None:
        self._print(f"  Advarsel: {text}")
        self.log(f"ADVARSEL: {text}")

    def error(self, text: str) -> None:
        self._print(f"\nFEIL: {text}")
        self.log(f"FEIL: {text}")

    def output(self, line: str) -> None:
        self._print(f"    | {line}")
        self.log(f"| {line}")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INPUT": "1", "GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1"})
    return env


def run(args: Sequence[str | Path], *, cwd: Path, reporter: Reporter | None = None, capture: bool = False,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command (never through a shell). Output is streamed to the console and log unless ``capture``."""
    command = [str(a) for a in args]
    if reporter is not None:
        reporter.log(f"$ {subprocess.list2cmdline(command)}   (mappe: {cwd})")
    try:
        if capture:
            done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=child_env(), stdin=subprocess.DEVNULL, check=False)
            output = (done.stdout or "") + (done.stderr or "")
            if reporter is not None and output.strip():
                reporter.log(output.rstrip())
            result = subprocess.CompletedProcess(command, done.returncode, done.stdout or "", done.stderr or "")
        else:
            tail: deque[str] = deque(maxlen=200)
            with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace", env=child_env(),
                                  stdin=subprocess.DEVNULL) as proc:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = raw.rstrip()
                    tail.append(line)
                    if reporter is not None:
                        reporter.output(line)
            output = "\n".join(tail)
            result = subprocess.CompletedProcess(command, proc.returncode, output, "")
    except OSError as exc:
        raise CommandFailed(command, -1, str(exc)) from exc
    if check and result.returncode != 0:
        raise CommandFailed(command, result.returncode, output)
    return result


def remove_tree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files (common on Windows)."""

    def _retry(func: Callable[..., Any], target: str, _exc: object) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)


def venv_python_path(root: Path) -> Path:
    venv = root / "backend" / ".venv"
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def strict_pins() -> bool:
    return os.environ.get("EMNEKLAR_STRICT_PINS", "").strip().lower() in {"1", "true", "yes", "ja"}


def pins_unavailable(pip_output: str) -> bool:
    """True if pip failed because the pinned versions do not exist (or cannot be built) for this Python."""
    return (any(marker in pip_output for marker in PINS_UNAVAILABLE_MARKERS)
            and not any(marker in pip_output for marker in NETWORK_ERROR_MARKERS))


EXTRAS_FILE = "emneklar-extras.txt"  # in backend/.venv: optional parts the user chose to install (e.g. "rag")
KNOWN_EXTRAS = {"rag": "lokale modeller for emnets kunnskapsbase"}


def chosen_extras(root: Path) -> list[str]:
    path = root / "backend" / ".venv" / EXTRAS_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [name for name in (line.strip() for line in lines) if name in KNOWN_EXTRAS]


def remember_extra(root: Path, extra: str) -> None:
    path = root / "backend" / ".venv" / EXTRAS_FILE
    current = chosen_extras(root)
    if extra not in current:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([*current, extra]) + "\n", encoding="utf-8")


def install_optional_extras(venv_python: Path, root: Path, reporter: Reporter) -> None:
    """Optional parts (``backend[rag]``) the user chose earlier. Never fails setup or update: EmneKlar works
    without them, so a failed install is reported as a warning."""
    backend = root / "backend"
    constraints = backend / "constraints.txt"
    for extra in chosen_extras(root):
        reporter.info(f"Installerer {KNOWN_EXTRAS[extra]} (kan ta lang tid første gang – flere GB) …")
        base: list[str | Path] = [venv_python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
        if constraints.is_file():
            base += ["-c", constraints]
        done = run([*base, "-e", f"{backend}[{extra}]"], cwd=root, reporter=reporter, check=False)
        if done.returncode != 0:
            reporter.warn(f"Klarte ikke å installere {KNOWN_EXTRAS[extra]}. EmneKlar virker likevel; kunnskapsbasen bruker "
                          "da nøkkelordsøk. Se loggen, og kjør setup.bat på nytt senere.")


def install_python_dependencies(venv_python: Path, root: Path, reporter: Reporter) -> None:
    """``pip install -c backend/constraints.txt -e backend`` – the tested versions.

    If the pinned versions do not exist for the venv's Python version (typically a Python release newer than
    the pins), the newest versions allowed by pyproject.toml are installed instead, with a warning – unless
    EMNEKLAR_STRICT_PINS=1 (used in CI). Network problems are never "solved" by dropping the pins.
    """
    backend = root / "backend"
    constraints = backend / "constraints.txt"
    base: list[str | Path] = [venv_python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    if not constraints.is_file():
        reporter.warn("Fant ikke backend\\constraints.txt – installerer nyeste tillatte versjoner.")
        run([*base, "-e", backend], cwd=root, reporter=reporter)
        install_optional_extras(venv_python, root, reporter)
        return
    try:
        run([*base, "-c", constraints, "-e", backend], cwd=root, reporter=reporter)
    except CommandFailed as exc:
        if strict_pins() or not pins_unavailable(exc.output):
            raise
        reporter.warn("De testede versjonene av avhengighetene finnes ikke for Python-versjonen i "
                      "backend\\.venv. Installerer de nyeste versjonene EmneKlar tillater i stedet. "
                      "Python 3.11–3.14 anbefales.")
        run([*base, "-e", backend], cwd=root, reporter=reporter)
    install_optional_extras(venv_python, root, reporter)


def npm_unsafe_character(path: Path) -> str | None:
    """A character in ``path`` that breaks npm's .cmd shims on Windows (they run ``SET dp0=%~dp0`` unquoted)."""
    if os.name != "nt":
        return None
    return next((char for char in "&^" if char in str(path)), None)


def npm_path_problem(path: Path) -> str | None:
    char = npm_unsafe_character(path)
    if char is None:
        return None
    return (f"Mappenavnet inneholder tegnet «{char}», og da klarer ikke npm å bygge brukergrensesnittet på Windows "
            f"({path}). Flytt EmneKlar-mappen til et sted uten «{char}» i navnet, eller bruk en ferdig utgivelse "
            "(EmneKlar-<versjon>.zip), som ikke trenger npm.")


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:  # no console to answer in (e.g. CI)
        raise UpdateAborted("Fikk ikke svar fordi det ikke finnes noe konsollvindu. Ingenting er endret.") from None


# -- installation facts -------------------------------------------------------------------------


def install_kind(root: Path) -> str:
    """git / release / source – the same rule as UpdateService.install_info()."""
    if (root / ".git").exists():
        return "git"
    if (root / "install.json").exists():
        return "release"
    return "source"


def read_version_file(path: Path) -> Version | None:
    try:
        return Version.parse(path.read_text(encoding="utf-8").strip())
    except OSError:
        return None


def read_update_settings(db_path: Path) -> tuple[str | None, str]:
    """``(advanced.update_repository, advanced.update_channel)`` from the app settings in the database."""
    if not db_path.is_file():
        return None, "stable"
    try:
        connection = sqlite3.connect(str(db_path), timeout=10)
        try:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", ("app",)).fetchone()
        finally:
            connection.close()
        settings = json.loads(row[0]) if row and row[0] else {}
    except (sqlite3.Error, ValueError, TypeError):
        return None, "stable"
    advanced = settings.get("advanced") if isinstance(settings, dict) else None
    if not isinstance(advanced, dict):
        return None, "stable"
    repo = advanced.get("update_repository")
    channel = "prerelease" if advanced.get("update_channel") == "prerelease" else "stable"
    return (repo if isinstance(repo, str) and REPO_RE.match(repo) else None), channel


def git_remote_repository(root: Path) -> str | None:
    """owner/repo of the ``origin`` remote in .git/config (same rule as core/updates/service.py)."""
    try:
        text = (root / ".git" / "config").read_text(encoding="utf-8")
    except OSError:
        return None
    section = re.search(r'\[remote "origin"\]([^\[]*)', text)
    url = re.search(r"^\s*url\s*=\s*(\S+)", section.group(1), re.MULTILINE) if section else None
    match = REMOTE_RE.search(url.group(1)) if url else None
    return match.group(1) if match and REPO_RE.match(match.group(1)) else None


def install_json_repository(root: Path) -> str | None:
    try:
        data = json.loads((root / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    repo = data.get("repository") if isinstance(data, dict) else None
    return repo if isinstance(repo, str) and REPO_RE.match(repo) else None


def resolve_repository(root: Path, db_path: Path) -> tuple[str | None, str, str]:
    """``(repository, channel, where it came from)``: app settings → git remote → install.json."""
    configured, channel = read_update_settings(db_path)
    if configured:
        return configured, channel, "innstillingene i EmneKlar"
    remote = git_remote_repository(root)
    if remote:
        return remote, channel, "Git-remote «origin»"
    packaged = install_json_repository(root)
    if packaged:
        return packaged, channel, "install.json"
    return None, channel, ""


# -- GitHub releases ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Release:
    version: Version
    tag: str
    name: str
    notes: str
    prerelease: bool
    assets: dict[str, str]
    url: str | None = None


def parse_release(data: object) -> Release | None:
    if not isinstance(data, dict) or data.get("draft"):
        return None
    version = Version.parse(str(data.get("tag_name") or ""))
    if version is None:
        return None
    assets: dict[str, str] = {}
    for asset in data.get("assets") or []:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str) \
                and isinstance(asset.get("browser_download_url"), str):
            assets[asset["name"]] = asset["browser_download_url"]
    return Release(version=version, tag=str(data.get("tag_name")), name=str(data.get("name") or ""),
                   notes=str(data.get("body") or "")[:20000], prerelease=bool(data.get("prerelease")),
                   assets=assets, url=data.get("html_url") if isinstance(data.get("html_url"), str) else None)


def select_release(data: object, *, include_prereleases: bool) -> Release | None:
    """The newest valid release in a ``/releases/latest`` object or a ``/releases`` list."""
    items = data if isinstance(data, list) else [data]
    releases = [r for r in (parse_release(item) for item in items)
                if r is not None and (include_prereleases or not r.prerelease)]
    return max(releases, key=lambda r: r.version.key(), default=None)


def _github_request(url: str, accept: str) -> urllib.request.Request:
    if not url.startswith("https://"):
        raise UpdateError(f"Avviser nedlasting som ikke bruker HTTPS: {url}")
    return urllib.request.Request(url, headers={  # noqa: S310 - https only, checked above
        "Accept": accept, "User-Agent": f"EmneKlar-updater/{__version__}", "X-GitHub-Api-Version": "2022-11-28"})


def _http_failure(exc: Exception, what: str) -> UpdateError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return UpdateError(f"Fant ikke {what} på GitHub (404). Sjekk oppdateringskilden under Innstillinger → "
                               "Avansert.")
        if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
            return UpdateError("GitHub begrenser antall forespørsler fra denne maskinen akkurat nå. Prøv igjen om "
                               "en time.")
        return UpdateError(f"GitHub svarte med feilkode {exc.code} for {what}.")
    reason = getattr(exc, "reason", None) or exc
    return UpdateError(f"Fikk ikke kontakt med GitHub ({reason}). Sjekk nettverksforbindelsen og prøv igjen.")


def github_json(url: str, what: str) -> Any:
    try:
        with urllib.request.urlopen(_github_request(url, "application/vnd.github+json"),  # noqa: S310
                                    timeout=30) as response:
            body = response.read(10 * 1024 * 1024 + 1)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise _http_failure(exc, what) from exc
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise UpdateError(f"GitHub sendte et uventet svar for {what}.") from exc


def fetch_latest_release(repo: str, *, channel: str) -> Release | None:
    prerelease = channel == "prerelease"
    url = f"{GITHUB_API}/repos/{repo}/releases" + ("?per_page=20" if prerelease else "/latest")
    return select_release(github_json(url, f"utgivelser for {repo}"), include_prereleases=prerelease)


def download(url: str, dest: Path, *, max_bytes: int) -> None:
    """Stream ``url`` to ``dest`` (written as .partial first)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".partial")
    try:
        response = urllib.request.urlopen(_github_request(url, "application/octet-stream"), timeout=60)  # noqa: S310
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise _http_failure(exc, dest.name) from exc
    received = 0
    try:
        with response, partial.open("wb") as out:
            if not response.geturl().startswith("https://"):
                raise UpdateError("Nedlastingen ble sendt videre til en adresse uten HTTPS – avbrutt.")
            while True:
                try:
                    chunk = response.read(1024 * 1024)
                except (OSError, http.client.HTTPException) as exc:
                    raise _http_failure(exc, dest.name) from exc
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise UpdateError(f"{dest.name} er større enn forventet – nedlastingen er avbrutt.")
                out.write(chunk)  # an OSError here is a local disk problem and is reported as such
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    os.replace(partial, dest)


# -- checksums and release packages -------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksum(text: str, expected_name: str) -> str:
    """The hex digest from a ``<sha256>  <filename>`` file (sha256sum format)."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([0-9A-Fa-f]{64})(?:\s+\*?(.+))?", line)
        if not match:
            raise UpdateError("Sjekksumfilen har et ukjent format.")
        name = (match.group(2) or "").strip()
        if name and PurePosixPath(name.replace("\\", "/")).name != expected_name:
            raise UpdateError(f"Sjekksumfilen gjelder «{name}», ikke «{expected_name}».")
        return match.group(1).lower()
    raise UpdateError("Sjekksumfilen er tom.")


def verify_checksum(path: Path, checksum_text: str) -> str:
    expected = parse_checksum(checksum_text, path.name)
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected):
        raise UpdateError(f"Sjekksummen for {path.name} stemmer ikke. Filen kan være skadet eller endret, og blir "
                          "ikke installert.")
    return actual


def _safe_member(name: str) -> PurePosixPath:
    if not name or "\\" in name or ":" in name or name.startswith("/"):
        raise UpdateError(f"Utgivelsespakken inneholder en ugyldig sti: {name!r}")
    path = PurePosixPath(name)
    if any(part in ("", ".", "..") for part in path.parts):
        raise UpdateError(f"Utgivelsespakken inneholder en ugyldig sti: {name!r}")
    return path


def extract_release(zip_path: Path, staging: Path) -> Path:
    """Unpack the release zip into ``staging`` (rejecting unsafe paths) and return the folder with VERSION."""
    remove_tree(staging)
    staging.mkdir(parents=True)
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError(f"{zip_path.name} er ikke en gyldig zip-fil.") from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_ENTRIES or sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            raise UpdateError("Utgivelsespakken er uventet stor – avbrutt.")
        for member in members:
            relative = _safe_member(member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise UpdateError(f"Utgivelsespakken inneholder en symbolsk lenke: {member.filename}")
            target = staging.joinpath(*relative.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
    entries = list(staging.iterdir())
    if not (staging / "VERSION").exists() and len(entries) == 1 and entries[0].is_dir():
        return entries[0]  # packaged as EmneKlar-<versjon>/...
    return staging


def validate_release_tree(tree: Path, expected: Version) -> None:
    missing = [name for name in RELEASE_REQUIRED_FILES if not (tree / name).is_file()]
    if missing:
        raise UpdateError(f"Utgivelsespakken mangler {', '.join(missing)}.")
    found = read_version_file(tree / "VERSION")
    if found != expected:
        raise UpdateError(f"Utgivelsespakken inneholder versjon {found}, men {expected} var ventet.")
    try:
        info = json.loads((tree / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError("install.json i utgivelsespakken er ugyldig.") from exc
    if not isinstance(info, dict) or info.get("type") != "release":
        raise UpdateError("install.json i utgivelsespakken er ugyldig.")


# -- replacing the program files of a release installation ----------------------------------------


def list_files(root: Path) -> set[str]:
    """Relative POSIX paths of all files under ``root``, skipping EXCLUDED_DIRS (at any depth) and symlinks."""
    found: set[str] = set()
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not Path(current, d).is_symlink()]
        base = Path(current)
        for name in files:
            path = base / name
            if not path.is_symlink():
                found.add(path.relative_to(root).as_posix())
    return found


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    shutil.copy2(source, target)


def _remove_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop and stop in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


@dataclass
class SwapRecord:
    install: Path
    backup: Path
    old_files: set[str]
    new_files: set[str]


def backup_program_files(install: Path, new_tree: Path, backup: Path, *, old_version: str) -> SwapRecord:
    """Copy the current program files to ``backup`` (a fresh folder) before a release is applied.

    Nothing inside EXCLUDED_DIRS (the venv, node_modules, .update, .git, caches) is included or ever touched.
    """
    old_files = list_files(install)
    new_files = list_files(new_tree)
    remove_tree(backup)
    backup.mkdir(parents=True)
    for rel in sorted(old_files):
        _copy_file(install / rel, backup / rel)
    manifest = {"version": old_version, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "files": sorted(old_files)}
    (backup / ".emneklar-sikkerhetskopi.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return SwapRecord(install=install, backup=backup, old_files=old_files, new_files=new_files)


def apply_release(record: SwapRecord, new_tree: Path) -> None:
    """Copy the new release over the installation.

    Files that the new release no longer contains are removed only below STALE_CLEANUP_PREFIXES (they remain in
    the backup). If this fails half-way, rollback_release(record) restores the previous state.
    """
    for rel in sorted(record.new_files):
        _copy_file(new_tree / rel, record.install / rel)
    for rel in sorted(record.old_files - record.new_files):
        if rel.startswith(STALE_CLEANUP_PREFIXES):
            target = record.install / rel
            target.unlink(missing_ok=True)
            _remove_empty_parents(target, record.install)


def rollback_release(record: SwapRecord) -> None:
    """Put the installation back exactly as it was before apply_release()."""
    problems: list[str] = []
    for rel in sorted(record.new_files - record.old_files):
        target = record.install / rel
        try:
            if target.exists() or target.is_symlink():
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
                target.unlink()
            _remove_empty_parents(target, record.install)
        except OSError as exc:
            problems.append(f"{rel}: {exc}")
    for rel in sorted(record.old_files):
        try:
            _copy_file(record.backup / rel, record.install / rel)
        except OSError as exc:
            problems.append(f"{rel}: {exc}")
    if problems:
        raise UpdateError(f"{len(problems)} fil(er) kunne ikke settes tilbake, f.eks. {problems[0]}")


def prune_code_backups(work: Path, keep: int = KEEP_CODE_BACKUPS) -> None:
    backups = sorted((d for d in work.glob("previous-*") if d.is_dir()), key=lambda d: d.stat().st_mtime,
                     reverse=True)
    for old in backups[keep:]:
        with contextlib.suppress(OSError):
            remove_tree(old)


# -- database ------------------------------------------------------------------------------------


def restore_database(backup: Path, db_path: Path, quarantine: Path) -> None:
    """Restore ``db_path`` from ``backup``.

    Normally through SQLite's backup API (handles WAL files correctly). If the damaged database cannot be
    opened, it is moved – never deleted – to ``quarantine`` and the backup file is copied into place.
    """
    try:
        source = sqlite3.connect(str(backup))
        try:
            target = sqlite3.connect(str(db_path), timeout=30)
            try:
                source.backup(target)
                row = target.execute("PRAGMA quick_check").fetchone()
                if row is None or row[0] != "ok":
                    raise sqlite3.DatabaseError("integritetskontrollen feilet etter gjenoppretting")
            finally:
                target.close()
        finally:
            source.close()
        return
    except sqlite3.Error:
        pass
    quarantine.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    for suffix in ("", "-wal", "-shm", "-journal"):
        damaged = Path(f"{db_path}{suffix}")
        if damaged.exists():
            os.replace(damaged, quarantine / f"etter-feilet-oppdatering-{stamp}.db{suffix}")
    partial = db_path.with_name(db_path.name + ".restore")
    shutil.copy2(backup, partial)
    os.replace(partial, db_path)


# -- the version decision -----------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    version: Version  # the version that will be installed
    newer: bool  # is there anything to install?
    notes: str
    url: str | None = None


def decide(current: Version, candidate: Candidate, *, allow_major: bool, from_app: bool,
           confirm: Callable[[Candidate], bool]) -> bool:
    """True = install, False = nothing newer. Raises UpdateAborted when a major upgrade is not confirmed."""
    if not candidate.newer:
        return False
    if current.is_major_upgrade_to(candidate.version) and not allow_major:
        if from_app:
            raise UpdateAborted(f"Versjon {candidate.version} er en større oppdatering, og den er ikke bekreftet. "
                                "Bekreft oppdateringen i EmneKlar (Innstillinger → Generelt), eller kjør "
                                "update.bat og skriv JA når du blir spurt.")
        if not confirm(candidate):
            raise UpdateAborted("Oppdateringen ble avbrutt. Ingenting er endret.")
    return True


# -- misc ----------------------------------------------------------------------------------------


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_free_space(path: Path, needed: int, what: str) -> None:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if free < needed:
        raise UpdateAborted(f"Det er for lite ledig diskplass for {what} ({free // 2**20} MB ledig, trenger "
                            f"minst {needed // 2**20} MB). Frigjør plass og prøv igjen.")


def _lock_is_stale(lock: Path) -> bool:
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return True  # gone in the meantime
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = None  # possibly being written right now
    alive = process_alive(info.get("pid")) if isinstance(info, dict) else None
    return age >= STALE_LOCK_SECONDS or alive is False or (alive is None and age > 60)


@contextlib.contextmanager
def update_lock(work: Path) -> Iterator[None]:
    """Only one update per installation at a time."""
    work.mkdir(parents=True, exist_ok=True)
    lock = work / "update.lock"
    for attempt in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if attempt == 0 and _lock_is_stale(lock):
                lock.unlink(missing_ok=True)  # left behind by an update that was killed
                continue
            raise UpdateAborted("En annen oppdatering av EmneKlar kjører allerede. Vent til den er ferdig.") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def describe_error(error: BaseException) -> str:
    if isinstance(error, KeyboardInterrupt):
        return "avbrutt av brukeren (Ctrl+C)."
    text = str(error) or type(error).__name__
    if isinstance(error, CommandFailed) and error.output.strip():
        last = [line for line in error.output.strip().splitlines() if line.strip()][-8:]
        text += "\n  Siste linjer:\n" + "\n".join(f"    {line}" for line in last)
    return text


# -- the update itself ---------------------------------------------------------------------------


@dataclass
class Options:
    root: Path
    from_app: bool = False
    allow_major: bool = False
    no_start: bool = False


STEP_TITLES = {
    1: "Ser etter EmneKlar som kjører",
    2: "Kontrollerer installasjonen",
    3: "Sikkerhetskopierer databasen",
    4: "Ser etter ny versjon",
    5: "Henter den nye versjonen",
    6: "Oppdaterer avhengigheter",
    7: "Oppdaterer databasen",
    8: "Bygger brukergrensesnittet",
    9: "Helsesjekk av den nye versjonen",
    10: "Starter EmneKlar",
}
INSTALL_LABELS = {"git": "Git-klone", "release": "utgivelse", "source": "kopi av kildekoden"}


class Updater:
    def __init__(self, options: Options, *, data_dir: Path, reporter: Reporter) -> None:
        self.o = options
        self.root = options.root
        self.data_dir = data_dir
        self.r = reporter
        self.work = self.root / ".update"
        self.run_dir = data_dir / "run"
        self.db_path = data_dir / "database.db"
        self.venv_python = venv_python_path(self.root)
        self.kind = "source"
        self.current = Version(0, 0, 0)
        self.target: Version | None = None
        self.release: Release | None = None
        self.step_number = 0
        # state needed for the rollback
        self.restart_wanted = False
        self.db_backup: Path | None = None
        self.code_backup: Path | None = None
        self.swap: SwapRecord | None = None
        self.previous_head: str | None = None
        self.dist_backup: Path | None = None
        self.dist_existed = False
        self.deps_started = False
        self.migrations_started = False
        self.frontend_build_started = False
        self.health_proc: subprocess.Popen[bytes] | None = None

    # -- driver ------------------------------------------------------------------------------------

    def step(self, number: int) -> None:
        self.step_number = number
        self.r.step(number, STEP_TITLES[number])

    def run(self) -> int:
        with update_lock(self.work):
            return self._run()

    def _run(self) -> int:
        try:
            self.detect_running()
            self.validate_install()
            self.backup_database()
            candidate = self.check_version()
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - nothing changed yet; explain and restart
            expected = isinstance(exc, UpdateError | KeyboardInterrupt)
            self.r.error(describe_error(exc) if expected else f"Uventet feil: {type(exc).__name__}: {exc}")
            self.start_app_again()
            if isinstance(exc, UpdateError):
                return exc.exit_code
            return EXIT_ABORTED if isinstance(exc, KeyboardInterrupt) else EXIT_FAILED
        if candidate is None:
            self.start_app_again()
            return EXIT_OK
        try:
            self.fetch()
            self.update_dependencies()
            self.migrate()
            self.build_frontend()
            self.health_check()
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - every failure in steps 5-9 is rolled back
            self.rollback(exc)
            return EXIT_FAILED
        self.step(10)
        started = self.start_app()
        self.cleanup(success=True)
        self.r.info()
        self.r.info(f"EmneKlar er oppdatert fra {self.current} til {self.target}." +
                    (" Programmet starter i et eget vindu." if started else ""))
        if self.db_backup is not None:
            self.r.info(f"Sikkerhetskopi av databasen: {self.db_backup}")
        if self.code_backup is not None and self.kind != "git":
            self.r.info(f"Forrige programversjon er lagret i {self.code_backup}")
        self.r.info(f"Logg: {self.r.log_path}")
        return EXIT_OK

    # -- step 1 --------------------------------------------------------------------------------

    def detect_running(self) -> None:
        self.step(1)
        info = running_instance(self.run_dir)
        if info is None:
            self.r.info("EmneKlar kjører ikke.")
            return
        register_secret(info.get("control_secret"))
        self.r.info(f"EmneKlar {info.get('version', '')} kjører på {info['origin']}.".replace("  ", " "))
        with ProcessWatcher(info.get("pid")) as watcher:
            if self.o.from_app:
                self.r.info("Avslutter EmneKlar før oppdateringen …")
                self._stop_running(info, watcher)
                return
            self.r.info("EmneKlar må være avsluttet mens oppdateringen pågår.")
            while True:
                answer = ask("  Skriv S og trykk Enter for å avslutte EmneKlar nå, eller lukk EmneKlar-vinduet selv "
                             "og trykk Enter.\n  Skriv A og trykk Enter for å avbryte: ").strip().upper()
                if answer == "A":
                    raise UpdateAborted("Oppdateringen ble avbrutt. Ingenting er endret.")
                if answer not in ("", "S"):
                    self.r.info("Ukjent valg – skriv S eller A, eller trykk bare Enter.")
                    continue
                if answer == "S":
                    self._stop_running(info, watcher)
                    return
                if running_instance(self.run_dir) is None:
                    watcher.wait(15)  # the window was closed; let the process finish exiting
                    self.restart_wanted = True
                    self.r.info("EmneKlar er avsluttet.")
                    return
                self.r.info("EmneKlar kjører fortsatt.")

    def _stop_running(self, info: dict[str, Any], watcher: ProcessWatcher) -> None:
        if not request_shutdown(info):
            raise UpdateAborted("EmneKlar svarte ikke på forespørselen om å avslutte. Lukk EmneKlar-vinduet og "
                                "start oppdateringen på nytt.")
        self.restart_wanted = True
        if not wait_until_stopped(info["origin"], watcher, STOP_TIMEOUT):
            raise UpdateAborted(f"EmneKlar avsluttet ikke innen {STOP_TIMEOUT:g} sekunder. Lukk EmneKlar-vinduet og "
                                "start oppdateringen på nytt.")
        self.r.info("EmneKlar er avsluttet.")

    # -- step 2 --------------------------------------------------------------------------------

    def validate_install(self) -> None:
        self.step(2)
        current = read_version_file(self.root / "VERSION")
        if current is None:
            raise UpdateAborted(f"Fant ingen gyldig VERSION-fil i {self.root}. Er dette en EmneKlar-mappe?")
        self.current = current
        if not self.venv_python.is_file():
            raise UpdateAborted("Fant ikke Python-miljøet (backend\\.venv). Kjør setup.bat først.")
        try:
            reported = run([self.venv_python, "-m", "emneklar.manage", "version"], cwd=self.root / "backend",
                           reporter=self.r, capture=True).stdout.strip()
        except CommandFailed as exc:
            raise UpdateAborted("Python-miljøet (backend\\.venv) virker ikke. Kjør setup.bat for å reparere "
                                "installasjonen, og prøv igjen.") from exc
        if reported != str(current):
            raise UpdateAborted(f"Python-miljøet svarer med versjon {reported or '?'}, men VERSION sier {current}. "
                                "Kjør setup.bat for å reparere installasjonen, og prøv igjen.")
        self.kind = install_kind(self.root)
        self.r.info(f"Installert versjon: {current} ({INSTALL_LABELS[self.kind]}) i {self.root}")
        problem = npm_path_problem(self.root) if self.kind == "git" else None
        if problem:
            raise UpdateAborted(problem)
        ensure_free_space(self.root, MIN_FREE_BYTES, "oppdateringen")

    # -- step 3 --------------------------------------------------------------------------------

    def backup_database(self) -> None:
        self.step(3)
        if not self.db_path.is_file():
            self.r.info("Fant ingen database ennå – ingenting å sikkerhetskopiere.")
            return
        ensure_free_space(self.data_dir, 2 * self.db_path.stat().st_size + 50 * 2**20, "sikkerhetskopien")
        target = self.data_dir / "backups" / "database" / f"for-oppdatering-{self.current}-{utc_stamp()}.db"
        try:
            backup_sqlite(self.db_path, target)
        except (OSError, sqlite3.Error) as exc:
            raise UpdateError(f"Klarte ikke å sikkerhetskopiere databasen ({exc}). Ingenting er endret.") from exc
        self.db_backup = target
        self.r.info(f"Sikkerhetskopi: {target}")

    # -- step 4 --------------------------------------------------------------------------------

    def check_version(self) -> Candidate | None:
        self.step(4)
        repo, channel, source = resolve_repository(self.root, self.db_path)
        if repo:
            self.r.info(f"Oppdateringskilde: github.com/{repo} (fra {source}, kanal: "
                        f"{'forhåndsversjoner' if channel == 'prerelease' else 'stabil'}).")
        candidate = self._check_git(repo, channel) if self.kind == "git" else self._check_release(repo, channel)
        if not decide(self.current, candidate, allow_major=self.o.allow_major, from_app=self.o.from_app,
                      confirm=self._confirm_major):
            self.r.info(f"Du har allerede den nyeste versjonen ({self.current}). Ingenting å oppdatere.")
            return None
        self.target = candidate.version
        self.r.info(f"Oppdaterer fra {self.current} til {candidate.version}.")
        return candidate

    def _check_release(self, repo: str | None, channel: str) -> Candidate:
        if repo is None:
            raise UpdateAborted("Vet ikke hvor oppdateringer skal hentes fra. Angi GitHub-repositoriet under "
                                "Innstillinger → Avansert i EmneKlar, og prøv igjen.")
        if self.kind == "source":
            self.r.info("Denne mappen er en kopi av kildekoden. Den oppdateres med utgivelsespakken fra GitHub og "
                        "blir deretter en vanlig utgivelse.")
        release = fetch_latest_release(repo, channel=channel)
        if release is None:
            raise UpdateError(f"Fant ingen gyldige utgivelser av EmneKlar i github.com/{repo}.")
        self.release = release
        self.r.info(f"Siste utgivelse: {release.version}" + (" (forhåndsversjon)" if release.prerelease else ""))
        return Candidate(version=release.version, newer=self.current < release.version, notes=release.notes,
                         url=release.url)

    def _git(self, *args: str) -> str:
        return run(["git", *args], cwd=self.root, reporter=self.r, capture=True).stdout.rstrip()

    def _check_git(self, repo: str | None, channel: str) -> Candidate:
        if shutil.which("git") is None:
            raise UpdateAborted("Dette er en Git-installasjon, men Git ble ikke funnet. Installer Git, eller "
                                "oppdater mappen manuelt.")
        dirty = self._git("status", "--porcelain", "--untracked-files=no")
        if dirty:
            files = ", ".join(line[3:] for line in dirty.splitlines()[:5])
            raise UpdateAborted("Git-mappen har endringer som ikke er committet (" + files + "). Oppdateringen "
                                "endrer ikke filer med lokale endringer. Commit eller forkast endringene "
                                "(f.eks. «git stash»), og prøv igjen.")
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if branch == "HEAD":
            raise UpdateAborted("Git-mappen står ikke på en gren (detached HEAD). Bytt til en gren, f.eks. med "
                                "«git switch main», og prøv igjen.")
        try:
            upstream = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        except CommandFailed as exc:
            raise UpdateAborted(f"Grenen «{branch}» følger ingen gren på GitHub. Sett det opp med «git branch "
                                f"--set-upstream-to=origin/{branch}», eller oppdater med Git selv.") from exc
        release: Release | None = None
        if repo:
            try:
                release = fetch_latest_release(repo, channel=channel)
            except UpdateError as exc:
                self.r.warn(f"Kunne ikke sjekke utgivelsene på GitHub: {exc}")
        if release is not None:
            self.r.info(f"Siste utgivelse på GitHub: {release.version}.")
        try:
            run(["git", "fetch", "--quiet"], cwd=self.root, reporter=self.r)
        except CommandFailed as exc:
            raise UpdateError("Klarte ikke å hente endringer med Git. Sjekk nettverket (og eventuell innlogging "
                              "mot GitHub), og prøv igjen.") from exc
        incoming = int(self._git("rev-list", "--count", "HEAD..@{u}") or "0")
        if incoming == 0:
            return Candidate(version=self.current, newer=False, notes="")
        try:
            run(["git", "merge-base", "--is-ancestor", "HEAD", "@{u}"], cwd=self.root, reporter=self.r, capture=True)
        except CommandFailed as exc:
            raise UpdateAborted(f"Grenen «{branch}» har commits som ikke finnes i {upstream}, så den kan ikke spoles "
                                "fram. Oppdater med Git selv.") from exc
        try:
            upstream_version = Version.parse(self._git("show", "@{u}:VERSION")) or self.current
        except CommandFailed:
            upstream_version = self.current
        log_lines = self._git("log", "--oneline", "--no-decorate", "-n", "30", "HEAD..@{u}")
        notes = f"Nye endringer på {upstream}:\n{log_lines}"
        if release is not None and release.version == upstream_version and release.notes.strip():
            notes = f"{release.notes.strip()}\n\n{notes}"
        self.r.info(f"{upstream} har {incoming} nye endring(er) – versjon {upstream_version}.")
        return Candidate(version=upstream_version, newer=True, notes=notes, url=release.url if release else None)

    def _confirm_major(self, candidate: Candidate) -> bool:
        self.r.info()
        self.r.info(f"Versjon {candidate.version} er en større oppdatering (fra {self.current}). Den kan endre hvordan "
                    "EmneKlar virker.")
        lines = (candidate.notes.strip() or "(ingen endringsnotater)").splitlines()
        self.r.info("Endringer:")
        for line in lines[:40]:
            self.r.info(f"  {line}")
        if len(lines) > 40:
            self.r.info(f"  … {len(lines) - 40} linjer til" + (f" – se {candidate.url}" if candidate.url else ""))
        answer = ask("\n  Skriv JA og trykk Enter for å oppdatere, eller bare Enter for å avbryte: ")
        self.r.log(f"Svar på spørsmålet om større oppdatering: {answer.strip()!r}")
        return answer.strip().upper() == "JA"

    # -- step 5 --------------------------------------------------------------------------------

    def fetch(self) -> None:
        self.step(5)
        self.code_backup = self.work / f"previous-{self.current}"
        if self.kind == "git":
            self._fetch_git()
        else:
            self._fetch_release()

    def _fetch_git(self) -> None:
        self.previous_head = self._git("rev-parse", "HEAD")
        dist = self.root / "frontend" / "dist"
        self.dist_existed = dist.is_dir()
        if self.dist_existed and self.code_backup is not None:
            self.dist_backup = self.code_backup / "frontend" / "dist"
            remove_tree(self.code_backup)
            shutil.copytree(dist, self.dist_backup)
        run(["git", "pull", "--ff-only"], cwd=self.root, reporter=self.r)
        pulled = read_version_file(self.root / "VERSION")
        if pulled is None:
            raise UpdateError("VERSION-filen i den nye versjonen er ugyldig.")
        self.target = pulled
        self.r.info(f"Hentet {self._git('rev-parse', '--short', 'HEAD')} (versjon {pulled}).")

    def _fetch_release(self) -> None:
        release = self.release
        assert release is not None and self.code_backup is not None
        name = f"EmneKlar-{release.version}.zip"
        zip_url, sum_url = release.assets.get(name), release.assets.get(f"{name}.sha256")
        if not zip_url or not sum_url:
            raise UpdateError(f"Utgivelsen {release.tag} mangler {name} eller sjekksumfilen {name}.sha256.")
        downloads = self.work / "download"
        remove_tree(downloads)
        self.r.info(f"Laster ned {name} …")
        download(sum_url, downloads / f"{name}.sha256", max_bytes=64 * 1024)
        download(zip_url, downloads / name, max_bytes=MAX_DOWNLOAD_BYTES)
        checksum_text = (downloads / f"{name}.sha256").read_text(encoding="utf-8", errors="replace")
        digest = verify_checksum(downloads / name, checksum_text)
        self.r.info(f"Sjekksummen stemmer (SHA-256 {digest[:16]}…).")
        tree = extract_release(downloads / name, self.work / "staging")
        validate_release_tree(tree, release.version)
        self.r.info(f"Tar vare på gjeldende programfiler i {self.code_backup} …")
        self.swap = backup_program_files(self.root, tree, self.code_backup, old_version=str(self.current))
        apply_release(self.swap, tree)
        self.r.info(f"Programfilene er byttet ut ({len(self.swap.new_files)} filer).")

    # -- steps 6-9 -----------------------------------------------------------------------------

    def update_dependencies(self) -> None:
        self.step(6)
        self.deps_started = True
        install_python_dependencies(self.venv_python, self.root, self.r)

    def migrate(self) -> None:
        self.step(7)
        self.migrations_started = True
        run([self.venv_python, "-m", "emneklar.manage", "migrate"], cwd=self.root / "backend", reporter=self.r)

    def build_frontend(self) -> None:
        self.step(8)
        frontend = self.root / "frontend"
        index = frontend / "dist" / "index.html"
        if self.kind != "git":
            if not index.is_file():
                raise UpdateError("Utgivelsen mangler det ferdigbygde brukergrensesnittet (frontend\\dist).")
            self.r.info("Utgivelsen har ferdigbygd brukergrensesnitt – ingenting å bygge.")
            return
        npm = shutil.which("npm")
        if npm is None:
            raise UpdateError("Node.js (npm) trengs for å bygge brukergrensesnittet i en Git-installasjon, men ble "
                              "ikke funnet. Installer Node.js LTS fra https://nodejs.org og kjør update.bat på nytt.")
        self.frontend_build_started = True
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, reporter=self.r)
        run([npm, "run", "build"], cwd=frontend, reporter=self.r)
        if not index.is_file():
            raise UpdateError("Byggingen av brukergrensesnittet ga ingen frontend\\dist\\index.html.")

    def health_check(self) -> None:
        self.step(9)
        port = free_local_port()
        origin = f"http://127.0.0.1:{port}"
        output = self.work / "helsesjekk.log"
        self.work.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as out:
            self.health_proc = subprocess.Popen(
                [str(self.venv_python), "-m", "emneklar", "--no-browser", "--port", str(port)],
                cwd=self.root / "backend", stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                env=child_env(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.r.info(f"Starter den nye versjonen på {origin} (venter opptil {HEALTH_TIMEOUT:g} sekunder) …")
        deadline = time.monotonic() + HEALTH_TIMEOUT
        health: dict[str, Any] | None = None
        while time.monotonic() < deadline and self.health_proc.poll() is None:
            health = fetch_health(origin, timeout=2.0)
            if health is not None:
                break
            time.sleep(0.5)
        if health is None:
            exited = self.health_proc.poll()
            self._kill_health_app()
            tail = "\n".join(output.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-15:])
            reason = f"avsluttet med kode {exited}" if exited is not None else f"svarte ikke innen {HEALTH_TIMEOUT:g} s"
            raise UpdateError(f"Den nye versjonen startet ikke ({reason}).\n  Utdata fra programmet:\n"
                              + "\n".join(f"    {line}" for line in tail.splitlines()))
        answered = Version.parse(str(health.get("version", "")))
        if answered != self.target:
            self._kill_health_app()
            raise UpdateError(f"Helsesjekken svarte med versjon {health.get('version')}, ventet {self.target}.")
        self.r.info(f"EmneKlar {answered} startet og svarer som det skal.")
        self._stop_health_app(origin)

    def _stop_health_app(self, origin: str) -> None:
        proc = self.health_proc
        if proc is None:
            return
        info = read_instance(self.run_dir)
        if info is not None and info["origin"] == origin:
            register_secret(info.get("control_secret"))
            if request_shutdown(info):
                try:
                    proc.wait(timeout=STOP_TIMEOUT)
                    self.health_proc = None
                    return
                except subprocess.TimeoutExpired:
                    pass
        self._kill_health_app()

    def _kill_health_app(self) -> None:
        proc = self.health_proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()  # on Windows the venv launcher's job object takes the interpreter with it
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=15)
        self.health_proc = None

    # -- step 10 and restarts ----------------------------------------------------------------------

    def start_app(self) -> bool:
        """Start EmneKlar normally (own console window, opens the browser). True if it was started."""
        if self.o.no_start:
            self.r.info("EmneKlar startes ikke automatisk (--no-start). Start programmet med start.bat.")
            return False
        try:
            if os.name == "nt":
                start_bat = self.root / "start.bat"
                comspec = os.environ.get("COMSPEC") or "cmd.exe"
                # /s + outer quotes: the path may contain spaces, parentheses, & or Norwegian letters.
                subprocess.Popen(f'"{comspec}" /d /s /c ""{start_bat}""', cwd=self.root, close_fds=True,
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            else:
                subprocess.Popen([str(self.venv_python), "-m", "emneklar"], cwd=self.root / "backend",
                                 start_new_session=True, stdin=subprocess.DEVNULL)
        except OSError as exc:
            self.r.warn(f"Klarte ikke å starte EmneKlar automatisk ({exc}). Start programmet med start.bat.")
            return False
        self.r.info("EmneKlar starter i et eget vindu, og nettleseren åpnes automatisk.")
        return True

    def start_app_again(self) -> None:
        """After a refused/aborted update: start EmneKlar again if this script stopped it."""
        if self.restart_wanted:
            self.r.info()
            self.start_app()

    # -- rollback ------------------------------------------------------------------------------

    def rollback(self, error: BaseException) -> None:
        failed = self.step_number
        self.r.error(f"Steg {failed} av {TOTAL_STEPS} ({STEP_TITLES.get(failed, '?')}) feilet: {describe_error(error)}")
        self.r.info()
        self.r.info("Setter alt tilbake til slik det var før oppdateringen …")
        results: list[tuple[bool, str]] = []
        self._kill_health_app()

        code_ok = True
        try:
            if self.kind == "git":
                self._rollback_git()
            elif self.swap is not None:
                rollback_release(self.swap)
            results.append((True, f"Programfilene er satt tilbake til versjon {self.current}."))
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - report and continue with the rest
            code_ok = False
            where = f" Kopien av forrige versjon ligger i {self.code_backup}." if self.code_backup else ""
            results.append((False, f"Programfilene kunne ikke settes tilbake: {describe_error(exc)}{where}"))

        if self.deps_started:
            try:
                install_python_dependencies(self.venv_python, self.root, self.r)
                results.append((True, f"Avhengighetene er installert på nytt for versjon {self.current}."))
            except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001
                results.append((False, f"Avhengighetene kunne ikke installeres på nytt ({describe_error(exc)}). Kjør "
                                       "setup.bat for å reparere Python-miljøet."))

        if self.migrations_started:
            quarantine = self.data_dir / "backups" / "database"
            try:
                if self.db_backup is not None:
                    restore_database(self.db_backup, self.db_path, quarantine)
                    results.append((True, "Databasen er hentet tilbake fra sikkerhetskopien."))
                elif self.db_path.exists():
                    # No database existed before: move the one the failed migration created out of the way.
                    target = quarantine / f"etter-feilet-oppdatering-{utc_stamp()}.db"
                    quarantine.mkdir(parents=True, exist_ok=True)
                    for suffix in ("", "-wal", "-shm"):
                        if Path(f"{self.db_path}{suffix}").exists():
                            os.replace(f"{self.db_path}{suffix}", f"{target}{suffix}")
                    results.append((True, f"Databasen som ble laget under oppdateringen er flyttet til {target}."))
            except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001
                results.append((False, f"Databasen kunne ikke hentes tilbake automatisk ({describe_error(exc)}). "
                                       f"Sikkerhetskopien ligger i {self.db_backup}."))

        if code_ok and self.o.no_start:
            results.append((True, f"EmneKlar {self.current} er klar, men startes ikke automatisk (--no-start)."))
        elif code_ok:
            started = self.start_app()
            results.append((started, f"EmneKlar {self.current} er startet igjen." if started else
                            f"EmneKlar {self.current} ble ikke startet. Start programmet med start.bat."))
        else:
            results.append((False, "EmneKlar ble ikke startet fordi programfilene ikke kunne settes tilbake. Kjør "
                                   "update.bat på nytt, eller kontakt den som har installert EmneKlar."))
        self.cleanup(success=False)

        self.r.info()
        self.r.info(f"Oppdateringen til {self.target or 'ny versjon'} feilet i steg {failed} av {TOTAL_STEPS}. "
                    "Dette ble gjort:")
        for ok, text in results:
            self.r.info(f"  [{'OK' if ok else 'FEIL'}] {text}")
        if self.db_backup is not None:
            self.r.info(f"Sikkerhetskopi av databasen: {self.db_backup}")
        if self.code_backup is not None and self.code_backup.exists() and self.kind != "git":
            self.r.info(f"Kopi av forrige programversjon: {self.code_backup}")
        self.r.info(f"Logg med alle detaljer: {self.r.log_path}")

    def _rollback_git(self) -> None:
        if self.previous_head and self._git("rev-parse", "HEAD") != self.previous_head:
            # Safe: an update is refused when tracked files have uncommitted changes.
            run(["git", "reset", "--hard", self.previous_head], cwd=self.root, reporter=self.r)
        if self.frontend_build_started:
            dist = self.root / "frontend" / "dist"
            remove_tree(dist)
            if self.dist_existed and self.dist_backup is not None:
                shutil.copytree(self.dist_backup, dist)

    def cleanup(self, *, success: bool) -> None:
        for leftover in (self.work / "staging", self.work / "download"):
            with contextlib.suppress(OSError):
                remove_tree(leftover)
        if success:
            with contextlib.suppress(OSError):
                (self.work / "helsesjekk.log").unlink(missing_ok=True)
            prune_code_backups(self.work)


# -- entry point ---------------------------------------------------------------------------------


def _remove_own_temp_copy() -> None:
    """update.bat runs a copy of this file from %TEMP%\\EmneKlar-oppdatering-*; remove that folder afterwards."""
    here = Path(__file__).resolve().parent
    temp_root = Path(tempfile.gettempdir()).resolve()
    if here.name.startswith("EmneKlar-oppdatering-") and temp_root in here.parents:
        shutil.rmtree(here, ignore_errors=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Oppdaterer EmneKlar til nyeste versjon.")
    parser.add_argument("--from-app", action="store_true", help="startet fra EmneKlar (ingen spørsmål)")
    parser.add_argument("--allow-major", action="store_true", help="tillat en større oppdatering uten å spørre")
    parser.add_argument("--repo", help="EmneKlar-mappen (standard: mappen over scripts)")
    parser.add_argument("--no-start", action="store_true", help="ikke start EmneKlar etter oppdateringen")
    parser.add_argument("--no-pause", action="store_true", help="ikke vent på Enter før vinduet lukkes")
    parser.add_argument("--temp-copy", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_stdio()

    root = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parents[1]
    data_dir = data_dir_from_env()
    reporter = Reporter(data_dir / "logs" / "update.log", total_steps=TOTAL_STEPS, title="EmneKlar-oppdatering")
    print("EmneKlar – oppdatering")
    print(f"  Program: {root}")
    print(f"  Dine data ({data_dir}) blir ikke slettet. Databasen sikkerhetskopieres før noe endres.")
    code = EXIT_FAILED
    try:
        if not (root / "VERSION").is_file() or not (root / "backend").is_dir():
            raise UpdateAborted(f"{root} ser ikke ut som en EmneKlar-mappe (mangler VERSION eller backend).")
        updater = Updater(Options(root=root, from_app=args.from_app, allow_major=args.allow_major,
                                  no_start=args.no_start), data_dir=data_dir, reporter=reporter)
        code = updater.run()
    except UpdateError as exc:
        reporter.error(describe_error(exc))
        code = exc.exit_code
    except KeyboardInterrupt:
        reporter.error(f"Oppdateringen ble avbrutt (Ctrl+C). Se loggen {reporter.log_path} for hva som ble gjort.")
        code = EXIT_ABORTED
    except Exception as exc:  # noqa: BLE001 - last line of defence: log, explain, keep the window open
        import traceback

        reporter.log(traceback.format_exc())
        reporter.error(f"Uventet feil: {type(exc).__name__}: {exc}. Se loggen {reporter.log_path}.")
        code = EXIT_FAILED
    finally:
        reporter.log(f"Avsluttet med kode {code}")
        reporter.close()
    if not args.no_pause and sys.stdin is not None and sys.stdin.isatty() and (code != EXIT_OK or not args.from_app):
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input("\nTrykk Enter for å lukke vinduet …")
    if args.temp_copy:
        _remove_own_temp_copy()
    return code


if __name__ == "__main__":
    sys.exit(main())
