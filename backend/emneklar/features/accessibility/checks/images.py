"""Images (WCAG 1.1.1, 1.4.5).

* Missing ``alt`` → violation. ``alt=""`` is correct for decorative images and
  is only questioned when the image seems informative.
* A caption (figcaption) is not a replacement for alt text.
"""

from __future__ import annotations

import re
from collections import defaultdict

from bs4 import Tag

from emneklar.core.canvas.html import element_path, filename_from_url, norm_text, text_of
from emneklar.features.accessibility.checks.base import ContentDoc, Issue, fix

GENERIC_ALT = {
    "bilde", "bildet", "image", "picture", "pic", "foto", "photo", "illustrasjon", "illustration", "grafikk",
    "graphic", "figur", "figure", "img", "spacer", "blank", "tom", "ikon", "icon", "bilde 1", "image 1", "logo",
    "screenshot", "skjermbilde", "untitled", "uten tittel", "default", "placeholder",
}
FILENAME_RE = re.compile(
    r"(\.(jpe?g|png|gif|bmp|svg|webp|tiff?|heic)$)|(^(img|dsc|dscn|pxl|photo|image|screenshot|skjermbilde)"
    r"[\s_-]?\d{2,})|(^\d{6,}$)|(^[a-f0-9]{16,}$)", re.IGNORECASE)
COMPLEX_HINTS = re.compile(r"diagram|graf|graph|chart|kart|map|infograf|figur|modell|model|flytskjema|flowchart|"
                           r"tidslinje|timeline|tabell|table|plot|kurve|statistikk", re.IGNORECASE)
TEXT_HINTS = re.compile(r"skjermbilde|screenshot|screen[ _-]?shot|plakat|poster|slide|lysbilde|tekst|text|"
                        r"infograf|sitat|quote|flyer|oppslag|scan|skann", re.IGNORECASE)
LONG_ALT = 250


def _decorative(img: Tag) -> bool:
    role = str(img.get("role") or "").lower()
    return role in ("presentation", "none") or img.get("aria-hidden") == "true"


def _has_aria_name(img: Tag) -> bool:
    return bool(norm_text(str(img.get("aria-label") or "")) or img.get("aria-labelledby"))


def _link_parent(img: Tag) -> Tag | None:
    node = img.parent
    while isinstance(node, Tag):
        if node.name == "a" and node.get("href"):
            return node
        if node.name in ("p", "div", "li", "td", "body"):
            return None
        node = node.parent
    return None


def _figcaption(img: Tag) -> str:
    figure = img.find_parent("figure")
    caption = figure.find("figcaption") if figure else None
    return text_of(caption) if caption else ""


def _size(img: Tag) -> int:
    best = 0
    for attr in ("width", "height"):
        value = str(img.get(attr) or "").strip().removesuffix("px")
        if value.isdigit():
            best = max(best, int(value))
    style = str(img.get("style") or "")
    for match in re.finditer(r"(?:width|height)\s*:\s*(\d+)px", style):
        best = max(best, int(match.group(1)))
    return best


def check_images(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    alts: dict[str, set[str]] = defaultdict(set)
    alt_elements: dict[str, list[Tag]] = defaultdict(list)
    for img in doc.soup.find_all("img"):
        src = str(img.get("src") or "")
        filename = filename_from_url(src)
        # Canvas equation images and emoji carry their own alt.
        classes = " ".join(img.get("class") or [])
        if "equation_image" in classes:
            continue
        path = element_path(img)
        caption = _figcaption(img)
        link = _link_parent(img)

        if not img.has_attr("alt"):
            if _decorative(img) or _has_aria_name(img):
                continue
            message = f"Bildet «{filename or 'uten filnavn'}» har ikke alt-attributt."
            if caption:
                message += " Bildeteksten under bildet erstatter ikke alt-teksten."
            issues.append(Issue(
                "UU-IMG-MISSING-ALT", message, element=img,
                evidence={"src": src, "filename": filename, "figcaption": caption or None, "in_link": bool(link)},
                fix=fix("set_alt", "Legg inn alt-tekst eller merk som dekorativt", path=path, src=src)))
            continue

        alt = norm_text(str(img.get("alt") or ""))
        if not alt:
            if link is not None and not text_of(link) and not link.get("aria-label"):
                issues.append(Issue(
                    "UU-IMG-EMPTY-ALT-LINK",
                    f"Bildet «{filename}» er eneste innhold i en lenke til {str(link.get('href'))[:120]}, men har tom "
                    "alt-tekst.",
                    element=img, evidence={"src": src, "href": link.get("href")},
                    fix=fix("set_alt", "Beskriv lenkemålet i alt-teksten", path=path, src=src, link=True)))
                continue
            reasons = []
            if caption:
                reasons.append("bildet har bildetekst")
            if _size(img) >= 300:
                reasons.append("bildet er stort")
            if COMPLEX_HINTS.search(filename):
                reasons.append("filnavnet tyder på diagram eller figur")
            if reasons:
                issues.append(Issue(
                    "UU-IMG-EMPTY-ALT-REVIEW",
                    f"Bildet «{filename}» er merket som dekorativt ({', '.join(reasons)}).",
                    element=img, confidence="medium",
                    evidence={"src": src, "reasons": reasons, "figcaption": caption or None},
                    fix=fix("set_alt", "Skriv alt-tekst (eller behold som dekorativt)", path=path, src=src)))
            continue

        alt_lower = alt.lower().strip(" .:")
        if FILENAME_RE.search(alt) or (filename and alt_lower == filename.lower()):
            issues.append(Issue(
                "UU-IMG-FILENAME-ALT", f"Alt-teksten «{alt}» ser ut som et filnavn.", element=img,
                evidence={"alt": alt, "src": src}, fix=fix("set_alt", "Skriv en beskrivende alt-tekst", path=path, src=src)))
        elif alt_lower in GENERIC_ALT:
            issues.append(Issue(
                "UU-IMG-GENERIC-ALT", f"Alt-teksten «{alt}» beskriver ikke hva bildet viser.", element=img,
                evidence={"alt": alt, "src": src}, fix=fix("set_alt", "Skriv en beskrivende alt-tekst", path=path, src=src)))
        elif len(alt) > LONG_ALT:
            issues.append(Issue(
                "UU-IMG-LONG-ALT", f"Alt-teksten er {len(alt)} tegn lang.", element=img,
                evidence={"length": len(alt)}, fix=fix("set_alt", "Kort ned alt-teksten", path=path, src=src)))
        alts[alt_lower].add(src)
        alt_elements[alt_lower].append(img)

        if COMPLEX_HINTS.search(f"{filename} {alt}"):
            issues.append(Issue(
                "UU-IMG-COMPLEX", f"Bildet «{alt[:80]}» ser ut til å være et diagram, en graf eller et kart.",
                element=img, confidence="medium", key=f"complex:{path}", evidence={"src": src, "alt": alt}))
        if TEXT_HINTS.search(filename):
            issues.append(Issue(
                "UU-IMG-TEXT", f"Filnavnet «{filename}» tyder på at bildet inneholder tekst.", element=img,
                confidence="low", key=f"text:{path}", evidence={"src": src}))

    for alt, sources in alts.items():
        if len(sources) > 1 and alt not in GENERIC_ALT:
            first = alt_elements[alt][0]
            issues.append(Issue(
                "UU-IMG-DUPLICATE-ALT", f"{len(sources)} ulike bilder har alt-teksten «{alt[:80]}».", element=first,
                confidence="medium", key=f"dup:{alt}", evidence={"alt": alt, "sources": sorted(sources)[:10]}))
    return issues
