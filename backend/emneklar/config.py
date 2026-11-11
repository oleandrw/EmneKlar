"""Process-level configuration.

This is *not* where user settings or secrets live:

* user settings (Canvas URL, analysis options, AI routing …) are stored in the
  local database and edited in the GUI (see ``core.storage.settings``);
* secrets (Canvas token, AI API keys) live in the OS credential store
  (see ``core.auth.secrets``).

Only what must be known before the app starts is read here, from environment
variables prefixed with ``EMNEKLAR_``. Program code and user data are kept
apart: everything persistent lives under :attr:`RuntimeConfig.data_dir`
(``%LOCALAPPDATA%\\EmneKlar`` on Windows), so replacing or updating the
program folder never touches user data.

Names: the program, its data folder and its credential-store service are all
called «EmneKlar» (decided before the first public release). Earlier versions
used «EmneKlar-Claude»; ``core/storage/legacy.py`` copies that data once.
Another, independent implementation of the same specification also uses
``%LOCALAPPDATA%\\EmneKlar`` (and port 8765). EmneKlar never opens a database
that is not its own (``core/storage/db.py``), so on a machine where that
program has data, EmneKlar refuses to start instead of touching it – and it
keeps its own port (8770) and a session cookie per port.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from emneklar.core.system import user_data_dir

DEFAULT_PORT = 8770
DATA_FOLDER = "EmneKlar"
#: The data folder of versions before the first public release (copied once, see core/storage/legacy.py).
LEGACY_DATA_FOLDER = "EmneKlar-Claude"
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class ConfigError(RuntimeError):
    """Raised when the process configuration is unsafe or invalid."""


#: Defaults for this one installation, in a file in the program folder that is never part of a release. The test
#: build of the installer writes it, so that «EmneKlar (test)» has its own data folder, port and credential-store
#: service whatever starts it (the shortcut, start.bat, update.bat, setup.bat) – it can never open the user's real
#: data, or replace the real Canvas token, by accident.
#: ``{"data_dir": "<absolute path>", "port": 8791, "keyring_service": "EmneKlar-test"}``. Environment variables
#: (EMNEKLAR_DATA_DIR, EMNEKLAR_PORT) win; the service name is read in core/auth/secrets.py.
LOCAL_FILE = "emneklar.local.json"


def installation_defaults() -> dict[str, Any]:
    try:
        data = json.loads((REPO_DIR / LOCAL_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def standard_data_dir() -> Path:
    """Where an ordinary installation keeps the user's data."""
    return user_data_dir(DATA_FOLDER)


def default_data_dir() -> Path:
    """The data folder when EMNEKLAR_DATA_DIR is not set: this installation's own (see LOCAL_FILE), else the standard."""
    local = installation_defaults().get("data_dir")
    if isinstance(local, str) and local.strip() and Path(local).is_absolute():
        return Path(local)
    return standard_data_dir()


def default_port() -> int:
    port = installation_defaults().get("port")
    return port if isinstance(port, int) and not isinstance(port, bool) and 1024 <= port <= 65535 else DEFAULT_PORT


def uses_standard_data_dir() -> bool:
    """True when the data folder is the standard one: not chosen with EMNEKLAR_DATA_DIR and not set for this
    installation. Only then is the data from the earlier folder name copied (core/storage/legacy.py)."""
    return not os.environ.get("EMNEKLAR_DATA_DIR") and default_data_dir() == standard_data_dir()


def legacy_data_dir() -> Path:
    return user_data_dir(LEGACY_DATA_FOLDER)


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
    def rag_dir(self) -> Path:
        """Emne-RAG: one search index file per course (derived data that can be rebuilt)."""
        return self.data_dir / "rag"

    @property
    def illustrations_dir(self) -> Path:
        """KI-bildeassistent: generated images (``<course>/<asset>.<ext>``), never stored in the database."""
        return self.data_dir / "illustrations"

    @property
    def models_dir(self) -> Path:
        """Downloaded local models (embedding, reranker, speech-to-text). Never shared with other programs."""
        return self.data_dir / "models"

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
            port=int(os.environ.get("EMNEKLAR_PORT") or default_port()),
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
