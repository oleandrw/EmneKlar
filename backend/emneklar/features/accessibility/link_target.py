"""What a link (or an embed) points to – fetched safely for a KI-forslag, never followed blindly.

* Canvas content (a relative address or the Canvas host) is read through the Canvas API with the teacher's own access:
  the title, and a short excerpt of pages, assignments and quizzes. Only the title of discussions (their posts can be
  written by students) and the name of files.
* Other http(s) addresses go through the SSRF-guarded client (:mod:`emneklar.core.security.guarded_http`): no cookies,
  no Canvas token, no proxy, every redirect re-validated, a time and size limit, HTML only.
* An address with credentials or tokens in it is not fetched at all, and :func:`safe_url` removes them before an
  address is sent to a KI provider or written to a log. The link in Canvas is never changed here.

A page that cannot be fetched is a status with an explanation – the suggestion is then based on the address and the
text around the link only, and the teacher is told so.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.html import norm_text, parse_html
from emneklar.core.container import AppContainer
from emneklar.core.security.guarded_http import USER_AGENT, build_guarded_client
from emneklar.core.security.ssrf import UrlBlocked, validate_url

TIMEOUT = 6.0
MAX_BYTES = 300_000
MAX_REDIRECTS = 4
EXCERPT = 400
CACHE_SECONDS = 600.0
#: Query parameters that may carry credentials, tokens or one-time codes (case-insensitive).
SENSITIVE = re.compile(r"(?i)(token|secret|passw|pwd|apikey|api_key|^key$|^sig$|signature|^auth|session|^sid$|^code$|"
                       r"^state$|ticket|verifier|credential|^x-amz-|^jwt$|^access)")
CANVAS_PATH = re.compile(r"^/courses/(\d+)/(pages|assignments|quizzes|discussion_topics|files)/([^/?#]+)")
KIND_WORD = {"pages": "siden", "assignments": "oppgaven", "quizzes": "quizen", "discussion_topics": "diskusjonen",
             "files": "filen"}


@dataclass(frozen=True)
class Target:
    kind: Literal["canvas", "web", "none"]
    fetched: bool
    #: What the suggestion can be based on, or why the target was not read – shown to the teacher.
    note: str
    title: str | None = None
    excerpt: str | None = None


def safe_url(url: str) -> tuple[str, bool]:
    """The address without user name, password and sensitive query parameters – for KI providers and logs – and
    whether anything was removed."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return "", True
    removed = bool(parts.username or parts.password)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if not SENSITIVE.search(k)]
    removed = removed or len(kept) < len(pairs)
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(kept), parts.fragment)), removed


def _excerpt(html: str | None) -> str | None:
    if not html:
        return None
    text = norm_text(parse_html(html).get_text(" "))
    return (text[:EXCERPT].rsplit(" ", 1)[0] + " …") if len(text) > EXCERPT else (text or None)


async def _canvas(c: AppContainer, kind: str, course_id: str, ident: str) -> Target:
    api = CanvasAPI(c.canvas())
    word = KIND_WORD[kind]
    try:
        if kind == "pages":
            page = await api.get_page(course_id, ident)
            return Target("canvas", True, f"Tittel og et kort utdrag fra {word} i Canvas.", page.get("title"),
                          _excerpt(page.get("body")))
        if kind == "assignments":
            a = await api.get_assignment(course_id, ident)
            return Target("canvas", True, f"Tittel og et kort utdrag fra {word} i Canvas.", a.get("name"),
                          _excerpt(a.get("description")))
        if kind == "quizzes":
            q = await api.get_quiz(course_id, ident)
            return Target("canvas", True, f"Tittel og et kort utdrag fra {word} i Canvas.", q.get("title"),
                          _excerpt(q.get("description")))
        if kind == "discussion_topics":
            d = await api.get_discussion(course_id, ident)
            return Target("canvas", True, f"Tittelen på {word} i Canvas.", d.get("title"))
        f = await api.get_file(ident)
        return Target("canvas", True, f"Navnet på {word} i Canvas.", f.get("display_name") or f.get("filename"))
    except CanvasError:
        return Target("canvas", False, f"Lenken går til {word} i Canvas, men den kunne ikke leses.")


def _client(c: AppContainer) -> httpx.AsyncClient:
    if c.link_transport is not None:  # tests: never the real network
        return httpx.AsyncClient(transport=c.link_transport, follow_redirects=False)
    return build_guarded_client(TIMEOUT, max_connections=2)


async def _read(response: httpx.Response) -> bytes:
    body = b""
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) >= MAX_BYTES:
            break
    return body[:MAX_BYTES]


def _page_facts(html: bytes) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    meta = {str(m.get("property") or m.get("name") or "").lower(): str(m.get("content") or "")
            for m in soup.find_all("meta")}
    title = norm_text(meta.get("og:title") or (soup.title.get_text(" ") if soup.title else "")) or None
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "template"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    description = norm_text(meta.get("og:description") or meta.get("description") or "")
    text = norm_text(main.get_text(" "))
    excerpt = " – ".join(x for x in (description, text) if x)
    if len(excerpt) > EXCERPT:
        excerpt = excerpt[:EXCERPT].rsplit(" ", 1)[0] + " …"
    return (title[:200] if title else None), (excerpt or None)


async def _web(c: AppContainer, url: str) -> Target:
    client = _client(c)
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            validate_url(current)
            async with client.stream("GET", current, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}) as r:
                location = r.headers.get("location")
                if r.status_code in (301, 302, 303, 307, 308) and location:
                    current = urljoin(current, location)
                    if safe_url(current)[1]:
                        return Target("web", False, "Målsiden sender videre til en adresse med tilgangsopplysninger, "
                                                    "så den ble ikke hentet.")
                    continue
                if r.status_code in (401, 403):
                    return Target("web", False, "Målsiden krever innlogging, så den ble ikke hentet.")
                if r.status_code >= 400:
                    return Target("web", False, f"Målsiden svarte med feil (HTTP {r.status_code}).")
                if "html" not in r.headers.get("content-type", "").lower():
                    return Target("web", False, "Lenken går til en fil eller annet innhold enn en nettside, så bare "
                                                "adressen er brukt.")
                title, excerpt = _page_facts(await _read(r))
                if not title and not excerpt:
                    return Target("web", False, "Målsiden hadde ingen lesbar tittel eller tekst.")
                return Target("web", True, "Tittel og et kort utdrag fra målsiden, hentet nå.", title, excerpt)
        return Target("web", False, "Målsiden sendte videre for mange ganger.")
    except UrlBlocked:
        return Target("web", False, "Adressen peker til et internt eller ugyldig sted og ble ikke hentet.")
    except (httpx.HTTPError, ValueError):
        return Target("web", False, "Målsiden kunne ikke hentes (ingen svar i tide).")
    finally:
        await client.aclose()


_cache: dict[str, tuple[float, Target]] = {}


async def describe_target(c: AppContainer, href: str) -> Target:
    """What ``href`` points to, as far as it can be read safely (cached for a few minutes per address)."""
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return Target("none", False, "Lenken går til et sted på samme side.")
    if href.lower().startswith(("mailto:", "tel:")):
        return Target("none", False, "Lenken er en e-postadresse eller et telefonnummer.")
    cached = _cache.get(href)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    canvas_host = (urlsplit(c.settings.get().canvas.base_url or "").hostname or "").lower()
    parts = urlsplit(href)
    if (not parts.scheme and href.startswith("/")) or (parts.hostname or "").lower() == canvas_host:
        match = CANVAS_PATH.match(parts.path)
        target = (await _canvas(c, match.group(2), match.group(1), match.group(3)) if match
                  else Target("canvas", False, "Lenken går til en del av Canvas som EmneKlar ikke leser."))
    elif parts.scheme not in ("http", "https"):
        target = Target("none", False, "Adressen er ikke en nettside og ble ikke hentet.")
    elif safe_url(href)[1]:
        target = Target("web", False, "Adressen inneholder innloggings- eller tilgangsopplysninger, så målsiden ble "
                                      "ikke hentet.")
    else:
        target = await _web(c, href)
    if len(_cache) > 500:
        _cache.clear()
    _cache[href] = (time.monotonic(), target)
    return target


def clear_cache() -> None:
    _cache.clear()
