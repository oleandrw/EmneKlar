"""The hierarchical context model (course → module → page → section) and the context package sent to the AI.

No image is planned from a title or a single paragraph. The analysis model always sees:

1. **Course context** – name, description, syllabus, learning objectives (where they exist), subject area and audience,
   key concepts, module structure, main themes, the desired pedagogical and visual expression;
2. **Module context** – the module's theme, objectives, its pages and other items, how it builds on earlier modules
   and how its pages connect;
3. **Page context** – the *whole* page, section by section (headings, explanations, definitions, examples, tasks and
   reflection questions, existing images and captions);
4. **Section context** – the section the image supports, with the text before and after it.

Large courses are handled by structured summarisation: levels 1 and 2 are analysed once (and cached) and passed on
as compact summaries, page text is shortened per section (each section keeps its beginning) instead of cutting the
end of the page, and the module outline gives each page a fixed budget.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from emneklar.features.illustrations.inventory import Inventory, ModuleInfo, PageInfo, html_text, module_outline
from emneklar.features.illustrations.privacy import scrub
from emneklar.features.illustrations.structure import PageStructure, outline, parse_page


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


# -------------------------------------------------------------------------------- level 1

def course_input(inv: Inventory, *, limit: int) -> dict[str, Any]:
    course = inv.course
    modules = []
    per_module = max(200, limit // max(1, len(inv.modules) + 2))
    for module in inv.modules:
        items = module_outline(inv, module)
        text = "; ".join(f"{i['type']}: {i['title']}" for i in items)
        modules.append({"position": module.position, "name": scrub(module.name), "items": clip(text, per_module)})
    front = inv.pages.get(inv.front_page_url or "")
    return {
        "name": scrub(course.get("name") or ""), "course_code": course.get("course_code") or "",
        "term": (course.get("term") or {}).get("name") if isinstance(course.get("term"), dict) else None,
        "language": course.get("locale") or "",
        "description": clip(html_text(course.get("public_description")), 2000),
        "syllabus": clip(html_text(course.get("syllabus_body")), limit // 3),
        "front_page": clip(html_text(front.body), limit // 6) if front else "",
        "modules": modules,
    }


# -------------------------------------------------------------------------------- level 2

def module_input(inv: Inventory, module: ModuleInfo, *, page_chars: int,
                 previous: list[dict[str, Any]]) -> dict[str, Any]:
    pages = []
    for url in module.page_urls:
        page = inv.pages.get(url)
        if page is None or page.block_editor:
            continue
        structure = parse_page(page.body)
        headings = [s.title for s in structure.sections if s.heading_index is not None][:20]
        pages.append({"page_url": url, "title": scrub(page.title), "headings": [scrub(h) for h in headings],
                      "beginning": clip(html_text(page.body), page_chars), "published": page.published})
    return {"name": scrub(module.name), "position": module.position,
            "position_of": len(inv.modules), "items": module_outline(inv, module), "pages": pages,
            "previous_modules": previous}


def outside_module_input(inv: Inventory) -> dict[str, Any]:
    return {"name": "Sider utenfor moduler", "position": None, "items": [], "pages": [], "previous_modules": [],
            "note": "Sidene ligger ikke i noen modul (for eksempel forsiden eller ressurssider)."}


# -------------------------------------------------------------------------------- level 3 + 4

def page_input(page: PageInfo, structure: PageStructure, *, page_chars: int) -> dict[str, Any]:
    sections = outline(structure, total_chars=page_chars)
    for section in sections:
        section["title"] = scrub(section["title"])
        section["text"] = scrub(section["text"])
    images = [{"alt": scrub(str(i.get("alt") or "")) if i.get("alt") is not None else None,
               "caption": scrub(i.get("caption") or ""), "section_id": i.get("section_id"),
               "emneklar": bool(i.get("emneklar"))} for i in structure.images()]
    return {"title": scrub(page.title), "published": page.published, "front_page": page.front_page,
            "sections": sections, "existing_images": images,
            "modules": [m["name"] for m in page.modules]}


def section_context(structure: PageStructure, section_id: str, *, limit: int = 3000) -> dict[str, Any]:
    """The section an illustration supports, with the neighbouring sections (before and after)."""
    ids = [s.id for s in structure.sections]
    if section_id not in ids:
        section_id = ids[0] if ids else "s0"
    index = ids.index(section_id) if section_id in ids else 0
    section = structure.sections[index] if structure.sections else None

    def text_of(i: int, size: int) -> str:
        if 0 <= i < len(structure.sections):
            s = structure.sections[i]
            return scrub(clip(structure.section_text(s, size), size))
        return ""

    return {"section_id": section_id, "title": scrub(section.title) if section else "",
            "parents": section.parent_titles if section else [], "text": text_of(index, limit),
            "before": {"title": scrub(structure.sections[index - 1].title) if index > 0 else "",
                       "text": text_of(index - 1, limit // 3)},
            "after": {"title": scrub(structure.sections[index + 1].title) if index + 1 < len(structure.sections) else "",
                      "text": text_of(index + 1, limit // 3)}}


def context_package(*, course: dict[str, Any], module: dict[str, Any] | None, page: dict[str, Any],
                    section: dict[str, Any] | None, design: dict[str, Any], placement: dict[str, Any] | None,
                    requirements: dict[str, Any], language: str) -> dict[str, Any]:
    """The structured package (the fields named in the specification) that the planning and review calls receive."""
    learning = list(dict.fromkeys([*(course.get("learning_objectives") or []),
                                   *((module or {}).get("learning_objectives") or []),
                                   *([page["learning_goal"]] if page.get("learning_goal") else [])]))
    concepts = list(dict.fromkeys([*(c.get("term", c) if isinstance(c, dict) else c
                                     for c in page.get("key_concepts") or []),
                                   *((module or {}).get("key_concepts") or []), *(course.get("key_concepts") or [])]))
    return {
        "course_context": course,
        "module_context": module,
        "page_context": page,
        "section_context": section,
        "learning_objectives": learning[:20],
        "key_concepts": concepts[:40],
        "pedagogical_purpose": (placement or {}).get("pedagogical_purpose") or page.get("learning_goal") or "",
        "visual_style_guide": design,
        "existing_images": page.get("existing_images") or [],
        "proposed_placement": placement,
        "image_requirements": requirements,
        "content_language": language,
    }


def language_of(course: dict[str, Any], page_analysis: dict[str, Any] | None) -> str:
    value = (page_analysis or {}).get("content_language") or course.get("content_language") or "nb"
    return str(value)[:20]
