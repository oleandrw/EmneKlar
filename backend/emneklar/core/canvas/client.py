"""Low-level Canvas REST API client.

Follows the official Canvas REST API documentation:

* token auth with ``Authorization: Bearer <token>`` – sent only to the
  configured Canvas origin, never to redirects or pagination links on other
  hosts;
* ``Accept: application/json+canvas-string-ids`` so ids are strings (Canvas
  ids can exceed 2^53 on sharded instances);
* pagination via the ``Link`` header (``rel="next"``), ``per_page=100``;
* throttling: Canvas answers ``403 Forbidden (Rate Limit Exceeded)`` (or 429)
  and exposes ``X-Rate-Limit-Remaining`` – we back off with jitter and slow
  down pro-actively when the bucket runs low;
* bounded concurrency (a semaphore) so one analysis never floods Canvas.

**Write guard.** Every mutating request (POST/PUT/PATCH/DELETE) requires a
:class:`WritePermit`, which only the shared change engine issues, and is
refused while Dry run is active. Features therefore cannot write to Canvas
except through preview → change set → backup → log.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from emneklar import __version__
from emneklar.core.errors import AppError

log = logging.getLogger(__name__)

_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')
USER_AGENT = f"EmneKlar/{__version__} (lokal kvalitetssikring av Canvas-emner)"
MAX_PAGES = 500
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class CanvasError(AppError):
    pass


class DryRunBlocked(AppError):
    def __init__(self) -> None:
        super().__init__("dry_run_active", status=409)


@dataclass(frozen=True)
class WritePermit:
    """Proof that a write was issued by the change engine for a specific change."""

    change_id: int | None
    reason: str


def validate_base_url(base_url: str, *, allow_http: bool = False) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    if base_url and "://" not in base_url:
        base_url = "https://" + base_url
    parts = urlsplit(base_url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise CanvasError("canvas_url_invalid", detail=base_url[:200])
    if parts.scheme == "http" and not allow_http:
        raise CanvasError("canvas_url_invalid", detail="Canvas må brukes over https")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise CanvasError("canvas_url_invalid", detail="Adressen kan ikke inneholde brukernavn, spørring eller fragment")
    if parts.path not in {"", "/"}:
        raise CanvasError("canvas_url_invalid", detail="Bruk bare adressen til Canvas, uten sti")
    return f"{parts.scheme}://{parts.netloc}".lower()


def _origin(url: str) -> tuple[str, str, int | None]:
    p = urlsplit(url)
    port = p.port or (443 if p.scheme == "https" else 80 if p.scheme == "http" else None)
    return (p.scheme, (p.hostname or "").lower(), port)


def parse_link_header(value: str | None) -> dict[str, str]:
    links: dict[str, str] = {}
    for url, rel in _LINK_RE.findall(value or ""):
        for r in rel.split():
            links[r] = url
    return links


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], str | None],
        *,
        http: httpx.AsyncClient | None = None,
        max_retries: int = 4,
        timeout: float = 30.0,
        allow_http: bool = False,
        max_concurrency: int = 4,
        dry_run: Callable[[], bool] = lambda: False,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.base_url = validate_base_url(base_url, allow_http=allow_http)
        self._origin = _origin(self.base_url)
        self._token_provider = token_provider
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=False,  # handled explicitly so the token never leaks to another host
            trust_env=False,
            headers={"User-Agent": USER_AGENT},
        )
        self._owns_http = http is None
        self._max_retries = max_retries
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._dry_run = dry_run
        self.request_count = 0

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # -- helpers -------------------------------------------------------------------

    def is_canvas_origin(self, url: str) -> bool:
        return _origin(url) == self._origin

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            url = path_or_url
        else:
            url = urljoin(self.base_url + "/", path_or_url.lstrip("/"))
        if not self.is_canvas_origin(url):
            raise CanvasError("canvas_error", detail="Avviste forespørsel til en annen vert enn Canvas")
        return url

    def _auth_headers(self) -> dict[str, str]:
        token = self._token_provider()
        if not token:
            raise CanvasError("canvas_token_missing", status=400)
        # Canvas rejects requests without a User-Agent (403 since 2026-06-20).
        return {"Authorization": f"Bearer {token}", "Accept": "application/json+canvas-string-ids",
                "User-Agent": USER_AGENT}

    @staticmethod
    def is_rate_limited(response: httpx.Response) -> bool:
        if response.status_code == 429:
            return True
        if response.status_code == 403:
            return "rate limit exceeded" in response.text[:500].lower()
        return False

    @staticmethod
    def raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        snippet = response.text[:300]
        if status == 401:
            raise CanvasError("canvas_token_invalid", status=401, detail=f"HTTP 401: {snippet}")
        if status == 403:
            raise CanvasError("canvas_forbidden", status=403, detail=f"HTTP 403: {snippet}")
        if status == 404:
            raise CanvasError("canvas_not_found", status=404, detail=f"HTTP 404: {snippet}")
        if status in (408, 502, 503, 504):
            raise CanvasError("canvas_unavailable", status=502, detail=f"HTTP {status}")
        if status == 422 or status == 400:
            raise CanvasError("canvas_error", status=422, detail=f"HTTP {status}: {snippet}")
        raise CanvasError("canvas_error", status=502, detail=f"HTTP {status}: {snippet}")

    async def _backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        delay = min(30.0, 0.8 * (2**attempt)) + random.uniform(0, 0.5)  # noqa: S311 - jitter, not crypto
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.replace(".", "", 1).isdigit():
                delay = max(delay, min(60.0, float(retry_after)))
        await self._sleep(delay)

    async def _throttle(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-Rate-Limit-Remaining")
        if remaining is None:
            return
        try:
            value = float(remaining)
        except ValueError:
            return
        if value < 150:
            # Be polite when the leaky bucket is nearly empty: the lower, the longer.
            await self._sleep(min(3.0, (150 - value) / 50))

    # -- core request --------------------------------------------------------------

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: Mapping[str, Any] | list[tuple[str, Any]] | None = None,
        json: Any = None,
        permit: WritePermit | None = None,
    ) -> httpx.Response:
        method = method.upper()
        if method in MUTATING:
            if permit is None:
                raise CanvasError("canvas_write_blocked", status=500, detail=f"{method} {path_or_url}")
            if self._dry_run():
                raise DryRunBlocked()
        url = self._url(path_or_url)
        # GETs are retried on transient errors. Writes are retried only when Canvas
        # explicitly refused them for rate limiting (then nothing was processed).
        retries = self._max_retries if method == "GET" else 0
        attempt = 0
        rate_attempts = 0
        while True:
            try:
                async with self._semaphore:
                    self.request_count += 1
                    response = await self._http.request(method, url, params=params, json=json,
                                                        headers=self._auth_headers())
            except httpx.TimeoutException as exc:
                if attempt < retries:
                    attempt += 1
                    await self._backoff(attempt)
                    continue
                raise CanvasError("canvas_unavailable", status=504, detail="Tidsavbrudd") from exc
            except httpx.TransportError as exc:
                if attempt < retries:
                    attempt += 1
                    await self._backoff(attempt)
                    continue
                raise CanvasError("canvas_unavailable", status=502, detail=type(exc).__name__) from exc

            if self.is_rate_limited(response):
                if rate_attempts < max(self._max_retries, 3):
                    rate_attempts += 1
                    log.info("Canvas rate limit – venter før nytt forsøk (%s)", rate_attempts)
                    await self._backoff(rate_attempts + 1, response)
                    continue
                raise CanvasError("canvas_rate_limited", status=429)
            if response.status_code >= 500 and attempt < retries:
                attempt += 1
                await self._backoff(attempt, response)
                continue
            await self._throttle(response)
            self.raise_for_status(response)
            return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise CanvasError("canvas_error", status=502, detail="Ugyldig JSON fra Canvas") from exc

    async def get_json(self, path: str, params: Mapping[str, Any] | list[tuple[str, Any]] | None = None) -> Any:
        return self._json(await self.request("GET", path, params=params))

    async def write_json(self, method: str, path: str, *, permit: WritePermit, json: Any = None,
                         params: Mapping[str, Any] | list[tuple[str, Any]] | None = None) -> Any:
        return self._json(await self.request(method, path, json=json, params=params, permit=permit))

    async def get_paginated(
        self,
        path: str,
        params: list[tuple[str, Any]] | None = None,
        *,
        max_items: int = 20_000,
    ) -> list[Any]:
        params = list(params or [])
        if not any(k == "per_page" for k, _ in params):
            params.append(("per_page", 100))
        items: list[Any] = []
        url: str | None = path
        first = True
        pages = 0
        visited: set[str] = set()
        while url and pages < MAX_PAGES:
            if url in visited:
                break  # a server repeating the same "next" link must not make us loop forever
            visited.add(url)
            response = await self.request("GET", url, params=params if first else None)
            first = False
            pages += 1
            payload = self._json(response)
            if not isinstance(payload, list):
                raise CanvasError("canvas_error", status=502, detail="Forventet en liste fra Canvas")
            items.extend(payload)
            if len(items) >= max_items:
                return items[:max_items]
            next_url = parse_link_header(response.headers.get("Link")).get("next")
            if next_url and not self.is_canvas_origin(next_url):
                raise CanvasError("canvas_error", detail="Pagineringslenke pekte til en annen vert")
            url = next_url
        return items

    async def upload_to(self, upload_url: str, upload_params: Mapping[str, Any], *, file_field: str, filename: str,
                        data: bytes, content_type: str, permit: WritePermit) -> tuple[int, str | None, Any]:
        """Step 2 of a Canvas file upload: multipart POST to the ``upload_url`` Canvas handed out.

        Follows the File Uploads documentation: the access token is NOT sent (the signed ``upload_params`` authorise
        the request), the parameters are sent unchanged, the file is the *last* part, and redirects are not followed
        here – the caller confirms the upload against the Canvas origin. Returns (status, Location, JSON or None).
        """
        if permit is None:  # pragma: no cover - typed, but keep the guard explicit
            raise CanvasError("canvas_write_blocked", status=500, detail="upload")
        if self._dry_run():
            raise DryRunBlocked()
        parts = urlsplit(upload_url)
        on_canvas = self.is_canvas_origin(upload_url)
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
            raise CanvasError("canvas_error", detail="Ugyldig opplastingsadresse fra Canvas")
        if parts.scheme == "http" and not on_canvas:
            raise CanvasError("canvas_error", detail="Opplasting over ukryptert http avvist")
        form = {str(k): str(v) for k, v in upload_params.items()}  # a dict: httpx treats other data as raw content
        try:
            async with self._semaphore:
                self.request_count += 1
                response = await self._http.post(upload_url, data=form, files=[(file_field, (filename, data,
                                                                                               content_type))],
                                                 headers={"User-Agent": USER_AGENT})
        except httpx.TimeoutException as exc:
            raise CanvasError("canvas_unavailable", status=504, detail="Tidsavbrudd ved opplasting") from exc
        except httpx.TransportError as exc:
            raise CanvasError("canvas_unavailable", status=502, detail=type(exc).__name__) from exc
        if response.status_code >= 400:
            self.raise_for_status(response)
        body: Any = None
        if response.content and "json" in response.headers.get("Content-Type", ""):
            try:
                body = response.json()
            except ValueError:
                body = None
        location = response.headers.get("Location")
        return response.status_code, urljoin(upload_url, location) if location else None, body

    async def fetch_bytes(self, url: str, *, max_bytes: int) -> tuple[bytes, str | None]:
        """Small authenticated download into memory (e.g. images for previews)."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob"
            _, content_type = await self.download(url, path, max_bytes=max_bytes)
            return path.read_bytes(), content_type

    async def download(self, url: str, dest: Path, *, max_bytes: int, max_redirects: int = 5) -> tuple[int, str | None]:
        """Stream a Canvas file to ``dest``.

        Canvas file URLs redirect to a storage host with a signed URL. The token
        is attached only while the URL is on the Canvas origin.
        """
        current = url
        for _ in range(max_redirects + 1):
            parts = urlsplit(current)
            if parts.scheme not in {"https", "http"}:
                raise CanvasError("canvas_error", detail="Ugyldig nedlastingsadresse")
            on_canvas = self.is_canvas_origin(current)
            if parts.scheme == "http" and not on_canvas:
                raise CanvasError("canvas_error", detail="Nedlasting over ukryptert http avvist")
            headers = self._auth_headers() if on_canvas else {"User-Agent": USER_AGENT}
            headers.pop("Accept", None)
            try:
                async with self._semaphore, self._http.stream("GET", current, headers=headers) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise CanvasError("canvas_error", detail="Omdirigering uten adresse")
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        await response.aread()  # error bodies are small; needed for the error message
                    self.raise_for_status(response)
                    declared = response.headers.get("Content-Length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise AppError("file_too_large", status=413, detail=f"{declared} bytes")
                    size = 0
                    with dest.open("wb") as fh:
                        async for chunk in response.aiter_bytes(65536):
                            size += len(chunk)
                            if size > max_bytes:
                                raise AppError("file_too_large", status=413, detail=f">{max_bytes} bytes")
                            fh.write(chunk)
                    return size, response.headers.get("Content-Type")
            except httpx.TimeoutException as exc:
                raise CanvasError("canvas_unavailable", status=504, detail="Tidsavbrudd ved nedlasting") from exc
            except httpx.TransportError as exc:
                raise CanvasError("canvas_unavailable", status=502, detail=type(exc).__name__) from exc
        raise CanvasError("canvas_error", detail="For mange omdirigeringer")
