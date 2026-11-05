"""Kartlegging: what the assistant reads from Canvas for a scope (whole course, one module, several modules, one page).

* The module structure of the *whole* course is always read (one list call): even when only one module or page is
  processed, the AI must know the module's role in the course.
* Only Canvas pages can receive illustrations. Other module items (assignments, discussions, quizzes, files, links,
  external tools, sub-headers) are part of the module context, never treated as pages.
* A page that appears in several modules is one page: it is processed once, with all its modules recorded (the first
  by position is its primary context).
* Unpublished pages are included when the teacher can see them (that is what the token allows); block editor pages
  have no HTML body and are listed as not supported.
* Pagination: list calls follow Canvas' Link headers (core/canvas/client.py); modules with more than 100 items are
  completed with the items endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from emneklar.core.canvas.api import CanvasAPI, is_block_editor_page
from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.html import norm_text, parse_html
from emneklar.features.illustrations.privacy import scrub

ITEM_TYPE_LABELS = {"Page": "Side", "Assignment": "Oppgave", "Discussion": "Diskusjon", "Quiz": "Quiz",
                    "File": "Fil", "ExternalUrl": "Ekstern lenke", "ExternalTool": "Eksternt verktøy",
                    "SubHeader": "Underoverskrift"}
OUTSIDE_MODULES = "__outside__"


class Scope(BaseModel):
    type: Literal["course", "module", "modules", "page"] = "course"
    module_ids: list[str] = Field(default_factory=list, max_length=500)
    page_url: str | None = Field(default=None, max_length=500)
    include_unpublished: bool = True
    include_outside_modules: bool = True  # whole course: pages that are in no module
    only_missing: bool = False  # re-run: only pages without EmneKlar illustrations or changed since

    def label(self) -> str:
        return {"course": "Hele emnet", "module": "Én modul", "modules": "Utvalgte moduler",
                "page": "Én side"}[self.type]


@dataclass
class PageInfo:
    url: str
    page_id: str
    title: str
    published: bool
    front_page: bool
    body: str | None
    updated_at: str | None
    block_editor: bool
    modules: list[dict[str, Any]] = field(default_factory=list)  # [{id, name, position, item_position}]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256((self.body or "").encode("utf-8")).hexdigest()

    @property
    def primary_module(self) -> dict[str, Any] | None:
        return min(self.modules, key=lambda m: (m["position"], m["item_position"])) if self.modules else None

    def html_url(self, course_id: str) -> str:
        return f"/courses/{course_id}/pages/{self.url}"


@dataclass
class ModuleInfo:
    id: str
    name: str
    position: int
    published: bool
    items: list[dict[str, Any]]

    @property
    def page_urls(self) -> list[str]:
        return [str(i["page_url"]) for i in self.items if i.get("type") == "Page" and i.get("page_url")]


@dataclass
class Inventory:
    course_id: str
    course: dict[str, Any]
    modules: list[ModuleInfo]
    pages: dict[str, PageInfo]
    targets: list[str]  # page urls to process, in course order, deduplicated
    target_modules: list[str]  # module ids in scope (OUTSIDE_MODULES for pages in no module)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    non_page_items: int = 0
    front_page_url: str | None = None

    def module(self, module_id: str | None) -> ModuleInfo | None:
        return next((m for m in self.modules if m.id == module_id), None)

    def module_of(self, url: str) -> ModuleInfo | None:
        page = self.pages.get(url)
        primary = page.primary_module if page else None
        return self.module(primary["id"]) if primary else None

    def stats(self) -> dict[str, Any]:
        modules = [m for m in self.target_modules if m != OUTSIDE_MODULES]
        return {"modules_total": len(self.modules), "modules_in_scope": len(modules), "pages_in_scope": len(self.targets),
                "pages_in_several_modules": sum(1 for u in self.targets if len(self.pages[u].modules) > 1),
                "unpublished_pages": sum(1 for u in self.targets if not self.pages[u].published),
                "non_page_items": self.non_page_items, "skipped": len(self.skipped)}


def html_text(html: str | None, limit: int | None = None) -> str:
    text = norm_text(parse_html(html).get_text(" "))
    text = scrub(text)
    return text if limit is None or len(text) <= limit else text[: limit - 1] + "…"


def _page_info(raw: dict[str, Any]) -> PageInfo:
    block = is_block_editor_page(raw)
    return PageInfo(url=str(raw.get("url") or ""), page_id=str(raw.get("page_id") or ""), title=raw.get("title") or "",
                    published=raw.get("published") is not False, front_page=bool(raw.get("front_page")),
                    body=None if block else (raw.get("body") or ""), updated_at=raw.get("updated_at"),
                    block_editor=block)


async def build_inventory(api: CanvasAPI, course_id: str, scope: Scope) -> Inventory:
    course_raw, modules_raw = await asyncio.gather(
        api.get_course(course_id, include=("term", "syllabus_body", "public_description")),
        api.list_modules(course_id))
    modules = [ModuleInfo(id=str(m["id"]), name=m.get("name") or "", position=int(m.get("position") or 0),
                          published=m.get("published") is not False,
                          items=sorted((dict(i) for i in m.get("items") or []), key=lambda i: int(i.get("position") or 0)))
               for m in modules_raw if isinstance(m, dict)]
    modules.sort(key=lambda m: m.position)
    inv = Inventory(course_id=course_id, course=course_raw or {}, modules=modules, pages={}, targets=[],
                    target_modules=[])
    membership: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        for item in module.items:
            if item.get("type") == "Page" and item.get("page_url"):
                membership.setdefault(str(item["page_url"]), []).append(
                    {"id": module.id, "name": module.name, "position": module.position,
                     "item_position": int(item.get("position") or 0)})

    # Which modules are in scope, and which pages are needed for context.
    if scope.type == "course":
        inv.target_modules = [m.id for m in modules]
    elif scope.type in ("module", "modules"):
        wanted = scope.module_ids[:1] if scope.type == "module" else scope.module_ids
        known = {m.id for m in modules}
        missing = [m for m in wanted if m not in known]
        if missing:
            raise CanvasError("canvas_not_found", status=404, detail=f"Fant ikke modul {', '.join(missing)}")
        inv.target_modules = [m.id for m in modules if m.id in wanted]
    elif scope.type == "page":
        if not scope.page_url:
            raise CanvasError("validation_error", status=400, detail="Velg en side")
        page_modules = membership.get(scope.page_url, [])
        inv.target_modules = [page_modules[0]["id"]] if page_modules else []

    # Fetch pages: the list call (with bodies) for the whole course, single pages otherwise.
    needed: list[str] = []
    for module_id in inv.target_modules:
        wanted_module = inv.module(module_id)
        if wanted_module:
            needed.extend(wanted_module.page_urls)
    if scope.type == "page" and scope.page_url:
        needed.append(scope.page_url)
    if scope.type == "course":
        raw_pages = await api.list_pages(course_id, include_body=True)
        for raw in raw_pages:
            if isinstance(raw, dict) and raw.get("url"):
                info = _page_info(raw)
                inv.pages[info.url] = info
    else:
        unique = list(dict.fromkeys(needed))
        results = await asyncio.gather(*(api.get_page(course_id, url) for url in unique), return_exceptions=True)
        for url, result in zip(unique, results, strict=True):
            if isinstance(result, dict):
                info = _page_info(result)
                inv.pages[info.url or url] = info
                if info.url and info.url != url:  # Canvas answered for a renamed page (old slug)
                    inv.pages[url] = info
            elif isinstance(result, CanvasError) and result.code == "canvas_not_found":
                inv.skipped.append({"kind": "page", "title": url, "reason": "Siden finnes ikke lenger i Canvas."})
            elif isinstance(result, BaseException):
                raise result
    for url, info in inv.pages.items():
        info.modules = membership.get(url, [])
        if info.front_page:
            inv.front_page_url = url

    # Targets in course order: module by module, item by item; then pages outside modules (whole course).
    ordered: list[str] = []
    for module_id in inv.target_modules:
        target_module = inv.module(module_id)
        if target_module is None:
            continue
        for item in target_module.items:
            if item.get("type") == "Page":
                if item.get("page_url"):
                    ordered.append(str(item["page_url"]))
            else:
                inv.non_page_items += 1
    if scope.type == "page" and scope.page_url:
        ordered = [scope.page_url]
    if scope.type == "course" and scope.include_outside_modules:
        outside = sorted((u for u, p in inv.pages.items() if not p.modules), key=lambda u: inv.pages[u].title.lower())
        if outside:
            inv.target_modules.append(OUTSIDE_MODULES)
        ordered.extend(outside)
    seen: set[str] = set()
    for url in ordered:
        if url in seen:
            continue  # the same page in several modules is one page
        seen.add(url)
        page = inv.pages.get(url)
        if page is None:
            if not any(s["title"] == url for s in inv.skipped):
                inv.skipped.append({"kind": "page", "title": url, "reason": "Siden finnes ikke lenger i Canvas."})
            continue
        if page.block_editor:
            inv.skipped.append({"kind": "page", "title": page.title, "url": url,
                                "reason": "Siden er laget i blokkredigereren og har ingen HTML som kan endres via API."})
            continue
        if not page.published and not scope.include_unpublished:
            inv.skipped.append({"kind": "page", "title": page.title, "url": url, "reason": "Siden er ikke publisert."})
            continue
        if not html_text(page.body).strip():
            inv.skipped.append({"kind": "page", "title": page.title, "url": url, "reason": "Siden har ikke tekst."})
            continue
        inv.targets.append(url)
    if inv.non_page_items:
        inv.limitations.append("Bare Canvas-sider kan få illustrasjoner. Oppgaver, diskusjoner, quizer, filer og lenker "
                               "i modulene brukes som kontekst.")
    return inv


def module_outline(inv: Inventory, module: ModuleInfo) -> list[dict[str, Any]]:
    return [{"type": ITEM_TYPE_LABELS.get(str(i.get("type")), str(i.get("type"))), "title": scrub(i.get("title") or ""),
             "page_url": i.get("page_url"), "indent": i.get("indent") or 0,
             "published": i.get("published") is not False} for i in module.items]
