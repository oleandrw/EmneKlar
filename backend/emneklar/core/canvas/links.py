"""Direct links into Canvas for a piece of content (open, edit, its module item) – for «Åpne i Canvas».

Canvas has no API for anchoring to an element inside a page. Where a short, distinctive text is known (link text,
heading text), a URL text fragment (``#:~:text=…``, supported by current Chromium, Edge, Safari and Firefox) asks the
browser to scroll to and highlight it; browsers without support simply open the page. Everything else falls back to
opening the right content with enough context in EmneKlar to find the spot.

URL patterns (canvas-lms routes): ``/courses/:id/pages/:url`` (+ ``/edit``), ``/assignments/:id`` (+ ``/edit``),
``/discussion_topics/:id`` (+ ``/edit``, also announcements), ``/quizzes/:id`` (+ ``/edit``),
``/assignments/syllabus``, ``/modules/items/:id``, ``/modules#context_module_:id``, ``/files?preview=:id``.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from emneklar.core.canvas.html import norm_text, parse_html, text_of

_HOST_CHARS = re.compile(r"[\w.-]+", re.UNICODE)  # letters (also æøå/IDN), digits, dots and hyphens


def href_problem(href: str | None) -> str | None:
    """Why a link address cannot work, in plain words – or None when it looks like a real address.

    Only clear-cut cases are reported (no network check): no address, code instead of an address, a missing or
    impossible host name – typically text pasted into the address field, e.g. ``http://PDF-versjon%20https``.
    """
    value = (href or "").strip()
    if not value:
        return "Lenken har ingen adresse."
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme in ("javascript", "vbscript", "data"):
        return "Adressen kjører kode eller inneholder data i stedet for å peke til en side."
    if scheme not in ("http", "https"):
        return None  # relative Canvas links, mailto:, tel:, anchors … are not judged here
    if re.match(r"(?i)^https?://+(https?:|www\.)?https?:", value) or re.match(r"(?i)^https?://+https?//", value):
        return "Adressen inneholder «http» to ganger – den er trolig limt inn to ganger eller skrevet feil."
    host = parts.netloc.rsplit("@", 1)[-1]
    host = host[1:host.index("]")] if host.startswith("[") and "]" in host else host.split(":", 1)[0]
    shown = unquote(host).strip()
    if not shown:
        return "Adressen mangler nettstedsnavn (for eksempel www.uio.no)."
    if re.search(r"\s", shown):
        hint = " Ordet «http» står inne i navnet." if re.search(r"(?i)https?", shown) else ""
        return (f"Adressen er ikke gyldig: «{shown}» inneholder mellomrom og er ikke et nettstedsnavn. Det ser ut som "
                f"tekst som er limt inn i adressefeltet i stedet for en nettadresse.{hint}")
    try:
        ipaddress.ip_address(shown)
        return None
    except ValueError:
        pass
    if not _HOST_CHARS.fullmatch(shown):
        return f"Adressen er ikke gyldig: «{shown}» inneholder tegn som ikke kan stå i et nettstedsnavn."
    if "." not in shown.strip(".") and shown.lower() != "localhost":
        return (f"Adressen er ikke gyldig: «{shown}» er ikke et nettstedsnavn (det mangler domene, for eksempel .no "
                "eller .com).")
    return None

VIEW_PATHS = {
    "page": "pages/{id}", "front_page": "pages/{id}", "assignment": "assignments/{id}",
    "discussion": "discussion_topics/{id}", "announcement": "discussion_topics/{id}", "quiz": "quizzes/{id}",
    "syllabus": "assignments/syllabus", "module_item": "modules/items/{id}", "module": "modules#context_module_{id}",
    "file": "files?preview={id}", "course": "",
}
EDIT_PATHS = {
    "page": "pages/{id}/edit", "front_page": "pages/{id}/edit", "assignment": "assignments/{id}/edit",
    "discussion": "discussion_topics/{id}/edit", "announcement": "discussion_topics/{id}/edit",
    "quiz": "quizzes/{id}/edit",
}


def text_fragment(text: str | None, *, max_words: int = 8) -> str | None:
    """``#:~:text=`` for a short, exact piece of text (``-``, ``&`` and ``,`` must be percent-encoded)."""
    words = norm_text(text).split()
    if not words:
        return None
    snippet = " ".join(words[:max_words])
    if len(snippet) < 3:
        return None
    return "#:~:text=" + quote(snippet, safe="").replace("-", "%2D")


def highlight_text(location: dict[str, Any] | None, evidence: dict[str, Any] | None) -> str | None:
    """The best short, visible text near the finding (link text, heading text) – None when there is none."""
    location, evidence = location or {}, evidence or {}
    if evidence.get("link_text"):
        return str(evidence["link_text"])
    snippet = str(location.get("snippet") or "")
    match = re.match(r"\s*<(a|h[1-6]|p|li|td|th|caption|figcaption|strong|b)\b", snippet, re.IGNORECASE)
    if match:
        text = text_of(parse_html(snippet))
        if text and not text.endswith("…"):
            return text
        if text:
            return text.rstrip("…").rsplit(" ", 1)[0] or None
    return None


def content_links(base_url: str | None, course_id: str, object_type: str | None, object_id: str | None, *,
                  object_url: str | None = None, location: dict[str, Any] | None = None,
                  evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """{view, edit, module_item, highlight, label} – absolute Canvas URLs, or None where Canvas has no such page."""
    base = (base_url or "").rstrip("/")
    if not base or not course_id:
        return {"view": object_url, "edit": None, "module_item": None, "highlight": None}
    root = f"{base}/courses/{course_id}"
    location, evidence = location or {}, evidence or {}
    ident = quote(str(object_id or ""), safe="")
    kind = object_type or ""
    if kind == "quiz_question" and evidence.get("quiz_id"):
        kind, ident = "quiz", quote(str(evidence["quiz_id"]), safe="")
    view = None
    if kind in VIEW_PATHS and (ident or "{id}" not in VIEW_PATHS[kind]):
        path = VIEW_PATHS[kind].format(id=ident)
        view = f"{root}/{path}" if path else root
    elif object_url:
        view = object_url
    if object_url and kind not in ("syllabus", "module", "file") and object_url.startswith(("http://", "https://")):
        view = object_url  # Canvas' own html_url wins (e.g. pages addressed by slug)
    edit = f"{root}/{EDIT_PATHS[kind].format(id=ident)}" if kind in EDIT_PATHS and ident else None
    item = location.get("module_item_id")
    module_item = f"{root}/modules/items/{quote(str(item), safe='')}" if item else None
    module = location.get("module_id")
    module_url = f"{root}/modules#context_module_{quote(str(module), safe='')}" if module else None
    fragment = text_fragment(highlight_text(location, evidence))
    highlight = f"{view}{fragment}" if view and fragment and "#" not in view else None
    return {"view": view, "edit": edit, "module_item": module_item, "module": module_url, "highlight": highlight}
