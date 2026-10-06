"""Process-level configuration.

This is *not* where user settings or secrets live:

* user settings (Canvas URL, analysis options, AI routing …) are stored in the
  local database and edited in the GUI (see ``core.storage.settings``);
* secrets (Canvas token, AI API keys) live in the OS credential store
  (see ``core.auth.secrets``).

Only what must be known before the app starts is read here, from environment
variables prefixed with ``EMNEKLAR_``. Program code and user data are kept
apart: everything persistent lives under :attr:`RuntimeConfig.data_dir`
(``%LOCALAPPDATA%\\EmneKlar-Claude`` on Windows), so replacing or updating the
program folder never touches user data.

Why not ``%LOCALAPPDATA%\\EmneKlar`` and port 8765: another, independent
implementation of the same specification uses exactly that folder (with the
same file and folder names) and that port. The two programs must never share
files, and both must be able to run at the same time.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8770
DATA_FOLDER = "EmneKlar-Claude"
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class ConfigError(RuntimeError):
    """Raised when the process configuration is unsafe or invalid."""


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / DATA_FOLDER
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / DATA_FOLDER
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / DATA_FOLDER.lower()


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass(frozen=True)
class RuntimeConfig:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    data_dir: Path = field(default_factory=default_data_dir)
    frontend_dist: Path | None = REPO_DIR / "frontend" / "dist"
    dev_mode: bool = False
    # "keyring" in normal use; "memory" for tests and throw-away sessions.
    secret_backend: str = "keyring"
    # Document parsing runs in separate worker processes by default.
    parser_isolation: bool = True
    # Dev/test only: a fixed launch token so the Vite dev server and Playwright can log in.
    dev_launch_token: str | None = None
    # Dev only: extra allowed origins (the Vite dev server).
    dev_origins: tuple[str, ...] = ()
    # Dev/test only: allow a Canvas base URL on http://127.0.0.1 (the fake Canvas used in E2E tests).
    allow_insecure_canvas: bool = False

    # -- persistent locations (all under data_dir) --------------------------------

    @property
    def db_path(self) -> Path:
        return self.data_dir / "database.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def run_dir(self) -> Path:
        """Files describing the running instance (port, control secret) for start/update scripts."""
        return self.data_dir / "run"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.backups_dir, self.reports_dir, self.logs_dir, self.cache_dir,
                     self.tmp_dir, self.run_dir):
            path.mkdir(parents=True, exist_ok=True)

    # -- network -------------------------------------------------------------------

    @property
    def origin(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    def allowed_hosts(self) -> set[str]:
        """Host header values accepted by the DNS-rebinding guard."""
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        if self.dev_mode:
            for origin in self.dev_origins:
                hosts.add(origin.split("://", 1)[-1])
        return hosts

    def allowed_origins(self) -> set[str]:
        origins = {f"http://{h}" for h in self.allowed_hosts()}
        if self.dev_mode:
            origins.update(self.dev_origins)
        return origins

    def validate(self) -> None:
        if not is_loopback_host(self.host):
            raise ConfigError(
                f"EmneKlar kan bare lytte på 127.0.0.1/localhost, ikke {self.host!r}. "
                "Programmet er laget for lokal bruk og skal ikke eksponeres mot nettverket."
            )
        if not (1024 <= self.port <= 65535):
            raise ConfigError(f"Ugyldig port: {self.port}")
        if self.secret_backend not in {"keyring", "memory"}:
            raise ConfigError(f"Ukjent lagring for hemmeligheter: {self.secret_backend!r}")

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        dev_mode = _env_bool("EMNEKLAR_DEV")
        data_dir_env = os.environ.get("EMNEKLAR_DATA_DIR")
        dist_env = os.environ.get("EMNEKLAR_FRONTEND_DIST")
        dev_origins = tuple(
            o.strip().rstrip("/")
            for o in os.environ.get("EMNEKLAR_DEV_ORIGINS", "http://127.0.0.1:5173").split(",")
            if o.strip()
        )
        config = cls(
            host=os.environ.get("EMNEKLAR_HOST", "127.0.0.1"),
            port=int(os.environ.get("EMNEKLAR_PORT", DEFAULT_PORT)),
            data_dir=Path(data_dir_env) if data_dir_env else default_data_dir(),
            frontend_dist=Path(dist_env) if dist_env else REPO_DIR / "frontend" / "dist",
            dev_mode=dev_mode,
            secret_backend=os.environ.get("EMNEKLAR_SECRET_BACKEND", "keyring"),
            parser_isolation=_env_bool("EMNEKLAR_PARSER_ISOLATION", True),
            dev_launch_token=os.environ.get("EMNEKLAR_DEV_LAUNCH_TOKEN") if dev_mode else None,
            dev_origins=dev_origins if dev_mode else (),
            allow_insecure_canvas=dev_mode and _env_bool("EMNEKLAR_ALLOW_INSECURE_CANVAS"),
        )
        config.validate()
        return config
