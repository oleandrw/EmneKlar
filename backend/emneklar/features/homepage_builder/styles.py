"""Visual styles for generated course homepages.

Only CSS properties Canvas keeps are used (docs/CANVAS_API.md) – e.g. no
``font-weight`` (use <strong>), no ``box-shadow``. Every colour pair meets
WCAG 2.2 AA contrast (tested in tests/test_homepage_builder.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    description: str
    text: str
    heading: str
    link: str
    banner_bg: str
    banner_text: str
    card_bg: str
    card_border: str
    section_bg: str
    accent: str  # decorative borders only (not used for text)
    heading_font: str = ""
    radius: str = "8px"


STYLES: dict[str, Style] = {s.key: s for s in (
    Style("academic", "Ren og akademisk", "Rolig og tydelig, med mørkeblått banner og klassiske overskrifter.",
          text="#1f2933", heading="#1f3a5f", link="#1d4f91", banner_bg="#1f3a5f", banner_text="#ffffff",
          card_bg="#ffffff", card_border="#c9d3e0", section_bg="#f3f6fa", accent="#1f3a5f",
          heading_font="Georgia, 'Times New Roman', serif", radius="4px"),
    Style("modern", "Moderne og visuell", "Fargerike kort og tydelige blokker med god luft.",
          text="#1c2430", heading="#0b4f5c", link="#0a5a78", banner_bg="#0b4f5c", banner_text="#ffffff",
          card_bg="#ffffff", card_border="#b9d9df", section_bg="#eaf5f7", accent="#0e7c86", radius="12px"),
    Style("warm", "Varm og innbydende", "Varme farger og en personlig tone.",
          text="#2d2a26", heading="#7a3015", link="#8a3a1a", banner_bg="#8a3a1a", banner_text="#ffffff",
          card_bg="#fffaf5", card_border="#ecd3bf", section_bg="#fdf1e7", accent="#c2672f", radius="10px"),
    Style("minimal", "Minimalistisk", "Mye hvit plass, tynne linjer og lite farge.",
          text="#222222", heading="#222222", link="#1a56b8", banner_bg="#ffffff", banner_text="#222222",
          card_bg="#ffffff", card_border="#d6d6d6", section_bg="#ffffff", accent="#222222", radius="0"),
)}

#: Marking of content the teacher must fill in or verify (same in every style, AA contrast).
PLACEHOLDER = {"bg": "#fff4ce", "border": "#8a6d00", "text": "#3d3000"}
AI_MARK = {"bg": "#f4effa", "border": "#6b3fa0", "text": "#2e1a47"}
