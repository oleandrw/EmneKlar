"""EmneKlar – oppdatering. Started by update.bat (also from Innstillinger → Generelt in the app).

The update runs in ten steps, each announced as "Steg N av 10 – …":

     1  detect a running EmneKlar and stop it      6  update Python dependencies (pinned versions)
     2  validate the installation                  7  migrate the database
     3  back up the database                       8  build the user interface (Git installations)
     4  check for a newer version on GitHub        9  health check of the new version
     5  fetch the new version                     10  start EmneKlar again

If anything in steps 5–9 fails, the program files, the dependencies and the database are rolled back and the
previous version is started again. User data (``%LOCALAPPDATA%\\EmneKlar``) is never deleted; the database is
backed up before anything changes.

Installation types (same rule as ``emneklar.core.updates.service``): ``git`` if ``.git`` exists (updated with
``git pull --ff-only``; refused if tracked files have uncommitted changes), ``release`` if ``install.json``
exists, otherwise ``source``. Release and source installations are updated with the release package
``EmneKlar-<versjon>.zip`` (verified against ``EmneKlar-<versjon>.zip.sha256``; a signature of that checksum file,
``EmneKlar-<versjon>.zip.sha256.sig``, is checked against RELEASE_SIGNING_KEYS when signing is in use).

Python: an installation made by the installer has its own runtime in ``runtime\\`` (Python with every dependency
already installed – see scripts/build_runtime.py). Such an installation never runs pip: in step 5 the runtime the
new version needs is fetched if it differs from the installed one (its SHA-256 is in the release package's
install.json), and in step 6 there is nothing to install. The runtime folder is replaced as a whole and put back as
a whole if a later step fails. update.bat therefore runs this script with a copy of the interpreter, so that
``runtime\\`` is not in use while it is replaced. Without ``runtime\\`` the installation uses the virtual environment
``backend\\.venv`` made by setup.bat, and step 6 installs the pinned dependencies with pip, as before.

Exit codes: 0 = updated, or already up to date
            1 = the update failed (changes were rolled back, or nothing had been changed yet)
            2 = not started: the user cancelled, or a safety check stopped it (major version without
                confirmation, uncommitted Git changes, EmneKlar could not be stopped, …)

update.bat runs a temporary copy of this file, so the update may safely replace ``scripts/``.
``scripts/setup.py`` reuses the helpers in the first half of this file.
"""

from __future__ import annotations

import argparse
import base64
import binascii
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
    import emneklar  # noqa: F401 - importable through the venv's editable install or the runtime's ._pth file
except ModuleNotFoundError:  # run by another Python (setup.bat), or by the interpreter copy update.bat makes
    # The installation is ``--repo <mappe>`` when given (update.bat runs a temporary copy of this file), else the
    # folder above scripts/.
    _repo = next((sys.argv[i + 1] for i, word in enumerate(sys.argv[:-1]) if word == "--repo"), None)
    sys.path.insert(0, str((Path(_repo) if _repo else Path(__file__).resolve().parents[1]).resolve() / "backend"))

from emneklar import __version__
from emneklar.core.security.redaction import redact, register_secret
from emneklar.core.system import platform_tag
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
# The bundled Python runtime of an installation: ``<installation>/runtime`` (built by scripts/build_runtime.py). It is
# not among the program files that are swapped one by one – it is replaced, and put back, as a whole folder.
RUNTIME_DIR = "runtime"
RUNTIME_INFO = "runtime.json"
ROOT_EXCLUDED_DIRS = frozenset({RUNTIME_DIR})  # only at the top level of the installation
RUNTIME_ID_RE = re.compile(r"^cp\d{2,3}-[0-9a-f]{12}$")
RUNTIME_PLATFORM_RE = re.compile(r"^[a-z0-9]+-[a-z0-9_]+$")
# Files of the old version that the new release no longer contains are removed only here (code that is
# discovered dynamically, e.g. Alembic migrations, and the built UI). They stay in the code backup.
STALE_CLEANUP_PREFIXES = ("backend/emneklar/", "backend/migrations/", "frontend/dist/", "scripts/")
RELEASE_REQUIRED_FILES = ("VERSION", "install.json", "backend/pyproject.toml", "backend/emneklar/__init__.py",
                          "frontend/dist/index.html", "start.bat", "update.bat")
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
# Signed releases (prepared): the checksum file of a release package may be signed with Ed25519 – the signature is
# ``EmneKlar-<versjon>.zip.sha256.sig`` (base64, 64 bytes) over the exact bytes of ``EmneKlar-<versjon>.zip.sha256``,
# verified against the public keys below (hex, 32 bytes each). No key yet: the signature is not checked (SHA-256 only).
# SIGNATURE_REQUIRED stays False until releases are signed in the release workflow – otherwise every update would stop.
RELEASE_SIGNING_KEYS: tuple[str, ...] = ()
SIGNATURE_REQUIRED = False
SIGNATURE_SUFFIX = ".sig"
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


def runtime_interpreter(folder: Path, *, windowed: bool = False) -> Path:
    """The interpreter inside a runtime folder. ``windowed``: the one that runs without a console window."""
    if os.name == "nt":
        return folder / ("pythonw.exe" if windowed else "python.exe")
    return folder / "bin" / "python3"


def bundled_python_path(root: Path, *, windowed: bool = False) -> Path:
    """The interpreter of the installation's own runtime (``<installation>/runtime``)."""
    return runtime_interpreter(root / RUNTIME_DIR, windowed=windowed)


def has_bundled_runtime(root: Path) -> bool:
    return bundled_python_path(root).is_file()


def installation_python(root: Path) -> Path:
    """The Python that runs this installation: its own runtime if it has one, else the venv made by setup."""
    return bundled_python_path(root) if has_bundled_runtime(root) else venv_python_path(root)


def installed_runtime_id(root: Path) -> str | None:
    """The id of the runtime in ``runtime\\`` (None: no runtime, or one without a readable runtime.json)."""
    try:
        info = json.loads((root / RUNTIME_DIR / RUNTIME_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    identifier = info.get("id") if isinstance(info, dict) else None
    return identifier if isinstance(identifier, str) and RUNTIME_ID_RE.match(identifier) else None


def strict_pins() -> bool:
    return os.environ.get("EMNEKLAR_STRICT_PINS", "").strip().lower() in {"1", "true", "yes", "ja"}


def pins_unavailable(pip_output: str) -> bool:
    """True if pip failed because the pinned versions do not exist (or cannot be built) for this Python."""
    return (any(marker in pip_output for marker in PINS_UNAVAILABLE_MARKERS)
            and not any(marker in pip_output for marker in NETWORK_ERROR_MARKERS))


def install_python_dependencies(venv_python: Path, root: Path, reporter: Reporter) -> None:
    """``pip install -c backend/constraints.txt -e backend`` – the tested versions.

    If the pinned versions do not exist for the venv's Python version (typically a Python release newer than
    the pins), the newest versions allowed by pyproject.toml are installed instead, with a warning – unless
    EMNEKLAR_STRICT_PINS=1 (used in CI). Network problems are never "solved" by dropping the pins.

    Only the dependencies of backend/pyproject.toml: nothing optional (such as local models) is ever asked about,
    downloaded or installed by setup or update.
    """
    backend = root / "backend"
    constraints = backend / "constraints.txt"
    base: list[str | Path] = [venv_python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    if not constraints.is_file():
        reporter.warn("Fant ikke backend\\constraints.txt – installerer nyeste tillatte versjoner.")
        run([*base, "-e", backend], cwd=root, reporter=reporter)
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


# -- release signatures (Ed25519, RFC 8032) -----------------------------------------------------------
# Verification only, in plain Python (no extra package – scripts/setup.py imports this file with the system Python).
# The algorithm is the reference algorithm in RFC 8032 section 6; it is tested against the RFC's test vectors.

_ED_P = 2**255 - 19
_ED_L = 2**252 + 27742317777372353535851937790883648493
_ED_D = -121665 * pow(121666, _ED_P - 2, _ED_P) % _ED_P
_ED_SQRT_M1 = pow(2, (_ED_P - 1) // 4, _ED_P)
_EdPoint = tuple[int, int, int, int]


def _ed_add(a: _EdPoint, b: _EdPoint) -> _EdPoint:
    p = _ED_P
    k1 = (a[1] - a[0]) * (b[1] - b[0]) % p
    k2 = (a[1] + a[0]) * (b[1] + b[0]) % p
    k3 = 2 * a[3] * b[3] * _ED_D % p
    k4 = 2 * a[2] * b[2] % p
    e, f, g, h = k2 - k1, k4 - k3, k4 + k3, k2 + k1
    return (e * f % p, g * h % p, f * g % p, e * h % p)


def _ed_mul(scalar: int, point: _EdPoint) -> _EdPoint:
    result: _EdPoint = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _ed_add(result, point)
        point = _ed_add(point, point)
        scalar >>= 1
    return result


def _ed_equal(a: _EdPoint, b: _EdPoint) -> bool:
    p = _ED_P
    return (a[0] * b[2] - b[0] * a[2]) % p == 0 and (a[1] * b[2] - b[1] * a[2]) % p == 0


def _ed_recover_x(y: int, sign: int) -> int | None:
    p = _ED_P
    if y >= p:
        return None
    x2 = (y * y - 1) * pow(_ED_D * y * y + 1, p - 2, p) % p
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * _ED_SQRT_M1 % p
    if (x * x - x2) % p != 0:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


def _ed_decompress(data: bytes) -> _EdPoint | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _ed_recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _ED_P)


_ED_GY = 4 * pow(5, _ED_P - 2, _ED_P) % _ED_P
_ED_GX = _ed_recover_x(_ED_GY, 0)
assert _ED_GX is not None
_ED_BASE: _EdPoint = (_ED_GX, _ED_GY, 1, _ED_GX * _ED_GY % _ED_P)


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True when ``signature`` is a valid Ed25519 signature of ``message`` by ``public_key`` (RFC 8032 5.1.7)."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _ed_decompress(public_key)
    r = _ed_decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _ED_L:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _ED_L
    return _ed_equal(_ed_mul(s, _ED_BASE), _ed_add(r, _ed_mul(k, a)))


def verify_release_signature(checksum_bytes: bytes, signature_text: str | None, *,
                             keys: Sequence[str] | None = None, required: bool | None = None) -> str:
    """Checks the signature of a release's checksum file; returns what was checked (for the log).

    * No public key in this version: nothing to check against – SHA-256 only (the signature is prepared).
    * A key, but no signature file: allowed while signing is not required; refused when it is.
    * A signature that does not match any key: always refused – the release may have been tampered with.
    """
    keys = RELEASE_SIGNING_KEYS if keys is None else keys
    required = SIGNATURE_REQUIRED if required is None else required
    if not keys:
        return "Signaturkontroll er forberedt, men ikke slått på i denne versjonen (bare SHA-256 er kontrollert)."
    if signature_text is None:
        if required:
            raise UpdateError("Utgivelsen mangler signaturfilen. Oppdateringen er stoppet – kontroller utgivelsen på "
                              "GitHub.")
        return "Utgivelsen er ikke signert – bare SHA-256 er kontrollert."
    try:
        signature = base64.b64decode("".join(signature_text.split()), validate=True)
    except (ValueError, binascii.Error):
        signature = b""
    if len(signature) != 64:
        raise UpdateError("Signaturfilen har et ukjent format. Oppdateringen er stoppet.")
    for key in keys:
        if ed25519_verify(bytes.fromhex(key), checksum_bytes, signature):
            return f"Signaturen er gyldig (nøkkel {key[:16]}…)."
    raise UpdateError("Signaturen på utgivelsen er ugyldig. Pakken kan være endret, og blir ikke installert.")


def _safe_member(name: str) -> PurePosixPath:
    if not name or "\\" in name or ":" in name or name.startswith("/"):
        raise UpdateError(f"Utgivelsespakken inneholder en ugyldig sti: {name!r}")
    path = PurePosixPath(name)
    if any(part in ("", ".", "..") for part in path.parts):
        raise UpdateError(f"Utgivelsespakken inneholder en ugyldig sti: {name!r}")
    return path


def unpack(zip_path: Path, staging: Path) -> None:
    """Unpack a zip from a release into the fresh folder ``staging``, rejecting unsafe paths, links and zip bombs."""
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


def extract_release(zip_path: Path, staging: Path) -> Path:
    """Unpack the release zip into ``staging`` (rejecting unsafe paths) and return the folder with VERSION."""
    unpack(zip_path, staging)
    entries = list(staging.iterdir())
    if not (staging / "VERSION").exists() and len(entries) == 1 and entries[0].is_dir():
        return entries[0]  # packaged as EmneKlar-<versjon>/...
    return staging


# -- the bundled runtime of a release -------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeRef:
    """One entry of ``runtimes`` in a release's install.json: the runtime the release needs on one platform."""

    platform: str
    id: str
    python: str
    asset: str
    sha256: str
    size: int


def runtime_asset_name(platform: str, identifier: str) -> str:
    return f"EmneKlar-runtime-{platform}-{identifier}.zip"


def release_runtimes(install_info: object) -> dict[str, RuntimeRef]:
    """``{platform: runtime}`` from the content of install.json. A malformed entry is an error – never a silent "no
    runtime": the SHA-256 recorded here is the only thing that makes the runtime download trustworthy."""
    section = install_info.get("runtimes") if isinstance(install_info, dict) else None
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise UpdateError("install.json i utgivelsespakken har en ugyldig liste over kjøretider.")
    found: dict[str, RuntimeRef] = {}
    for platform, entry in section.items():
        identifier, python = (entry.get("id"), entry.get("python")) if isinstance(entry, dict) else (None, None)
        asset, digest, size = (entry.get("asset"), entry.get("sha256"), entry.get("size")) \
            if isinstance(entry, dict) else (None, None, None)
        if (not isinstance(platform, str) or not RUNTIME_PLATFORM_RE.match(platform)
                or not isinstance(identifier, str) or not RUNTIME_ID_RE.match(identifier)
                or not isinstance(python, str) or not re.fullmatch(r"\d+\.\d+\.\d+", python)
                or asset != runtime_asset_name(platform, identifier)
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_DOWNLOAD_BYTES):
            raise UpdateError(f"install.json i utgivelsespakken har en ugyldig kjøretid for «{platform}».")
        found[platform] = RuntimeRef(platform=platform, id=identifier, python=python, asset=asset, sha256=digest,
                                     size=size)
    return found


def read_runtime_info(folder: Path) -> dict[str, Any]:
    try:
        info = json.loads((folder / RUNTIME_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError("Kjøretiden i utgivelsen mangler en gyldig runtime.json.") from exc
    if not isinstance(info, dict):
        raise UpdateError("Kjøretiden i utgivelsen mangler en gyldig runtime.json.")
    return info


def verify_runtime_archive(path: Path, wanted: RuntimeRef) -> None:
    """The size and SHA-256 recorded in install.json – which itself came out of the verified release package."""
    if path.stat().st_size != wanted.size or not hmac.compare_digest(sha256_file(path), wanted.sha256):
        raise UpdateError(f"{path.name} stemmer ikke med sjekksummen i utgivelsen. Filen kan være skadet eller endret, "
                          "og blir ikke installert.")


def extract_runtime(zip_path: Path, staging: Path, wanted: RuntimeRef) -> None:
    """Unpack a verified runtime zip into ``staging`` and check that it is the runtime the release asked for."""
    unpack(zip_path, staging)
    info = read_runtime_info(staging)
    if info.get("id") != wanted.id or info.get("platform") != wanted.platform:
        raise UpdateError(f"Kjøretiden i {zip_path.name} er ikke den utgivelsen ber om ({wanted.id}).")
    if not runtime_interpreter(staging).is_file():
        raise UpdateError(f"Kjøretiden i {zip_path.name} mangler Python.")


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
    """Relative POSIX paths of all files under ``root``, skipping EXCLUDED_DIRS (at any depth), the bundled runtime
    (``runtime`` at the top level) and symlinks."""
    found: set[str] = set()
    for current, dirs, files in os.walk(root):
        top = Path(current) == root
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not (top and d in ROOT_EXCLUDED_DIRS)
                   and not Path(current, d).is_symlink()]
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


def _rename_folder(source: Path, target: Path, *, attempts: int = 20) -> None:
    """Rename a whole folder (the bundled runtime). A virus scanner may hold a file open for a moment right after it
    was written, so a refused rename is tried again for a few seconds before it counts as a failure."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25)


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
        # An installation with its own runtime never uses pip; one without it uses the venv made by setup.
        self.bundled = has_bundled_runtime(self.root)
        self.python = installation_python(self.root)
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
        self.new_runtime: RuntimeRef | None = None  # set when the new version needs another runtime
        self.runtime_swapped = False

    @property
    def runtime_staging(self) -> Path:
        return self.work / "runtime-new"

    @property
    def runtime_previous(self) -> Path:
        return self.work / "runtime-previous"

    def start_hint(self) -> str:
        return "Start EmneKlar fra Start-menyen." if self.bundled else "Start programmet med start.bat."

    def repair_hint(self) -> str:
        if self.bundled:
            return "Installer EmneKlar på nytt med installasjonsprogrammet (dataene dine beholdes)"
        return "Kjør setup.bat for å reparere installasjonen"

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
                    ((" Programmet starter nå." if self.bundled else " Programmet starter i et eget vindu.")
                     if started else ""))
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
                answer = ask("  Skriv S og trykk Enter for å avslutte EmneKlar nå, eller avslutt EmneKlar selv og "
                             "trykk Enter.\n  Skriv A og trykk Enter for å avbryte: ").strip().upper()
                if answer == "A":
                    raise UpdateAborted("Oppdateringen ble avbrutt. Ingenting er endret.")
                if answer not in ("", "S"):
                    self.r.info("Ukjent valg – skriv S eller A, eller trykk bare Enter.")
                    continue
                if answer == "S":
                    self._stop_running(info, watcher)
                    return
                if running_instance(self.run_dir) is None:
                    watcher.wait(15)  # EmneKlar was closed; let the process finish exiting
                    self.restart_wanted = True
                    self.r.info("EmneKlar er avsluttet.")
                    return
                self.r.info("EmneKlar kjører fortsatt.")

    def _stop_running(self, info: dict[str, Any], watcher: ProcessWatcher) -> None:
        if not request_shutdown(info):
            raise UpdateAborted("EmneKlar svarte ikke på forespørselen om å avslutte. Avslutt EmneKlar og start "
                                "oppdateringen på nytt.")
        self.restart_wanted = True
        if not wait_until_stopped(info["origin"], watcher, STOP_TIMEOUT):
            raise UpdateAborted(f"EmneKlar avsluttet ikke innen {STOP_TIMEOUT:g} sekunder. Avslutt EmneKlar og "
                                "start oppdateringen på nytt.")
        self.r.info("EmneKlar er avsluttet.")

    # -- step 2 --------------------------------------------------------------------------------

    def validate_install(self) -> None:
        self.step(2)
        current = read_version_file(self.root / "VERSION")
        if current is None:
            raise UpdateAborted(f"Fant ingen gyldig VERSION-fil i {self.root}. Er dette en EmneKlar-mappe?")
        self.current = current
        if not self.python.is_file():
            raise UpdateAborted("Fant ikke Python-miljøet (backend\\.venv). Kjør setup.bat først.")
        where = "Kjøretiden (runtime)" if self.bundled else "Python-miljøet (backend\\.venv)"
        try:
            reported = run([self.python, "-m", "emneklar.manage", "version"], cwd=self.root / "backend",
                           reporter=self.r, capture=True).stdout.strip()
        except CommandFailed as exc:
            raise UpdateAborted(f"{where} virker ikke. {self.repair_hint()}, og prøv igjen.") from exc
        if reported != str(current):
            raise UpdateAborted(f"{where} svarer med versjon {reported or '?'}, men VERSION sier {current}. "
                                f"{self.repair_hint()}, og prøv igjen.")
        self.kind = install_kind(self.root)
        self.r.info(f"Installert versjon: {current} ({INSTALL_LABELS[self.kind]}) i {self.root}")
        if self.bundled:
            self.r.info(f"Innebygd kjøretid: {installed_runtime_id(self.root) or 'ukjent'}")
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
        sig_url = release.assets.get(f"{name}.sha256{SIGNATURE_SUFFIX}")
        if not zip_url or not sum_url:
            raise UpdateError(f"Utgivelsen {release.tag} mangler {name} eller sjekksumfilen {name}.sha256.")
        downloads = self.work / "download"
        remove_tree(downloads)
        self.r.info(f"Laster ned {name} …")
        download(sum_url, downloads / f"{name}.sha256", max_bytes=64 * 1024)
        signature_text = None
        if sig_url:
            download(sig_url, downloads / f"{name}.sha256{SIGNATURE_SUFFIX}", max_bytes=4 * 1024)
            signature_text = (downloads / f"{name}.sha256{SIGNATURE_SUFFIX}").read_text(encoding="ascii",
                                                                                       errors="replace")
        # The checksum file is trusted only after its signature is checked (when signing is in use).
        self.r.info(verify_release_signature((downloads / f"{name}.sha256").read_bytes(), signature_text))
        download(zip_url, downloads / name, max_bytes=MAX_DOWNLOAD_BYTES)
        checksum_text = (downloads / f"{name}.sha256").read_text(encoding="utf-8", errors="replace")
        digest = verify_checksum(downloads / name, checksum_text)
        self.r.info(f"Sjekksummen stemmer (SHA-256 {digest[:16]}…).")
        tree = extract_release(downloads / name, self.work / "staging")
        validate_release_tree(tree, release.version)
        self._stage_runtime(tree, release)  # fetched and checked before anything in the installation is changed
        self.r.info(f"Tar vare på gjeldende programfiler i {self.code_backup} …")
        self.swap = backup_program_files(self.root, tree, self.code_backup, old_version=str(self.current))
        apply_release(self.swap, tree)
        self.r.info(f"Programfilene er byttet ut ({len(self.swap.new_files)} filer).")
        self._swap_runtime()

    # -- the bundled runtime ---------------------------------------------------------------------

    def _stage_runtime(self, tree: Path, release: Release) -> None:
        """Fetch the runtime the new version needs into ``.update/runtime-new`` – unless it is the installed one."""
        try:
            info = json.loads((tree / "install.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UpdateError("install.json i utgivelsespakken er ugyldig.") from exc
        runtimes = release_runtimes(info)
        if not self.bundled:
            return  # this installation runs in the venv made by setup; step 6 installs the dependencies
        tag = platform_tag()
        wanted = runtimes.get(tag)
        if wanted is None:
            raise UpdateError(f"Utgivelsen {release.tag} har ingen innebygd kjøretid for denne maskinen ({tag}). "
                              "Installasjonen er ikke endret.")
        if installed_runtime_id(self.root) == wanted.id:
            self.r.info(f"Kjøretiden er den samme som før ({wanted.id}) – ingenting å hente.")
            return
        url = release.assets.get(wanted.asset)
        if not url:
            raise UpdateError(f"Utgivelsen {release.tag} mangler kjøretidfilen {wanted.asset}.")
        live = (self.root / RUNTIME_DIR).resolve()
        if live in Path(sys.executable).resolve().parents:
            raise UpdateError("Denne oppdateringen bytter den innebygde kjøretiden og må startes med update.bat "
                              "(eller fra Innstillinger i EmneKlar). Ingenting er endret.")
        ensure_free_space(self.root, 4 * wanted.size + MIN_FREE_BYTES, "den nye kjøretiden")
        self.r.info(f"Laster ned ny kjøretid ({wanted.asset}, {wanted.size / 2**20:.0f} MB) …")
        archive = self.work / "download" / wanted.asset
        download(url, archive, max_bytes=wanted.size)
        verify_runtime_archive(archive, wanted)
        self.r.info(f"Sjekksummen for kjøretiden stemmer (SHA-256 {wanted.sha256[:16]}…).")
        extract_runtime(archive, self.runtime_staging, wanted)
        self.new_runtime = wanted

    def _swap_runtime(self) -> None:
        """Replace ``runtime\\`` with the staged one: two renames of whole folders. The old one waits in
        ``.update/runtime-previous`` until the new version has passed its health check."""
        if self.new_runtime is None:
            return
        live = self.root / RUNTIME_DIR
        remove_tree(self.runtime_previous)
        self.runtime_swapped = True  # from here on a failure puts the old folder back (see _rollback_runtime)
        _rename_folder(live, self.runtime_previous)
        _rename_folder(self.runtime_staging, live)
        self.r.info(f"Kjøretiden er byttet ut ({self.new_runtime.id}, Python {self.new_runtime.python}).")

    def _rollback_runtime(self) -> None:
        live = self.root / RUNTIME_DIR
        if self.runtime_swapped and self.runtime_previous.is_dir():
            if live.exists():
                failed = self.work / "runtime-failed"
                remove_tree(failed)
                _rename_folder(live, failed)
            _rename_folder(self.runtime_previous, live)
        for leftover in (self.runtime_staging, self.work / "runtime-failed"):
            with contextlib.suppress(OSError):
                remove_tree(leftover)

    # -- steps 6-9 -----------------------------------------------------------------------------

    def update_dependencies(self) -> None:
        self.step(6)
        if self.bundled:
            self.r.info("Avhengighetene følger med den innebygde kjøretiden – ingenting å installere.")
            return
        self.deps_started = True
        install_python_dependencies(self.python, self.root, self.r)

    def migrate(self) -> None:
        self.step(7)
        self.migrations_started = True
        run([self.python, "-m", "emneklar.manage", "migrate"], cwd=self.root / "backend", reporter=self.r)

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
                [str(self.python), "-m", "emneklar", "--no-browser", "--port", str(port)],
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
        """Start EmneKlar the way the user does: without a console window when the installation has its own runtime
        (as the shortcut does), else with start.bat in its own window. True if it was started."""
        if self.o.no_start:
            self.r.info(f"EmneKlar startes ikke automatisk (--no-start). {self.start_hint()}")
            return False
        try:
            if self.bundled:
                flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                subprocess.Popen([str(bundled_python_path(self.root, windowed=True)), "-m", "emneklar"],
                                 cwd=self.root, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")
            elif os.name == "nt":
                start_bat = self.root / "start.bat"
                comspec = os.environ.get("COMSPEC") or "cmd.exe"
                # /s + outer quotes: the path may contain spaces, parentheses, & or Norwegian letters.
                subprocess.Popen(f'"{comspec}" /d /s /c ""{start_bat}""', cwd=self.root, close_fds=True,
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            else:
                subprocess.Popen([str(self.python), "-m", "emneklar"], cwd=self.root / "backend",
                                 start_new_session=True, stdin=subprocess.DEVNULL)
        except OSError as exc:
            self.r.warn(f"Klarte ikke å starte EmneKlar automatisk ({exc}). {self.start_hint()}")
            return False
        self.r.info("EmneKlar starter, og nettleseren åpnes automatisk." if self.bundled else
                    "EmneKlar starter i et eget vindu, og nettleseren åpnes automatisk.")
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
            if self.new_runtime is not None:
                swapped = self.runtime_swapped
                self._rollback_runtime()
                if swapped:
                    results.append((True, "Den forrige kjøretiden er satt tilbake."))
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - report and continue with the rest
            code_ok = False
            where = f" Kopien av forrige versjon ligger i {self.code_backup}." if self.code_backup else ""
            results.append((False, f"Programfilene kunne ikke settes tilbake: {describe_error(exc)}{where}"))

        if self.deps_started:
            try:
                install_python_dependencies(self.python, self.root, self.r)
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
                            f"EmneKlar {self.current} ble ikke startet. {self.start_hint()}"))
        else:
            results.append((False, "EmneKlar ble ikke startet fordi programfilene ikke kunne settes tilbake. "
                                   f"{self.repair_hint()}, eller kontakt den som har installert EmneKlar."))
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
        leftovers = [self.work / "staging", self.work / "download", self.runtime_staging]
        if success:
            leftovers.append(self.runtime_previous)  # the new version passed its health check: not needed any more
        for leftover in leftovers:
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
