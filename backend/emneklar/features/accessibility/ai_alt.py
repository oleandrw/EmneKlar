"""KI-forslag til alt-tekst: API (optional, privacy-gated, always «KI-forslag – må vurderes»).

The work itself – prompt, image fetch, cache and the background queue – lives in
:mod:`emneklar.features.accessibility.alt_suggestions`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core import flags
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.storage.models import AltTextSuggestion, Finding
from emneklar.features.accessibility.alt_suggestions import (
    generate,
    input_hash,
    is_image_finding,
    queue_for,
    suggestion_dict,
)
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")


class AltTextBody(BaseModel):
    finding_id: int
    confirmed: bool = False


class BatchBody(BaseModel):
    course_id: str
    finding_ids: list[int] = Field(default_factory=list, max_length=5000)  # empty = every open image finding
    confirmed: bool = False


class PriorityBody(BaseModel):
    course_id: str
    finding_ids: list[int] = Field(min_length=1, max_length=50)  # the one being viewed first, then the next ones


def _image_finding(c: AppContainer, finding_id: int) -> Finding:
    finding = FindingStore(c.db).get(finding_id)
    if not is_image_finding(finding):
        raise AppError("unsupported", message="KI-forslag til alt-tekst gjelder bare bildefunn.")
    return finding


def _open_image_findings(c: AppContainer, course_id: str, ids: list[int]) -> list[Finding]:
    if ids:
        store = FindingStore(c.db)
        findings = [store.get(i) for i in dict.fromkeys(ids)]
    else:
        rows, _ = FindingStore(c.db).current(course_id, "accessibility")
        findings = sorted(rows, key=lambda f: ((f.object_title or "").lower(), f.id))
    return [f for f in findings if f.course_id == course_id and f.status == "open" and is_image_finding(f)]


@router.post("/ai/tasks/alt-text/prepare")
async def prepare(body: AltTextBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    finding = _image_finding(c, body.finding_id)
    return queue_for(c).plan(finding.course_id, 1)


@router.post("/ai/tasks/alt-text")
async def suggest(body: AltTextBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """One suggestion now (cached: an unchanged image is never sent twice)."""
    flags.require(c.settings.get(), "ai_alt_text")
    finding = _image_finding(c, body.finding_id)
    if body.confirmed:
        queue_for(c).consent.add(finding.course_id)
    result = await generate(c, finding, confirmed=body.confirmed)
    if result["status"] == "failed":
        raise AppError("ai_all_failed", status=502, message=result.get("error") or "KI-forslaget feilet.")
    return result


@router.post("/ai/tasks/alt-text/batch/prepare")
async def batch_prepare(body: BatchBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """What «Forbered KI-forslag» would send – shown to the teacher before anything leaves the machine."""
    course_id = require_course_id(body.course_id)
    findings = _open_image_findings(c, course_id, body.finding_ids)
    queue = queue_for(c)
    with c.db.session() as session:
        from sqlalchemy import select

        rows = {r.fingerprint: r for r in session.scalars(select(AltTextSuggestion).where(
            AltTextSuggestion.course_id == course_id,
            AltTextSuggestion.fingerprint.in_([f.fingerprint for f in findings]))).all()}
    ready = sum(1 for f in findings if (r := rows.get(f.fingerprint)) is not None and r.status == "ready"
                and r.input_hash == input_hash(f))
    todo = len(findings) - ready
    return {**queue.plan(course_id, max(1, todo)), "images": len(findings), "already_ready": ready, "to_send": todo,
            "queue": queue.state(course_id)}


@router.post("/ai/tasks/alt-text/batch/start")
async def batch_start(body: BatchBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(body.course_id)
    queue = queue_for(c)
    plan = queue.plan(course_id, 1)
    if not plan["available"]:
        raise AppError("ai_not_configured", status=409, message=plan["reason"])
    if plan["needs_confirmation"] and not body.confirmed:
        raise AppError("ai_consent_required", status=409)
    queue.consent.add(course_id)
    added = queue.enqueue(course_id, _open_image_findings(c, course_id, body.finding_ids))
    return {"added": added, "queue": queue.state(course_id)}


@router.post("/ai/tasks/alt-text/prioritize")
async def prioritize(body: PriorityBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """The teacher opened an image: prepare it and the next ones first – only once suggestions are allowed for the
    course (consent given, or no confirmation needed). Otherwise nothing is sent."""
    course_id = require_course_id(body.course_id)
    queue = queue_for(c)
    if not queue.allowed(course_id):
        return {"added": 0, "queue": queue.state(course_id), "allowed": False}
    store = FindingStore(c.db)
    findings = [f for f in (store.get(i) for i in body.finding_ids) if f.course_id == course_id and is_image_finding(f)]
    return {"added": queue.enqueue(course_id, findings, front=True), "queue": queue.state(course_id), "allowed": True}


@router.post("/ai/tasks/alt-text/retry")
async def retry(body: AltTextBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    finding = _image_finding(c, body.finding_id)
    queue = queue_for(c)
    if body.confirmed:
        queue.consent.add(finding.course_id)
    if not queue.allowed(finding.course_id):
        raise AppError("ai_consent_required", status=409)
    queue.enqueue(finding.course_id, [finding], front=True, retry_failed=True)
    return {"queue": queue.state(finding.course_id)}


@router.post("/courses/{course_id}/alt-text/cancel")
async def cancel(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    queue_for(c).cancel(course_id)
    return {"queue": queue_for(c).state(course_id)}


@router.get("/courses/{course_id}/alt-text/status")
async def status(course_id: str, ids: list[int] = Query(default=[]),
                 c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Suggestion status per finding id (ready / queued / running / failed / stale / none) and the queue."""
    from sqlalchemy import select

    course_id = require_course_id(course_id)
    store = FindingStore(c.db)
    findings = [store.get(i) for i in ids[:200]]
    fingerprints = {f.fingerprint: f for f in findings if f.course_id == course_id}
    with c.db.session() as session:
        rows = {r.fingerprint: r for r in session.scalars(select(AltTextSuggestion).where(
            AltTextSuggestion.course_id == course_id, AltTextSuggestion.fingerprint.in_(list(fingerprints)))).all()}
        items = {str(f.id): (suggestion_dict(rows[fp], input_hash(f)) if fp in rows else {"status": "none"})
                 for fp, f in fingerprints.items()}
    return {"items": items, "queue": queue_for(c).state(course_id)}
