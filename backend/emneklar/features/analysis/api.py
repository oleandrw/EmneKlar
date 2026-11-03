"""Global analysis, background jobs and live progress (SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.flags import is_enabled
from emneklar.core.jobs.manager import JobContext
from emneklar.core.storage.models import AnalysisRun, Job
from emneklar.features.analysis.core import AnalysisRequest
from emneklar.features.analysis.orchestrator import run_analysis

router = APIRouter(prefix="/api")

DOMAIN_TITLES = {"accessibility": "UU", "content_quality": "innhold", "structure": "struktur", "quiz": "quiz"}


@router.post("/analysis")
async def start_analysis(body: AnalysisRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    body.course_id = require_course_id(body.course_id)
    domains = list(dict.fromkeys(body.domains))
    if "quiz" in domains and not is_enabled(c.settings.get(), "quiz_assistant"):
        domains.remove("quiz")
    if not domains or (body.scope == "modules" and not body.module_ids) or (body.scope == "items" and not body.items):
        raise AppError("analysis_nothing_selected")
    body.domains = domains
    c.canvas()  # fail fast with a clear message if Canvas is not configured

    async def runner(ctx: JobContext) -> dict[str, Any]:
        return await run_analysis(ctx, c, body)

    scope_label = {"course": "hele emnet", "modules": "valgte moduler", "items": "valgte elementer"}[body.scope]
    title = f"Analyse av {scope_label}"
    state = c.jobs.submit(kind="analysis", title=title, runner=runner, course_id=body.course_id,
                          params=body.model_dump(), supports_pause=True, hard_cancel=True)
    return state.public()


def _history_job(c: AppContainer, job_id: str) -> dict[str, Any] | None:
    with c.db.session() as session:
        row = session.get(Job, job_id)
        if row is None:
            return None
        return {"id": row.id, "kind": row.kind, "course_id": row.course_id, "title": row.title, "status": row.status,
                "supports_pause": False, "error": row.error, "result": row.result,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "progress": row.progress or {}}


@router.get("/jobs")
async def list_jobs(active: bool = False, course_id: str | None = None,
                    c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    jobs = [j.public() for j in c.jobs.list(course_id=course_id, active_only=active)]
    return {"jobs": jobs}


@router.get("/jobs/history")
async def job_history(course_id: str | None = None, limit: int = 20,
                      c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return {"jobs": c.jobs.history(course_id=course_id, limit=min(100, max(1, limit)))}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    try:
        return c.jobs.get(job_id).public()
    except NotFoundError:
        stored = _history_job(c, job_id)
        if stored is None:
            raise
        return stored


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.jobs.pause(job_id).public()


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.jobs.resume(job_id).public()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.jobs.cancel(job_id).public()


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, c: AppContainer = Depends(get_container)) -> StreamingResponse:
    c.jobs.get(job_id)  # 404 before streaming starts

    async def stream() -> AsyncIterator[str]:
        yield "retry: 3000\n\n"
        async for item in c.jobs.stream(job_id):
            if await request.is_disconnected():
                return
            if item.get("heartbeat"):
                yield ": ping\n\n"
            else:
                yield f"event: job\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/courses/{course_id}/content-index")
async def content_index(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Modules and content items for choosing an analysis scope (live from Canvas)."""
    import asyncio

    from emneklar.core.canvas.api import CanvasAPI

    course_id = require_course_id(course_id)
    api = CanvasAPI(c.canvas())
    results: list[Any] = await asyncio.gather(
        api.list_modules(course_id), api.list_pages(course_id, include_body=False), api.list_assignments(course_id),
        api.list_discussions(course_id), api.list_quizzes(course_id), return_exceptions=True)
    modules, pages, assignments, discussions, quizzes = results

    def ok(value: Any) -> list[dict[str, Any]]:
        return value if isinstance(value, list) else []

    module_of: dict[str, str] = {}
    for module in ok(modules):
        for item in module.get("items") or []:
            kind = {"Page": "page", "Assignment": "assignment", "Discussion": "discussion", "Quiz": "quiz"}.get(
                str(item.get("type")))
            ident = item.get("page_url") if kind == "page" else item.get("content_id")
            if kind and ident is not None:
                module_of.setdefault(f"{kind}:{ident}", module.get("name") or "")
    items: list[dict[str, Any]] = []
    for kind, rows, id_key, title_key in (("page", pages, "url", "title"), ("assignment", assignments, "id", "name"),
                                          ("discussion", discussions, "id", "title"),
                                          ("quiz", quizzes, "id", "title")):
        for row in ok(rows):
            ident = str(row.get(id_key))
            items.append({"object_type": kind, "object_id": ident, "title": row.get(title_key) or "",
                          "module": module_of.get(f"{kind}:{ident}")})
    return {
        "modules": [{"id": str(m["id"]), "name": m.get("name") or "", "items_count": len(m.get("items") or [])}
                    for m in ok(modules)],
        "items": items,
        "partial": any(isinstance(x, BaseException) for x in (modules, pages, assignments, discussions, quizzes)),
    }


@router.get("/courses/{course_id}/runs")
async def list_runs(course_id: str, limit: int = 20, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    with c.db.session() as session:
        rows = session.scalars(select(AnalysisRun).where(AnalysisRun.course_id == course_id)
                               .order_by(AnalysisRun.started_at.desc()).limit(min(100, max(1, limit)))).all()
        return {"runs": [run_dict(r) for r in rows]}


def run_dict(r: AnalysisRun) -> dict[str, Any]:
    scope = r.scope or {}
    return {"id": r.id, "job_id": r.job_id, "domains": r.domains, "scope_type": scope.get("type"),
            "status": r.status, "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "counts": r.counts,
            "ruleset_version": r.ruleset_version, "profile_id": r.profile_id, "profile_version": r.profile_version,
            "limitations": r.limitations, "stats": scope.get("stats") or {}}
