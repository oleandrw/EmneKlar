"""Canvas-verktøy → Automatiske modulkrav (preview and staging through the change engine)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.requirements import describe
from emneklar.core.container import AppContainer
from emneklar.features.module_requirements.planner import CHANGING, PlanRequest, options, plan

router = APIRouter(prefix="/api")


async def _load(c: AppContainer, course_id: str, request: PlanRequest) -> dict[str, Any]:
    api = CanvasAPI(c.canvas())
    modules, assignments = await asyncio.gather(api.list_modules(course_id), api.list_assignments(course_id))
    submission_types = {str(a.get("id")): [str(t) for t in a.get("submission_types") or []] for a in assignments}
    return plan(modules, request, submission_types)


@router.get("/module-requirements/options")
async def requirement_options() -> dict[str, Any]:
    return options()


@router.post("/courses/{course_id}/module-requirements/preview")
async def preview(course_id: str, body: PlanRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return await _load(c, require_course_id(course_id), body)


@router.post("/courses/{course_id}/module-requirements/stage")
async def stage(course_id: str, body: PlanRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    result = await _load(c, course_id, body)
    staged = []
    for module in result["modules"]:
        for row in module["items"]:
            if row["status"] not in CHANGING:
                continue
            reason = (f"Fullføringskrav for {row['type_label'].lower()}: «{describe(row['proposed'])}» "
                      f"(var: «{describe(row['current'])}»).")
            if row["notes"]:
                reason += " " + " ".join(row["notes"])
            change = c.changes.stage(
                course_id=course_id, domain="canvas", kind="module_item.update",
                title=f"Modulkrav: {row['title']}",
                target={"object_type": "module_item", "object_id": row["item_id"], "module_id": module["id"],
                        "item_type": row["type"], "title": row["title"], "url": row["html_url"],
                        "module_name": module["name"]},
                before={"completion_requirement": row["current"]},
                proposed={"completion_requirement": row["proposed"]},
                rationale=reason + " Fullføringskrav påvirker hvordan studentene ser fremdriften sin.",
                risk="medium", source={"feature": "module_requirements"}, merge=True)
            staged.append(change["id"])
        changed = module["settings"]["changed"]
        if changed:
            current = module["settings"]["current"]
            labels: dict[str, dict[Any, str]] = {"require_sequential_progress": {True: "i rekkefølge", False: "fritt"}}
            text = ", ".join(f"{labels[k][current[k]]} → {labels[k][v]}" for k, v in changed.items())
            change = c.changes.stage(
                course_id=course_id, domain="canvas", kind="module.update", title=f"Modulinnstillinger: {module['name']}",
                target={"object_type": "module", "object_id": module["id"], "title": module["name"]},
                before={k: current[k] for k in changed}, proposed=dict(changed),
                rationale=f"Endrer modulens fullføring: {text}.", risk="medium",
                source={"feature": "module_requirements"}, merge=True)
            staged.append(change["id"])
    return {"staged": len(staged), "change_ids": staged, "counts": result["counts"]}
