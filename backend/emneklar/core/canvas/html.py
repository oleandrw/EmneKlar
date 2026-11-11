"""Helpers for reading Canvas HTML (pages, assignment descriptions, …).

Canvas HTML is untrusted input: it is parsed (never executed or rendered by
the backend), and all helpers are defensive about malformed markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

MAX_HTML_CHARS = 2_000_000
_WS = re.compile(r"\s+")

BLOCK_CONTEXT_TAGS = ("p", "li", "td", "th", "dd", "dt", "figcaption", "caption", "blockquote")


def parse_html(html: str | None) -> BeautifulSoup:
    return BeautifulSoup((html or "")[:MAX_HTML_CHARS], "html.parser")


def norm_text(text: str | None) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def text_of(el: Tag | None) -> str:
    if el is None:
        return ""
    return norm_text(el.get_text(" "))


def element_path(el: Tag) -> str:
    """A CSS-like path (tag:nth-of-type) that identifies the element within the document."""
    parts: list[str] = []
    node: Tag | None = el
    while node is not None and isinstance(node, Tag) and node.name not in ("[document]", "html", "body"):
        parent = node.parent
        if parent is None:
            break
        siblings = list(parent.find_all(node.name, recursive=False))
        index = siblings.index(node) + 1 if node in siblings else 1
        parts.append(f"{node.name}:nth-of-type({index})")
        node = parent if isinstance(parent, Tag) else None
    return " > ".join(reversed(parts))


def find_by_path(soup: BeautifulSoup, path: str) -> Tag | None:
    """Inverse of :func:`element_path` (used to re-locate an element for a fix)."""
    node: Tag = soup
    for part in (p.strip() for p in path.split(">") if p.strip()):
        match = re.fullmatch(r"([a-z0-9]+):nth-of-type\((\d+)\)", part)
        if not match:
            return None
        name, index = match.group(1), int(match.group(2))
        candidates = node.find_all(name, recursive=False)
        if len(candidates) < index:
            return None
        node = candidates[index - 1]
    return node if node is not soup else None


def snippet(el: Tag, limit: int = 300) -> str:
    raw = str(el)
    return raw if len(raw) <= limit else raw[: limit - 1] + "…"


def outer_open_tag(el: Tag, limit: int = 300) -> str:
    attrs = " ".join(
        f'{k}="{" ".join(v) if isinstance(v, list) else v}"' for k, v in el.attrs.items()
    )
    text = f"<{el.name}{(' ' + attrs) if attrs else ''}>"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def accessible_name(el: Tag, soup: BeautifulSoup | None = None) -> str:
    """Approximate accessible name of a link/button (aria-labelledby, aria-label, content, title)."""
    labelledby = el.get("aria-labelledby")
    if labelledby and soup is not None:
        ids = labelledby if isinstance(labelledby, list) else str(labelledby).split()
        parts = [text_of(soup.find(id=i)) for i in ids]
        name = norm_text(" ".join(p for p in parts if p))
        if name:
            return name
    label = norm_text(str(el.get("aria-label") or ""))
    if label:
        return label
    pieces: list[str] = []
    for node in el.descendants:
        if isinstance(node, NavigableString):
            pieces.append(str(node))
        elif isinstance(node, Tag) and node.name == "img":
            if node.get("aria-hidden") == "true":
                continue
            pieces.append(" " + str(node.get("alt") or "") + " ")
        elif isinstance(node, Tag) and node.name == "svg":
            title = node.find("title")
            if title:
                pieces.append(" " + text_of(title) + " ")
    name = norm_text("".join(pieces))
    if name:
        return name
    return norm_text(str(el.get("title") or ""))


def context_text(el: Tag) -> str:
    """Text of the nearest block container (sentence/paragraph/list item/cell) – for 2.4.4 'in context'."""
    node = el.parent
    while isinstance(node, Tag):
        if node.name in BLOCK_CONTEXT_TAGS:
            return text_of(node)
        if node.name in ("div", "section", "article", "body", "[document]"):
            break
        node = node.parent
    return text_of(el.parent) if isinstance(el.parent, Tag) else ""


def is_hidden(el: Tag) -> bool:
    node: Tag | None = el
    while isinstance(node, Tag):
        if node.get("aria-hidden") == "true" or node.has_attr("hidden"):
            return True
        style = str(node.get("style") or "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        node = node.parent if isinstance(node.parent, Tag) else None
    return False


def filename_from_url(src: str) -> str:
    path = urlsplit(src or "").path
    name = unquote(path.rsplit("/", 1)[-1])
    return name


# -- Canvas URL understanding ----------------------------------------------------------------

_COURSE_URL = re.compile(
    r"^/(?:api/v1/)?courses/(?P<course>\d+)(?:/(?P<kind>pages|wiki|assignments|quizzes|discussion_topics|files|"
    r"modules|announcements|external_tools|grades|syllabus|assignments/syllabus)(?:/(?P<rest>[^?#]*))?)?"
)


@dataclass(frozen=True)
class CanvasRef:
    course_id: str
    kind: str | None  # pages|assignments|quizzes|discussion_topics|files|modules|external_tools|syllabus|…
    ident: str | None  # page slug / numeric id / module item id
    sub: str | None  # e.g. "items" for modules/items/:id, "download" for files


def canvas_ref(url: str, canvas_host: str | None) -> CanvasRef | None:
    """Parse a link to Canvas content (absolute on the Canvas host, or root-relative)."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme in ("http", "https"):
        if not canvas_host or (parts.hostname or "").lower() != canvas_host.lower():
            return None
    elif parts.scheme or parts.netloc:
        return None
    match = _COURSE_URL.match(parts.path or "")
    if not match:
        return None
    kind = match.group("kind")
    rest = (match.group("rest") or "").strip("/")
    if kind == "wiki":
        kind = "pages"
    if kind == "assignments/syllabus":
        kind = "syllabus"
    ident: str | None = None
    sub: str | None = None
    if rest:
        segments = rest.split("/")
        if kind == "modules" and segments[0] == "items" and len(segments) > 1:
            ident, sub = segments[1], "items"
        else:
            ident = unquote(segments[0])
            sub = segments[1] if len(segments) > 1 else None
    return CanvasRef(course_id=match.group("course"), kind=kind, ident=ident, sub=sub)


def absolute(url: str, base: str | None) -> str:
    return urljoin(base + "/", url) if base and not urlsplit(url).scheme else url


# -- iframe titles ----------------------------------------------------------------------------

# Titles that do not say what an embedded frame contains (WCAG 4.1.2). The one list used by the
# accessibility check and the video standardiser, so both agree on what «generic» means.
GENERIC_IFRAME_TITLES = frozenset({
    "iframe", "frame", "embed", "embedded content", "embedded video", "video", "youtube", "youtube video",
    "youtube video player", "media", "content", "untitled", "player", "external tool", "vimeo", "video player",
    "innhold", "ramme", "innebygd innhold", "spiller",
})


def is_generic_iframe_title(title: str | None) -> bool:
    """True for a missing or generic title («YouTube video player», «Video», …), case-insensitive."""
    text = norm_text(title).lower().rstrip(":.-–— ")
    return not text or text in GENERIC_IFRAME_TITLES


# -- media ------------------------------------------------------------------------------------

YOUTUBE_RE = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|v/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{6,})")
VIMEO_RE = re.compile(r"(?:player\.)?vimeo\.com/(?:video/)?(\d+)")
MEDIA_ID_RE = re.compile(r"media_comment_([A-Za-z0-9_]+)|/media_objects(?:_iframe)?/([A-Za-z0-9_]+)|entryid/([A-Za-z0-9_]+)",
                         re.IGNORECASE)
ATTACHMENT_IFRAME_RE = re.compile(r"/media_attachments_iframe/(\d+)")

MEDIA_FILE_EXT = {".mp4": "video", ".mov": "video", ".webm": "video", ".m4v": "video", ".mp3": "audio",
                  ".m4a": "audio", ".wav": "audio", ".ogg": "audio"}
DOCUMENT_EXT = {".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx", ".doc": "doc", ".ppt": "ppt",
                ".xls": "xls", ".odt": "odt", ".odp": "odp", ".ods": "ods"}


@dataclass(frozen=True)
class MediaRef:
    kind: str  # canvas_media|canvas_attachment|youtube|vimeo|html5_video|html5_audio|other_embed
    ident: str | None  # attachment id (canvas_attachment), media id (canvas_media) or video id
    src: str
    element: str  # tag name
    media_id: str | None = None  # Canvas media id (data-media-id), when present


CANVAS_FILE_SRC = re.compile(r"^(?:https?://[^/]+)?/(?:courses/\d+/)?files/(\d+)(?:/(?:download|preview))?(?:[?#]|$)")


def _canvas_file_source(el: Tag) -> str | None:
    """File id when a <video>/<audio> plays a Canvas file (``/courses/:id/files/:id/download`` in src or <source>).

    Absolute addresses are only trusted when Canvas' own editor marked the source (``instructure_*_link``)."""
    candidates = [(str(el.get("src") or ""), " ".join(el.get("class") or []))]
    candidates += [(str(s.get("src") or ""), " ".join(s.get("class") or [])) for s in el.find_all("source")]
    for src, classes in candidates:
        match = CANVAS_FILE_SRC.match(src.strip())
        if match and (src.startswith("/") or "instructure_" in classes):
            return match.group(1)
    return None


def find_media(soup: BeautifulSoup) -> list[tuple[Tag, MediaRef]]:
    found: list[tuple[Tag, MediaRef]] = []
    for el in soup.find_all(["iframe", "video", "audio", "a", "embed", "object"]):
        src = str(el.get("src") or el.get("data") or el.get("href") or "")
        classes = " ".join(el.get("class") or [])
        media_id = str(el.get("data-media-id") or "")
        if el.name in ("video", "audio") and not media_id:
            # Canvas renders its own media (recorded or uploaded in the editor) as <video>/<audio> too: those are Canvas
            # media with tracks in Canvas, not a plain HTML5 player that must carry <track> elements itself.
            legacy = str(el.get("data-media_comment_id") or "")
            if legacy or "instructure_inline_media_comment" in classes:
                found.append((el, MediaRef(kind="canvas_media", ident=legacy or None, src=src, element=el.name,
                                           media_id=legacy or None)))
                continue
            file_id = _canvas_file_source(el)
            if file_id:
                found.append((el, MediaRef(kind="canvas_attachment", ident=file_id, src=src, element=el.name)))
                continue
            found.append((el, MediaRef(kind=f"html5_{el.name}", ident=None, src=src, element=el.name)))
            continue
        attachment = ATTACHMENT_IFRAME_RE.search(src)
        if attachment:
            found.append((el, MediaRef(kind="canvas_attachment", ident=attachment.group(1), src=src, element=el.name,
                                       media_id=media_id or None)))
            continue
        match = MEDIA_ID_RE.search(src) or MEDIA_ID_RE.search(classes)
        legacy_id = str(el.get("data-media_comment_id") or "")
        if media_id or legacy_id or match or "instructure_inline_media_comment" in classes:
            ident = media_id or legacy_id or (next((g for g in match.groups() if g), None) if match else None)
            found.append((el, MediaRef(kind="canvas_media", ident=ident, src=src, element=el.name, media_id=ident)))
            continue
        if el.name == "a":
            continue  # ordinary links are handled by the link checks
        yt = YOUTUBE_RE.search(src)
        if yt:
            found.append((el, MediaRef(kind="youtube", ident=yt.group(1), src=src, element=el.name)))
            continue
        vimeo = VIMEO_RE.search(src)
        if vimeo:
            found.append((el, MediaRef(kind="vimeo", ident=vimeo.group(1), src=src, element=el.name)))
            continue
    return found
