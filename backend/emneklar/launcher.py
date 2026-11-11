"""Start EmneKlar and show it – in a window of its own – with a one-time login link.

    python -m emneklar.launcher [--port 8770] [--no-browser]

``EMNEKLAR_NO_BROWSER=1`` does the same as ``--no-browser`` (for tests and scripts that start EmneKlar the way
the shortcut or the updater does, where no argument can be added).

* EmneKlar is shown in a window of its own: Edge or Chrome in app mode, without
  address bar or tabs (``core/system.open_user_interface``). Without either of
  them it opens in a tab of the default browser.
* If EmneKlar is already running for this Windows user, a new login link is
  requested from the running instance (local control channel) and a new window
  is opened – no second server is started.
* The server only ever listens on 127.0.0.1.
* Started from the shortcut (``pythonw.exe``) there is no console window: the
  browser window is the whole user interface, and a start-up problem is shown in
  a message box. EmneKlar stops when its last window has been closed
  (``core/presence.py``), or at once with «Avslutt EmneKlar» in the program or in
  the Start menu. Started with ``start.bat`` there is a console window as well:
  closing it (or Ctrl+C) stops EmneKlar too.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import socket
import sys
import threading
import time

import uvicorn

from emneklar import APP_NAME, __version__
from emneklar.config import ConfigError, RuntimeConfig
from emneklar.core.container import AppContainer
from emneklar.core.logging_setup import configure_logging
from emneklar.core.storage.db import ForeignDatabaseError, database_owner
from emneklar.core.storage.legacy import prepare_data_dir
from emneklar.core.system import has_console, open_user_interface, prepare_standard_streams, tell_user
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


def _fail(message: str, code: int) -> int:
    """A start-up problem the user must see – in the console, or in a message box when there is none."""
    tell_user(APP_NAME, message, error=True)
    return code


def _announce(url: str, open_browser: bool) -> None:
    # Shown to the user only (never written to the log file): the link contains a one-time token.
    if has_console():
        print(
            f"\n  {APP_NAME} {__version__} kjører lokalt på denne maskinen.\n"
            "  Åpne denne lenken i nettleseren hvis EmneKlar ikke åpnes av seg selv (gyldig i 5 minutter, kan brukes "
            "én gang):\n"
            f"  {url}\n"
            "  Lukk dette vinduet for å avslutte EmneKlar.\n",
            flush=True,
        )
    if open_browser and not open_user_interface(url) and not has_console():
        tell_user(APP_NAME, f"{APP_NAME} kjører, men nettleseren lot seg ikke åpne. Åpne denne adressen i nettleseren "
                            f"selv (gyldig i 5 minutter, kan brukes én gang):\n\n{url}")


def _wait_and_open(url: str, origin: str, open_browser: bool) -> None:
    for _ in range(150):
        if fetch_health(origin, timeout=1) is not None:
            _announce(url, open_browser)
            return
        time.sleep(0.2)
    # Never open the browser on an address nothing answers on; main() reports why the start failed.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    prepare_standard_streams()
    open_browser = not args.no_browser and os.environ.get("EMNEKLAR_NO_BROWSER", "").strip().lower() not in {
        "1", "true", "yes", "ja", "on"}

    try:
        config = RuntimeConfig.from_env()
        if args.port:
            config = dataclasses.replace(config, port=args.port)
            config.validate()
        # Before anything is created in the data folder: never move into another program's folder.
        if database_owner(config.db_path) == "foreign":
            raise ForeignDatabaseError(config.db_path)
        copied = prepare_data_dir(config)  # data from before the program got its final name: copied once
    except ConfigError as exc:
        return _fail(f"Feil i oppsettet: {exc}", 2)
    config.ensure_dirs()

    existing = running_instance(config.run_dir)
    if existing is not None:
        url = request_launch_url(existing)
        if url:
            print(f"{APP_NAME} kjører allerede. Åpner et nytt vindu …", flush=True)
            if open_browser:
                open_user_interface(url)
            return 0

    configure_logging(config.logs_dir)
    if copied is not None:
        log.info("Dataene fra %s er kopiert til %s (%s). Den gamle mappen er ikke endret.", copied.source,
                 copied.target, ", ".join(copied.entries))
    if not _port_free(config.host, config.port):
        for candidate in range(config.port + 1, config.port + 30):
            if _port_free(config.host, candidate):
                log.warning("Port %s er opptatt – bruker %s", config.port, candidate)
                config = dataclasses.replace(config, port=candidate)
                break
        else:
            return _fail("Fant ingen ledig port. Kjører EmneKlar allerede?", 1)

    log_file = config.logs_dir / "emneklar.log"
    try:
        container = AppContainer(config)
        app = create_app(container)
        server = uvicorn.Server(uvicorn.Config(
            app, host=config.host, port=config.port, log_config=None, access_log=False, proxy_headers=False,
            server_header=False, date_header=False, timeout_graceful_shutdown=5,
        ))
        presence = app.state.presence

        def request_shutdown() -> None:
            presence.stopping.set()  # the windows' connections end at once instead of holding up the stop
            server.should_exit = True

        app.state.request_shutdown = request_shutdown
        if open_browser:  # EmneKlar shows a window itself: closing the last one stops it, like any program
            presence.stop = request_shutdown
        token = config.dev_launch_token or container.sessions.new_launch_token()
        url = f"{config.origin}/auth/launch?token={token}"
        threading.Thread(target=_wait_and_open, args=(url, config.origin, open_browser), daemon=True).start()
        server.run()
    except Exception as exc:
        log.exception("%s kunne ikke starte", APP_NAME)
        return _fail(f"{APP_NAME} kunne ikke starte ({type(exc).__name__}). Detaljene står i loggen:\n{log_file}", 1)
    if not server.started:
        return _fail(f"{APP_NAME} kunne ikke starte. Detaljene står i loggen:\n{log_file}", 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
