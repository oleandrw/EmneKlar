"""Deterministic placement and insertion of illustrations in Canvas page HTML.

The AI proposes *where* an illustration helps (a section and a placement type); this module turns that into a
concrete, robust anchor (the block's tag + a hash of its text, not a fragile path or a text search) and inserts a
``<figure>`` by splicing the original HTML at a block boundary. Existing content is never rewritten, moved or
deleted. Removal (undo) cuts out exactly the figures EmneKlar inserted – identified by ``data-emneklar-illustration`` –
so everything else the teacher has changed in the meantime is kept.
"""

from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass
from typing import Any

from emneklar.core.changes.appliers import normalise_html
from emneklar.features.illustrations.htmlspans import scan
from emneklar.features.illustrations.structure import MARKER_ATTR, Block, PageStructure, Section, parse_page

PLACEMENTS = {
    "page_start": "I starten av siden",
    "after_intro": "Etter innledningen",
    "under_heading": "Rett under overskriften",
    "after_explanation": "Etter den faglige forklaringen",
    "end_of_section": "Mellom to tekstseksjoner (etter seksjonen)",
    "before_task": "Før oppgaven",
}
TEXT_KINDS = ("paragraph",)


class PlacementError(Exception):
    pass


@dataclass
class Anchor:
    """Insert *after* block ``block_index`` (or at the start of the container when ``block_index`` is -1)."""

    placement: str
    section_id: str | None
    block_index: int
    block_tag: str | None = None
    block_hash: str | None = None
    block_text: str = ""
    section_title: str = ""
    warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"placement": self.placement, "placement_label": PLACEMENTS.get(self.placement, self.placement),
                "section_id": self.section_id, "section_title": self.section_title, "block_index": self.block_index,
                "block_tag": self.block_tag, "block_hash": self.block_hash, "block_text": self.block_text,
                "warning": self.warning}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Anchor:
        return cls(placement=str(data.get("placement") or "end_of_section"), section_id=data.get("section_id"),
                   block_index=int(data.get("block_index", -1)), block_tag=data.get("block_tag"),
                   block_hash=data.get("block_hash"), block_text=str(data.get("block_text") or ""),
                   section_title=str(data.get("section_title") or ""), warning=data.get("warning"))


def _start_anchor(placement: str, section: Section | None) -> Anchor:
    return Anchor(placement=placement, section_id=section.id if section else None, block_index=-1,
                  section_title=section.title if section else "")


def _after(structure: PageStructure, index: int, placement: str, section: Section | None) -> Anchor:
    block = structure.blocks[index]
    anchor = Anchor(placement=placement, section_id=section.id if section else None, block_index=index,
                    section_title=section.title if section else "", **{
                        k: v for k, v in block.anchor().items() if k != "block_index"})
    neighbours = [structure.blocks[i] for i in (index, index + 1) if 0 <= i < len(structure.blocks)]
    if any(b.kind in ("image", "figure", "media") for b in neighbours):
        anchor.warning = "Plasseringen ligger rett ved et eksisterende bilde eller en video."
    return anchor


def anchor_for(structure: PageStructure, section_id: str | None, placement: str) -> Anchor:
    """The concrete anchor for a proposed placement. Falls back to the nearest sensible position."""
    if placement not in PLACEMENTS:
        placement = "end_of_section"
    sections = structure.sections
    if not structure.blocks:
        return _start_anchor("page_start", sections[0] if sections else None)
    section = structure.section(section_id or "") or sections[0]
    if placement == "page_start":
        return _start_anchor(placement, sections[0])
    if placement == "after_intro":
        intro = structure.section("s0")
        first_text = next((i for i in (intro.block_indices if intro else []) if structure.blocks[i].kind == "paragraph"),
                          None)
        if first_text is not None:
            return _after(structure, first_text, placement, intro)
        first = sections[0]
        if first.heading_index is not None:
            return _after(structure, first.heading_index, "under_heading", first)
        return _start_anchor("page_start", first)
    if placement == "under_heading":
        if section.heading_index is not None:
            return _after(structure, section.heading_index, placement, section)
        placement = "after_explanation"
    if placement == "after_explanation":
        run_end = None
        for index in section.block_indices:
            if structure.blocks[index].kind in TEXT_KINDS:
                run_end = index
            elif run_end is not None:
                break
        if run_end is not None:
            return _after(structure, run_end, placement, section)
        placement = "end_of_section"
    if placement == "before_task":
        position = sections.index(section)
        if section.heading_index is None or position == 0:
            return _start_anchor("page_start", section)
        previous = sections[position - 1]
        last = previous.last
        if last is None:
            return _start_anchor("page_start", section)
        anchor = _after(structure, last, placement, section)
        return anchor
    last = section.last
    if last is None:
        return _start_anchor("page_start", section)
    return _after(structure, last, "end_of_section", section)


def candidate_anchors(structure: PageStructure) -> list[dict[str, Any]]:
    """Every placement the teacher can choose for this page (for «Endre plassering»)."""
    out: list[dict[str, Any]] = [anchor_for(structure, None, "page_start").as_dict()]
    seen: set[int] = {-1}
    for section in structure.sections:
        kinds = ("after_intro", "end_of_section") if section.heading_index is None else (
            "under_heading", "after_explanation", "end_of_section")
        for placement in kinds:
            anchor = anchor_for(structure, section.id, placement)
            if anchor.block_index in seen:
                continue
            seen.add(anchor.block_index)
            out.append(anchor.as_dict())
    return out


def resolve(structure: PageStructure, anchor: Anchor) -> int:
    """Offset in ``structure.html`` where the figure goes. Raises :class:`PlacementError` when the anchor's block no
    longer exists (the page was changed): the illustration must then be placed again."""
    if anchor.block_index < 0:
        container = structure.container
        return container.start_end if container.tag != "#root" else 0
    candidates: list[Block] = [b for b in structure.blocks if b.tag == anchor.block_tag
                               and b.fingerprint == anchor.block_hash]
    if not candidates:
        raise PlacementError("Fant ikke avsnittet illustrasjonen skulle stå ved. Siden er endret – velg plassering på nytt.")
    block = min(candidates, key=lambda b: abs(b.index - anchor.block_index))
    return block.span.end


def figure_html(*, marker: str, src: str, alt: str, caption: str | None, width: int | None, height: int | None,
                decorative: bool, api_endpoint: str | None = None) -> str:
    """Semantic, Canvas-safe HTML (``figure``/``figcaption`` are on Canvas' sanitiser allowlist; inline styles use
    only allowed properties). Responsive: the image scales down with the page."""
    alt_value = "" if decorative else alt.strip()
    attrs = [f'src="{htmllib.escape(src, quote=True)}"', f'alt="{htmllib.escape(alt_value, quote=True)}"']
    if width and height:
        attrs.append(f'width="{int(width)}" height="{int(height)}"')
    if api_endpoint:
        attrs.append(f'data-api-endpoint="{htmllib.escape(api_endpoint, quote=True)}" data-api-returntype="File"')
    if decorative:
        attrs.append('role="presentation"')
    attrs.append('style="display: block; max-width: 100%; height: auto; margin: 0 auto;"')
    parts = [f'<figure class="emneklar-illustration" {MARKER_ATTR}="{htmllib.escape(marker, quote=True)}" '
             'style="margin: 1.5em auto; max-width: 100%; text-align: center;">',
             f"<img {' '.join(attrs)}>"]
    if caption and caption.strip() and not decorative:
        parts.append(f'<figcaption style="margin-top: 0.5em; font-size: 0.95em; text-align: left;">'
                     f"{htmllib.escape(caption.strip())}</figcaption>")
    parts.append("</figure>")
    return "".join(parts)


@dataclass
class Insertion:
    marker: str
    anchor: Anchor
    html: str


def insert(html: str, insertions: list[Insertion]) -> str:
    """Splice figures into the original HTML. Figures already on the page (same marker) are not inserted again."""
    structure = parse_page(html)
    if not structure.reliable:
        raise PlacementError("Sidens HTML er for uryddig til at EmneKlar trygt kan sette inn bilder automatisk: "
                             + "; ".join(structure.scan.problems[:3]))
    existing = set(structure.emneklar_markers())
    points: list[tuple[int, int, str]] = []
    for order, item in enumerate(insertions):
        if item.marker in existing:
            continue
        points.append((resolve(structure, item.anchor), order, item.html))
    out = html
    # Splice from the end so earlier offsets stay valid; at the same offset keep the given order.
    for offset, _order, fragment in sorted(points, key=lambda p: (p[0], p[1]), reverse=True):
        out = out[:offset] + "\n" + fragment + "\n" + out[offset:]
    return out


DUPLICATE_SEPARATOR = "\n<!-- emneklar: same marker again -->\n"


def find_figures(html: str) -> dict[str, str]:
    """marker → normalised HTML of the EmneKlar figure(s) on the page. When the teacher has copied a figure, every
    occurrence is included, so the value differs from what EmneKlar inserted and undo treats it as a change."""
    result = scan(html or "")
    found: dict[str, list[str]] = {}
    for span in result.root.walk():
        marker = span.attr(MARKER_ATTR)
        if marker:
            found.setdefault(marker, []).append(normalise_html(html[span.start:span.end]))
    return {marker: DUPLICATE_SEPARATOR.join(parts) for marker, parts in found.items()}


def remove(html: str, markers: set[str] | None = None) -> tuple[str, list[str]]:
    """Remove EmneKlar figures (all, or those in ``markers``). Nothing else on the page is touched. Refuses when the
    HTML is too broken to know where a figure ends (an unclosed element would otherwise take the rest with it)."""
    result = scan(html or "")
    if not result.reliable:
        raise PlacementError("Sidens HTML er for uryddig til at EmneKlar trygt kan fjerne figurer automatisk: "
                             + "; ".join(result.problems[:3]))
    spans: list[tuple[Any, str]] = []
    for span in result.root.walk():
        marker = span.attr(MARKER_ATTR)
        if not marker or (markers is not None and marker not in markers):
            continue
        if any(s.start <= span.start and span.end <= s.end for s, _ in spans):
            continue  # only the outermost marked element is removed
        spans.append((span, marker))
    out = html
    removed = []
    for span, marker in sorted(spans, key=lambda item: item[0].start, reverse=True):
        start, end = span.start, span.end
        if out[end:end + 1] == "\n":
            end += 1
        if start > 0 and out[start - 1:start] == "\n":
            start -= 1
        out = out[:start] + out[end:]
        removed.append(marker)
    return out, removed


def text_preserved(before: str, after: str) -> bool:
    """True when removing EmneKlar figures from ``after`` gives exactly ``before`` (modulo whitespace)."""
    stripped, _ = remove(after)
    collapse = re.compile(r"\s+")
    return collapse.sub(" ", stripped).strip() == collapse.sub(" ", remove(before)[0]).strip()
