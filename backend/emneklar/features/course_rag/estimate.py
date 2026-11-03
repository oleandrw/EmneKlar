"""Estimate before building: what will be read, how long it may take, what must be downloaded, what AI is used.

Counts are exact (from the same mapping the build uses). Times are rough estimates from stated assumptions and
are shown as an interval. EmneKlar stores no prices, so AI use is shown as calls, tokens and the chosen model.
"""

from __future__ import annotations

import asyncio
from typing import Any

from emneklar.core.ai.local.whisper import Transcriber, choose_models
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.container import AppContainer
from emneklar.features.course_rag import engine
from emneklar.features.course_rag.markdown import to_markdown
from emneklar.features.course_rag.media import choose_track
from emneklar.features.course_rag.sources import (
    TEXT_KINDS,
    Inventory,
    SourceItem,
    SourceOptions,
    discover,
    group_counts,
    media_duration,
)
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
# Transcription time as a share of the audio duration (faster-whisper; int8 on CPU, float16 on GPU).
REALTIME_FACTOR = {("cpu", "tiny"): 0.08, ("cpu", "base"): 0.15, ("cpu", "small"): 0.35, ("cpu", "medium"): 0.9,
                   ("cpu", "large"): 2.0, ("cuda", "tiny"): 0.02, ("cuda", "base"): 0.03, ("cuda", "small"): 0.05,
                   ("cuda", "medium"): 0.08, ("cuda", "large"): 0.12}
ASSUMED_BITRATE_MBIT = 1.5  # for files whose duration is unknown
MAX_TRACK_LOOKUPS = 30


def _text_chunks(inv: Inventory) -> tuple[int, int]:
    words = chunks = 0
    for item in inv.items:
        if item.kind in TEXT_KINDS and not item.meta.get("link_source_only") and item.parsed is not None:
            count = len(to_markdown(item.parsed.blocks).split())
            words += count
            chunks += max(1, -(-count // WORDS_PER_CHUNK)) if count else 0
    return words, chunks


async def _video(c: AppContainer, api: CanvasAPI, inv: Inventory, device: str) -> tuple[dict[str, Any], float,
                                                                                        list[dict[str, Any]], list[str]]:
    items: list[SourceItem] = [i for i in inv.items if i.kind in ("media", "youtube") or (i.kind == "file" and
                               i.meta.get("category") in ("video_file", "subtitle"))]
    files = [i for i in items if i.kind == "file" and i.meta.get("category") == "video_file"][:MAX_TRACK_LOOKUPS]
    tracks = await asyncio.gather(*(api.media_attachment_tracks(i.canvas_id) for i in files), return_exceptions=True)
    file_captions = {i.key: isinstance(t, list) and choose_track(t) is not None for i, t in zip(files, tracks,
                                                                                            strict=True)}
    settings = c.settings.get()
    local = c.local_models
    nb, other = choose_models(local, settings.rag.whisper_model, settings.rag.whisper_other_language_model, device)
    worker = Transcriber(local, nb, other, device)
    with_captions = to_transcribe = unknown = youtube = 0
    known = transcribe_seconds = 0.0
    for item in items:
        duration = media_duration(item) if item.kind == "media" else None
        if duration:
            known += duration
        elif item.kind != "youtube":
            unknown += 1
        if item.kind == "youtube":
            youtube += 1
            continue
        captioned = item.meta.get("category") == "subtitle" or (
            choose_track(list(item.meta.get("tracks") or [])) is not None if item.kind == "media"
            else file_captions.get(item.key, False))
        if captioned:
            with_captions += 1
            continue
        to_transcribe += 1
        seconds = duration or int(item.meta.get("size") or 0) * 8 / (ASSUMED_BITRATE_MBIT * 1_000_000)
        transcribe_seconds += seconds * REALTIME_FACTOR.get((device, nb.size or "small"), 1.0)
    downloads = []
    notes = []
    if to_transcribe:
        if not worker.available():
            notes.append(f"{to_transcribe} video(er) uten teksting kan ikke transkriberes fordi lokale modeller ikke er "
                         "installert (setup-emne-rag.bat).")
            transcribe_seconds = 0.0
        elif worker.downloads_needed():
            downloads.append({"label": f"{nb.label} (konverteres lokalt første gang)", "size_mb": nb.size_mb,
                              "kind": "whisper"})
            notes.append(f"{other.label} (ca. {other.size_mb} MB) lastes ned bare hvis det finnes tale på et annet språk "
                         "enn norsk.")
    summary = {"count": len(items), "with_captions": with_captions, "to_transcribe": to_transcribe,
               "youtube": youtube, "minutes_known": round(known / 60, 1), "unknown_duration": unknown,
               "unavailable": sum(1 for s in inv.skipped if s.kind in ("tool", "vimeo")), "model": nb.label}
    return summary, transcribe_seconds, downloads, notes


async def estimate(c: AppContainer, course_id: str, options: SourceOptions) -> dict[str, Any]:
    settings = c.settings.get()
    api = CanvasAPI(c.canvas())
    inv = await discover(api, course_id, options, settings.canvas.base_url or "")
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
    registry = engine.registry(c, course_id)
    privacy = ["Bare lærerprodusert innhold leses: sider, oppgave- og quizbeskrivelser, emneplan, lærerens "
               "diskusjonsinnlegg og lærerens filer.",
               "Innleveringer, karakterer, meldinger, studentinnlegg og svar i diskusjoner hentes aldri."]
    downloads = []
    video = None
    assumptions_extra: list[str] = []
    if options.video:
        video, transcribe_seconds, video_downloads, video_notes = await _video(c, api, inv, device)
        seconds += transcribe_seconds
        downloads += video_downloads
        inv.limitations.extend(video_notes)
        assumptions_extra.append(f"Transkripsjon med {video['model']} på {'GPU' if device == 'cuda' else 'CPU'}; "
                                 f"videoer med ukjent varighet er anslått ut fra filstørrelsen "
                                 f"({ASSUMED_BITRATE_MBIT:g} Mbit/s).")
    images = None
    if options.images:
        from emneklar.features.course_rag.images import metadata_reason

        candidates = [i for i in inv.items if i.kind == "image" or (i.kind == "file" and
                      i.meta.get("category") == "image_file")]
        likely = [i for i in candidates if metadata_reason(i.meta) is None]
        images = {"candidates": len(candidates), "after_filter": len(likely),
                  "documents_note": "bilder inne i dokumenter telles under byggingen"}
        plan = c.ai.plan("rag_image", input_chars=1500, images=1, summary="")
        ai.append({"task": "rag_image", "label": "Bildebeskrivelser", "calls": len(likely), "images": len(likely),
                   "input_tokens": len(likely) * 2100, "available": plan["available"], "reason": plan["reason"],
                   "route": plan["route"], "external": plan["external"]})
        if plan["available"]:
            seconds += len(likely) * IMAGE_SECONDS / 2
        else:
            inv.limitations.append(f"Bildene kan ikke beskrives: {plan['reason']}")
        if plan["external"]:
            privacy.append(f"Opptil {len(likely)} bilder fra emnet (og bilder i dokumenter) sendes til KI-leverandøren "
                           "med sidetittel og tekst rundt bildet. Pynt og duplikater filtreres bort først.")
    from emneklar.features.course_rag.builder import BuildRequest, evaluation_may_use_ai

    if evaluation_may_use_ai(c, BuildRequest(**options.model_dump(), confirmed=True)):
        plan = c.ai.plan("rag_eval", input_chars=6000, images=0, summary="")
        ai.append({"task": "rag_eval", "label": "Testspørsmål til evalueringen", "calls": 3, "input_tokens": 6000,
                   "available": True, "reason": None, "route": plan["route"], "external": plan["external"]})
    if embedding.needs_download:
        downloads.append({"label": embedding.label, "size_mb": embedding.download_mb, "kind": "embedding"})
    if reranker.available and reranker.needs_download:
        downloads.append({"label": reranker.label, "size_mb": reranker.download_mb, "kind": "reranker"})
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
                     *assumptions_extra,
                     "Første nedlasting av modeller er ikke regnet med."]},
        "video": video,
        "images": images,
        "downloads": downloads,
        "ai": ai,
        "embedding": embedding.as_dict(),
        "reranker": reranker.as_dict(),
        "device": device,
        "privacy": privacy,
        "index": {"exists": index_path(c.config.rag_dir, course_id).exists(),
                  "embedding": (registry or {}).get("embedding"), "built_at": (registry or {}).get("built_at")},
    }
