"""Course structure view, student journey and staging of structure suggestions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.requirements import describe
from emneklar.core.canvas.snapshot import SnapshotView
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.storage.models import Snapshot
from emneklar.features.course_structure.rules import JOURNEY_LABEL
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")


def latest_snapshot(c: AppContainer, course_id: str) -> SnapshotView | None:
    with c.db.session() as session:
        snap = session.scalars(select(Snapshot).where(Snapshot.course_id == course_id,
                                                      Snapshot.status.in_(("complete", "partial")))
                               .order_by(Snapshot.created_at.desc()).limit(1)).first()
        snapshot_id = snap.id if snap else None
    return SnapshotView.load(c.db, snapshot_id) if snapshot_id else None


def journey(types: list[str]) -> list[str]:
    steps: list[str] = []
    for kind in types:
        label = JOURNEY_LABEL.get(kind)
        if label and label != "Overskrift" and (not steps or steps[-1] != label):
            steps.append(label)
    return steps


@router.get("/courses/{course_id}/structure")
async def structure(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    view = latest_snapshot(c, course_id)
    if view is None:
        return {"snapshot_at": None, "modules": []}
    modules = []
    for module in view.modules():
        items = []
        for item in view.items_of(module.canvas_id):
            ref = view.item_content_ref(item)
            content = view.by_ref.get(ref or "")
            due = (item.meta.get("content_details") or {}).get("due_at") or (content.meta.get("due_at") if content else None)
            items.append({"id": item.canvas_id, "title": item.title, "type": item.meta.get("type"),
                          "published": item.meta.get("published"), "indent": item.meta.get("indent") or 0,
                          "requirement": describe(item.meta.get("completion_requirement")) if
                          item.meta.get("completion_requirement") else None,
                          "due_at": due, "url": item.html_url, "content_ref": ref})
        modules.append({"id": module.canvas_id, "name": module.title, "position": module.meta.get("position"),
                        "published": module.meta.get("published"),
                        "require_sequential_progress": module.meta.get("require_sequential_progress"),
                        "requirement_type": module.meta.get("requirement_type"), "items": items,
                        "journey": journey([str(i["type"]) for i in items])})
    return {"snapshot_at": view.created_at.isoformat(), "modules": modules}


class StageBody(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    module_id: str | None = Field(default=None, max_length=20)


@router.post("/structure/findings/{finding_id}/stage")
async def stage_suggestion(finding_id: int, body: StageBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    finding = FindingStore(c.db).get(finding_id)
    fix = finding.fix or {}
    params = fix.get("params") or {}
    api = CanvasAPI(c.canvas())
    source = {"feature": "structure", "finding_fingerprints": [finding.fingerprint], "rule_ids": [finding.rule_id]}
    if fix.get("type") == "rename_module":
        name = (body.name or params.get("name") or "").strip()
        if not name:
            raise AppError("validation_error", message="Skriv inn et navn.")
        module = await api.get_module(finding.course_id, str(params["module_id"]))
        return c.changes.stage(
            course_id=finding.course_id, domain="structure", kind="module.update",
            title=f"Nytt navn på modul: {module.get('name')}",
            target={"object_type": "module", "object_id": str(params["module_id"]), "title": module.get("name")},
            before={"name": module.get("name")}, proposed={"name": name},
            rationale=f"{finding.message} Forslag: «{name}».", risk="low", source=source, editable=True)
    if fix.get("type") == "move_item":
        target_module = (body.module_id or params.get("to_module") or "").strip()
        if not target_module.isdigit():
            raise AppError("validation_error", message="Velg en modul.")
        item = await api.get_module_item(finding.course_id, str(params["from_module"]), str(params["item_id"]))
        module_items = await api.list_module_items(finding.course_id, target_module)
        position = len(module_items) + 1
        requirement = item.get("completion_requirement") or None
        if requirement:
            requirement = {k: v for k, v in requirement.items() if k in ("type", "min_score")}
        return c.changes.stage(
            course_id=finding.course_id, domain="structure", kind="module_item.update",
            title=f"Flytt «{item.get('title')}»",
            target={"object_type": "module_item", "object_id": str(item["id"]), "title": item.get("title"),
                    "module_id": str(params["from_module"]), "item_type": item.get("type")},
            before={"module_id": str(params["from_module"]), "position": item.get("position")},
            proposed={"module_id": target_module, "position": position},
            rationale=f"{finding.message} Felles nøkkelord: {', '.join(finding.evidence.get('shared_terms') or [])}.",
            risk="medium", source=source)
    raise AppError("unsupported", message="Dette forslaget kan ikke legges i endringskøen automatisk.")
