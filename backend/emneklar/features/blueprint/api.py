"""Canvas-verktøy → Blueprint-låsing.

Only content types the Blueprint API supports are offered. Lock status is read
from Canvas list calls (``restricted_by_master_course``); where Canvas does not
report it (files), the current status is shown as unknown and cannot be restored
by undo. Every lock/unlock is previewed and staged as one high-risk change.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError

router = APIRouter(prefix="/api")

ContentType = Literal["wiki_page", "assignment", "discussion_topic", "quiz", "attachment"]
CONTENT_TYPES: tuple[ContentType, ...] = ("wiki_page", "assignment", "discussion_topic", "quiz", "attachment")
TYPE_LABELS = {"wiki_page": "Sider", "assignment": "Oppgaver", "discussion_topic": "Diskusjoner", "quiz": "Quizer",
               "attachment": "Filer"}
RESTRICTION_LABELS = {"content": "Innhold", "points": "Poeng", "due_dates": "Frister",
                      "availability_dates": "Tilgjengelighetsdatoer"}
NOT_SUPPORTED = ("Eksterne verktøy (LTI) og nye quizer (New Quizzes) vises ikke her. Lås dem i Blueprint-emnet "
                 "i Canvas.")


def _all_types() -> list[ContentType]:
    return list(CONTENT_TYPES)


class BlueprintRequest(BaseModel):
    action: Literal["lock", "unlock"]
    content_types: list[ContentType] = Field(default_factory=_all_types, min_length=1)
    module_ids: list[str] = Field(default_factory=list, max_length=500)  # empty = whole course
    restrictions: dict[str, bool] | None = None  # None = the Blueprint's default restrictions

    @field_validator("restrictions")
    @classmethod
    def _restrictions(cls, value: dict[str, bool] | None) -> dict[str, bool] | None:
        if value is None:
            return None
        unknown = set(value) - set(RESTRICTION_LABELS)
        if unknown:
            raise ValueError(f"Ukjente låsetyper: {sorted(unknown)}")
        if not any(value.values()):
            raise ValueError("Velg minst én del som skal låses")
        return value


def _module_refs(modules: list[dict[str, Any]], pages_by_url: dict[str, str]) -> dict[tuple[str, str], list[str]]:
    """(content_type, content_id) → module ids that contain it."""
    kinds = {"Page": "wiki_page", "Assignment": "assignment", "Discussion": "discussion_topic", "Quiz": "quiz",
             "File": "attachment"}
    refs: dict[tuple[str, str], list[str]] = {}
    for module in modules:
        for item in module.get("items") or []:
            kind = kinds.get(str(item.get("type")))
            if kind == "wiki_page":
                ident = pages_by_url.get(str(item.get("page_url")))
            else:
                ident = str(item.get("content_id")) if item.get("content_id") is not None else None
            if kind and ident:
                refs.setdefault((kind, ident), []).append(str(module.get("id")))
    return refs


def _lock(raw: dict[str, Any]) -> tuple[bool | None, dict[str, Any] | None]:
    if "restricted_by_master_course" not in raw:
        return None, None
    restricted = bool(raw.get("restricted_by_master_course"))
    return restricted, (raw.get("master_course_restrictions") or None) if restricted else None


async def _inventory(api: CanvasAPI, course_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages, assignments, discussions, quizzes, files, modules = await asyncio.gather(
        api.list_pages(course_id, include_body=False), api.list_assignments(course_id),
        api.list_discussions(course_id), api.list_quizzes(course_id), api.list_files(course_id),
        api.list_modules(course_id))
    pages_by_url = {str(p.get("url")): str(p.get("page_id")) for p in pages}
    refs = _module_refs(modules, pages_by_url)
    names = {str(m.get("id")): m.get("name") or "" for m in modules}
    items: list[dict[str, Any]] = []

    def add(kind: str, raw: dict[str, Any], ident: Any, title: Any) -> None:
        if ident is None:
            return
        restricted, restrictions = _lock(raw)
        module_ids = refs.get((kind, str(ident)), [])
        items.append({"content_type": kind, "content_id": str(ident), "title": str(title or ""),
                      "type_label": TYPE_LABELS[kind], "restricted": restricted, "restrictions": restrictions,
                      "module_ids": module_ids, "modules": [names.get(m, "") for m in module_ids],
                      "html_url": raw.get("html_url")})

    for p in pages:
        add("wiki_page", p, p.get("page_id"), p.get("title"))
    for a in assignments:
        types = set(a.get("submission_types") or [])
        if "online_quiz" in types or "discussion_topic" in types or a.get("quiz_id") or a.get("discussion_topic"):
            continue  # locked through the quiz/discussion itself
        add("assignment", a, a.get("id"), a.get("name"))
    for d in discussions:
        add("discussion_topic", d, d.get("id"), d.get("title"))
    for q in quizzes:
        add("quiz", q, q.get("id"), q.get("title"))
    for f in files:
        add("attachment", f, f.get("id"), f.get("display_name") or f.get("filename"))
    module_list = [{"id": str(m.get("id")), "name": m.get("name") or ""} for m in modules]
    return items, module_list


async def _template(api: CanvasAPI, course_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    template, subscriptions = await asyncio.gather(api.blueprint_template(course_id),
                                                   api.blueprint_subscriptions(course_id))
    return template, subscriptions


def _unavailable(subscriptions: list[dict[str, Any]]) -> dict[str, Any]:
    reason = ("Emnet er ikke et Blueprint-emne. Blueprint-låsing kan bare gjøres i selve Blueprint-emnet (malemnet). "
              "Om et emne er Blueprint-emne, bestemmes av Canvas-administratoren.")
    parent = None
    if subscriptions:
        parent = (subscriptions[0].get("blueprint_course") or {}).get("name")
        reason = (f"Dette emnet får innhold fra Blueprint-emnet «{parent}». Låsing styres i Blueprint-emnet, "
                  "ikke her.") if parent else "Dette emnet er knyttet til et Blueprint-emne. Låsing styres der."
    return {"available": False, "reason": reason, "is_child": bool(subscriptions), "parent": parent}


@router.get("/courses/{course_id}/blueprint")
async def blueprint(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    api = CanvasAPI(c.canvas())
    template, subscriptions = await _template(api, course_id)
    if template is None:
        return _unavailable(subscriptions)
    items, modules = await _inventory(api, course_id)
    counts = {kind: {"total": sum(1 for i in items if i["content_type"] == kind),
                     "locked": sum(1 for i in items if i["content_type"] == kind and i["restricted"] is True),
                     "unknown": sum(1 for i in items if i["content_type"] == kind and i["restricted"] is None)}
              for kind in CONTENT_TYPES}
    return {"available": True, "template": {"associated_course_count": template.get("associated_course_count"),
                                            "last_export_completed_at": template.get("last_export_completed_at")},
            "items": items, "modules": modules, "counts": counts,
            "content_types": [{"value": k, "label": TYPE_LABELS[k]} for k in CONTENT_TYPES],
            "restriction_options": [{"value": k, "label": v} for k, v in RESTRICTION_LABELS.items()],
            "note": NOT_SUPPORTED}


def _plan(items: list[dict[str, Any]], body: BlueprintRequest) -> list[dict[str, Any]]:
    wanted = set(body.module_ids)
    target = body.action == "lock"
    rows = []
    for item in items:
        if item["content_type"] not in body.content_types:
            continue
        if wanted and not wanted & set(item["module_ids"]):
            continue
        current = item["restricted"]
        same_restrictions = body.restrictions is None or item["restrictions"] == body.restrictions
        if current is None:
            status, label = "unknown", "Nåværende status er ukjent"
        elif current == target and (not target or same_restrictions):
            status, label = "unchanged", "Uendret"
        else:
            status, label = "change", "Låses" if target else "Låses opp"
        rows.append({**item, "proposed": target, "status": status, "status_label": label})
    return rows


async def _rows(c: AppContainer, course_id: str, body: BlueprintRequest) -> list[dict[str, Any]]:
    api = CanvasAPI(c.canvas())
    template, subscriptions = await _template(api, course_id)
    if template is None:
        raise AppError("unsupported", status=409, message=_unavailable(subscriptions)["reason"])
    items, _ = await _inventory(api, course_id)
    return _plan(items, body)


@router.post("/courses/{course_id}/blueprint/preview")
async def preview(course_id: str, body: BlueprintRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    rows = await _rows(c, require_course_id(course_id), body)
    return {"rows": rows, "counts": {s: sum(1 for r in rows if r["status"] == s) for s in ("change", "unchanged",
                                                                                        "unknown")}}


@router.post("/courses/{course_id}/blueprint/stage")
async def stage(course_id: str, body: BlueprintRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    rows = [r for r in await _rows(c, course_id, body) if r["status"] != "unchanged"]
    if not rows:
        raise AppError("validation_error", message="Ingen elementer må endres med dette valget.")
    lock = body.action == "lock"
    before = {"items": [{"content_type": r["content_type"], "content_id": r["content_id"], "title": r["title"],
                         "restricted": r["restricted"], "restrictions": r["restrictions"]} for r in rows]}
    proposed = {"restricted": lock, "restrictions": body.restrictions if lock else None,
                "items": [{"content_type": r["content_type"], "content_id": r["content_id"], "title": r["title"]}
                          for r in rows]}
    unknown = sum(1 for r in rows if r["status"] == "unknown")
    rationale = (f"{'Låser' if lock else 'Låser opp'} {len(rows)} elementer i Blueprint-emnet. "
                 + ("Låste elementer kan ikke endres i tilknyttede emner, og lokale endringer der overskrives ved "
                    "neste synkronisering." if lock else
                    "Ulåste elementer kan endres i tilknyttede emner etter neste synkronisering."))
    if unknown:
        rationale += f" For {unknown} elementer er nåværende status ukjent; de kan ikke settes tilbake med angre."
    return c.changes.stage(
        course_id=course_id, domain="canvas", kind="blueprint.restrict",
        title=f"Blueprint: {'lås' if lock else 'lås opp'} {len(rows)} elementer",
        target={"object_type": "course", "object_id": course_id, "title": f"{len(rows)} elementer"},
        before=before, proposed=proposed, rationale=rationale, risk="high", requires_confirmation=True,
        source={"feature": "blueprint"})
