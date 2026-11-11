"""HTML sanitisation mirroring what Canvas keeps (CanvasSanitize allowlist, docs/CANVAS_API.md).

Used for (1) previews – always rendered in a sandboxed iframe as well – and
(2) checking that generated HTML (Emnedesign, fixes) survives Canvas'
sanitiser, so what the teacher previews is what Canvas will store.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

import nh3
from bs4 import BeautifulSoup

ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "caption", "cite", "code", "col", "colgroup", "dd", "del", "div", "dl", "dt", "em",
    "figure", "figcaption", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "iframe", "img", "ins", "li", "ol",
    "p", "pre", "q", "small", "source", "span", "strike", "strong", "sub", "sup", "abbr", "table", "tbody", "td",
    "tfoot", "th", "thead", "tr", "u", "ul", "video", "track", "audio", "address", "acronym", "map", "area", "bdo",
    "dfn", "kbd", "legend", "samp", "tt", "var", "big", "article", "aside", "details", "footer", "header", "nav",
    "section", "summary", "time", "picture", "ruby", "rt", "rp", "mark",
}
GLOBAL_ATTRS = {"style", "class", "id", "title", "role", "lang", "dir"}
TAG_ATTRS = {
    "a": {"href", "target", "name"},
    "img": {"align", "alt", "height", "src", "usemap", "width", "longdesc"},
    "iframe": {"src", "width", "height", "name", "align", "frameborder", "scrolling", "allow", "loading",
               "allowfullscreen"},
    "table": {"summary", "width", "border", "cellpadding", "cellspacing", "frame", "rules"},
    "td": {"abbr", "axis", "colspan", "rowspan", "width", "align", "valign"},
    "th": {"abbr", "axis", "colspan", "rowspan", "width", "align", "valign", "scope"},
    "col": {"span", "width"},
    "colgroup": {"span", "width"},
    "ol": {"start", "type"},
    "ul": {"type"},
    "video": {"src", "poster", "controls", "muted", "playsinline", "width", "height"},
    "audio": {"src", "controls", "muted"},
    "track": {"default", "kind", "label", "src", "srclang"},
    "source": {"src", "type"},
    "time": {"datetime"},
    "font": {"color", "face", "size"},
}
ALLOWED_CSS = {
    "align-content", "align-items", "align-self", "background", "background-color", "background-image",
    "background-position", "background-repeat", "background-size", "border", "border-bottom", "border-bottom-color",
    "border-bottom-style", "border-bottom-width", "border-collapse", "border-color", "border-left", "border-left-color",
    "border-left-style", "border-left-width", "border-radius", "border-right", "border-right-color",
    "border-right-style", "border-right-width", "border-spacing", "border-style", "border-top", "border-top-color",
    "border-top-style", "border-top-width", "border-width", "clear", "color", "column-gap", "cursor", "direction",
    "display", "flex", "flex-basis", "flex-direction", "flex-flow", "flex-grow", "flex-shrink", "flex-wrap", "float",
    "font", "font-family", "font-size", "font-stretch", "font-style", "font-variant", "gap", "grid",
    "grid-area", "grid-auto-columns", "grid-auto-flow", "grid-auto-rows", "grid-column", "grid-gap", "grid-row",
    "grid-template", "grid-template-areas", "grid-template-columns", "grid-template-rows", "height",
    "justify-content", "justify-items", "justify-self", "left", "line-height", "list-style", "list-style-image",
    "list-style-position", "list-style-type", "margin", "margin-bottom", "margin-left", "margin-right", "margin-top",
    "max-height", "max-width", "min-height", "min-width", "order", "overflow", "overflow-x", "overflow-y", "padding",
    "padding-bottom", "padding-left", "padding-right", "padding-top", "place-content", "place-items", "place-self",
    "position", "right", "row-gap", "table-layout", "text-align", "text-decoration", "text-indent", "top",
    "vertical-align", "visibility", "white-space", "width", "z-index",
}


def canvas_sanitize(html: str) -> str:
    """What Canvas' Rich Content sanitiser would keep (approximation of CanvasSanitize)."""
    return nh3.clean(
        html or "",
        tags=ALLOWED_TAGS,
        clean_content_tags={"script", "style", "svg", "noscript", "template", "object", "embed"},
        attributes={"*": GLOBAL_ATTRS, **TAG_ATTRS},
        generic_attribute_prefixes={"data-", "aria-"},
        url_schemes={"http", "https", "mailto", "tel"},
        strip_comments=True,
        link_rel=None,
        filter_style_properties=ALLOWED_CSS,
    )


_STYLE_PROP = re.compile(r"(?:^|;)\s*([a-zA-Z-]+)\s*:")


def canvas_safe(html: str) -> tuple[str, list[str]]:
    """Sanitise like Canvas and report what Canvas would remove (so the preview matches the stored page)."""
    soup = BeautifulSoup(html or "", "html.parser")
    warnings: list[str] = []
    removed_tags = sorted({t.name for t in soup.find_all(True) if t.name not in ALLOWED_TAGS})
    if removed_tags:
        warnings.append("Canvas fjerner disse elementene: " + ", ".join(f"<{t}>" for t in removed_tags) + ".")
    props: set[str] = set()
    for tag in soup.find_all(style=True):
        props |= {p.lower() for p in _STYLE_PROP.findall(str(tag.get("style")))}
    dropped = sorted(p for p in props if p not in ALLOWED_CSS)
    if dropped:
        warnings.append("Canvas fjerner disse stilene: " + ", ".join(dropped) + ".")
    return canvas_sanitize(html), warnings


_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)


def preview_html(html: str, canvas_base: str | None) -> str:
    """Sanitised HTML for the sandboxed preview, with Canvas images routed via the local proxy."""
    clean = canvas_sanitize(html)
    if not canvas_base:
        return clean
    host = (urlsplit(canvas_base).hostname or "").lower()

    def rewrite(match: re.Match[str]) -> str:
        src = match.group(2).replace("&amp;", "&")
        parts = urlsplit(src)
        if not parts.scheme and src.startswith("/"):
            absolute = canvas_base.rstrip("/") + src
        elif (parts.hostname or "").lower() == host:
            absolute = src
        else:
            return match.group(0)
        return f"{match.group(1)}/api/canvas/image?url={quote(absolute, safe='')}{match.group(3)}"

    return _IMG_SRC.sub(rewrite, clean)
