"""The background job that builds and updates an Emne-RAG index.

Phases: map the course → text from Canvas → documents → (video and audio) → (images) → finish (evaluation).

* **Progress** is truthful: totals are added when the work is known, and every element is marked done only when
  its chunks are stored.
* **Pause, cancel, resume:** checkpoints between elements. Every element is committed to the index when it is
  finished, so a cancelled or interrupted build keeps what is done; «Fortsett» starts an update that skips all
  unchanged elements.
* **Incremental:** an element is processed again only when its signature (``updated_at``, content hash, module
  membership and processing options) changed. Elements that no longer exist in Canvas are removed.
* **Robust:** an element that fails is logged and listed as skipped; the build continues.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from emneklar.core.ai.local.embedding import Embedder, open_embedder, open_reranker
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import CanvasError
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.jobs.manager import JobContext
from emneklar.features.course_rag import engine
from emneklar.features.course_rag.chunking import ChunkDraft, chunk_blocks, chunk_units
from emneklar.features.course_rag.convert.documents import group_of
from emneklar.features.course_rag.images import Deduplicator
from emneklar.features.course_rag.sources import KIND_LABELS, TEXT_KINDS, Inventory, SourceItem, SourceOptions, discover
from emneklar.features.course_rag.store import ChunkRecord, IndexStore, ItemRecord

log = logging.getLogger(__name__)

PARSER_TIMEOUT = 240.0
DOC_CONCURRENCY = 2
PARSER_ERRORS = {"timeout": "Filen tok for lang tid å lese og ble hoppet over.",
                 "crashed": "Leseren krasjet på filen (den kan være skadet).",
                 "memory": "Filen krevde for mye minne å lese.",
                 "exception": "Filen kunne ikke leses (den kan være skadet eller i et uventet format).",
                 "bad_response": "Filen kunne ikke leses.", "unsupported": "Filformatet støttes ikke."}


class BuildRequest(SourceOptions):
    mode: Literal["update", "full"] = "update"
    confirmed: bool = False  # consent for AI and external embeddings (payload summary shown in the estimate)
    accept_downloads: bool = False  # first-time download of local models (size shown in the estimate)


@dataclass
class BuildState:
    c: AppContainer
    ctx: JobContext
    course_id: str
    request: BuildRequest
    store: IndexStore
    api: CanvasAPI
    embedder: Embedder | None
    tmp: Path
    done: int = 0
    failed: int = 0
    skipped: int = 0
    unchanged: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    images_seen: Deduplicator = field(default_factory=Deduplicator)  # perceptual hashes seen in this build


def chunk_records(item: SourceItem, drafts: list[ChunkDraft], *, extra_meta: dict[str, Any] | None = None) -> list[
        ChunkRecord]:
    records = []
    module_ids = [m["id"] for m in item.modules]
    for index, draft in enumerate(drafts):
        meta = {**(extra_meta or {}), **draft.meta}
        if item.kind == "file" and draft.type == "table" and draft.heading_path:
            meta.setdefault("sheet", draft.heading_path[0])
        records.append(ChunkRecord(
            uid=f"{item.key}#{index}", item_key=item.key, type=draft.type, item_kind=item.kind, title=item.title,
            text=draft.text, heading_path=draft.heading_path, module_ids=module_ids, module_name=item.module_name,
            url=draft.meta.get("url") or item.url, page=draft.page, page_end=draft.page_end, start=draft.start,
            end=draft.end, updated_at=item.updated_at, tokens=draft.tokens, meta=meta))
    return records


def item_record(item: SourceItem, options: SourceOptions, *, status: str = "done", reason: str | None = None,
                content_hash: str | None = None, meta: dict[str, Any] | None = None) -> ItemRecord:
    return ItemRecord(key=item.key, kind=item.kind, title=item.title, canvas_id=item.canvas_id, url=item.url,
                      modules=item.modules, updated_at=item.updated_at, content_hash=content_hash or item.content_hash,
                      signature=item.signature(options), status=status, reason=reason, meta=meta or {})


async def embed_records(state: BuildState, records: list[ChunkRecord]) -> np.ndarray | None:
    if state.embedder is None or not records:
        return None
    async with state.lock:  # one embedding batch at a time (CPU/GPU bound)
        return await state.embedder.embed_documents([r.search_text() for r in records])


async def store_chunks(state: BuildState, item: SourceItem, records: list[ChunkRecord], *,
                       content_hash: str | None = None, meta: dict[str, Any] | None = None) -> None:
    if state.request.contextual_enrichment and records:
        from emneklar.features.course_rag.enrich import enrich_records

        await enrich_records(state, item, records)
    vectors = await embed_records(state, records)
    status = "done" if records else "skipped"
    reason = None if records else "Elementet har ingen tekst som kan indekseres."
    state.store.put_item(item_record(item, state.request, status=status, reason=reason, content_hash=content_hash,
                                     meta=meta), records, vectors)
    if records:
        state.done += 1
    else:
        state.skipped += 1


def mark(state: BuildState, item: SourceItem, status: str, reason: str) -> None:
    state.store.put_item(item_record(item, state.request, status=status, reason=reason), [])
    if status == "failed":
        state.failed += 1
    else:
        state.skipped += 1


async def guarded(state: BuildState, item: SourceItem, task_type: str, operation: str,
                  work: Callable[[], Awaitable[None]]) -> None:
    """Run one element: progress, errors logged and recorded, never aborting the whole build."""
    await state.ctx.checkpoint()
    started = state.ctx.progress.start(task_type, item=item.title, operation=operation)
    failed = False
    try:
        await work()
    except (AppError, CanvasError) as exc:
        if exc.code in ("ai_consent_required", "ai_not_configured", "ai_sharing_disabled"):
            raise
        failed = True
        log.warning("Emne-RAG: %s feilet: %s", item.key, exc.code)
        mark(state, item, "failed", exc.message)
        state.ctx.progress.note(f"Hoppet over «{item.title}»: {exc.message}")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        failed = True
        log.exception("Emne-RAG: %s feilet uventet", item.key)
        mark(state, item, "failed", f"Uventet feil ({type(exc).__name__}).")
        state.ctx.progress.note(f"Hoppet over «{item.title}» på grunn av en feil.")
    finally:
        state.ctx.progress.finish(task_type, started, failed=failed)


# --------------------------------------------------------------------------------------------- text


async def process_text(state: BuildState, item: SourceItem) -> None:
    assert item.parsed is not None
    drafts = chunk_blocks(item.parsed.blocks)
    await store_chunks(state, item, chunk_records(item, drafts))


# ----------------------------------------------------------------------------------------- documents


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


async def download_file(state: BuildState, item: SourceItem, target: Path, *, max_mb: int) -> tuple[Path, str]:
    url = item.meta.get("download_url")
    if not url:
        info = await state.api.get_file(item.canvas_id)
        url = info.get("url")
    if not url:
        raise AppError("file_unsupported", message="Filen har ingen nedlastingsadresse i Canvas.")
    target.parent.mkdir(parents=True, exist_ok=True)
    await state.api.client.download(str(url), target, max_bytes=max_mb * 1024 * 1024)
    return target, _sha256(target)


async def ocr_units(state: BuildState, item: SourceItem, path: Path, work: Path) -> list[dict[str, Any]] | None:
    """Text for a scanned PDF via Tesseract or the AI image model; None when no OCR route is available."""
    from emneklar.features.course_rag.convert import ocr

    use_ai = state.request.images and state.c.ai.plan("rag_image", input_chars=500, images=1, summary="")["available"]
    if ocr.tesseract_languages() is None and not use_ai:
        return None
    rendered = await state.c.parsers.run({"job": "rag_render_pdf", "args": {"path": str(path),
                                                                              "out_dir": str(work / "ocr")}},
                                         timeout=PARSER_TIMEOUT)
    pages = rendered.get("pages") or []
    units = []
    for page in pages:
        await state.ctx.checkpoint()
        image = Path(page["path"])
        if ocr.tesseract_languages() is not None:
            text = await asyncio.to_thread(ocr.tesseract_text, image)
        else:
            from emneklar.features.course_rag.images import ai_ocr

            text = await ai_ocr(state, item, image)
        from emneklar.features.course_rag.convert.documents import text_to_blocks

        blocks = text_to_blocks(text, page=int(page["number"]))
        if blocks:
            units.append({"kind": "page", "number": int(page["number"]), "blocks": [b.as_dict() for b in blocks]})
    return units


async def process_document(state: BuildState, item: SourceItem) -> None:
    max_mb = state.c.settings.get().rag.max_file_mb
    size = int(item.meta.get("size") or 0)
    if size > max_mb * 1024 * 1024:
        mark(state, item, "skipped", f"Filen er større enn grensen på {max_mb} MB (Emne-RAG → Innstillinger).")
        return
    work = state.tmp / hashlib.sha1(item.key.encode()).hexdigest()[:12]  # noqa: S324 - folder name only
    try:
        path, sha = await download_file(state, item, work / "fil", max_mb=max_mb)
        fmt = str(item.meta.get("format"))
        images_dir = str(work / "bilder") if state.request.images else None
        result = await state.c.parsers.run({"job": "rag_convert", "args": {
            "path": str(path), "fmt": fmt, "out_dir": images_dir, "max_images": 40}}, timeout=PARSER_TIMEOUT)
        if result.get("error"):
            mark(state, item, "failed", PARSER_ERRORS.get(str(result["error"]), "Filen kunne ikke leses."))
            return
        if "encrypted" in (result.get("warnings") or []):
            mark(state, item, "skipped", "PDF-en er passordbeskyttet og kan ikke leses.")
            return
        units = list(result.get("units") or [])
        meta = {"format": fmt, "pages": result.get("pages")}
        if result.get("needs_ocr"):
            ocr = await ocr_units(state, item, path, work)
            if ocr is None:
                mark(state, item, "skipped", "PDF-en ser skannet ut (bilder av tekst). OCR krever Tesseract med norsk "
                     "språkpakke, eller at bilder er slått på og en bildemodell er tilgjengelig via KI.")
                return
            units = ocr
            meta["ocr"] = True
        drafts = chunk_units(units, title=item.title)
        records = chunk_records(item, drafts, extra_meta={"format": fmt})
        if state.request.images and result.get("images"):
            from emneklar.features.course_rag.images import document_image_records

            state.ctx.progress.set_current(item.title, operation="Beskriver bilder i dokumentet")
            image_records, notes = await document_image_records(state, item, list(result["images"]), len(records))
            records += image_records
            meta["images_described"] = len(image_records)
            if notes:
                meta["notes"] = notes
        await store_chunks(state, item, records, content_hash=sha, meta=meta)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------------------------------- the job


def evaluation_may_use_ai(c: AppContainer, request: BuildRequest) -> bool:
    """AI writes the test questions only when it is local, or when this build already sends content to AI with consent."""
    plan = c.ai.plan("rag_eval", input_chars=6000, images=0, summary="")
    if not plan["available"]:
        return False
    return not plan["external"] or (request.confirmed and (request.contextual_enrichment or request.images))


async def run_evaluation(state: BuildState, reranker_def: Any, device: str) -> None:
    from emneklar.features.course_rag.evaluation import evaluate

    progress = state.ctx.progress
    progress.add_tasks("evaluation", 1)
    started = progress.start("evaluation", item="Testspørsmål", operation="Måler søket med testspørsmål")
    failed = False
    try:
        reranker = None
        if reranker_def.available and not reranker_def.needs_download:
            reranker = await open_reranker(reranker_def, state.c.local_models, device=device)
        result = await evaluate(state.store, embedder=state.embedder, reranker=reranker, ai=state.c.ai,
                                use_ai=evaluation_may_use_ai(state.c, state.request), confirmed=state.request.confirmed,
                                course_id=state.course_id, candidates=state.c.settings.get().rag.candidates)
        if result:
            engine.update_registry(state.c, state.course_id, evaluation=result)
            progress.note(f"Helsescore for søket: {result['health']} av 100 ({result['health_label'].lower()}).")
    except (AppError, CanvasError) as exc:
        failed = True
        progress.note(f"Evalueringen kunne ikke kjøres: {exc.message}")
    except Exception:  # the index is usable without an evaluation
        failed = True
        log.exception("Emne-RAG: evalueringen feilet")
        progress.note("Evalueringen kunne ikke kjøres.")
    finally:
        progress.finish("evaluation", started, failed=failed)


def plan_items(inv: Inventory, store: IndexStore, options: SourceOptions) -> tuple[list[SourceItem], int, list[str]]:
    existing = store.items()
    todo: list[SourceItem] = []
    unchanged = 0
    keys = set()
    for item in inv.items:
        if item.meta.get("link_source_only"):
            continue
        keys.add(item.key)
        row = existing.get(item.key)
        if row and row["signature"] == item.signature(options) and row["status"] in ("done", "skipped"):
            unchanged += 1
            continue
        todo.append(item)
    removed = [k for k in existing if k not in keys]
    return todo, unchanged, removed


def skipped_list(inv: Inventory, store: IndexStore) -> list[dict[str, Any]]:
    out = [s.as_dict() for s in inv.skipped]
    for key, row in store.items().items():
        if row["status"] in ("skipped", "failed"):
            out.append({"key": key, "kind": row["kind"], "kind_label": KIND_LABELS.get(row["kind"], row["kind"]),
                        "title": row["title"], "reason": row["reason"] or "", "url": row["url"],
                        "failed": row["status"] == "failed"})
    return out


async def run_build(ctx: JobContext, c: AppContainer, course_id: str, request: BuildRequest) -> dict[str, Any]:
    progress = ctx.progress
    phases = ["Kartlegger emnet"]
    if request.text:
        phases.append("Tekst fra Canvas")
    if request.documents:
        phases.append("Dokumenter")
    if request.video:
        phases.append("Video og lyd")
    if request.images:
        phases.append("Bilder")
    phases.append("Ferdigstiller indeksen")
    total = len(phases)
    progress.set_phase("discover", phases[0], index=1, count=total, determinate=False)
    api = CanvasAPI(c.canvas())
    settings = c.settings.get()
    base = settings.canvas.base_url or ""
    progress.add_tasks("list", 8 if (request.documents or request.images or request.video) else 7)

    def on_list(_name: str, label: str, _count: int | None, error: str | None) -> None:
        started = progress.start("list", item=label, operation="Henter fra Canvas")
        progress.finish("list", started, failed=error is not None)

    inv = await discover(api, course_id, request, base, on_list=on_list)
    embedding, reranker_def, device = engine.choices(c)
    identity = embedding.identity if embedding.available else None
    store = engine.store_for(c, course_id)
    if request.mode == "full" or not store.items():
        store.reset(identity)
    elif (store.embedding_identity or None) != identity:
        store.close()
        raise AppError("rag_model_changed", status=409)
    tmp = c.config.tmp_dir / f"rag-{ctx.job_id[:8]}"
    state = BuildState(c, ctx, course_id, request, store, api, None, tmp)
    status = "partial"
    engine.update_registry(c, course_id, status="building", options=request.model_dump(
        exclude={"confirmed", "accept_downloads", "mode"}), last_job_id=ctx.job_id,
        embedding={"identity": identity, "label": embedding.label if identity else "Bare nøkkelordsøk (BM25)",
                   "backend": embedding.backend if identity else "none"})
    try:
        if identity is not None:
            progress.set_current("Laster embedding-modell", operation=embedding.label)
            state.embedder = await open_embedder(embedding, c.local_models, c.ai, device=device,
                                                 confirmed=request.confirmed, course_id=course_id)
            if reranker_def.available and request.accept_downloads and reranker_def.needs_download:
                progress.set_current("Laster ned rerangeringsmodell", operation=reranker_def.label)
                await open_reranker(reranker_def, c.local_models, device=device)
        todo, state.unchanged, removed = plan_items(inv, store, request)
        if removed:
            store.delete_items(removed)
            progress.note(f"{len(removed)} element(er) som ikke lenger finnes i Canvas (eller utenfor omfanget), "
                          "ble fjernet fra indeksen.")
        if state.unchanged:
            progress.note(f"{state.unchanged} element(er) er uendret siden sist og ble ikke behandlet på nytt.")
        text_items = [i for i in todo if i.kind in TEXT_KINDS]
        documents = [i for i in todo if i.kind == "file" and i.meta.get("category") == "document"]
        media_items = [i for i in todo if i.kind in ("media", "youtube", "vimeo") or
                       (i.kind == "file" and i.meta.get("category") in ("video_file", "subtitle"))]
        image_items = [i for i in todo if i.kind == "image" or (i.kind == "file" and i.meta.get("category") ==
                       "image_file")]
        for items, task in ((text_items, None), (documents, "document"), (media_items, "media"),
                            (image_items, "image")):
            for item in items:
                progress.add_tasks(task or item.kind, 1)
        phase = 1
        if request.text:
            phase += 1
            progress.set_phase("text", "Tekst fra Canvas", index=phase, count=total, determinate=True)
            for item in text_items:
                await guarded(state, item, item.kind, "Gjør om til Markdown og deler opp",
                              functools.partial(process_text, state, item))
        if request.documents:
            phase += 1
            progress.set_phase("documents", "Dokumenter", index=phase, count=total, determinate=True)
            semaphore = asyncio.Semaphore(DOC_CONCURRENCY)

            async def one(item: SourceItem) -> None:
                async with semaphore:
                    label = group_of(str(item.meta.get("format"))) or "fil"
                    await guarded(state, item, "document", f"Leser {label.upper() if label == 'pdf' else label}",
                                  functools.partial(process_document, state, item))

            await asyncio.gather(*(one(item) for item in documents))
        if request.video:
            phase += 1
            progress.set_phase("media", "Video og lyd", index=phase, count=total, determinate=True)
            from emneklar.features.course_rag.media import process_media

            for item in media_items:
                await guarded(state, item, "media", "Henter teksting eller transkriberer",
                              functools.partial(process_media, state, item))
        if request.images:
            phase += 1
            progress.set_phase("images", "Bilder", index=phase, count=total, determinate=True)
            from emneklar.features.course_rag.images import process_images

            await process_images(state, image_items, inv)
        phase += 1
        progress.set_phase("finish", "Ferdigstiller indeksen", index=phase, count=total, determinate=True)
        await run_evaluation(state, reranker_def, device)
        status = "ready"
    finally:
        stats = store.stats()
        skipped = skipped_list(inv, store)
        finished: dict[str, Any] = {"built_at": datetime.now(UTC)} if status == "ready" else {}
        engine.update_registry(c, course_id, status=status, stats=stats, skipped=skipped, limitations=inv.limitations,
                               **finished)
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)
    result = {"items_processed": state.done, "unchanged": state.unchanged, "skipped": state.skipped,
              "failed": state.failed, "chunks": stats["chunks"], "skipped_total": len(skipped)}
    progress.add_findings("rag:chunks", stats["chunks"])
    return result
