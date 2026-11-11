"""Local web security. "localhost" is not assumed to be safe.

* **DNS rebinding**: the Host header must be 127.0.0.1/localhost:<port>.
* **Session**: the launcher opens the browser with a one-time launch token
  which is exchanged for an HttpOnly, SameSite=Strict session cookie. Other
  web sites and other local users cannot use the API without it. Sessions are
  persisted (hashed) so a bookmark keeps working after a restart. Browsers do
  not separate cookies by port, so the cookie name includes the port: other
  local apps on 127.0.0.1 (or another EmneKlar instance) never overwrite it.
* **CSRF / localhost CSRF**: state-changing requests need an allowed
  ``Origin`` *and* the per-session ``X-CSRF-Token`` header (a custom header
  also forces a CORS preflight, which is never approved).
* **CORS**: no CORS headers are ever sent – cross-origin reads are blocked.
* **Clickjacking/XSS**: strict CSP (no inline scripts, no eval, no external
  hosts), frame-ancestors 'self' and X-Frame-Options SAMEORIGIN (only EmneKlar
  itself may show its pages in a frame – the illustration preview is a page of
  its own shown in a frame), nosniff, no referrer.
* **Control channel**: ``/control/*`` (used by start.bat/update.bat to open a
  new browser session or stop the app) requires the per-instance control
  secret, which only exists in the user's own data folder.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Protocol

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from emneklar.config import RuntimeConfig
from emneklar.core.errors import MESSAGES

SESSION_COOKIE_PREFIX = "emneklar_session"
CSRF_HEADER = "x-csrf-token"
CONTROL_HEADER = "x-emneklar-control"
LAUNCH_TOKEN_TTL = 300  # seconds
SESSION_IDLE_TTL = 30 * 24 * 3600
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_API_PATHS = {"/api/health"}

# Previews of Canvas HTML are rendered in sandboxed srcdoc iframes (no scripts);
# 'self' images allow the authenticated Canvas image proxy. style-src still has
# 'unsafe-inline': a srcdoc frame inherits this policy, and Canvas HTML is styled
# with style attributes (Emnedesign is built on them), as is the report view.
# React's style props are set through the CSSOM and do not need it. Scripts never
# run inline (script-src 'self').
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; media-src 'self'; object-src 'none'; frame-src 'self'; "
    "frame-ancestors 'self'; base-uri 'none'; form-action 'self'; worker-src 'self'; manifest-src 'self'"
)

SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
]


@dataclass
class Session:
    id: str
    csrf: str
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class SessionPersistence(Protocol):
    def load(self) -> list[tuple[str, str, float, float]]: ...

    def save(self, id_hash: str, csrf: str, created: float, last_seen: float) -> None: ...

    def delete(self, id_hash: str) -> None: ...


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def session_cookie_name(port: int) -> str:
    return f"{SESSION_COOKIE_PREFIX}_{port}"


class SessionStore:
    """In-memory sessions keyed by the SHA-256 of the cookie value, optionally persisted."""

    def __init__(self, dev_launch_token: str | None = None, persistence: SessionPersistence | None = None,
                 cookie_name: str = SESSION_COOKIE_PREFIX) -> None:
        self.cookie_name = cookie_name
        self._launch: dict[str, float] = {}
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._dev_token = dev_launch_token
        self._persistence = persistence
        self._last_persist: dict[str, float] = {}
        self._loaded = persistence is None

    def _ensure_loaded(self) -> None:
        """Load persisted sessions on first use (after start-up migrations have run)."""
        if self._loaded or self._persistence is None:
            return
        rows = self._persistence.load()
        now = time.time()
        with self._lock:
            if self._loaded:
                return
            for id_hash, csrf, created, last_seen in rows:
                if now - last_seen <= SESSION_IDLE_TTL:
                    self._sessions.setdefault(
                        id_hash, Session(id=id_hash, csrf=csrf, created=created, last_seen=last_seen))
            self._loaded = True

    def new_launch_token(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = time.time()
            self._launch = {t: exp for t, exp in self._launch.items() if exp > now}
            self._launch[token] = now + LAUNCH_TOKEN_TTL
        return token

    def redeem(self, token: str) -> tuple[str, Session] | None:
        """Exchange a launch token for (cookie value, session)."""
        self._ensure_loaded()
        with self._lock:
            if self._dev_token and token and hmac.compare_digest(token, self._dev_token):
                valid = True  # dev/test mode only: reusable
            else:
                expires = self._launch.pop(token, None)
                valid = expires is not None and expires > time.time()
            if not valid:
                return None
            cookie_value = secrets.token_urlsafe(32)
            id_hash = _hash(cookie_value)
            session = Session(id=id_hash, csrf=secrets.token_urlsafe(32))
            self._sessions[id_hash] = session
        if self._persistence is not None:
            self._persistence.save(id_hash, session.csrf, session.created, session.last_seen)
        return cookie_value, session

    def get(self, cookie_value: str | None) -> Session | None:
        if not cookie_value:
            return None
        self._ensure_loaded()
        id_hash = _hash(cookie_value)
        persist = False
        with self._lock:
            session = self._sessions.get(id_hash)
            if session is None:
                return None
            now = time.time()
            if now - session.last_seen > SESSION_IDLE_TTL:
                self._sessions.pop(id_hash, None)
                expired = True
            else:
                expired = False
                session.last_seen = now
                if now - self._last_persist.get(id_hash, 0) > 3600:
                    self._last_persist[id_hash] = now
                    persist = True
        if expired:
            if self._persistence is not None:
                self._persistence.delete(id_hash)
            return None
        if persist and self._persistence is not None:
            self._persistence.save(id_hash, session.csrf, session.created, session.last_seen)
        return session

    def drop(self, cookie_value: str | None) -> None:
        if not cookie_value:
            return
        id_hash = _hash(cookie_value)
        with self._lock:
            self._sessions.pop(id_hash, None)
        if self._persistence is not None:
            self._persistence.delete(id_hash)


def header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


def session_cookie_from_scope(scope: Scope, name: str) -> str | None:
    raw = header(scope, b"cookie")
    if not raw:
        return None
    cookie: SimpleCookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:  # noqa: BLE001
        return None
    morsel = cookie.get(name)
    return morsel.value if morsel else None


def session_cookie_header(name: str, cookie_value: str) -> tuple[bytes, bytes]:
    value = f"{name}={cookie_value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_IDLE_TTL}"
    return (b"set-cookie", value.encode())


class SecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        config: RuntimeConfig,
        sessions: SessionStore,
        control_secret: Callable[[], str | None],
    ) -> None:
        self.app = app
        self.allowed_hosts = config.allowed_hosts()
        self.allowed_origins = config.allowed_origins()
        self.sessions = sessions
        self.control_secret = control_secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()

        host = (header(scope, b"host") or "").lower()
        if host not in self.allowed_hosts:
            await self._reject(send, 421, "host_rejected")
            return

        if path.startswith("/control/"):
            secret = self.control_secret()
            supplied = header(scope, CONTROL_HEADER.encode()) or ""
            if method != "POST" or header(scope, b"origin") or not secret or not hmac.compare_digest(supplied, secret):
                await self._reject(send, 403, "control_rejected")
                return
        elif path.startswith("/api/") and path not in PUBLIC_API_PATHS:
            if method == "OPTIONS":
                await self._reject(send, 403, "origin_rejected")  # never approve CORS preflights
                return
            session = self.sessions.get(session_cookie_from_scope(scope, self.sessions.cookie_name))
            if session is None:
                await self._reject(send, 401, "session_required")
                return
            if method in UNSAFE_METHODS:
                origin = header(scope, b"origin")
                if not origin or origin.rstrip("/") not in self.allowed_origins:
                    await self._reject(send, 403, "origin_rejected")
                    return
                token = header(scope, CSRF_HEADER.encode()) or ""
                if not hmac.compare_digest(token, session.csrf):
                    await self._reject(send, 403, "csrf_failed")
                    return
            scope.setdefault("state", {})["emneklar_session"] = session

        no_store = path.startswith(("/api/", "/auth/", "/control/"))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                names = {k for k, _ in SECURITY_HEADERS}
                headers = [h for h in message.get("headers", []) if h[0].lower() not in names]
                headers.extend(SECURITY_HEADERS)
                if no_store and not any(h[0].lower() == b"cache-control" for h in headers):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)

    @staticmethod
    async def _reject(send: Send, status: int, code: str) -> None:
        body = json.dumps({"error": {"code": code, "message": MESSAGES.get(code, code)}}).encode("utf-8")
        headers: list[Any] = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
            *SECURITY_HEADERS,
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
