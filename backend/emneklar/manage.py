"""Maintenance commands for EmneKlar (used by setup.bat, update.bat and CI).

    python -m emneklar.manage version
    python -m emneklar.manage migrate
    python -m emneklar.manage backup-db <fil eller mappe>
    python -m emneklar.manage health [--origin http://127.0.0.1:8770] [--wait SEKUNDER]
    python -m emneklar.manage stop [--timeout SEKUNDER]

Exit code 0 means success, 1 means failure. The control secret from ``run/instance.json`` and one-time
login links are never printed.

The helpers in this module (instance file, health check, shutdown, SQLite backup, process watching) use
only the standard library at import time: ``scripts/update.py`` and ``scripts/setup.py`` import them
before the dependencies are installed and before program files are replaced.
"""

from __future__ import annotations

import argparse
import http.client
import json
import logging
import logging.handlers
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Any, NoReturn
from urllib.parse import urlsplit

from emneklar import APP_NAME, __version__
from emneklar.config import ConfigError, RuntimeConfig, default_data_dir

log = logging.getLogger("emneklar.manage")

INSTANCE_FILE = "instance.json"
CONTROL_HEADER = "X-EmneKlar-Control"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


# -- locations ----------------------------------------------------------------------------------


def data_dir_from_env() -> Path:
    """The data folder exactly as ``RuntimeConfig.from_env()`` resolves it (``EMNEKLAR_DATA_DIR`` or default)."""
    raw = os.environ.get("EMNEKLAR_DATA_DIR")
    return Path(raw) if raw else default_data_dir()


# -- the running instance (run/instance.json + /api/health + /control/*) ------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The local server never redirects these endpoints; never follow (and never forward the secret)."""

    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str,
                         headers: http.client.HTTPMessage, newurl: str) -> None:
        return None


# No proxies: a proxy configured for the internet must never see requests (or the control secret) meant
# for 127.0.0.1.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def check_local_origin(origin: str) -> str:
    """Return ``http://<loopback>:<port>`` normalised, or raise ValueError for anything else."""
    parts = urlsplit(origin.strip())
    try:
        port = parts.port
    except ValueError:
        port = None
    if (parts.scheme != "http" or parts.hostname not in LOOPBACK_HOSTS or port is None or parts.username
            or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError(f"{origin!r} er ikke en lokal EmneKlar-adresse (http://127.0.0.1:<port>).")
    host = f"[{parts.hostname}]" if parts.hostname == "::1" else parts.hostname
    return f"http://{host}:{port}"


def read_instance(run_dir: Path) -> dict[str, Any] | None:
    """Contents of ``run/instance.json`` if present and pointing at a loopback origin."""
    try:
        info = json.loads((run_dir / INSTANCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    try:
        info["origin"] = check_local_origin(str(info.get("origin", "")))
    except ValueError:
        return None
    return info


def _local_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
                timeout: float = 2.0) -> Any:
    # Callers pass URLs built from check_local_origin(): always http://<loopback>:<port>/...
    request = urllib.request.Request(  # noqa: S310
        url, method=method, headers={"Accept": "application/json", **(headers or {})},
        data=b"" if method == "POST" else None)
    with _LOCAL_OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read(65536).decode("utf-8"))


def fetch_health(origin: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """The ``/api/health`` payload if EmneKlar answers on ``origin``, else None."""
    try:
        data = _local_json(f"{check_local_origin(origin)}/api/health", timeout=timeout)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return data if isinstance(data, dict) and data.get("app") == APP_NAME else None


def running_instance(run_dir: Path, timeout: float = 2.0) -> dict[str, Any] | None:
    """Instance info (incl. the control secret – never print it) if EmneKlar answers, else None."""
    info = read_instance(run_dir)
    if info is None:
        return None
    health = fetch_health(info["origin"], timeout=timeout)
    if health is None:
        return None
    return {**info, "version": health.get("version", info.get("version"))}


def request_launch_url(info: dict[str, Any], timeout: float = 5.0) -> str | None:
    """A fresh one-time login link from the running instance (local control channel), or None."""
    secret = info.get("control_secret")
    if not isinstance(secret, str) or not secret:
        return None
    try:
        origin = check_local_origin(str(info.get("origin", "")))
        data = _local_json(f"{origin}/control/launch-url", method="POST", headers={CONTROL_HEADER: secret},
                           timeout=timeout)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    url = data.get("url") if isinstance(data, dict) else None
    # Only ever open a link to the local instance itself.
    return url if isinstance(url, str) and url.startswith(f"{origin}/auth/launch?") else None


def request_shutdown(info: dict[str, Any], timeout: float = 5.0) -> bool:
    """Ask the instance to shut down via the local control channel. True if it accepted."""
    secret = info.get("control_secret")
    if not isinstance(secret, str) or not secret:
        return False
    try:
        data = _local_json(f"{check_local_origin(str(info.get('origin', '')))}/control/shutdown", method="POST",
                           headers={CONTROL_HEADER: secret}, timeout=timeout)
    except (OSError, ValueError, http.client.HTTPException):
        return False
    return isinstance(data, dict) and data.get("ok") is True


# -- waiting for a process ----------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _SYNCHRONIZE = 0x00100000
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ERROR_INVALID_PARAMETER = 87
    _WAIT_OBJECT_0 = 0
    _WAIT_TIMEOUT = 0x102
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class ProcessWatcher:
    """Waits for one specific process to exit.

    On Windows a process handle is opened right away, so a PID that is reused after the process exited
    cannot be mistaken for it. ``wait()``/``exited()`` return None when the state cannot be determined.
    """

    def __init__(self, pid: object) -> None:
        self.pid = pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None
        self._handle: int | None = None
        self._gone = False
        if self.pid is not None and sys.platform == "win32":
            handle = _kernel32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
            if handle:
                self._handle = handle
            elif ctypes.get_last_error() == _ERROR_INVALID_PARAMETER:
                self._gone = True  # no such process

    def __enter__(self) -> ProcessWatcher:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None and sys.platform == "win32":
            _kernel32.CloseHandle(self._handle)
        self._handle = None

    def exited(self) -> bool | None:
        return self.wait(0)

    def wait(self, timeout: float) -> bool | None:
        if self._gone:
            return True
        if self.pid is None:
            return None
        if sys.platform == "win32":
            if self._handle is None:
                return None
            result = _kernel32.WaitForSingleObject(self._handle, max(0, int(timeout * 1000)))
            if result == _WAIT_OBJECT_0:
                return True
            return False if result == _WAIT_TIMEOUT else None
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                pass  # exists, owned by someone else
            except OSError:
                return None
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)


def process_alive(pid: object) -> bool | None:
    """True/False if the state of ``pid`` is known, None otherwise."""
    with ProcessWatcher(pid) as watcher:
        exited = watcher.exited()
    return None if exited is None else not exited


def wait_until_stopped(origin: str, watcher: ProcessWatcher, timeout: float) -> bool:
    """Wait until the process has exited (or, if that cannot be observed, until the server stops answering)."""
    deadline = time.monotonic() + timeout
    result = watcher.wait(timeout)
    if result is not None:
        return result
    while time.monotonic() < deadline:
        if fetch_health(origin, timeout=1.0) is None:
            # The server stopped listening; give the process a moment to finish shutting down.
            time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
            return True
        time.sleep(0.25)
    return False


def stop_instance(run_dir: Path, timeout: float = 30.0) -> str:
    """Stop the running instance. Returns ``not_running``, ``stopped``, ``refused`` or ``timeout``."""
    info = running_instance(run_dir)
    if info is None:
        return "not_running"
    with ProcessWatcher(info.get("pid")) as watcher:
        if not request_shutdown(info):
            return "refused"
        return "stopped" if wait_until_stopped(info["origin"], watcher, timeout) else "timeout"


# -- SQLite --------------------------------------------------------------------------------------


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def backup_sqlite(source: Path, target: Path) -> Path:
    """Consistent copy of a (possibly live) SQLite database via the online backup API, verified with quick_check.

    The copy is written next to ``target`` first and renamed into place, so ``target`` is either complete or absent.
    """
    if not source.is_file():
        raise FileNotFoundError(str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    src = sqlite3.connect(str(source), timeout=30)
    try:
        dest = sqlite3.connect(str(partial))
        try:
            src.backup(dest)
            row = dest.execute("PRAGMA quick_check").fetchone()
            if row is None or row[0] != "ok":
                raise sqlite3.DatabaseError(f"Kopien besto ikke integritetskontrollen: {row[0] if row else 'ukjent'}")
        finally:
            dest.close()
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        src.close()
    os.replace(partial, target)
    return target


# -- command line -------------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"Feil: {message}\n")


def _fail(message: str) -> int:
    print(message, file=sys.stderr, flush=True)
    return 1


def _config() -> RuntimeConfig:
    return RuntimeConfig.from_env()


class _FileLogging:
    """Log this command to the app's log file (redacted JSON lines, like the app) without printing log lines."""

    # emneklar.* logs the migration and the backup it took; alembic only contributes warnings and errors.
    LEVELS = {"emneklar": logging.INFO, "alembic": logging.WARNING}

    def __init__(self, logs_dir: Path) -> None:
        self.handler: logging.Handler | None = None
        self.previous = {name: logging.getLogger(name).level for name in self.LEVELS}
        from emneklar.core.logging_setup import JsonFormatter
        from emneklar.core.security.redaction import RedactingFilter

        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(logs_dir / "emneklar.log", maxBytes=2_000_000,
                                                           backupCount=5, encoding="utf-8")
        except OSError:
            return  # logging is a convenience here; the command itself must still run
        handler.setFormatter(JsonFormatter())
        handler.addFilter(RedactingFilter())
        for name, level in self.LEVELS.items():
            logging.getLogger(name).addHandler(handler)
            logging.getLogger(name).setLevel(level)
        self.handler = handler

    def close(self) -> None:
        if self.handler is None:
            return
        for name, level in self.previous.items():
            logging.getLogger(name).removeHandler(self.handler)
            logging.getLogger(name).setLevel(level)
        self.handler.close()
        self.handler = None


def cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_migrate(_args: argparse.Namespace) -> int:
    try:
        config = _config()
    except ConfigError as exc:
        return _fail(f"Feil i oppsettet: {exc}")
    if running_instance(config.run_dir) is not None:
        return _fail("EmneKlar kjører. Avslutt EmneKlar før databasen oppdateres "
                     "(lukk EmneKlar-vinduet eller kjør «python -m emneklar.manage stop»).")
    from emneklar.core.storage.db import ForeignDatabaseError, database_owner

    if database_owner(config.db_path) == "foreign":
        return _fail(str(ForeignDatabaseError(config.db_path)))
    config.ensure_dirs()
    file_logging = _FileLogging(config.logs_dir)
    try:
        from emneklar.core.security.redaction import redact
        from emneklar.core.storage.db import Database

        db = Database(config.db_path)
        try:
            result = db.migrate(config.backups_dir)
        except Exception as exc:  # any migration failure is reported with exit code 1
            log.exception("Oppdatering av databasen feilet")
            return _fail(f"Oppdateringen av databasen feilet: {type(exc).__name__}: {redact(str(exc))[:500]}")
        finally:
            db.dispose()
    finally:
        file_logging.close()
    if result.previous == result.current:
        print(f"Databasen er allerede oppdatert (revisjon {result.current}).")
    else:
        print(f"Databasen er oppdatert fra revisjon {result.previous or 'tom database'} til {result.current}.")
        if result.backup_path is not None:
            print(f"Sikkerhetskopi fra før oppdateringen: {result.backup_path}")
    return 0


def cmd_backup_db(args: argparse.Namespace) -> int:
    try:
        config = _config()
    except ConfigError as exc:
        return _fail(f"Feil i oppsettet: {exc}")
    source = config.db_path
    if not source.is_file():
        return _fail(f"Fant ingen database å sikkerhetskopiere ({source}).")
    target = Path(args.dest).expanduser()
    if target.is_dir():
        target = target / f"emneklar-database-{utc_stamp()}.db"
    target = target.resolve()
    if target == source.resolve():
        return _fail("Sikkerhetskopien kan ikke skrives over selve databasen.")
    if target.exists():
        return _fail(f"Filen finnes allerede: {target}. Velg et annet filnavn.")
    try:
        backup_sqlite(source, target)
    except (OSError, sqlite3.Error) as exc:
        return _fail(f"Sikkerhetskopieringen feilet: {exc}")
    print(f"Sikkerhetskopi av databasen er lagret i {target}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    fixed_origin: str | None = None
    run_dir: Path | None = None
    if args.origin:
        try:
            fixed_origin = check_local_origin(args.origin)
        except ValueError as exc:
            return _fail(str(exc))
    else:
        run_dir = data_dir_from_env() / "run"
    deadline = time.monotonic() + max(0.0, args.wait)
    origin = fixed_origin
    while True:
        if run_dir is not None:
            info = read_instance(run_dir)  # may appear while waiting for a starting instance
            origin = info["origin"] if info else None
        health = fetch_health(origin) if origin else None
        if health is not None:
            print(f"{APP_NAME} {health.get('version', '?')} svarer på {origin}.")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    if origin is None:
        return _fail(f"{APP_NAME} kjører ikke (fant ingen aktiv instans).")
    return _fail(f"{APP_NAME} svarer ikke på {origin}.")


def cmd_stop(args: argparse.Namespace) -> int:
    result = stop_instance(data_dir_from_env() / "run", timeout=args.timeout)
    if result == "not_running":
        print(f"{APP_NAME} kjører ikke – ingenting å stoppe.")
        return 0
    if result == "stopped":
        print(f"{APP_NAME} er avsluttet.")
        return 0
    if result == "refused":
        return _fail(f"{APP_NAME} avviste forespørselen om å avslutte. Lukk {APP_NAME}-vinduet i stedet.")
    return _fail(f"{APP_NAME} avsluttet ikke innen {args.timeout:g} sekunder. Lukk {APP_NAME}-vinduet i stedet.")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m emneklar.manage", description=f"Vedlikehold av {APP_NAME}.")
    commands = parser.add_subparsers(dest="command", metavar="kommando", parser_class=_Parser)
    commands.add_parser("version", help="skriv ut versjonsnummeret").set_defaults(func=cmd_version)
    commands.add_parser("migrate", help="oppdater databasen (tar sikkerhetskopi først)").set_defaults(func=cmd_migrate)
    backup = commands.add_parser("backup-db", help="lag en konsistent kopi av databasen")
    backup.add_argument("dest", help="målfil, eller en mappe (filnavn lages automatisk)")
    backup.set_defaults(func=cmd_backup_db)
    health = commands.add_parser("health", help="sjekk at EmneKlar svarer")
    health.add_argument("--origin", help="adresse, f.eks. http://127.0.0.1:8770 (standard: kjørende instans)")
    health.add_argument("--wait", type=float, default=0.0, metavar="SEKUNDER",
                        help="vent opptil så lenge på at EmneKlar svarer")
    health.set_defaults(func=cmd_health)
    stop = commands.add_parser("stop", help="avslutt den kjørende EmneKlar-instansen")
    stop.add_argument("--timeout", type=float, default=30.0, metavar="SEKUNDER",
                      help="hvor lenge det ventes på at programmet avslutter (standard 30)")
    stop.set_defaults(func=cmd_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # UTF-8 also when redirected (CI logs, pipes); consoles are Unicode anyway
            reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return 1
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
