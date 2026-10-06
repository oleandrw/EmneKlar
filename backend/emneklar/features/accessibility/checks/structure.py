"""Headings (1.3.1, 2.4.6), links (2.4.4), tables (1.3.1) and lists (1.3.1).

Canvas renders the page title as <h1>, so content headings should start at
<h2>. Heading level skips are *not* a WCAG failure by themselves (no W3C
failure technique) and are reported as «Bør vurderes»; text that only looks
like a heading (F2) is a likely failure.
"""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

from bs4 import NavigableString, Tag

from emneklar.core.canvas.html import accessible_name, context_text, element_path, is_hidden, norm_text, text_of
from emneklar.features.accessibility.checks.base import ContentDoc, Issue, fix

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
BLOCKS = ("p", "ul", "ol", "table", "div", "blockquote", "pre", "figure", "dl", "h1", "h2", "h3", "h4", "h5", "h6")

# ---------------------------------------------------------------------------- headings


def _is_bold_only(p: Tag) -> bool:
    """True when every non-whitespace piece of text in the paragraph is bold or large."""
    texts = [t for t in p.find_all(string=True) if norm_text(str(t))]
    if not texts:
        return False
    for t in texts:
        node = t.parent
        styled = False
        while isinstance(node, Tag) and node is not p.parent:
            if node.name in ("strong", "b"):
                styled = True
                break
            style = str(node.get("style") or "").lower().replace(" ", "")
            size = re.search(r"font-size:(\d+(?:\.\d+)?)(px|pt|em|rem)", style)
            if "font-weight:bold" in style or "font-weight:700" in style:
                styled = True
                break
            if size:
                value, unit = float(size.group(1)), size.group(2)
                px = value * {"px": 1, "pt": 1.333, "em": 16, "rem": 16}[unit]
                if px >= 20:
                    styled = True
                    break
            node = node.parent
        if not styled:
            return False
    return True


def _next_block(el: Tag) -> Tag | None:
    sibling = el.next_sibling
    while sibling is not None:
        if isinstance(sibling, Tag):
            return sibling
        if isinstance(sibling, NavigableString) and norm_text(str(sibling)):
            return None
        sibling = sibling.next_sibling
    return None


def check_headings(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    soup = doc.soup
    headings = [h for h in soup.find_all(HEADINGS) if not is_hidden(h)]
    previous = 1  # Canvas renders the title as h1
    for h in headings:
        level = int(h.name[1])
        text = text_of(h)
        path = element_path(h)
        if not text and not h.find("img", alt=True):
            issues.append(Issue("UU-HEAD-EMPTY", f"Tom overskrift (nivå {level}).", element=h,
                                fix=fix("remove_element", "Fjern den tomme overskriften", path=path)))
            continue
        if level == 1:
            issues.append(Issue(
                "UU-HEAD-H1", f"«{text[:80]}» er kodet som overskrift nivå 1.", element=h,
                fix=fix("demote_headings", "Senk alle overskrifter ett nivå (h1 → h2 …)")))
        elif level > previous + 1:
            target = previous + 1
            issues.append(Issue(
                "UU-HEAD-SKIP", f"«{text[:80]}» er nivå {level}, men forrige overskrift er nivå {previous}.",
                element=h, evidence={"level": level, "previous": previous},
                fix=fix("change_heading_level", f"Endre til overskrift nivå {target}", path=path, level=target)))
        if len(text) > 120:
            issues.append(Issue("UU-HEAD-LONG", f"Overskriften er {len(text)} tegn lang.", element=h,
                                key=f"long:{path}"))
        previous = level

    # Text that looks like a heading but is not marked up as one (F2).
    last_level = 1
    for el in soup.find_all(["p", *HEADINGS]):
        if el.name in HEADINGS:
            last_level = int(el.name[1])
            continue
        if el.find_parent(["li", "td", "th", "table", "blockquote"]) or is_hidden(el):
            continue
        text = text_of(el)
        if not (3 <= len(text) <= 80) or text.endswith((".", "!", "?", ",")) or el.find("a"):
            continue
        if not _is_bold_only(el):
            continue
        following = _next_block(el)
        if following is None or following.name not in BLOCKS or not text_of(following):
            continue
        suggested = 2 if last_level <= 1 else last_level  # same level as the section it follows
        issues.append(Issue(
            "UU-HEAD-FAKE", f"«{text}» ser ut som en overskrift, men er formatert som vanlig tekst.", element=el,
            confidence="medium",
            fix=fix("convert_to_heading", "Gjør om til ekte overskrift", path=element_path(el), level=suggested)))

    words = len(text_of(soup).split())
    if not headings and words > 400:
        issues.append(Issue("UU-HEAD-NONE", f"Siden har {words} ord, men ingen overskrifter.", key="no-headings",
                            evidence={"words": words}))
    return issues


# ------------------------------------------------------------------------------------- links

VAGUE = {
    "klikk her", "trykk her", "her", "les mer", "mer", "les mer her", "se her", "lenke", "link", "denne lenken",
    "lenken", "klikk", "trykk", "click here", "here", "read more", "more", "this link", "link here", "info",
    "mer info", "mer informasjon", "gå hit", "dette", "se mer", "les her", "last ned", "download", "åpne",
    "open", "video", "pdf", "fil", "file",
}
STOP = {"og", "i", "på", "til", "av", "for", "med", "er", "en", "et", "den", "det", "de", "som", "kan", "du", "the",
        "and", "to", "of", "a", "in", "is", "for", "you", "your", "her", "klikk", "trykk", "les", "mer", "se"}


def _meaningful_context(link: Tag, name: str) -> int:
    context = context_text(link).lower()
    if name:
        context = context.replace(name.lower(), " ", 1)
    words = [w for w in re.findall(r"[a-zæøåA-ZÆØÅ0-9-]{3,}", context) if w.lower() not in STOP]
    return len(words)


def _normalise_href(href: str) -> str:
    parts = urlsplit(href)
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}?{parts.query}"


def check_links(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    soup = doc.soup
    by_name: dict[str, set[str]] = defaultdict(set)
    first_by_name: dict[str, Tag] = {}
    for a in soup.find_all("a"):
        href = str(a.get("href") or "").strip()
        if not href or is_hidden(a):
            continue
        name = accessible_name(a, soup)
        path = element_path(a)
        if not name:
            images = a.find_all("img")
            if images and all(img.has_attr("alt") and not norm_text(str(img.get("alt"))) for img in images):
                continue  # reported by UU-IMG-EMPTY-ALT-LINK
            removable = not a.find(True) and not norm_text(a.get_text())
            issues.append(Issue(
                "UU-LINK-EMPTY", f"Lenken til {href[:120]} har ikke noe tilgjengelig navn.", element=a,
                evidence={"href": href},
                fix=fix("remove_element", "Fjern den tomme lenken", path=path) if removable
                else fix("set_link_text", "Legg inn lenketekst", path=path)))
            continue
        lowered = name.lower().strip(" .:!»«\"'")
        if lowered in VAGUE:
            meaningful = _meaningful_context(a, name)
            if meaningful >= 4:
                issues.append(Issue(
                    "UU-LINK-VAGUE-CONTEXT", f"Lenketeksten «{name}» er vag, men teksten rundt forklarer trolig målet.",
                    element=a, context=context_text(a), confidence="medium", evidence={"href": href},
                    fix=fix("set_link_text", "Skriv en beskrivende lenketekst", path=path)))
            else:
                issues.append(Issue(
                    "UU-LINK-VAGUE", f"Lenketeksten «{name}» forklarer ikke hvor lenken går.", element=a,
                    context=context_text(a), confidence="medium", evidence={"href": href},
                    fix=fix("set_link_text", "Skriv en beskrivende lenketekst", path=path)))
            continue
        if re.match(r"^(https?://|www\.)\S+$", name) and len(name) > 30:
            issues.append(Issue(
                "UU-LINK-RAWURL", "Lenketeksten er en nettadresse.", element=a, evidence={"href": href},
                fix=fix("set_link_text", "Skriv en beskrivende lenketekst", path=path)))
            continue
        if not href.startswith(("#", "mailto:", "tel:")):
            by_name[lowered].add(_normalise_href(href))
            first_by_name.setdefault(lowered, a)
    for name, targets in by_name.items():
        if len(targets) > 1:
            issues.append(Issue(
                "UU-LINK-SAME-TEXT", f"{len(targets)} lenker med teksten «{name[:60]}» går til ulike steder.",
                element=first_by_name[name], key=f"same:{name}", confidence="medium",
                evidence={"targets": sorted(targets)[:10]}))
    return issues


# ------------------------------------------------------------------------------------ tables


def _rows(table: Tag) -> list[Tag]:
    return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]


def _span(cell: Tag, attr: str) -> int:
    value = str(cell.get(attr) or "1").strip()
    return int(value) if value.isdigit() else 1


def _cells(tr: Tag) -> list[Tag]:
    return [c for c in tr.find_all(["td", "th"], recursive=False)]


def check_tables(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    for table in doc.soup.find_all("table"):
        if is_hidden(table):
            continue
        path = element_path(table)
        role = str(table.get("role") or "").lower()
        rows = _rows(table)
        cells = [_cells(r) for r in rows]
        max_cols = max((len(c) for c in cells), default=0)
        has_th = table.find("th") is not None
        if role in ("presentation", "none"):
            if has_th or table.find("caption"):
                issues.append(Issue("UU-TABLE-LAYOUT", "Tabellen er merket som layout, men har overskriftsceller "
                                    "eller tabelltittel.", element=table, key=f"layout:{path}"))
            continue
        if not text_of(table) and not table.find("img"):
            issues.append(Issue("UU-TABLE-EMPTY", "Tabellen er tom.", element=table))
            continue
        blocks = table.find_all(["p", "img", "ul", "ol", "h2", "h3", "h4", "table", "iframe"])
        nested = any(b.name == "table" for b in blocks)
        if nested or ((len(rows) == 1 or max_cols == 1) and blocks):
            issues.append(Issue("UU-TABLE-LAYOUT", "Tabellen ser ut til å brukes til å plassere innhold.",
                                element=table, confidence="medium", key=f"layout:{path}",
                                evidence={"rows": len(rows), "columns": max_cols}))
            continue
        if not has_th and len(rows) >= 2 and max_cols >= 2:
            first = cells[0] if cells else []
            bold_header = bool(first) and all(c.find(["strong", "b"]) and text_of(c.find(["strong", "b"])) ==
                                              text_of(c) for c in first if text_of(c))
            issues.append(Issue(
                "UU-TABLE-NO-HEADERS",
                f"Tabellen ({len(rows)} rader × {max_cols} kolonner) har ingen overskriftsceller.",
                element=table, confidence="high" if bold_header else "medium",
                evidence={"rows": len(rows), "columns": max_cols, "first_row_bold": bold_header},
                fix=fix("table_headers", "Gjør første rad til kolonneoverskrifter", path=path)))
        if has_th:
            header_row = bool(cells) and all(c.name == "th" for c in cells[0])
            header_col = len(cells) > 1 and all(r and r[0].name == "th" for r in cells[1:])
            for r_index, row in enumerate(cells):
                for c_index, cell in enumerate(row):
                    if cell.name == "th" and not text_of(cell) and not cell.find("img"):
                        if r_index == 0 and c_index == 0 and header_row and header_col:
                            continue  # empty top-left corner is fine
                        issues.append(Issue("UU-TABLE-EMPTY-HEADER", "Tom overskriftscelle.", element=cell))
            if header_row and header_col and any(not th.get("scope") for th in table.find_all("th")):
                issues.append(Issue("UU-TABLE-SCOPE", "Tabellen har rad- og kolonneoverskrifter uten scope.",
                                    element=table, key=f"scope:{path}",
                                    fix=fix("table_scope", "Legg til scope på overskriftscellene", path=path)))
            if not table.find("caption") and len(rows) >= 3:
                issues.append(Issue("UU-TABLE-CAPTION", "Datatabellen har ingen tabelltittel.", element=table,
                                    key=f"caption:{path}",
                                    fix=fix("table_caption", "Legg til tabelltittel", path=path)))
        merged = any(_span(c, "colspan") > 1 or _span(c, "rowspan") > 1 for row in cells for c in row)
        thead = table.find("thead")
        multi_header = thead is not None and len(thead.find_all("tr")) > 1
        if merged or multi_header:
            issues.append(Issue("UU-TABLE-COMPLEX", "Tabellen har sammenslåtte celler eller flere overskriftsnivåer.",
                                element=table, key=f"complex:{path}"))
    return issues


# ------------------------------------------------------------------------------------- lists

MARKER = re.compile(r"^\s*([-–—•*·▪◦●]|\d{1,2}[.)]|[a-zA-Z][.)])\s+\S")


def _marker_kind(text: str) -> str | None:
    match = MARKER.match(text)
    if not match:
        return None
    return "ordered" if match.group(1)[0].isalnum() else "unordered"


def check_lists(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    soup = doc.soup
    seen: set[int] = set()
    for p in soup.find_all("p"):
        if id(p) in seen or p.find_parent(["li", "table"]):
            continue
        if p.find("br"):
            # A single paragraph with <br>-separated marker lines.
            lines = [norm_text(x) for x in p.get_text("\n").split("\n") if norm_text(x)]
            marked = [ln for ln in lines if _marker_kind(ln)]
            if len(marked) >= 2 and len(marked) >= len(lines) - 1:
                issues.append(Issue(
                    "UU-LIST-FAKE", f"{len(marked)} linjer i ett avsnitt ser ut som en liste.", element=p,
                    confidence="medium",
                    fix=fix("convert_fake_list", "Gjør om til ekte liste", paths=[element_path(p)],
                            ordered=_marker_kind(marked[0]) == "ordered", mode="br")))
                continue
        kind = _marker_kind(text_of(p))
        if kind is None:
            continue
        run = [p]
        sibling = p.next_sibling
        while sibling is not None:
            if isinstance(sibling, NavigableString):
                if norm_text(str(sibling)):
                    break
                sibling = sibling.next_sibling
                continue
            if isinstance(sibling, Tag) and sibling.name == "p" and _marker_kind(text_of(sibling)) == kind:
                run.append(sibling)
                sibling = sibling.next_sibling
                continue
            break
        for el in run:
            seen.add(id(el))
        if len(run) >= 2:
            issues.append(Issue(
                "UU-LIST-FAKE", f"{len(run)} avsnitt starter med listetegn, men er ikke kodet som liste.", element=p,
                confidence="medium" if kind == "ordered" else "high",
                fix=fix("convert_fake_list", "Gjør om til ekte liste", paths=[element_path(x) for x in run],
                        ordered=kind == "ordered", mode="paragraphs")))
    for li in soup.find_all("li"):
        if not text_of(li) and not li.find(["img", "iframe", "ul", "ol"]):
            issues.append(Issue("UU-LIST-EMPTY-ITEM", "Tomt listepunkt.", element=li,
                                fix=fix("remove_element", "Fjern det tomme listepunktet", path=element_path(li))))
    for lst in soup.find_all(["ul", "ol"]):
        bad = [c for c in lst.children if isinstance(c, Tag) and c.name not in ("li", "script", "template")]
        if bad:
            issues.append(Issue(
                "UU-LIST-NESTING", f"Listen inneholder {', '.join(sorted({b.name for b in bad}))} direkte, "
                "utenfor et listepunkt.", element=lst,
                fix=fix("fix_list_nesting", "Flytt underlisten inn i listepunktet", path=element_path(lst))))
    return issues
