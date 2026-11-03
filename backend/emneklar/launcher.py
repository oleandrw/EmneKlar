"""Start EmneKlar and open the browser with a one-time login link.

    python -m emneklar.launcher [--port 8770] [--no-browser]

* If EmneKlar is already running for this Windows user, a new login link is
  requested from the running instance (local control channel) and the
  browser is opened – no second server is started.
* The server only ever listens on 127.0.0.1. Closing the console window (or
  Ctrl+C) stops the application.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from emneklar import APP_NAME, __version__
from emneklar.config import ConfigError, RuntimeConfig
from emneklar.core.container import AppContainer
from emneklar.core.logging_setup import configure_logging
from emneklar.core.storage.db import ForeignDatabaseError, database_owner
from emneklar.main import create_app
from emneklar.manage import fetch_health, request_launch_url, running_instance

log = logging.getLogger("emneklar.launcher")


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _announce(url: str, open_browser: bool) -> None:
    # Printed to the console only (never to the log file): the link contains a one-time token.
    print(
        f"\n  {APP_NAME} {__version__} kjører lokalt på denne maskinen.\n"
        "  Åpne denne lenken hvis nettleseren ikke åpnes av seg selv (gyldig i 5 minutter, kan brukes én gang):\n"
        f"  {url}\n"
        "  Lukk dette vinduet for å avslutte EmneKlar.\n",
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)


def _wait_and_open(url: str, origin: str, open_browser: bool) -> None:
    for _ in range(150):
        if fetch_health(origin, timeout=1) is not None:
            break
        time.sleep(0.2)
    _announce(url, open_browser)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = RuntimeConfig.from_env()
        if args.port:
            config = dataclasses.replace(config, port=args.port)
            config.validate()
        # Before anything is created in the data folder: never move into another program's folder.
        if database_owner(config.db_path) == "foreign":
            raise ForeignDatabaseError(config.db_path)
    except ConfigError as exc:
        print(f"Feil i oppsettet: {exc}", file=sys.stderr)
        return 2
    config.ensure_dirs()

    existing = running_instance(config.run_dir)
    if existing is not None:
        url = request_launch_url(existing)
        if url:
            print(f"{APP_NAME} kjører allerede. Åpner nettleseren …", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0

    configure_logging(config.logs_dir)
    if not _port_free(config.host, config.port):
        for candidate in range(config.port + 1, config.port + 30):
            if _port_free(config.host, candidate):
                log.warning("Port %s er opptatt – bruker %s", config.port, candidate)
                config = dataclasses.replace(config, port=candidate)
                break
        else:
            print("Fant ingen ledig port. Kjører EmneKlar allerede i et annet vindu?", file=sys.stderr)
            return 1

    container = AppContainer(config)
    app = create_app(container)
    server = uvicorn.Server(uvicorn.Config(
        app, host=config.host, port=config.port, log_config=None, access_log=False, proxy_headers=False,
        server_header=False, date_header=False, timeout_graceful_shutdown=5,
    ))
    app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    token = config.dev_launch_token or container.sessions.new_launch_token()
    url = f"{config.origin}/auth/launch?token={token}"
    threading.Thread(target=_wait_and_open, args=(url, config.origin, not args.no_browser),
                     daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
