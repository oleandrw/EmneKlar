"""Applies an Emnedesign profile to Canvas HTML – deterministic, idempotent and content-preserving.

* **Earlier design is removed first** (any profile or version), so applying a design again or switching profile
  never doubles wrappers or accumulates styling. EmneKlar's design is recognised three ways – never by a hidden
  marker alone: the classes ``ek-design*`` / ``data-ek-design`` on its wrappers, ``data-ek-d`` listing the CSS
  properties EmneKlar added to an element, and declarations that exactly match what a profile generates (when Canvas
  or an editor dropped the attributes).
* **The teacher's own inline styles are never removed** – EmneKlar only adds properties an element does not have, so a
  colour with a meaning (red for a warning) stays and is reported.
* **«Behold oppbyggingen»** adds no element and removes, moves or rewrites nothing – except the design wrapper and, on
  the front page, a banner with the course name.
* **«Foreslå bedre oppbygging»** places the existing top-level blocks into sections from a validated plan; it may add a
  section heading from a fixed list of generic labels (never learning goals, criteria or other subject content).
* Only HTML and inline styles Canvas keeps (``core/security/sanitize.py``); no scripts, stylesheets or classes that
  carry the look. Links are underlined (identifiable without colour); standalone links are not turned into buttons.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from emneklar.core.canvas.html import norm_text
from emneklar.core.errors import AppError
from emneklar.features.course_design.profiles import Declarations, Profile, known_declarations, norm_value

MARK = "data-ek-d"  # the CSS properties EmneKlar added to the element (space separated)
ROOT_CLASS = "ek-design"
INSERTED = "data-ek-inserted"  # a section heading EmneKlar added (structure mode)
ROLE_ATTR = "data-ek-role"
BOX_ROLES = {"goals": "box_info", "resources": "box_info", "example": "box_card", "activity": "box_note"}
SECTION_ROLES = ("intro", "goals", "content", "example", "activity", "resources", "summary")
ROLE_LABELS = {"intro": "Introduksjon", "goals": "Læringsmål", "content": "Fagstoff", "example": "Eksempler",
               "activity": "Aktiviteter", "resources": "Ressurser", "summary": "Oppsummering"}
ALLOWED_LABELS = set(ROLE_LABELS.values()) | {"Eksempel", "Aktivitet", "Oppgaver"}
#: Element tag → the roles whose declarations can sit on it (for recognising EmneKlar's styling without data-ek-d).
TAG_ROLES = {
    "div": ("root", "banner", "body", "box_info", "box_card", "box_note"),
    "p": ("lead", "banner_title", "banner_sub"),
    "h2": ("h2", "box_label"), "h3": ("h3", "box_label"), "h4": ("h4", "box_label"),
    "a": ("a", "action"), "table": ("table",), "caption": ("caption",), "th": ("th",), "td": ("td",),
    "blockquote": ("blockquote",), "pre": ("pre",), "hr": ("hr",), "img": ("img",), "iframe": ("iframe",),
    "video": ("video",),
}
STYLED_TAGS = ("h2", "h3", "h4", "table", "caption", "th", "td", "blockquote", "pre", "hr", "img", "iframe", "video")
VIDEO_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com", "media_objects_iframe",
               "media_attachments_iframe")
_DECL = re.compile(r"\s*([a-zA-Z-]+)\s*:\s*([^;]+)")


# -- inline styles ----------------------------------------------------------------------------------------------


def parse_style(style: object) -> Declarations:
    return [(m.group(1).lower(), m.group(2).strip()) for m in _DECL.finditer(str(style or ""))]


def format_style(decls: Declarations) -> str:
    return "; ".join(f"{p}: {v}" for p, v in decls) + (";" if decls else "")


def _classes(el: Tag) -> list[str]:
    value: Any = el.get("class") or []
    return [str(v) for v in value] if isinstance(value, list) else str(value).split()


def _add(el: Tag, decls: Declarations) -> None:
    """Add the declarations the element does not have yet, and list them in ``data-ek-d``."""
    own = parse_style(el.get("style"))
    have = {p for p, _ in own}
    added = [(p, v) for p, v in decls if p not in have]
    if not added:
        return
    el["style"] = format_style(added + own)
    listed = str(el.get(MARK) or "").split()
    el[MARK] = " ".join(dict.fromkeys([*listed, *(p for p, _ in added)]))


def _known_for(el: Tag) -> set[tuple[str, str]]:
    known = known_declarations()
    out: set[tuple[str, str]] = set()
    for role in TAG_ROLES.get(el.name, ()):
        out |= known.get(role, set())
    return out


def _is_root(el: Tag) -> bool:
    if el.name != "div":
        return False
    if ROOT_CLASS in _classes(el) or el.has_attr("data-ek-design"):
        return True
    roots = known_declarations().get("root", set())
    # Signature: the max-width, margin and line-height of a profile's root – all three.
    keys = {p for p, v in parse_style(el.get("style")) if (p, norm_value(v)) in roots}
    return {"max-width", "margin", "line-height"} <= keys


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def strip_design(html: str) -> str:
    """The content without EmneKlar's design (any profile, any version). Section boxes from «Foreslå bedre oppbygging»
    stay as structure (without their style) – they are part of the content once approved."""
    soup = _soup(html)
    roots = [el for el in soup.find_all(True) if _is_root(el)]
    root_ids = {id(r) for r in roots}
    inside = {id(d) for r in roots for d in r.find_all(True)}
    for el in list(soup.find_all(True)):
        if el.decomposed:
            continue
        classes = _classes(el)
        if "ek-design-banner" in classes:
            el.decompose()
            continue
        listed = str(el.get(MARK) or "").split()
        own = parse_style(el.get("style"))
        if listed:
            known = _known_for(el)
            own = [(p, v) for p, v in own if not (p in listed and (p, norm_value(v)) in known)]
            del el[MARK]
        elif id(el) in inside or id(el) in root_ids:
            known = _known_for(el)
            own = [(p, v) for p, v in own if (p, norm_value(v)) not in known]
        if own:
            el["style"] = format_style(own)
        elif el.has_attr("style"):
            del el["style"]
    for el in list(soup.find_all(class_="ek-design-body")):
        el.unwrap()
    for root in roots:
        if not root.decomposed:
            root.unwrap()
    return str(soup).strip()


def detect(html: str) -> str | None:
    """«profile@version» (or «ukjent» for an unrecognised EmneKlar wrapper) when the content has an Emnedesign."""
    for el in _soup(html).find_all("div"):
        if _is_root(el):
            return str(el.get("data-ek-design") or "") or next(
                (c.removeprefix("ek-design--") for c in _classes(el) if c.startswith("ek-design--")), "ukjent")
    return None


# -- blocks and structure ----------------------------------------------------------------------------------------


def _blocks(soup: BeautifulSoup) -> list[Tag | NavigableString]:
    return [n for n in soup.contents if isinstance(n, Tag) or (isinstance(n, NavigableString) and n.strip())]


def describe_blocks(html: str, *, limit: int = 280) -> list[dict[str, str]]:
    """Top-level blocks with ids for the structure suggestion (the AI only sees short excerpts and the tag)."""
    soup = _soup(_flatten(strip_design(html)))
    out = []
    for i, node in enumerate(_blocks(soup), start=1):
        tag = node.name if isinstance(node, Tag) else "text"
        text = norm_text(node.get_text(" ") if isinstance(node, Tag) else str(node))
        out.append({"id": f"b{i}", "tag": tag or "text", "text": text[:limit]})
    return out


def _flatten(html: str) -> str:
    """Structure mode builds sections anew: earlier section boxes are unwrapped and headings EmneKlar added removed."""
    soup = _soup(html)
    for el in list(soup.select(f"[{INSERTED}]")):
        el.decompose()
    for el in list(soup.find_all("div", class_="ek-design-box")):
        el.unwrap()
    for el in soup.find_all(class_="ek-design-label"):
        rest = [c for c in _classes(el) if c != "ek-design-label"]
        if rest:
            el["class"] = " ".join(rest)
        else:
            del el["class"]
    return str(soup).strip()


@dataclass
class Plan:
    sections: list[dict[str, Any]]


def validate_plan(plan: dict[str, Any], blocks: list[dict[str, str]]) -> Plan:
    """Every block exactly once, known roles, labels only from the fixed list – otherwise the suggestion is refused."""
    ids = [b["id"] for b in blocks]
    seen: list[str] = []
    sections = []
    for raw in plan.get("sections") or []:
        role = str(raw.get("role") or "content")
        if role not in SECTION_ROLES:
            raise AppError("validation_error", status=422, message=f"Ukjent seksjonstype: {role}")
        members = [str(b) for b in raw.get("blocks") or []]
        if not members:
            continue  # never an empty section
        label = raw.get("label")
        if label is not None and label not in ALLOWED_LABELS:
            raise AppError("validation_error", status=422,
                           message=f"Overskriften «{label}» er ikke en av de faste seksjonsoverskriftene.")
        seen.extend(members)
        sections.append({"role": role, "label": label, "blocks": members})
    if sorted(seen) != sorted(ids) or len(seen) != len(set(seen)):
        raise AppError("validation_error", status=422,
                       message="Forslaget mangler eller gjentar deler av innholdet og kan ikke brukes.")
    return Plan(sections)


def _restructure(soup: BeautifulSoup, plan: Plan) -> list[str]:
    nodes = {f"b{i}": n for i, n in enumerate(_blocks(soup), start=1)}
    original = list(nodes)
    changes: list[str] = []
    for node in nodes.values():
        node.extract()
    order: list[str] = []
    for section in plan.sections:
        members = [nodes[b] for b in section["blocks"]]
        order.extend(section["blocks"])
        first = members[0]
        has_heading = isinstance(first, Tag) and first.name in ("h2", "h3", "h4")
        heading: Tag | None = first if has_heading and isinstance(first, Tag) else None
        if heading is None and section["label"]:
            heading = soup.new_tag("h2", attrs={INSERTED: "1"})
            heading.string = section["label"]
            members.insert(0, heading)
            changes.append(f"Ny seksjonsoverskrift: «{section['label']}»")
        box_role = BOX_ROLES.get(section["role"])
        teacher_box = any(isinstance(m, Tag) and m.name == "div" and parse_style(m.get("style")) for m in members)
        if box_role and not teacher_box:
            box = soup.new_tag("div", attrs={"class": f"ek-design-box ek-design-box--{section['role']}",
                                             ROLE_ATTR: section["role"]})
            for m in members:
                box.append(m)
            if heading is not None:
                heading["class"] = " ".join([*_classes(heading), "ek-design-label"])
            soup.append(box)
            name = heading.get_text(" ").strip() if heading is not None else ROLE_LABELS[section["role"]]
            changes.append(f"«{name}» vises som eget felt ({ROLE_LABELS[section['role']].lower()})")
        else:
            for m in members:
                soup.append(m)
    for position, block in enumerate(order):
        if original.index(block) != position:
            node = nodes[block]
            text = norm_text(node.get_text(" ") if isinstance(node, Tag) else str(node))[:60]
            changes.append(f"Flyttet: «{text}{'…' if len(text) == 60 else ''}»")
    return changes


# -- applying a profile ------------------------------------------------------------------------------------------


@dataclass
class DesignResult:
    html: str
    notes: list[str] = field(default_factory=list)
    structure_changes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def _is_video(src: str) -> bool:
    return any(h in src for h in VIDEO_HOSTS)


def apply_design(html: str, profile: Profile, *, kind: str = "page", course_name: str | None = None,
                 course_sub: str | None = None, plan: Plan | None = None) -> DesignResult:
    """The content with the profile applied (see the module docstring). ``kind``: front_page | syllabus |
    module_intro | page | assignment | quiz – the layout fits the content type (a banner only on the front page, a
    lead paragraph on a module introduction)."""
    base = strip_design(html)
    if plan is not None:
        base = _flatten(base)
    soup = _soup(base)
    for node in list(soup.contents):  # whitespace between top-level blocks carries nothing and would move around
        if isinstance(node, NavigableString) and not node.strip():
            node.extract()
    structure_changes = _restructure(soup, plan) if plan is not None else []
    counts: Counter[str] = Counter()
    notes: list[str] = []

    for el in soup.find_all(True):
        classes = _classes(el)
        if el.name == "div" and "ek-design-box" in classes:
            _add(el, profile.declarations(BOX_ROLES.get(str(el.get(ROLE_ATTR)), "box_info")))
            counts["felt"] += 1
        elif "ek-design-label" in classes:
            _add(el, profile.declarations("box_label"))
        elif el.name in STYLED_TAGS:
            if el.name == "iframe" and not _is_video(str(el.get("src") or "")):
                counts["innebygde verktøy"] += 1
            _add(el, profile.declarations(el.name))
            counts[el.name] += 1
        elif el.name == "a" and el.get("href"):
            _add(el, profile.declarations("a"))
            counts["lenker"] += 1

    own_colour = [el for el in soup.find_all(True)
                  if any(p in ("color", "background-color", "background") for p, _ in parse_style(el.get("style"))
                         if p not in str(el.get(MARK) or "").split())
                  or (el.name == "font" and el.get("color"))]
    if own_colour:
        notes.append(f"{len(own_colour)} element(er) har egen farge eller bakgrunn. Den er beholdt, fordi den kan ha en "
                     "faglig betydning – kontroller at den passer med designet.")
    if counts["innebygde verktøy"]:
        notes.append(f"{counts['innebygde verktøy']} innebygd(e) verktøy (iframe) er beholdt uendret; bare maksimal "
                     "bredde er satt, så de ikke går ut over skjermen.")
    if soup.find("h1"):
        notes.append("Innholdet har en h1-overskrift. Canvas viser sidetittelen som h1; overskriftsnivået endres ikke.")

    if kind == "module_intro":
        lead = next((n for n in _blocks(soup) if isinstance(n, Tag) and n.name == "p" and n.get_text(strip=True)), None)
        if lead is not None:
            _add(lead, profile.declarations("lead"))

    root = soup.new_tag("div", attrs={"class": f"{ROOT_CLASS} {ROOT_CLASS}--{profile.id}", "data-ek-design": profile.ref,
                                      "style": format_style(profile.declarations("root"))})
    container: Tag = root
    if kind == "front_page" and course_name:
        banner = soup.new_tag("div", attrs={"class": "ek-design-banner",
                                            "style": format_style(profile.declarations("banner"))})
        title = soup.new_tag("p", attrs={"style": format_style(profile.declarations("banner_title"))})
        strong = soup.new_tag("strong")
        strong.string = course_name
        title.append(strong)
        banner.append(title)
        if course_sub:
            sub = soup.new_tag("p", attrs={"style": format_style(profile.declarations("banner_sub"))})
            sub.string = course_sub
            banner.append(sub)
        body = soup.new_tag("div", attrs={"class": "ek-design-body", "style": format_style(profile.declarations("body"))})
        root.append(banner)
        root.append(body)
        container = body
    for node in list(soup.contents):
        if node is not root:
            container.append(node.extract())
    soup.append(root)
    return DesignResult(html=str(soup).strip(), notes=notes, structure_changes=structure_changes, counts=dict(counts))


# -- preservation ------------------------------------------------------------------------------------------------


def signature(html: str) -> dict[str, Any]:
    """What must survive a design: text, links, images with alt text, embeds, media, anchors, tables, code, maths."""
    soup = _soup(strip_design(html))
    for el in list(soup.select(f"[{INSERTED}]")):
        el.decompose()
    text = norm_text(soup.get_text(" "))
    return {
        "text": text,
        "words": Counter(text.split()),
        "links": Counter(str(a.get("href")) for a in soup.find_all("a", href=True)),
        "images": Counter((str(i.get("src")), str(i.get("alt"))) for i in soup.find_all("img")),
        "embeds": Counter(str(f.get("src")) for f in soup.find_all(["iframe", "embed", "object"])),
        "media": Counter(str(m.get("src")) for m in soup.find_all(["video", "audio", "source", "track"])),
        "ids": Counter(str(e.get("id")) for e in soup.find_all(id=True)),
        "tables": len(soup.find_all("table")),
        "table_headers": Counter(norm_text(th.get_text(" ")) for th in soup.find_all("th")),
        "captions": Counter(norm_text(c.get_text(" ")) for c in soup.find_all(["caption", "figcaption"])),
        "code": Counter(norm_text(c.get_text(" ")) for c in soup.find_all(["code", "pre"])),
        "maths": len(soup.select("math, .math_equation_latex, img.equation_image, [data-equation-content]")),
        "headings": [(h.name, norm_text(h.get_text(" "))) for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])],
    }


LABELS = {"text": "teksten", "words": "teksten", "links": "lenker eller lenkemål", "images": "bilder eller alt-tekst",
          "embeds": "innebygd innhold", "media": "video eller lyd", "ids": "ankere (id)", "tables": "tabeller",
          "table_headers": "tabelloverskrifter", "captions": "bildetekster eller tabelltitler", "code": "kode",
          "maths": "ligninger", "headings": "overskrifter"}


def preservation_problems(before: str, after: str, *, structure: bool) -> list[str]:
    """What the design would lose or change in the content – empty when everything is kept. In structure mode the
    order may change (words and headings are compared as sets), never the content itself."""
    a, b = signature(before), signature(after)
    keys = [k for k in a if k not in ("text", "headings")] if structure else [k for k in a if k != "words"]
    problems = [LABELS[k] for k in keys if a[k] != b[k]]
    if structure and Counter(a["headings"]) != Counter(b["headings"]):
        problems.append(LABELS["headings"])
    return list(dict.fromkeys(problems))
