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


# -- sync to associated courses ---------------------------------------------------------------------------------


async def sync_preview(c: AppContainer, course_id: str) -> dict[str, Any]:
    api = CanvasAPI(c.canvas())
    template = await api.blueprint_template(course_id)
    if template is None:
        raise AppError("unsupported", status=409, message="Emnet er ikke et Blueprint-emne, så det er ingenting å "
                       "synkronisere herfra.")
    unsynced, associated = await asyncio.gather(api.blueprint_unsynced_changes(course_id),
                                                api.blueprint_associated_courses(course_id))
    return {"course_id": course_id, "unsynced": [
        {"asset_type": u.get("asset_type"), "asset_name": u.get("asset_name"), "change_type": u.get("change_type"),
         "locked": u.get("locked"), "html_url": u.get("html_url")} for u in unsynced[:500]],
        "unsynced_count": len(unsynced),
        "associated_courses": [{"id": str(a.get("id")), "name": a.get("name"), "course_code": a.get("course_code")}
                               for a in associated[:500]],
        "associated_course_count": len(associated) or template.get("associated_course_count"),
        "note": ("Canvas synkroniserer alle endringer i Blueprint-emnet som ikke er synkronisert ennå – også endringer "
                 "som er gjort utenfor EmneKlar. Låst innhold oppdateres i alle tilknyttede emner; ulåst innhold "
                 "oppdateres bare der det ikke er endret lokalt.")}


@router.get("/courses/{course_id}/blueprint/sync")
async def sync_info(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return await sync_preview(c, require_course_id(course_id))


def stage_sync(c: AppContainer, course_id: str, preview: dict[str, Any]) -> dict[str, Any]:
    count = preview["associated_course_count"] or 0
    names = ", ".join(str(a["name"]) for a in preview["associated_courses"][:5] if a.get("name"))
    reach = "1 tilknyttet emne" if count == 1 else f"{count} tilknyttede emner"
    return c.changes.stage(
        course_id=course_id, domain="canvas", kind="blueprint.sync",
        title=f"Synkroniser Blueprint-emnet til {reach}",
        target={"object_type": "course", "object_id": course_id, "title": "Blueprint-synkronisering"},
        before={"unsynced_count": preview["unsynced_count"], "associated_course_count": count},
        proposed={"comment": "Synkronisert fra EmneKlar", "associated_courses": preview["associated_courses"][:50]},
        rationale=(f"Sender endringene i Blueprint-emnet til de tilknyttede emnene ({names}"
                   f"{' …' if count > 5 else ''}). {preview['note']}"),
        risk="high", requires_confirmation=True, source={"feature": "blueprint_sync"}, merge=True)


@router.post("/courses/{course_id}/blueprint/sync/stage")
async def sync_stage(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Queue a sync (high risk, confirmed when published). One open sync per Blueprint course."""
    course_id = require_course_id(course_id)
    return stage_sync(c, course_id, await sync_preview(c, course_id))


@router.get("/courses/{course_id}/blueprint/migrations/{migration_id}")
async def sync_status(course_id: str, migration_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    migration = await CanvasAPI(c.canvas()).blueprint_migration(require_course_id(course_id), migration_id)
    state = str(migration.get("workflow_state") or "")
    return {"id": str(migration.get("id") or migration_id), "workflow_state": state,
            "finished": state in ("completed", "exports_failed", "imports_failed"),
            "failed": state in ("exports_failed", "imports_failed"),
            "label": {"queued": "I kø hos Canvas", "exporting": "Canvas pakker endringene",
                      "imports_queued": "Canvas legger inn endringene", "completed": "Fullført",
                      "exports_failed": "Feilet i Blueprint-emnet",
                      "imports_failed": "Feilet i ett eller flere tilknyttede emner"}.get(state, state or "Ukjent")}


# -- move a refused fix to the Blueprint course -------------------------------------------------------------------


async def _master_object(api: CanvasAPI, master_id: str, object_type: str, object_id: str,
                         title: str | None) -> tuple[str, str] | None:
    """The same content in the Blueprint course: pages by their url (kept by the sync), other types by an exact,
    unique title. Returns (object id, HTML) or None when it cannot be identified safely."""
    from emneklar.core.canvas.client import CanvasError

    if object_type == "page":
        try:
            page = await api.get_page(master_id, object_id)
            return str(page.get("url") or object_id), page.get("body") or ""
        except CanvasError as exc:
            if exc.code != "canvas_not_found":
                raise
        pages = [p for p in await api.list_pages(master_id, include_body=False) if p.get("title") == title]
        if len(pages) == 1:
            page = await api.get_page(master_id, str(pages[0].get("url")))
            return str(page.get("url")), page.get("body") or ""
        return None
    listing = {"assignment": (api.list_assignments, "name", "description", api.get_assignment),
               "discussion": (api.list_discussions, "title", "message", api.get_discussion),
               "quiz": (api.list_quizzes, "title", "description", api.get_quiz)}.get(object_type)
    if listing is None or not title:
        return None
    lister, title_key, field, getter = listing
    matches = [x for x in await lister(master_id) if x.get(title_key) == title]
    if len(matches) != 1:
        return None
    full = await getter(master_id, str(matches[0].get("id")))
    return str(full.get("id")), full.get(field) or ""


async def plan_move(c: AppContainer, change_id: int) -> dict[str, Any]:
    from emneklar.core.canvas.blueprint import blueprint_info
    from emneklar.core.canvas.client import CanvasError
    from emneklar.features.accessibility.fixes import HTML_FIELD, apply_recipes, display

    change = c.changes.get(change_id)
    data, row = c.changes._load(change_id)
    recipes = list((row.source or {}).get("fixes") or [])
    object_type = str(change["target"].get("object_type") or "")
    if not recipes or object_type not in HTML_FIELD:
        raise AppError("unsupported", status=409, message="Denne endringen kan ikke flyttes automatisk. Åpne "
                       "Blueprint-emnet i Canvas og gjør endringen der.")
    api = CanvasAPI(c.canvas())
    info = await blueprint_info(api, change["course_id"], fresh=True)
    parent = info.get("parent") or {}
    if not info.get("is_child") or not parent.get("id"):
        raise AppError("unsupported", status=409, message="Emnet er ikke knyttet til et Blueprint-emne.")
    try:
        await api.get_course(parent["id"], include=())
    except CanvasError as exc:
        raise AppError("canvas_forbidden", status=409, message=(
            f"Du har ikke tilgang til Blueprint-emnet «{parent.get('name') or parent['id']}» med Canvas-brukeren "
            "EmneKlar er koblet til. Be en som er lærer eller designer i Blueprint-emnet om å gjøre rettingen der."),
        ) from exc
    found = await _master_object(api, parent["id"], object_type, str(change["target"].get("object_id")),
                                 change["target"].get("title"))
    if found is None:
        raise AppError("not_found", status=409, message=(
            "Fant ikke det samme innholdet i Blueprint-emnet (samme sideadresse eller entydig tittel). Åpne "
            "Blueprint-emnet i Canvas og gjør rettingen der."))
    master_object_id, master_html = found
    try:
        after = apply_recipes(master_html, recipes, relaxed=True)
    except AppError as exc:
        raise AppError("change_conflict", status=409, message=(
            "Rettingen passer ikke med innholdet i Blueprint-emnet (det er endret siden siste synkronisering). Kjør "
            "en analyse av Blueprint-emnet og rett det der.")) from exc
    field = HTML_FIELD[object_type]
    return {"change": change, "data": data, "row": row, "parent": parent, "object_id": master_object_id,
            "field": field, "before": master_html, "after": after, "recipes": recipes,
            "before_display": display(master_html), "after_display": display(after)}


@router.get("/changes/{change_id}/blueprint-move")
async def move_preview(change_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    plan = await plan_move(c, change_id)
    preview = await sync_preview(c, plan["parent"]["id"])
    return {"parent": plan["parent"], "object_id": plan["object_id"], "before_display": plan["before_display"],
            "after_display": plan["after_display"], "associated_course_count": preview["associated_course_count"],
            "associated_courses": preview["associated_courses"][:20], "note": preview["note"]}


@router.post("/changes/{change_id}/blueprint-move")
async def move(change_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Stage the same fix in the Blueprint course (+ a sync) and take the refused change out of the queue."""
    plan = await plan_move(c, change_id)
    change, parent = plan["change"], plan["parent"]
    source = dict(plan["row"].source or {})
    # The findings belong to the associated course: they stay «I endringskø» there until the sync has brought the fix
    # and a new analysis confirms it (the Blueprint change itself does not fix them yet).
    source["associated_finding_fingerprints"] = source.pop("finding_fingerprints", [])
    source["relaxed"] = True  # the recipes were made on the associated course's copy (other course and file ids)
    moved = c.changes.stage(
        course_id=parent["id"], domain=change["domain"], kind=change["kind"],
        title=f"{change['target'].get('title') or ''}: rettet i Blueprint-emnet",
        target={**change["target"], "object_id": plan["object_id"], "url": None,
                "moved_from": {"course_id": change["course_id"], "change_id": change_id}},
        before={plan["field"]: plan["before"]}, proposed={plan["field"]: plan["after"]},
        rationale=f"Flyttet fra et tilknyttet emne fordi Canvas avviste endringen der (låst av Blueprint).\n"
                  f"{change['rationale']}",
        risk=change["risk"], source={**source, "moved_from_course": change["course_id"]}, merge=True,
        ai_generated=change["ai_generated"])
    c.changes.discard(change_id, note=f"Flyttet til Blueprint-emnet «{parent.get('name') or parent['id']}».")
    sync = stage_sync(c, parent["id"], await sync_preview(c, parent["id"]))
    # The teacher approved the fix and confirmed the move (after seeing the diff and the courses it reaches): both are
    # ready to publish. The sync is high risk and is confirmed once more when publishing.
    approved = {row["id"]: row for row in c.changes.approve([moved["id"], sync["id"]])}
    return {"moved": approved[moved["id"]], "sync": approved[sync["id"]]}
