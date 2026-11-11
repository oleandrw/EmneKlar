"""Change set (endringskø), publishing, change log (endringslogg), undo and backups.

One queue for every feature: UU and content-quality fixes, structure changes, quizzes, the front page, Canvas tools
and the illustration assistant all stage changes here, and «Publiser til Canvas» publishes the approved ones –
across courses – in one job.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container
from emneklar.core.changes.engine import LISTED_STATUSES
from emneklar.core.container import AppContainer
from emneklar.core.storage.models import Backup

router = APIRouter(prefix="/api")

#: domain -> (singular, plural) for «1 UU-retting» / «4 UU-rettinger».
DOMAIN_LABELS = {"accessibility": ("UU-retting", "UU-rettinger"),
                 "content_quality": ("innholdsretting", "innholdsrettinger"),
                 "structure": ("strukturendring", "strukturendringer"), "quiz": ("quizendring", "quizendringer"),
                 "homepage": ("forsideendring", "forsideendringer"), "canvas": ("Canvas-endring", "Canvas-endringer"),
                 "illustrations": ("illustrasjonsendring", "illustrasjonsendringer")}


def group_label(domain: str, count: int) -> str:
    singular, plural = DOMAIN_LABELS.get(domain, (domain, domain))
    return singular if count == 1 else plural


class Ids(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=2000)


class ApplyBody(Ids):
    confirm_high_risk: bool = False


class ProposedBody(BaseModel):
    proposed: dict[str, Any]


@router.get("/changes")
async def list_changes(course_id: str | None = None, include_done: bool = False,
                       c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    statuses: tuple[str, ...] = LISTED_STATUSES
    if include_done:
        statuses = (*statuses, "applied", "discarded", "undone")
    items = c.changes.list(course_id, statuses)
    names = c.changes.course_names(sorted({i["course_id"] for i in items}))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    courses: dict[str, dict[str, Any]] = {}
    for item in items:
        groups[item["domain"]].append(item)
        item["course_name"] = names.get(item["course_id"])
        entry = courses.setdefault(item["course_id"], {"course_id": item["course_id"],
                                                       "name": names.get(item["course_id"]), "count": 0,
                                                       "approved": 0, "problems": 0})
        entry["count"] += 1
        entry["approved"] += int(item["status"] == "approved")
        entry["problems"] += int(item["status"] in ("failed", "conflict"))
    running = c.changes.publishing()
    return {
        "items": items,
        "groups": [{"domain": d, "label": group_label(d, len(v)), "count": len(v)} for d, v in groups.items()],
        "courses": list(courses.values()),
        "summary": c.changes.summary(course_id),
        "publishing_job": running.public() if running else None,
    }


@router.get("/changes/summary")
async def summary(course_id: str | None = None, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.changes.summary(course_id)


@router.get("/changes/{change_id}")
async def get_change(change_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.changes.get(change_id)


@router.get("/changes/{change_id}/preview")
async def change_preview(change_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    from emneklar.core.security.sanitize import preview_html

    change = c.changes.get(change_id)
    field = next((f for f in ("body", "description", "message", "syllabus_body", "question_text")
                  if isinstance(change["proposed"].get(f), str)), None)
    if field is None:
        return {"html": None}
    return {"html": preview_html(change["proposed"][field], c.settings.get().canvas.base_url)}


@router.patch("/changes/{change_id}")
async def edit_change(change_id: int, body: ProposedBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.changes.update_proposed(change_id, body.proposed)


@router.delete("/changes/{change_id}")
async def discard_change(change_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.changes.discard(change_id)


@router.post("/changes/approve")
async def approve(body: Ids, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return {"items": c.changes.approve(body.ids)}


@router.post("/changes/unapprove")
async def unapprove(body: Ids, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return {"items": c.changes.unapprove(body.ids)}


@router.post("/changes/check-conflicts")
async def check_conflicts(body: Ids, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return {"items": await c.changes.check_conflicts(body.ids)}


@router.post("/changes/{change_id}/rebuild")
async def rebuild(change_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Lag forslaget på nytt»: rebuild a fix change on the current content in Canvas after a conflict."""
    return await c.changes.rebuild(change_id)


@router.post("/changes/apply")
async def apply_changes(body: ApplyBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Publiser til Canvas»: publish the given changes (one job, possibly several courses)."""
    return c.changes.submit_apply(body.ids, confirm_high_risk=body.confirm_high_risk).public()


@router.get("/changelog")
async def changelog(course_id: str | None = None, limit: int = 50, offset: int = 0,
                    c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.changes.changelog(course_id, limit=min(200, max(1, limit)), offset=max(0, offset))


@router.get("/changelog/{log_id}")
async def log_entry(log_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.changes.log_entry(log_id)


@router.post("/changelog/{log_id}/undo")
async def undo(log_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return await c.changes.undo(log_id)


@router.get("/backups")
async def backups(course_id: str | None = None, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return {"items": c.changes.backups.list(course_id)}


@router.get("/backups/{backup_id}")
async def backup(backup_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    with c.db.session() as session:
        row = session.get(Backup, backup_id)
        meta = {"id": row.id, "title": row.title, "object_type": row.object_type} if row else {}
    return {**meta, "content": c.changes.backups.load(backup_id)}
