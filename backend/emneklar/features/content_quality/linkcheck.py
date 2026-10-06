"""External link checker with honest states.

States: WORKING, REDIRECT, DEAD, TIMEOUT, AUTH_REQUIRED, UNKNOWN.

* 403 and timeouts are never reported as DEAD (sites block bots; servers are slow).
* DEAD is reserved for 404/410 and non-existent domains.
* Every URL and every redirect hop goes through the SSRF guard; localhost,
  private and link-local addresses, cloud metadata and file: URLs are never
  requested.
* Results are cached locally (link_checks) to avoid hammering sites.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from emneklar.core.security.ssrf import UrlBlocked, validate_url
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import LinkCheck

LinkState = Literal["WORKING", "REDIRECT", "DEAD", "TIMEOUT", "AUTH_REQUIRED", "UNKNOWN"]
REDIRECT_CODES = (301, 302, 303, 307, 308)
LOGIN_HINTS = ("login", "signin", "sign-in", "logon", "/sso", "/auth", "idp.feide.no", "accounts.google.com",
               "login.microsoftonline.com", "shibboleth", "/cas/")


@dataclass
class LinkResult:
    url: str
    state: LinkState
    detail: str
    http_status: int | None = None
    final_url: str | None = None
    permanent_redirect: bool = False
    confidence: str = "high"
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    from_cache: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"url": self.url, "state": self.state, "detail": self.detail, "http_status": self.http_status,
                "final_url": self.final_url, "permanent_redirect": self.permanent_redirect,
                "confidence": self.confidence, "checked_at": self.checked_at.isoformat(), "from_cache": self.from_cache}


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def _looks_like_login(original: str, final: str) -> bool:
    if original == final:
        return False
    target = final.lower()
    return any(h in target for h in LOGIN_HINTS) and not any(h in original.lower() for h in LOGIN_HINTS)


def classify_status(url: str, final: str, status: int, redirected: bool, permanent: bool) -> LinkResult:
    if 200 <= status < 300:
        if _looks_like_login(url, final):
            return LinkResult(url, "AUTH_REQUIRED", "Lenken videresender til en innloggingsside.", status, final)
        if redirected:
            kind = "permanent" if permanent else "midlertidig"
            return LinkResult(url, "REDIRECT", f"Lenken videresendes ({kind}) til {final}.", status, final, permanent)
        return LinkResult(url, "WORKING", "Lenken virker.", status, final)
    if status in (401, 407):
        return LinkResult(url, "AUTH_REQUIRED", f"Nettstedet krever innlogging (HTTP {status}).", status, final)
    if status in (404, 410):
        return LinkResult(url, "DEAD", f"Siden finnes ikke (HTTP {status}).", status, final)
    if status == 403:
        return LinkResult(url, "UNKNOWN", "Nettstedet avviste kontrollen (HTTP 403). Lenken kan kreve innlogging eller "
                          "blokkere automatiske sjekker – den er ikke nødvendigvis død.", status, final, confidence="low")
    if status == 429:
        return LinkResult(url, "UNKNOWN", "Nettstedet ba oss vente (HTTP 429). Prøv igjen senere.", status, final,
                          confidence="low")
    if status >= 500:
        return LinkResult(url, "UNKNOWN", f"Serverfeil hos nettstedet (HTTP {status}). Kan være midlertidig.", status,
                          final, confidence="low")
    return LinkResult(url, "UNKNOWN", f"Uventet svar (HTTP {status}).", status, final, confidence="low")


class LinkChecker:
    def __init__(self, client: httpx.AsyncClient, *, timeout: float = 10.0, per_host: int = 2,
                 max_redirects: int = 5, db: Database | None = None, cache_hours: int = 24) -> None:
        self.client = client
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.db = db
        self.cache_hours = cache_hours
        self._hosts: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(max(1, per_host)))
        self._inflight: dict[str, asyncio.Future[LinkResult]] = {}

    # -- cache ---------------------------------------------------------------------------------

    def _cached(self, url: str) -> LinkResult | None:
        if self.db is None or self.cache_hours <= 0:
            return None
        with self.db.session() as session:
            row = session.get(LinkCheck, url_hash(url))
            if row is None:
                return None
            checked = row.checked_at if row.checked_at.tzinfo else row.checked_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - checked > timedelta(hours=self.cache_hours):
                return None
            return LinkResult(url, row.state, row.detail or "", row.http_status, row.final_url,  # type: ignore[arg-type]
                              checked_at=checked, from_cache=True)

    def _store(self, result: LinkResult) -> None:
        if self.db is None:
            return
        with self.db.session() as session:
            key = url_hash(result.url)
            row = session.get(LinkCheck, key)
            if row is None:
                row = LinkCheck(url_hash=key, url=result.url[:2000], state=result.state)
                session.add(row)
            row.state, row.http_status, row.final_url = result.state, result.http_status, result.final_url
            row.detail, row.checked_at = result.detail, result.checked_at

    # -- checking ------------------------------------------------------------------------------

    async def check(self, url: str, *, use_cache: bool = True) -> LinkResult:
        if use_cache:
            cached = self._cached(url)
            if cached is not None:
                return cached
        if url in self._inflight:
            return await self._inflight[url]
        future: asyncio.Future[LinkResult] = asyncio.get_running_loop().create_future()
        self._inflight[url] = future
        try:
            result = await self._check(url)
            self._store(result)
            future.set_result(result)
            return result
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(url, None)

    async def _check(self, url: str) -> LinkResult:
        try:
            validated = validate_url(url)
        except UrlBlocked as exc:
            return LinkResult(url, "UNKNOWN", f"Ikke kontrollert: {exc.message}", confidence="low")
        async with self._hosts[validated.host]:
            try:
                async with asyncio.timeout(self.timeout * 3):
                    result = await self._follow(url, "HEAD")
                    if result.state in ("DEAD", "UNKNOWN", "AUTH_REQUIRED") and result.http_status not in (None, 410):
                        # Many servers answer HEAD wrongly – confirm with a GET before reporting.
                        result = await self._follow(url, "GET")
                    return result
            except TimeoutError:
                return LinkResult(url, "TIMEOUT", f"Nettstedet svarte ikke innen {int(self.timeout)} sekunder.")

    async def _follow(self, url: str, method: str) -> LinkResult:
        current = url
        redirected = False
        permanent = True
        for _ in range(self.max_redirects + 1):
            try:
                validate_url(current)
                if method == "HEAD":
                    response = await self.client.request("HEAD", current)
                else:
                    async with self.client.stream("GET", current) as stream_response:
                        async for _chunk in stream_response.aiter_bytes(16384):
                            break  # the status line and headers are enough
                        response = stream_response
            except UrlBlocked as exc:
                if exc.code == "url_dns":
                    return LinkResult(url, "DEAD", "Fant ikke domenet (DNS). Hvis mange lenker får denne feilen, kan "
                                      "nettverket ha vært utilgjengelig.", final_url=current, confidence="medium")
                return LinkResult(url, "UNKNOWN", f"Ikke kontrollert: {exc.message}", final_url=current,
                                  confidence="low")
            except httpx.TimeoutException:
                return LinkResult(url, "TIMEOUT", f"Nettstedet svarte ikke innen {int(self.timeout)} sekunder.",
                                  final_url=current)
            except httpx.ConnectError as exc:
                text = str(exc).lower()
                if "certificate" in text or "ssl" in text:
                    return LinkResult(url, "UNKNOWN", "Sertifikatfeil hos nettstedet.", final_url=current,
                                      confidence="low")
                return LinkResult(url, "UNKNOWN", "Fikk ikke kontakt med nettstedet. Det kan være midlertidig nede.",
                                  final_url=current, confidence="low")
            except httpx.HTTPError as exc:
                return LinkResult(url, "UNKNOWN", f"Kunne ikke kontrollere lenken ({type(exc).__name__}).",
                                  final_url=current, confidence="low")
            if response.status_code in REDIRECT_CODES:
                location = response.headers.get("Location")
                if not location:
                    return LinkResult(url, "UNKNOWN", "Videresending uten adresse.", response.status_code, current,
                                      confidence="low")
                redirected = True
                permanent = permanent and response.status_code in (301, 308)
                current = urljoin(current, location)
                continue
            return classify_status(url, current, response.status_code, redirected, permanent)
        return LinkResult(url, "UNKNOWN", "For mange videresendinger.", final_url=current, confidence="low")


def is_checkable(url: str) -> bool:
    scheme = urlsplit(url).scheme.lower()
    return scheme in ("http", "https")
