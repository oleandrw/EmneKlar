"""Estimate before building: what will be read, how long it may take, what must be downloaded, what AI is used.

Counts are exact (from the same mapping the build uses). Times are rough estimates from stated assumptions and
are shown as an interval. EmneKlar stores no prices, so AI use is shown as calls, tokens and the chosen model.
"""

from __future__ import annotations

from typing import Any

from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.container import AppContainer
from emneklar.features.course_rag import engine
from emneklar.features.course_rag.markdown import to_markdown
from emneklar.features.course_rag.sources import TEXT_KINDS, Inventory, SourceOptions, discover, group_counts
from emneklar.features.course_rag.store import index_path

WORDS_PER_CHUNK = 300
# Assumptions for the time estimate (seconds). Shown to the user with the estimate.
FETCH_PER_FILE = 1.5
FETCH_PER_MB = 1.0
PARSE_PER_FILE = 1.0
CHUNKS_PER_SECOND = {"cpu": 3.0, "cuda": 40.0, "provider": 30.0}
ENRICH_PER_CALL = 8.0
ENRICH_BATCH = 8
IMAGE_SECONDS = 6.0
CHARS_PER_TOKEN = 3


def _text_chunks(inv: Inventory) -> tuple[int, int]:
    words = chunks = 0
    for item in inv.items:
        if item.kind in TEXT_KINDS and not item.meta.get("link_source_only") and item.parsed is not None:
            count = len(to_markdown(item.parsed.blocks).split())
            words += count
            chunks += max(1, -(-count // WORDS_PER_CHUNK)) if count else 0
    return words, chunks


async def estimate(c: AppContainer, course_id: str, options: SourceOptions) -> dict[str, Any]:
    settings = c.settings.get()
    inv = await discover(CanvasAPI(c.canvas()), course_id, options, settings.canvas.base_url or "")
    counts = group_counts(inv)
    words, text_chunks = _text_chunks(inv)
    documents = [i for i in inv.items if i.kind == "file" and i.meta.get("category") == "document"]
    doc_mb = sum(int(i.meta.get("size") or 0) for i in documents) / (1024 * 1024)
    too_large = [i for i in documents if int(i.meta.get("size") or 0) > settings.rag.max_file_mb * 1024 * 1024]
    # Documents: roughly one chunk per 40 KB of file (very rough; PDFs vary a lot).
    doc_chunks = sum(max(1, int(int(i.meta.get("size") or 0) / 40_000)) for i in documents)
    total_chunks = text_chunks + doc_chunks
    embedding, reranker, device = engine.choices(c)
    rate = CHUNKS_PER_SECOND["provider"] if embedding.backend == "provider" else CHUNKS_PER_SECOND.get(device, 3.0)
    seconds = (len(documents) * (FETCH_PER_FILE + PARSE_PER_FILE) + doc_mb * FETCH_PER_MB
               + (total_chunks / rate if embedding.available else 0))
    ai: list[dict[str, Any]] = []
    if options.contextual_enrichment:
        calls = -(-total_chunks // ENRICH_BATCH)
        tokens = (words * 2 + doc_mb * 150_000) // CHARS_PER_TOKEN
        plan = c.ai.plan("rag_context", input_chars=12_000, images=0, summary="")
        ai.append({"task": "rag_context", "label": "Kontekstuell berikelse", "calls": calls,
                   "input_tokens": int(tokens), "available": plan["available"], "reason": plan["reason"],
                   "route": plan["route"], "external": plan["external"]})
        seconds += calls * ENRICH_PER_CALL
    downloads = []
    if embedding.needs_download:
        downloads.append({"label": embedding.label, "size_mb": embedding.download_mb, "kind": "embedding"})
    if reranker.available and reranker.needs_download:
        downloads.append({"label": reranker.label, "size_mb": reranker.download_mb, "kind": "reranker"})
    registry = engine.registry(c, course_id)
    privacy = ["Bare lærerprodusert innhold leses: sider, oppgave- og quizbeskrivelser, emneplan, lærerens "
               "diskusjonsinnlegg og lærerens filer.",
               "Innleveringer, karakterer, meldinger, studentinnlegg og svar i diskusjoner hentes aldri."]
    if embedding.external:
        privacy.append(f"Utdragene sendes til {embedding.label} for embedding (ekstern leverandør).")
    return {
        "counts": counts,
        "words": words,
        "documents": {"count": len(documents), "size_mb": round(doc_mb, 1),
                      "too_large": [{"title": i.title, "size_mb": round(int(i.meta.get('size') or 0) / 1048576, 1)}
                                    for i in too_large]},
        "chunks_estimate": total_chunks,
        "skipped": [s.as_dict() for s in inv.skipped],
        "limitations": inv.limitations,
        "modules": inv.modules,
        "time": {"low_seconds": int(seconds * 0.5), "high_seconds": int(seconds * 2 + 10),
                 "assumptions": [
                     f"Embedding: ca. {rate:g} utdrag per sekund ({'GPU' if device == 'cuda' else 'CPU'}"
                     f"{', leverandør' if embedding.backend == 'provider' else ''}).",
                     "Dokumenter: ca. 2,5 sekunder per fil pluss 1 sekund per MB.",
                     "Første nedlasting av modeller er ikke regnet med."]},
        "downloads": downloads,
        "ai": ai,
        "embedding": embedding.as_dict(),
        "reranker": reranker.as_dict(),
        "device": device,
        "privacy": privacy,
        "index": {"exists": index_path(c.config.rag_dir, course_id).exists(),
                  "embedding": (registry or {}).get("embedding"), "built_at": (registry or {}).get("built_at")},
    }
