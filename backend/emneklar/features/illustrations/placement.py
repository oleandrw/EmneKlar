"""Deterministic placement and insertion of illustrations in Canvas page HTML.

The page's *insertion points* are the boundaries between units (see :mod:`structure`): never between an introductory
sentence and its list, a heading and its first paragraph, an example and its explanation, or an image and its caption.
The AI chooses one of these points (by id) together with what the image should show; this module turns it into a
concrete, robust anchor (the block's tag + a hash of its text, not a fragile path or a text search) and inserts a
``<figure>`` by splicing the original HTML at that block boundary. Before inserting, the point is checked again on the
page as it is now. Existing content is never rewritten, moved or deleted. Removal (undo) cuts out exactly the figures
EmneKlar inserted – identified by ``data-emneklar-illustration`` – so everything else the teacher has changed in the
meantime is kept.
"""

from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass
from typing import Any

from emneklar.core.changes.appliers import normalise_html
from emneklar.features.illustrations.htmlspans import scan
from emneklar.features.illustrations.structure import (
    MARKER_ATTR,
    PageStructure,
    Section,
    Unit,
    looks_like_task,
    parse_page,
)

PLACEMENTS = {
    "page_start": "I starten av siden",
    "after_intro": "Etter innledningen",
    "under_heading": "Etter første avsnitt under overskriften",
    "after_explanation": "Etter den faglige forklaringen",
    "end_of_section": "Mellom to tekstseksjoner (etter seksjonen)",
    "before_task": "Før oppgaven",
}


class PlacementError(Exception):
    pass


@dataclass
class Anchor:
    """Insert *after* block ``block_index`` (or at the start of the container when ``block_index`` is -1).

    ``label`` describes the spot in the page's own words («Etter punktlisten «…», før «…»»); ``before_text`` and
    ``after_text`` are the text right before and after it (shown with the preview, so the teacher sees the image in
    its surroundings)."""

    placement: str
    section_id: str | None
    block_index: int
    block_tag: str | None = None
    block_hash: str | None = None
    block_text: str = ""
    section_title: str = ""
    warning: str | None = None
    label: str = ""
    before_text: str = ""
    after_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"placement": self.placement,
                "placement_label": self.label or PLACEMENTS.get(self.placement, self.placement),
                "section_id": self.section_id, "section_title": self.section_title, "block_index": self.block_index,
                "block_tag": self.block_tag, "block_hash": self.block_hash, "block_text": self.block_text,
                "warning": self.warning, "label": self.label, "before_text": self.before_text,
                "after_text": self.after_text}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Anchor:
        return cls(placement=str(data.get("placement") or "end_of_section"), section_id=data.get("section_id"),
                   block_index=int(data.get("block_index", -1)), block_tag=data.get("block_tag"),
                   block_hash=data.get("block_hash"), block_text=str(data.get("block_text") or ""),
                   section_title=str(data.get("section_title") or ""), warning=data.get("warning"),
                   label=str(data.get("label") or ""), before_text=str(data.get("before_text") or ""),
                   after_text=str(data.get("after_text") or ""))


# -------------------------------------------------------------------------------- insertion points

#: How the spot is described: the kind of the unit's last block.
KIND_WORDS = {"paragraph": "avsnittet", "table": "tabellen", "quote": "sitatet", "code": "kodeeksempelet",
              "media": "videoen", "image": "bildet", "figure": "figuren", "component": "innholdsboksen",
              "rule": "skillelinjen", "other": "innholdet", "heading": "overskriften"}
NEAR_IMAGE = "Plasseringen ligger rett ved et eksisterende bilde eller en video."


@dataclass
class Point:
    """A place an illustration can go: after block ``after`` – the last block of a unit (-1 = the top of the page)."""

    id: str
    after: int  # block index; -1 = top of the page
    placement: str
    section: Section | None
    label: str
    before_text: str
    after_text: str
    next_heading: str
    near_image: bool

    def anchor(self, structure: PageStructure) -> Anchor:
        section_id = self.section.id if self.section else None
        title = self.section.title if self.section else ""
        anchor = Anchor(placement=self.placement, section_id=section_id, block_index=self.after, section_title=title,
                        label=self.label, before_text=self.before_text, after_text=self.after_text,
                        warning=NEAR_IMAGE if self.near_image else None)
        if self.after >= 0:
            block = structure.blocks[self.after]
            anchor.block_tag, anchor.block_hash, anchor.block_text = block.tag, block.fingerprint, block.text[:140]
        return anchor

    def for_ai(self) -> dict[str, Any]:
        """The point as the planner sees it: where it is, the text it follows and what comes next."""
        return {"id": self.id, "section_id": self.section.id if self.section else None,
                "section_title": self.section.title if self.section else "", "type": self.placement,
                "after_text": self.before_text or "(toppen av siden)",
                "next": f"Neste deloverskrift: «{self.next_heading}»" if self.next_heading
                else (self.after_text or "(slutten av siden)")}


def _words(text: str, count: int) -> str:
    words = text.split()
    return " ".join(words[:count]) + (" …" if len(words) > count else "")


def _tail(text: str, limit: int = 220) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else "… " + text[-limit:].split(" ", 1)[-1]


def _head(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _kind_word(structure: PageStructure, index: int) -> str:
    block = structure.blocks[index]
    if block.kind == "list":
        return "den nummererte listen" if block.tag == "ol" else "punktlisten"
    return KIND_WORDS.get(block.kind, "innholdet")


def insertion_points(structure: PageStructure) -> list[Point]:
    """Every place an illustration may go, in page order: the top of the page, then after each unit that has content
    (never right under a bare heading). ``p0`` is always the top of the page."""
    blocks, units = structure.blocks, structure.units
    first_heading = next((b.text for b in blocks[:1] if b.kind == "heading"), "")
    top = Point(id="p0", after=-1, placement="page_start", section=structure.sections[0] if structure.sections else None,
                label="Øverst på siden", before_text="", after_text=_head(structure.unit_text(units[0])) if units else "",
                next_heading=first_heading, near_image=bool(blocks) and blocks[0].kind in ("image", "figure", "media"))
    points = [top]
    for position, unit in enumerate(units):
        if all(blocks[i].kind == "heading" for i in range(unit.first, unit.last + 1)):
            continue
        following: Unit | None = units[position + 1] if position + 1 < len(units) else None
        section = structure.section_of(unit.last)
        next_block = blocks[following.first] if following else None
        next_heading = next_block.text if next_block is not None and next_block.kind == "heading" else ""
        if section is None or section.heading_index is None:
            placement = "after_intro"
        elif following is None or next_heading:
            placement = "end_of_section"
            following_section = structure.section_of(following.first) if following else None
            if following_section is not None and _looks_like_task(structure, following_section):
                placement = "before_task"
        else:
            placement = "after_explanation"
        last = blocks[unit.last]
        label = f"Etter {_kind_word(structure, unit.last)}"
        if last.text:
            label += f" «{_words(last.text, 8)}»"
        if next_heading:
            label += f", før «{_words(next_heading, 10)}»"
        elif following is None:
            label += ", nederst på siden"
        # Right after an image or video (with its caption), or right before one: two pictures in a row.
        visual = ("image", "figure", "media")
        near = last.kind in visual or "caption" in unit.reasons or (following is not None and (
            blocks[following.first].kind in visual or "caption" in following.reasons))
        points.append(Point(id=f"p{len(points)}", after=unit.last, placement=placement, section=section, label=label,
                            before_text=_tail(structure.unit_text(unit)),
                            after_text=_head(structure.unit_text(following)) if following else "",
                            next_heading=next_heading, near_image=near))
    return points


def _looks_like_task(structure: PageStructure, section: Section) -> bool:
    return looks_like_task(section.title) or any(looks_like_task(structure.blocks[i].text[:200])
                                                 for i in section.block_indices[:2])


def planner_points(structure: PageStructure) -> list[Point]:
    """The points the planner may choose from: not right next to an existing image or video (unless nothing else is
    left), and the top of the page only as an opening image."""
    points = insertion_points(structure)
    clear = [p for p in points if not p.near_image]
    return clear or points


def anchor_for(structure: PageStructure, section_id: str | None, placement: str) -> Anchor:
    """A placement *type* in a section turned into an insertion point (used when no point id is given, e.g. for older
    proposals). Always lands between units; falls back to the nearest sensible point."""
    points = insertion_points(structure)
    if placement not in PLACEMENTS:
        placement = "end_of_section"
    if not structure.blocks or placement == "page_start" or len(points) == 1:
        return points[0].anchor(structure)
    section = structure.section(section_id or "") or structure.sections[0]
    inside = [p for p in points[1:] if p.section is not None and p.section.id == section.id]
    if placement == "before_task":
        position = structure.sections.index(section)
        previous = structure.sections[position - 1] if position > 0 else None
        earlier = [p for p in points[1:] if previous is not None and p.section is not None
                   and p.section.id == previous.id]
        return (earlier[-1] if earlier else points[0]).anchor(structure)
    if placement == "after_intro":
        intro = [p for p in points[1:] if p.section is not None and p.section.heading_index is None]
        return (intro[0] if intro else points[1]).anchor(structure)
    if not inside:
        before = [p for p in points if p.after < (section.first if section.first is not None else 0)]
        return (before[-1] if before else points[0]).anchor(structure)
    if placement == "under_heading":
        return inside[0].anchor(structure)
    if placement == "after_explanation":
        # The end of the first run of explanatory text: the first point followed by something other than a paragraph.
        for point in inside:
            nxt = point.after + 1
            if nxt >= len(structure.blocks) or structure.blocks[nxt].kind != "paragraph":
                return point.anchor(structure)
    return inside[-1].anchor(structure)


def candidate_anchors(structure: PageStructure) -> list[dict[str, Any]]:
    """Every placement the teacher can choose for this page (for «Endre plassering»), in page order."""
    return [point.anchor(structure).as_dict() for point in insertion_points(structure)]


def resolve(structure: PageStructure, anchor: Anchor) -> int:
    """Offset in ``structure.html`` where the figure goes – checked on the page as it is now. Raises
    :class:`PlacementError` when the anchor's block no longer exists, or when the page has changed so that the
    figure would now split text that belongs together: the illustration must then be placed again."""
    if anchor.block_index < 0:
        container = structure.container
        return container.start_end if container.tag != "#root" else 0
    candidates = [b for b in structure.blocks if b.tag == anchor.block_tag and b.fingerprint == anchor.block_hash]
    if not candidates:
        raise PlacementError("Fant ikke avsnittet illustrasjonen skulle stå ved. Siden er endret – velg plassering på nytt.")
    block = min(candidates, key=lambda b: abs(b.index - anchor.block_index))
    unit = structure.unit_of(block.index)
    if unit is not None and unit.last != block.index:
        raise PlacementError("Plasseringen ville nå delt opp tekst som hører sammen (for eksempel en innledende setning "
                             "og listen etter den). Velg plassering på nytt.")
    return block.span.end


DEFAULT_MAX_WIDTH = 900
#: The tallest an illustration is shown in the text column (px): wide images use the full width, square and tall
#: images are narrower, so no image fills the whole screen.
MAX_DISPLAY_HEIGHT = 560
MIN_DISPLAY_WIDTH = 360
EAGER_PLACEMENTS = ("page_start", "after_intro")


def display_width(max_width: int, width: int | None, height: int | None) -> int:
    """Maximum display width: as wide as the text column allows (``max_width``), but never taller than
    ``MAX_DISPLAY_HEIGHT`` – so a 16:9 or 3:2 image uses the column, a square or portrait image is narrower."""
    if not width or not height:
        return max_width
    by_height = round(MAX_DISPLAY_HEIGHT * width / height)
    return max(min(max_width, MIN_DISPLAY_WIDTH), min(max_width, by_height))


def lazy_for(anchor: Anchor) -> bool:
    """Lazy loading for images further down the page; images at the top load straight away."""
    return anchor.placement not in EAGER_PLACEMENTS and anchor.block_index > 1


def figure_html(*, marker: str, src: str, alt: str, caption: str | None, width: int | None, height: int | None,
                decorative: bool, max_width: int = DEFAULT_MAX_WIDTH, lazy: bool = False,
                credit: str | None = None) -> str:
    """Semantic, responsive, Canvas-safe HTML: ``figure`` > ``img`` + ``figcaption`` (on Canvas' sanitiser allowlist).

    The figure is at most ``max_width`` px wide and shrinks with the screen; the image fills the figure, so the
    caption below it follows the image's width and is left-aligned. The credit line (e.g. «KI-generert illustrasjon»)
    is a separate element after the caption, never part of it. ``loading="lazy"`` is set for images further down the
    page (Canvas may remove it – what Canvas kept is checked after publishing)."""
    alt_value = "" if decorative else alt.strip()
    attrs = [f'src="{htmllib.escape(src, quote=True)}"', f'alt="{htmllib.escape(alt_value, quote=True)}"']
    if width and height:
        attrs.append(f'width="{int(width)}" height="{int(height)}"')
    if lazy:
        attrs.append('loading="lazy"')
    if decorative:
        attrs.append('role="presentation"')
    attrs.append('style="display: block; width: 100%; max-width: 100%; height: auto;"')
    shown = display_width(max_width, width, height)
    parts = [f'<figure class="emneklar-illustration" {MARKER_ATTR}="{htmllib.escape(marker, quote=True)}" '
             f'style="margin: 1.5em auto; max-width: {int(shown)}px;">',
             f"<img {' '.join(attrs)}>"]
    caption_text = caption.strip() if caption and caption.strip() and not decorative else ""
    credit_text = (credit or "").strip()
    if caption_text or credit_text:
        inner = htmllib.escape(caption_text)
        if credit_text:
            inner += (f'<small class="emneklar-credit" style="display: block; margin-top: 0.25em; font-size: 0.85em;">'
                      f"{htmllib.escape(credit_text)}</small>")
        parts.append(f'<figcaption style="margin-top: 0.5em; font-size: 0.95em; text-align: left;">{inner}</figcaption>')
    parts.append("</figure>")
    return "".join(parts)


def check_figure(fragment: str | None, *, file_id: str, alt: str, caption: bool, lazy: bool) -> dict[str, Any]:
    """What Canvas kept of a published figure: required parts (figure, image file, alt text, caption) and optional
    attributes (loading, width/height, responsive style)."""
    from bs4 import BeautifulSoup

    if not fragment:
        return {"ok": False, "missing": ["figuren"], "dropped": []}
    soup = BeautifulSoup(fragment, "html.parser")
    figure, img = soup.find("figure"), soup.find("img")
    missing, dropped = [], []
    if figure is None:
        missing.append("figure")
    if img is None or f"/files/{file_id}" not in str(img.get("src") or ""):
        missing.append("bildet (img src)")
    elif str(img.get("alt") if img.get("alt") is not None else "<mangler>").strip() != alt.strip():
        missing.append("alternativ tekst")
    if caption and soup.find("figcaption") is None:
        missing.append("figcaption")
    if img is not None:
        if lazy and img.get("loading") != "lazy":
            dropped.append('loading="lazy"')
        if not (img.get("width") and img.get("height")):
            dropped.append("width/height")
        if "100%" not in str(img.get("style") or ""):
            dropped.append("responsiv bredde (style)")
    if figure is not None and "max-width" not in str(figure.get("style") or ""):
        dropped.append("maksimal bredde (style)")
    return {"ok": not missing, "missing": missing, "dropped": dropped}


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


def excerpt_around(html: str, marker: str, *, units_before: int = 1, units_after: int = 1) -> str | None:
    """The figure with ``marker`` with the text right around it – the unit before and the unit after (a heading with
    its first paragraph counts as one unit) – inside the page's own content wrapper, so it looks as on the page."""
    structure = parse_page(html)
    index = next((b.index for b in structure.blocks if b.emneklar_marker == marker), None)
    if index is None:
        return None
    position = next(i for i, u in enumerate(structure.units) if u.first <= index <= u.last)
    first = structure.units[max(0, position - units_before)]
    last = structure.units[min(len(structure.units) - 1, position + units_after)]
    start, end = structure.blocks[first.first].span.start, structure.blocks[last.last].span.end
    body = html[start:end]
    container = structure.container
    if container.tag != "#root":
        body = html[container.start:container.start_end] + body + f"</{container.tag}>"
    return body


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
