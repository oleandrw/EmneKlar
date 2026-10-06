"""HTTP client for untrusted URLs: SSRF-safe network backend.

* addresses are validated at connect time and the socket connects to the
  validated IP (DNS rebinding cannot bypass the check);
* no proxies from the environment, no cookies, no credentials – the Canvas
  token or AI keys can never be sent to a URL found in course content;
* redirects are NOT followed by the client – callers follow them manually and
  validate every hop with :func:`emneklar.core.security.ssrf.validate_url`.
"""

from __future__ import annotations

import ssl
from typing import Any

import certifi
import httpcore
import httpx

from emneklar import __version__
from emneklar.core.security.ssrf import UrlBlocked, resolve_public

USER_AGENT = f"EmneKlar/{__version__} (lenkesjekk for Canvas-emne; ingen JavaScript)"


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolves, validates and connects to the validated IP address only."""

    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await resolve_public(host, port)
        last: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as exc:
                last = exc
        raise httpcore.ConnectError(str(last) if last else "connect failed")

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise UrlBlocked("url_blocked", "Unix-sockets er ikke tillatt.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def build_guarded_client(timeout: float, *, max_connections: int = 8) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(retries=0)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    # Replace the connection pool with one that uses the guarded backend.
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl_context,
        max_connections=max_connections,
        network_backend=GuardedNetworkBackend(),
    )
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "nb,nn;q=0.9,en;q=0.7",
        },
    )
