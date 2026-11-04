"""The semantic structure of one Canvas page: blocks, sections and anchors.

A *block* is a block-level element directly inside the page's content container (the page body, or the innermost
single wrapper ``<div>`` that many Canvas templates put around everything). Illustrations are only ever inserted
*between* blocks of the container – never inside a paragraph, list, table, iframe, figure or a template component –
so the text and layout of the page stay exactly as the teacher wrote them.

Sections start at headings. Section ``s0`` is the introduction before the first heading.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from emneklar.core.canvas.html import norm_text
from emneklar.features.illustrations.htmlspans import ScanResult, Span, scan

MARKER_ATTR = "data-emneklar-illustration"
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
BLOCK_TAGS = {"p", "ul", "ol", "dl", "table", "blockquote", "pre", "div", "section", "article", "aside", "header",
              "footer", "figure", "details", "hr", "iframe", "video", "audio", "nav", "form", "main", "address",
              *HEADINGS}
WRAPPERS = {"div", "section", "article", "main", "html", "body"}
TASK_WORDS = re.compile(r"\b(oppgave|oppgaver|øving|refleksjon|refleksjonsspørsmål|diskuter|diskusjon|aktivitet|"
                        r"spørsmål|quiz|test deg selv|innlevering|arbeidskrav|task|exercise|reflect)\w*", re.IGNORECASE)
# Canvas/template components that must be kept intact (insertion never goes inside them anyway; they are labelled
# so the planner knows the layout).
COMPONENT_HINTS = ("dp-", "kl_", "accordion", "tabs", "panel", "callout", "enhanceable_content", "ic-", "carousel")


@dataclass
class Block:
    index: int
    tag: str
    kind: str  # heading|paragraph|list|table|image|media|figure|quote|code|component|rule|other
    span: Span
    text: str
    level: int = 0  # heading level
    emneklar_marker: str | None = None
    images: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(f"{self.tag}|{self.text}".encode()).hexdigest()[:16]  # noqa: S324 - identity, not security

    def anchor(self) -> dict[str, Any]:
        return {"block_index": self.index, "block_tag": self.tag, "block_hash": self.fingerprint,
                "block_text": self.text[:140]}


@dataclass
class Section:
    id: str
    title: str
    level: int
    heading_index: int | None  # block index of the heading (None for the introduction)
    block_indices: list[int]
    parent_titles: list[str] = field(default_factory=list)

    @property
    def first(self) -> int | None:
        return self.heading_index if self.heading_index is not None else (
            self.block_indices[0] if self.block_indices else None)

    @property
    def last(self) -> int | None:
        indices = ([self.heading_index] if self.heading_index is not None else []) + self.block_indices
        return max(indices) if indices else None


@dataclass
class PageStructure:
    html: str
    scan: ScanResult
    container: Span
    blocks: list[Block]
    sections: list[Section]
    wrapper_depth: int

    @property
    def reliable(self) -> bool:
        return self.scan.reliable

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def section_of(self, block_index: int) -> Section | None:
        for section in self.sections:
            if block_index == section.heading_index or block_index in section.block_indices:
                return section
        return None

    def section_text(self, section: Section, limit: int = 6000) -> str:
        parts = []
        for index in section.block_indices:
            block = self.blocks[index]
            if block.kind in ("image", "figure") and block.emneklar_marker:
                continue
            if block.text:
                prefix = {"list": "• ", "table": "[Tabell] ", "quote": "[Sitat] ", "code": "[Kode] ",
                          "media": "[Video/innebygd innhold] ", "image": "[Bilde] ", "figure": "[Figur] "}.get(
                    block.kind, "")
                parts.append(prefix + block.text)
        text = "\n".join(parts)
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def images(self) -> list[dict[str, Any]]:
        out = []
        for block in self.blocks:
            for image in block.images:
                section = self.section_of(block.index)
                out.append({**image, "block_index": block.index, "section_id": section.id if section else None,
                            "section_title": section.title if section else "", "emneklar": block.emneklar_marker})
        return out

    def emneklar_markers(self) -> list[str]:
        markers = []
        for span in self.scan.root.walk():
            marker = span.attr(MARKER_ATTR)
            if marker:
                markers.append(marker)
        return markers


def _text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(["script", "style", "noscript", "template"]):
        el.decompose()
    return norm_text(soup.get_text(" "))


def _images(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for img in soup.find_all("img"):
        caption = ""
        figure = img.find_parent("figure")
        found = figure.find("figcaption") if figure is not None else None
        if found is not None:
            caption = norm_text(found.get_text(" "))
        src = str(img.get("src") or "")
        out.append({"alt": img.get("alt"), "src": src, "caption": caption,
                    "file": src.rsplit("/", 2)[-2] if "/files/" in src else "",
                    "role": str(img.get("role") or "")})
    return out


def _kind(span: Span, html: str, text: str) -> str:
    tag = span.tag
    classes = span.attr("class").lower()
    if tag in HEADINGS:
        return "heading"
    if tag == "p":
        inner = html[span.start_end:span.inner_end]
        if not text and "<img" in inner.lower():
            return "image"
        if not text and ("<iframe" in inner.lower() or "<video" in inner.lower()):
            return "media"
        return "paragraph"
    if tag in ("ul", "ol", "dl"):
        return "list"
    if tag == "table":
        return "table"
    if tag == "figure":
        return "figure"
    if tag in ("iframe", "video", "audio"):
        return "media"
    if tag == "blockquote":
        return "quote"
    if tag == "pre":
        return "code"
    if tag == "hr":
        return "rule"
    if any(hint in classes for hint in COMPONENT_HINTS) or span.attr("id").lower().startswith("dp-"):
        return "component"
    if tag == "div" and not text and "<img" in html[span.start_end:span.inner_end].lower():
        return "image"
    return "other" if tag not in ("div", "section", "aside", "details") else "component"


def _container(root: Span, html: str) -> tuple[Span, int]:
    """Descend into single wrapper elements (template wrappers such as ``<div id="dp-wrapper">``)."""
    node, depth = root, 0
    while True:
        elements = list(node.children)
        if len(elements) != 1 or elements[0].tag not in WRAPPERS:
            return node, depth
        only = elements[0]
        # Text directly in the wrapper (outside child elements) means it is content, not a wrapper.
        inner = html[only.start_end:only.inner_end]
        child_spans = sorted(only.children, key=lambda s: s.start)
        cursor, loose = only.start_end, ""
        for child in child_spans:
            loose += html[cursor:child.start]
            cursor = child.end
        loose += html[cursor:only.inner_end]
        if norm_text(re.sub(r"<!--.*?-->", "", loose, flags=re.DOTALL)) or not inner.strip():
            return node, depth
        if only.attr(MARKER_ATTR):
            return node, depth
        node, depth = only, depth + 1


def parse_page(html: str | None) -> PageStructure:
    html = html or ""
    result = scan(html)
    container, depth = _container(result.root, html)
    blocks: list[Block] = []
    for span in container.children:
        if span.tag not in BLOCK_TAGS and span.tag not in ("img", "a", "span", "strong", "em", "b", "i", "br"):
            continue
        if span.tag not in BLOCK_TAGS:
            continue  # inline content at container level is never an insertion anchor
        fragment = html[span.start:span.end]
        text = _text(fragment)
        block = Block(index=len(blocks), tag=span.tag, kind=_kind(span, html, text), span=span, text=text,
                      level=HEADINGS.get(span.tag, 0), emneklar_marker=span.attr(MARKER_ATTR) or None,
                      images=_images(fragment) if "<img" in fragment.lower() else [])
        if block.emneklar_marker:
            block.kind = "figure"
        blocks.append(block)
    sections: list[Section] = [Section(id="s0", title="Innledning", level=0, heading_index=None, block_indices=[])]
    trail: list[tuple[int, str]] = []
    for block in blocks:
        if block.kind == "heading" and block.text:
            while trail and trail[-1][0] >= block.level:
                trail.pop()
            sections.append(Section(id=f"s{len(sections)}", title=block.text[:200], level=block.level,
                                    heading_index=block.index, block_indices=[],
                                    parent_titles=[t for _, t in trail]))
            trail.append((block.level, block.text[:200]))
        else:
            sections[-1].block_indices.append(block.index)
    if not sections[0].block_indices and len(sections) > 1:
        sections = sections[1:]
    return PageStructure(html=html, scan=result, container=container, blocks=blocks, sections=sections,
                         wrapper_depth=depth)


def looks_like_task(text: str) -> bool:
    return bool(TASK_WORDS.search(text or ""))


def outline(structure: PageStructure, *, section_chars: int = 6000, total_chars: int = 60_000) -> list[dict[str, Any]]:
    """Sections with their full text for the AI (structured, never just the title). Long pages are shortened per
    section (each section keeps its beginning), so every section stays represented."""
    sections = []
    budget = max(1500, total_chars // max(1, len(structure.sections)))
    limit = min(section_chars, budget) if sum(len(structure.section_text(s, 10**9)) for s in structure.sections) \
        > total_chars else section_chars
    for section in structure.sections:
        kinds = [structure.blocks[i].kind for i in section.block_indices]
        sections.append({
            "section_id": section.id, "title": section.title, "level": section.level,
            "parents": section.parent_titles, "text": structure.section_text(section, limit),
            "contains": sorted(set(kinds)),
            "has_existing_image": any(k in ("image", "figure") for k in kinds),
            "has_emneklar_illustration": any(structure.blocks[i].emneklar_marker for i in section.block_indices),
            "looks_like_task": looks_like_task(section.title) or any(
                looks_like_task(structure.blocks[i].text[:200]) for i in section.block_indices[:2]),
        })
    return sections
