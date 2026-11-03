"""Canvas HTML → structured Markdown blocks (headings, paragraphs, lists, tables, code, quotes).

Besides the text, the converter collects what later steps need: images (with alt text, surrounding text and
the heading they appear under), embedded media (Canvas media, YouTube, Vimeo …) and links to Canvas files.
Hidden elements, scripts and styles are dropped. Canvas equation images become their LaTeX alt text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import NavigableString, Tag

from emneklar.core.canvas.html import MediaRef, canvas_ref, find_media, is_hidden, norm_text, parse_html
from emneklar.features.course_rag.markdown import Block

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
BLOCK_TAGS = {"p", "ul", "ol", "table", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section",
              "article", "main", "aside", "header", "footer", "figure", "details", "dl", "hr", "form", "nav"}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "button", "input", "select", "textarea", "head",
             "object", "embed", "link", "meta"}
CONTEXT_CHARS = 500
FILE_API = re.compile(r"/(?:api/v1/)?(?:courses/\d+/)?files/(\d+)")


@dataclass
class ImageRef:
    src: str
    alt: str | None  # None = no alt attribute; "" = explicitly empty
    title: str
    width: int | None
    height: int | None
    context: str
    heading: str
    classes: str
    role: str
    file_id: str | None = None  # Canvas file id when the image is a course file

    def as_dict(self) -> dict[str, object]:
        return {"src": self.src, "alt": self.alt, "title": self.title, "width": self.width, "height": self.height,
                "context": self.context, "heading": self.heading, "classes": self.classes, "role": self.role,
                "file_id": self.file_id}


@dataclass
class HtmlResult:
    blocks: list[Block]
    images: list[ImageRef] = field(default_factory=list)
    media: list[MediaRef] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)
    media_titles: dict[str, str] = field(default_factory=dict)  # media ref ident → iframe/link title


def _int(value: object) -> int | None:
    match = re.match(r"\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


class _Converter:
    def __init__(self, base_url: str, canvas_host: str | None) -> None:
        self.base = base_url.rstrip("/")
        self.host = canvas_host
        self.blocks: list[Block] = []
        self.images: list[ImageRef] = []
        self.file_ids: list[str] = []
        self.loose: list[str] = []
        self.headings: list[tuple[int, str]] = []

    # -- helpers ---------------------------------------------------------------------------------------

    def absolute(self, url: str) -> str:
        if not url or url.startswith(("data:", "mailto:", "tel:", "#", "javascript:")):
            return url
        return urljoin(self.base + "/", url) if not urlsplit(url).scheme else url

    def heading_path(self) -> str:
        return " › ".join(text for _, text in self.headings)

    def note_file_link(self, href: str) -> None:
        ref = canvas_ref(href, self.host)
        file_id = None
        if ref and ref.kind == "files" and ref.ident and ref.ident.isdigit():
            file_id = ref.ident
        else:
            parts = urlsplit(href)
            if not parts.scheme or (self.host and (parts.hostname or "").lower() == self.host.lower()):
                match = FILE_API.search(parts.path or "")
                file_id = match.group(1) if match else None
        if file_id and file_id not in self.file_ids:
            self.file_ids.append(file_id)

    def image(self, el: Tag) -> str:
        src = self.absolute(str(el.get("src") or el.get("data-src") or ""))
        alt_attr = el.get("alt")
        alt = None if alt_attr is None else norm_text(str(alt_attr))
        if "/equation_images/" in src:
            return f" ${alt}$ " if alt else ""
        if not src or src.startswith("data:"):
            return f" [Bilde: {alt}] " if alt else ""
        figure = el.find_parent("figure")
        figcaption = figure.find("figcaption") if figure is not None else None
        caption = norm_text(figcaption.get_text(" ")) if isinstance(figcaption, Tag) else ""
        container = el.find_parent(["p", "li", "td", "th", "figure", "dd", "blockquote"]) or el.parent
        context = norm_text(container.get_text(" ")) if container else ""
        if caption and caption not in context:
            context = f"{caption} {context}".strip()
        ref = canvas_ref(src, self.host)
        file_id = ref.ident if ref and ref.kind == "files" and ref.ident and ref.ident.isdigit() else None
        self.images.append(ImageRef(src=src, alt=alt, title=norm_text(str(el.get("title") or "")),
                                    width=_int(el.get("width")), height=_int(el.get("height")),
                                    context=context[:CONTEXT_CHARS], heading=self.heading_path(),
                                    classes=" ".join(el.get("class") or []), role=str(el.get("role") or ""),
                                    file_id=file_id))
        return f" [Bilde: {alt}] " if alt else " "

    # -- inline ----------------------------------------------------------------------------------------

    def inline(self, el: Tag) -> str:
        text = "".join(self.render(child) for child in el.children)
        lines = [norm_text(line) for line in text.split("\n")]
        return "\n".join(line for line in lines if line)

    def render(self, child: object) -> str:
        """One node as inline Markdown (text, emphasis, links, images, embedded media)."""
        if isinstance(child, NavigableString):
            if type(child).__name__ in ("Comment", "CData", "ProcessingInstruction", "Doctype"):
                return ""
            return str(child)
        if not isinstance(child, Tag) or child.name in SKIP_TAGS or is_hidden(child):
            return ""
        name = child.name
        if name == "br":
            return "\n"
        if name == "img":
            return self.image(child)
        if name in ("iframe", "video", "audio"):
            title = norm_text(str(child.get("title") or child.get("aria-label") or ""))
            return f" [Video: {title}] " if title else " [Innebygd innhold] "
        if name in ("strong", "b"):
            text = norm_text(self.inline(child))
            return f" **{text}** " if text else ""
        if name in ("em", "i"):
            text = norm_text(self.inline(child))
            return f" *{text}* " if text else ""
        if name == "code":
            text = norm_text(child.get_text(" "))
            return f" `{text}` " if text else ""
        if name == "a":
            href = str(child.get("href") or "")
            for candidate in (href, str(child.get("data-api-endpoint") or "")):
                if candidate:
                    self.note_file_link(candidate)
            text = norm_text(self.inline(child))
            url = self.absolute(href)
            if text and url and not url.startswith(("#", "javascript:")) and url != text:
                return f" [{text}]({url}) "
            return f" {text} " if text else ""
        if name in ("ul", "ol", "table", "p", "div", "blockquote", "pre"):
            return " " + norm_text(self.inline(child)) + " "
        return self.inline(child)

    # -- blocks ----------------------------------------------------------------------------------------

    def flush(self) -> None:
        if self.loose:
            text = norm_text(" ".join(self.loose))
            if text:
                self.blocks.append(Block("paragraph", text))
            self.loose.clear()

    def list_text(self, el: Tag, depth: int = 0) -> list[str]:
        lines: list[str] = []
        ordered = el.name == "ol"
        number = _int(el.get("start")) or 1
        for li in el.find_all("li", recursive=False):
            if is_hidden(li):
                continue
            nested = list(li.find_all(["ul", "ol"], recursive=False))
            for n in nested:
                n.extract()
            text = norm_text(self.inline(li).replace("\n", " "))
            marker = f"{number}." if ordered else "-"
            if text:
                lines.append(f"{'  ' * depth}{marker} {text}")
                number += 1
            for n in nested:
                lines.extend(self.list_text(n, depth + 1))
        return lines

    def table(self, el: Tag) -> None:
        rows: list[list[str]] = []
        for tr in el.find_all("tr"):
            if tr.find_parent("table") is not el:
                continue
            cells = [norm_text(self.inline(cell).replace("\n", " ")) for cell in tr.find_all(["th", "td"], recursive=False)]
            if any(cells):
                rows.append(cells)
        caption = el.find("caption")
        if caption is not None:
            text = norm_text(caption.get_text(" "))
            if text:
                self.blocks.append(Block("paragraph", f"**{text}**"))
        width = max((len(r) for r in rows), default=0)
        if width <= 1 or (len(rows) <= 1 and width <= 2):
            # Layout tables (one column or one small row) are text, not data.
            for row in rows:
                for cell in row:
                    if cell:
                        self.blocks.append(Block("paragraph", cell))
            return
        self.blocks.append(Block("table", rows=rows))

    def walk(self, el: Tag) -> None:
        for child in el.children:
            if isinstance(child, NavigableString):
                if type(child).__name__ in ("Comment", "CData", "ProcessingInstruction", "Doctype"):
                    continue
                if str(child).strip():
                    self.loose.append(str(child))
                continue
            if not isinstance(child, Tag) or child.name in SKIP_TAGS or is_hidden(child):
                continue
            name = child.name
            if name in HEADINGS:
                self.flush()
                text = norm_text(self.inline(child).replace("\n", " "))
                if text:
                    level = HEADINGS[name]
                    self.headings = [h for h in self.headings if h[0] < level] + [(level, text)]
                    self.blocks.append(Block("heading", text, level=level))
            elif name == "p":
                self.flush()
                text = self.inline(child)
                if text:
                    self.blocks.append(Block("paragraph", text))
            elif name in ("ul", "ol"):
                self.flush()
                lines = self.list_text(child)
                if lines:
                    self.blocks.append(Block("list", "\n".join(lines)))
            elif name == "table":
                self.flush()
                self.table(child)
            elif name == "blockquote":
                self.flush()
                text = self.inline(child)
                if text:
                    self.blocks.append(Block("quote", text))
            elif name == "pre":
                self.flush()
                text = child.get_text()
                if text.strip():
                    self.blocks.append(Block("code", text.strip("\n")))
            elif name == "dl":
                self.flush()
                for item in child.find_all(["dt", "dd"], recursive=False):
                    text = norm_text(self.inline(item))
                    if text:
                        self.blocks.append(Block("paragraph", f"**{text}**" if item.name == "dt" else text))
            elif name == "hr":
                self.flush()
            elif name in BLOCK_TAGS or child.find(list(BLOCK_TAGS)) is not None:
                self.flush()
                self.walk(child)
                self.flush()
            else:
                text = self.render(child)
                if text.strip():
                    self.loose.append(text)


def html_to_blocks(html: str | None, *, base_url: str, canvas_host: str | None = None) -> HtmlResult:
    soup = parse_html(html)
    media_pairs = find_media(soup)
    media_titles: dict[str, str] = {}
    for el, ref in media_pairs:
        title = norm_text(str(el.get("title") or el.get_text(" ") or ""))
        if ref.ident and title:
            media_titles.setdefault(ref.ident, title)
    converter = _Converter(base_url, canvas_host)
    converter.walk(soup)
    converter.flush()
    return HtmlResult(blocks=converter.blocks, images=converter.images, media=[ref for _, ref in media_pairs],
                      file_ids=converter.file_ids, media_titles=media_titles)
