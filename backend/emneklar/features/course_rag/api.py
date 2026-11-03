"""Emne-RAG API (Canvas-verktøy → Emne-RAG). Read-only towards Canvas."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from emneklar.api.deps import get_container, require_course_id
from emneklar.core import flags
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.jobs.manager import JobContext
from emneklar.features.course_rag import engine
from emneklar.features.course_rag.answer import generate_answer, payload_summary, rewrite_query
from emneklar.features.course_rag.builder import BuildRequest, run_build
from emneklar.features.course_rag.convert.documents import GROUP_LABELS
from emneklar.features.course_rag.estimate import estimate
from emneklar.features.course_rag.search import needs_rewrite, search
from emneklar.features.course_rag.sources import SourceOptions
from emneklar.features.course_rag.store import CHUNK_TYPES

router = APIRouter(prefix="/api")

CHUNK_TYPE_LABELS = {"text": "Tekst", "table": "Tabeller", "image": "Bilder", "transcript": "Video og lyd",
                     "slide": "Lysbilder"}
NOT_YET: dict[str, str] = {}  # options that are not available in this version (key → explanation)


def _flag(c: AppContainer) -> None:
    flags.require(c.settings.get(), "course_rag")


def _check_options(options: SourceOptions) -> None:
    if not (options.text or options.documents or options.images or options.video) or (
            options.scope == "modules" and not options.module_ids):
        raise AppError("rag_nothing_selected")
    for key, message in NOT_YET.items():
        if getattr(options, key, False):
            raise AppError("unsupported", status=409, message=message)


@router.get("/courses/{course_id}/rag")
async def status(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    settings = c.settings.get()
    stats = None
    modules: list[dict[str, str]] = []
    index_embedding = None
    error = None
    if engine.has_index(c, course_id):
        try:
            store = engine.store_for(c, course_id, create=False)
        except AppError as exc:
            error = {"code": exc.code, "message": exc.message}
        else:
            stats, modules, index_embedding = store.stats(), store.modules(), store.embedding_identity
            store.close()
    embedding, reranker, device = engine.choices(c)
    local = await asyncio.to_thread(c.local_models.status, settings.rag.device)
    ai_reason = c.ai.unavailable_reason(settings)
    from emneklar.core.ai.transcription import catalog as transcription_catalog

    rag = settings.rag
    transcription = c.ai.transcription_plan(rag.transcription_provider_id, rag.transcription_model, summary="") \
        if rag.transcription == "provider" else None
    return {
        "index": engine.registry(c, course_id), "stats": stats, "modules": modules, "error": error,
        "index_embedding": index_embedding or None,
        "model_mismatch": stats is not None and (index_embedding or None) != (
            embedding.identity if embedding.available else None),
        "embedding": embedding.as_dict(), "reranker": reranker.as_dict(), "device": device, "local": local,
        "ai": {"available": ai_reason is None, "reason": ai_reason},
        "busy_job": engine.busy_job(c, course_id),
        "settings": settings.rag.model_dump(mode="json"),
        "file_groups": [{"key": k, "label": v} for k, v in GROUP_LABELS.items()],
        "chunk_types": [{"key": k, "label": CHUNK_TYPE_LABELS[k]} for k in CHUNK_TYPES],
        "not_available": NOT_YET,
        "transcription": {"mode": rag.transcription, "plan": transcription},
        "transcription_models": [m.as_dict() for m in transcription_catalog()],
        "providers": [{"id": p.id, "name": p.name, "type": p.type} for p in settings.ai.providers
                      if p.type != "anthropic"],
    }


@router.post("/courses/{course_id}/rag/estimate")
async def estimate_build(course_id: str, body: SourceOptions, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    _check_options(body)
    return await estimate(c, course_id, body)


@router.post("/courses/{course_id}/rag/build")
async def build(course_id: str, body: BuildRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    _check_options(body)
    if engine.busy_job(c, course_id):
        raise AppError("rag_index_busy", status=409)
    c.canvas()  # fail fast with a clear message if Canvas is not configured
    embedding, reranker, _ = engine.choices(c)
    if (embedding.needs_download or (reranker.available and reranker.needs_download)) and not body.accept_downloads:
        raise AppError("rag_download_required", status=409)
    if embedding.needs_confirmation and not body.confirmed:
        raise AppError("ai_consent_required", status=409)
    if body.contextual_enrichment or body.images:
        task = "rag_context" if body.contextual_enrichment else "rag_image"
        plan = c.ai.plan(task, input_chars=4000, images=1 if task == "rag_image" else 0, summary="")
        if body.contextual_enrichment and not plan["available"]:
            raise AppError("ai_not_configured", status=409, message=plan["reason"])
        if plan["available"] and plan["needs_confirmation"] and not body.confirmed:
            raise AppError("ai_consent_required", status=409)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        return await run_build(ctx, c, course_id, body)

    exists = engine.has_index(c, course_id)
    title = ("Emne-RAG: oppretter kunnskapsbasen" if not exists else "Emne-RAG: bygger kunnskapsbasen på nytt"
             if body.mode == "full" else "Emne-RAG: oppdaterer kunnskapsbasen")
    state = c.jobs.submit(kind=engine.JOB_KIND, title=title, runner=runner, course_id=course_id,
                          params=body.model_dump(), supports_pause=True, hard_cancel=True)
    return state.public()


@router.delete("/courses/{course_id}/rag")
async def remove(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    _flag(c)
    engine.delete_index(c, require_course_id(course_id))
    return {"ok": True}


class QueryBody(BaseModel):
    query: str = Field(max_length=2000)
    module_ids: list[str] = Field(default_factory=list, max_length=200)
    types: list[str] = Field(default_factory=list, max_length=10)
    debug: bool = False
    confirmed: bool = False


def _query(body: QueryBody) -> str:
    query = body.query.strip()
    if not query:
        raise AppError("rag_query_empty")
    if any(t not in CHUNK_TYPES for t in body.types):
        raise AppError("validation_error", detail="Ukjent kildetype")
    return query


async def _search(c: AppContainer, course_id: str, body: QueryBody, *, extra: list[str] | None = None) -> Any:
    settings = c.settings.get()
    store = engine.store_for(c, course_id, create=False)
    try:
        embedder, reranker, notes = await engine.load_search_models(c, course_id=course_id, confirmed=body.confirmed)
        outcome = await search(store, _query(body), embedder=embedder, reranker=reranker,
                               module_ids=body.module_ids or None, types=body.types or None,
                               candidates=settings.rag.candidates, top_k=settings.rag.top_k, extra_queries=extra)
    finally:
        store.close()
    outcome.notes = notes + outcome.notes
    return outcome


@router.post("/courses/{course_id}/rag/search")
async def search_index(course_id: str, body: QueryBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    outcome = await _search(c, require_course_id(course_id), body)
    return outcome.as_dict(debug=body.debug)


@router.post("/courses/{course_id}/rag/ask/prepare")
async def prepare_answer(course_id: str, body: QueryBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    require_course_id(course_id)
    query = _query(body)
    top_k = c.settings.get().rag.top_k
    summary = (f"Spørsmålet ({len(query)} tegn) og inntil {top_k} utdrag fra lærerens innhold i emnet sendes til "
               "KI-leverandøren. Ingen studentdata sendes.")
    return c.ai.plan("rag_answer", input_chars=len(query) + top_k * 2000, images=0, summary=summary)


@router.post("/courses/{course_id}/rag/ask")
async def ask(course_id: str, body: QueryBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    query = _query(body)
    extra: list[str] = []
    settings = c.settings.get()
    rewrite_note = None
    if settings.rag.query_rewrite and needs_rewrite(query):
        try:
            extra = await rewrite_query(c.ai, query, confirmed=body.confirmed, course_id=course_id)
        except AppError as exc:
            if exc.code == "ai_consent_required":
                raise
            rewrite_note = "Spørsmålet kunne ikke skrives om. Det er søkt med spørsmålet slik det er skrevet."
    outcome = await _search(c, course_id, body, extra=extra)
    if rewrite_note:
        outcome.notes.append(rewrite_note)
    sources = [{**hit.as_dict(), "id": f"S{i}"} for i, hit in enumerate(outcome.hits, start=1)]
    if not outcome.hits:
        return {"answer": None, "coverage": "none", "cited": [], "sources": [], "search": outcome.as_dict(
            debug=body.debug), "message": "Fant ingenting i emnet som passer til spørsmålet."}
    result = await generate_answer(c.ai, query, outcome.hits, confirmed=body.confirmed, course_id=course_id)
    for source in sources:
        source["cited"] = source["id"] in result["cited"]
    return {**result, "sources": sources, "search": outcome.as_dict(debug=body.debug),
            "payload_summary": payload_summary(query, outcome.hits)}


class EvaluateBody(BaseModel):
    use_ai: bool = False
    confirmed: bool = False


@router.post("/courses/{course_id}/rag/evaluate")
async def run_evaluate(course_id: str, body: EvaluateBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Run the retrieval evaluation again (also done automatically after every build)."""
    from emneklar.features.course_rag.evaluation import evaluate

    _flag(c)
    course_id = require_course_id(course_id)
    if engine.busy_job(c, course_id):
        raise AppError("rag_index_busy", status=409)
    engine.store_for(c, course_id, create=False).close()  # 404 before the job starts
    if body.use_ai:
        plan = c.ai.plan("rag_eval", input_chars=6000, images=0, summary="")
        if not plan["available"]:
            raise AppError("ai_not_configured", status=409, message=plan["reason"])
        if plan["needs_confirmation"] and not body.confirmed:
            raise AppError("ai_consent_required", status=409)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        progress = ctx.progress
        progress.set_phase("evaluate", "Måler søket med testspørsmål", index=1, count=1, determinate=True)
        progress.add_tasks("evaluation", 1)
        started = progress.start("evaluation", item="Testspørsmål", operation="Søker med testspørsmål")
        store = engine.store_for(c, course_id, create=False)
        try:
            embedder, reranker, _notes = await engine.load_search_models(c, course_id=course_id, confirmed=body.confirmed)
            result = await evaluate(store, embedder=embedder, reranker=reranker, ai=c.ai, use_ai=body.use_ai,
                                    confirmed=body.confirmed, course_id=course_id,
                                    candidates=c.settings.get().rag.candidates)
        finally:
            store.close()
            progress.finish("evaluation", started)
        engine.update_registry(c, course_id, evaluation=result)
        return {"health": result.get("health"), "recall_at_5": result.get("recall_at_5"), "mrr": result.get("mrr")}

    state = c.jobs.submit(kind=engine.EVAL_JOB_KIND, title="Emne-RAG: evaluering av søket", runner=runner,
                          course_id=course_id, params=body.model_dump(), supports_pause=False, hard_cancel=True)
    return state.public()


@router.get("/courses/{course_id}/rag/export")
async def export_index(course_id: str, format: str = "zip", c: AppContainer = Depends(get_container)) -> FileResponse:
    import tempfile
    from datetime import UTC, datetime
    from pathlib import Path
    from urllib.parse import quote

    from emneklar.core.storage.models import Course
    from emneklar.features.course_rag.export import FORMATS, export

    _flag(c)
    course_id = require_course_id(course_id)
    if format not in FORMATS:
        raise AppError("validation_error", detail="Ukjent eksportformat")
    with c.db.session() as session:
        row = session.get(Course, course_id)
        course = {"id": course_id, "name": row.name if row else f"Emne {course_id}",
                  "course_code": row.course_code if row else None}
    store = engine.store_for(c, course_id, create=False)
    c.config.tmp_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="rag-eksport-", dir=c.config.tmp_dir)
    import os

    os.close(handle)
    target = Path(name)
    try:
        await asyncio.to_thread(export, store, course, format, target)  # type: ignore[arg-type]
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        store.close()
    media_type, ext = FORMATS[format]
    code = re.sub(r"[^A-Za-z0-9æøåÆØÅ_-]+", "-", str(course.get("course_code") or course_id)).strip("-") or course_id
    filename = f"emne-rag-{code}-{datetime.now(UTC).strftime('%Y%m%d')}.{ext}"
    ascii_name = filename.encode("ascii", "replace").decode()
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return FileResponse(target, media_type=media_type, background=BackgroundTask(target.unlink, missing_ok=True),
                        headers={"Content-Disposition": disposition})
