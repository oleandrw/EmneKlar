"""Start EmneKlar and open the browser with a one-time login link.

    python -m emneklar.launcher [--port 8765] [--no-browser]

* If EmneKlar is already running for this Windows user, a new login link is
  requested from the running instance (local control channel) and the
  browser is opened – no second server is started.
* The server only ever listens on 127.0.0.1. Closing the console window (or
  Ctrl+C) stops the application.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from emneklar import APP_NAME, __version__
from emneklar.config import ConfigError, RuntimeConfig
from emneklar.core.container import AppContainer
from emneklar.core.logging_setup import configure_logging
from emneklar.main import create_app

log = logging.getLogger("emneklar.launcher")


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 2.0) -> dict:
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed local URL
        return json.loads(response.read().decode("utf-8"))


def running_instance(config: RuntimeConfig) -> dict | None:
    """Return the running instance's info (incl. control secret) if one answers."""
    path: Path = config.run_dir / "instance.json"
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        health = _http_json(f"{info['origin']}/api/health")
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return None
    if health.get("app") != APP_NAME:
        return None
    return info


def request_launch_url(info: dict) -> str | None:
    try:
        data = _http_json(f"{info['origin']}/control/launch-url", method="POST",
                          headers={"X-EmneKlar-Control": info["control_secret"]})
    except (OSError, ValueError, urllib.error.URLError):
        return None
    url = data.get("url")
    return url if isinstance(url, str) else None


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


def _wait_and_open(url: str, health: str, open_browser: bool) -> None:
    for _ in range(150):
        try:
            with urllib.request.urlopen(health, timeout=1) as response:  # noqa: S310 - fixed local URL
                if response.status == 200:
                    break
        except OSError:
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
    except ConfigError as exc:
        print(f"Feil i oppsettet: {exc}", file=sys.stderr)
        return 2
    config.ensure_dirs()

    existing = running_instance(config)
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
    threading.Thread(target=_wait_and_open, args=(url, f"{config.origin}/api/health", not args.no_browser),
                     daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
