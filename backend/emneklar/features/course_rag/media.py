"""Video and audio: existing captions first, otherwise local transcription with NB-Whisper.

Order per video:

1. Canvas captions – ``media_attachments/:id/media_tracks?include[]=webvtt_content`` for uploaded files, the
   track ``url`` from ``courses/:id/media_objects`` for recorded media;
2. YouTube captions (``youtube-transcript-api``, unofficial; can be turned off). YouTube audio is never
   downloaded – a video without captions is skipped with an explanation;
3. local transcription (``core/ai/local/whisper``) of the Canvas file or media source.

Transcripts are cached on disk by the SHA-256 of the media file (``cache/rag/transcripts``), so the same
recording is never transcribed twice. Transcripts are split into chunks of about 60–120 seconds, cut at pauses or
sentence ends, with ~10 seconds of overlap. Timestamps are kept: YouTube and Vimeo links open at the right time;
Canvas cannot open a video at a given time from a link, so the link goes to the page or file and the citation
shows the time.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from emneklar.core.ai.local.whisper import Segment, Transcriber, Transcript, TranscriptionStopped, choose_models
from emneklar.core.canvas.client import CanvasError
from emneklar.core.errors import AppError
from emneklar.features.course_rag.chunking import ChunkDraft
from emneklar.features.course_rag.convert.documents import decode_text
from emneklar.features.course_rag.sources import SourceItem, Waiting

if TYPE_CHECKING:
    from emneklar.features.course_rag.builder import BuildState

log = logging.getLogger(__name__)

MIN_SECONDS = 60.0
MAX_SECONDS = 120.0
OVERLAP_SECONDS = 10.0
PAUSE_SECONDS = 1.2
CAPTION_LOCALES = ("nb", "no", "nn", "nb-no", "nn-no", "en", "en-us", "en-gb")
_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_TAG = re.compile(r"<[^>]+>")


# ------------------------------------------------------------------------------------------- captions


def _seconds(match: re.Match[str]) -> float:
    hours, minutes, seconds, millis = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000


def parse_captions(text: str) -> list[Segment]:
    """WebVTT or SRT → segments (tags, cue settings, NOTE/STYLE blocks and rolling duplicates removed)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line for line in block.split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start_text, _, end_text = lines[timing_index].partition("-->")
        start, end = _TIME.search(start_text), _TIME.search(end_text)
        if not start or not end:
            continue
        cue = " ".join(_TAG.sub("", line).strip() for line in lines[timing_index + 1:])
        cue = re.sub(r"\s+", " ", cue).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()
        if not cue:
            continue
        segment = Segment(_seconds(start), _seconds(end), cue)
        if segments and (segments[-1].text == cue or (cue.startswith(segments[-1].text) and
                         segment.start - segments[-1].end < 0.5)):
            # rolling (YouTube-style) captions repeat the previous line: keep the longest version
            segments[-1] = Segment(segments[-1].start, segment.end, cue)
            continue
        segments.append(segment)
    return segments


def chunk_transcript(segments: list[Segment], *, title: str) -> list[ChunkDraft]:
    """~60–120 s chunks cut at a pause or sentence end, with ~10 s overlap."""
    chunks: list[ChunkDraft] = []
    current: list[Segment] = []
    overlap_only = False
    for index, segment in enumerate(segments):
        current.append(segment)
        overlap_only = False
        duration = segment.end - current[0].start
        following = segments[index + 1] if index + 1 < len(segments) else None
        pause = (following.start - segment.end) if following else 99.0
        sentence_end = segment.text.rstrip().endswith((".", "?", "!", "…"))
        if duration >= MAX_SECONDS or (duration >= MIN_SECONDS and (sentence_end or pause >= PAUSE_SECONDS)):
            chunks.append(_transcript_chunk(current, title))
            carry = [s for s in current if s.start >= segment.end - OVERLAP_SECONDS and s is not current[0]]
            current = carry
            overlap_only = bool(carry)
    if current and not overlap_only:
        chunks.append(_transcript_chunk(current, title))
    return chunks


def _transcript_chunk(segments: list[Segment], title: str) -> ChunkDraft:
    text = " ".join(s.text for s in segments)
    return ChunkDraft("transcript", text, [title] if title else [], start=segments[0].start, end=segments[-1].end)


def timestamp_url(item: SourceItem, seconds: float | None) -> str | None:
    if seconds is None:
        return item.url
    whole = int(seconds)
    if item.kind == "youtube":
        return f"https://www.youtube.com/watch?v={item.canvas_id}&t={whole}s"
    if item.kind == "vimeo":
        return f"https://vimeo.com/{item.canvas_id}#t={whole}s"
    return item.url


def choose_track(tracks: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [t for t in tracks if str(t.get("kind") or "subtitles") in ("captions", "subtitles")
              and str(t.get("workflow_state") or "ready") == "ready"]

    def rank(track: dict[str, Any]) -> tuple[int, int]:
        locale = str(track.get("locale") or "").lower()
        position = CAPTION_LOCALES.index(locale) if locale in CAPTION_LOCALES else len(CAPTION_LOCALES)
        return (position, 1 if track.get("asr") else 0)

    return sorted(usable, key=rank)[0] if usable else None


# ---------------------------------------------------------------------------------------------- cache


def cache_dir(state: BuildState) -> Path:
    path = state.c.config.cache_dir / "rag" / "transcripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cached_transcript(state: BuildState, sha: str) -> Transcript | None:
    path = cache_dir(state) / f"{sha}.json"
    try:
        return Transcript.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def store_transcript(state: BuildState, sha: str, transcript: Transcript) -> None:
    path = cache_dir(state) / f"{sha}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(transcript.as_dict(), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------------------- transcripts


async def canvas_captions(state: BuildState, item: SourceItem) -> Transcript | None:
    try:
        if item.kind == "file":
            tracks = await state.api.media_attachment_tracks(item.canvas_id, include_content=True)
            track = choose_track(tracks)
            content = track.get("webvtt_content") or track.get("content") if track else None
            if track and not content and track.get("url"):
                content = await state.api.media_track_text(str(track["url"]))
        else:
            track = choose_track(list(item.meta.get("tracks") or []))
            content = await state.api.media_track_text(str(track["url"])) if track and track.get("url") else None
    except CanvasError as exc:
        log.info("Emne-RAG: fant ikke teksting for %s: %s", item.key, exc.code)
        return None
    if not track or not content:
        return None
    segments = parse_captions(str(content))
    if not segments:
        return None
    return Transcript(segments, str(track.get("locale") or "") or None, "canvas", "captions",
                      notes=["Teksting fra Canvas" + (" (automatisk generert)" if track.get("asr") else "") + " er brukt."])


YOUTUBE_LANGUAGES = ("no", "nb", "nn", "en", "en-US", "en-GB", "sv", "da")
NO_AUDIO = "Lyd fra YouTube lastes ikke ned (YouTubes vilkår), så videoen er ikke med."
YOUTUBE_REASONS = {
    "TranscriptsDisabled": f"YouTube-videoen har ingen teksting. {NO_AUDIO}",
    "NoTranscriptFound": f"YouTube-videoen har ingen teksting. {NO_AUDIO}",
    "VideoUnavailable": "YouTube-videoen er ikke tilgjengelig (slettet, privat eller feil lenke) – sjekk lenken i emnet.",
    "InvalidVideoId": "Lenken peker ikke på en gyldig YouTube-video – sjekk lenken i emnet.",
    "VideoUnplayable": ("YouTube-videoen kan ikke spilles av her (for eksempel begrenset av opplasteren eller blokkert i "
                        "regionen)."),
    "AgeRestricted": "YouTube-videoen har aldersgrense, og tekstingen kan ikke hentes uten innlogging.",
}


def _youtube_rows(item: SourceItem) -> tuple[list[Any], str | None, bool]:
    """Captions in a preferred language (manual before automatic), else any captions the video has."""
    from youtube_transcript_api import NoTranscriptFound, YouTubeTranscriptApi

    listing = YouTubeTranscriptApi().list(item.canvas_id)
    try:
        chosen = listing.find_transcript(YOUTUBE_LANGUAGES)
    except NoTranscriptFound:
        available = list(listing)  # manually created first, then automatic
        if not available:
            raise
        chosen = available[0]
    fetched = chosen.fetch()
    return list(fetched), str(chosen.language_code or "") or None, bool(chosen.is_generated)


async def youtube_captions(state: BuildState, item: SourceItem) -> tuple[Transcript | None, str | None]:
    """YouTube captions via youtube-transcript-api (only the video id is sent). Returns (transcript, reason)."""
    if not state.c.settings.get().rag.youtube_captions:
        return None, Waiting(f"Henting av YouTube-teksting er slått av (Emne-RAG → Innstillinger). {NO_AUDIO}")
    try:
        import youtube_transcript_api  # noqa: F401
    except ImportError:
        return None, Waiting("YouTube-teksting krever pakken youtube-transcript-api. Lukk EmneKlar og kjør update.bat.")
    try:
        rows, language, generated = await asyncio.to_thread(_youtube_rows, item)
    except Exception as exc:  # noqa: BLE001 - every failure of the unofficial interface becomes a clear reason
        name = type(exc).__name__
        log.info("Emne-RAG: ingen YouTube-teksting for %s (%s)", item.canvas_id, name)
        if name in YOUTUBE_REASONS:
            return None, YOUTUBE_REASONS[name]
        return None, Waiting("YouTube svarte ikke på forespørselen om teksting (blokkert nettverk, for mange "
                             f"forespørsler eller en endring hos YouTube: {name}). Prøves igjen ved neste oppdatering.")
    segments = []
    for row in rows:
        text = str(getattr(row, "text", None) or (row.get("text") if isinstance(row, dict) else "") or "").strip()
        start = float(getattr(row, "start", None) or (row.get("start") if isinstance(row, dict) else 0) or 0)
        duration = float(getattr(row, "duration", None) or (row.get("duration") if isinstance(row, dict) else 0) or 0)
        if text:
            segments.append(Segment(start, start + duration, re.sub(r"\s+", " ", text)))
    if not segments:
        return None, f"YouTube-tekstingen er tom. {NO_AUDIO}"
    kind = "automatisk generert teksting" if generated else "teksting"
    return Transcript(segments, language, "youtube", "youtube",
                      notes=[f"YouTube-{kind}{f' ({language})' if language else ''} er brukt."]), None


def media_download_url(item: SourceItem) -> str | None:
    if item.kind == "file":
        return item.meta.get("download_url")
    sources = [s for s in item.meta.get("sources") or [] if isinstance(s, dict) and s.get("url")]
    if not sources:
        return None
    audio = [s for s in sources if str(s.get("content_type") or "").startswith("audio/")]
    mp4 = [s for s in sources if "mp4" in str(s.get("content_type") or s.get("fileExt") or "")]
    pool = audio or mp4 or sources

    def bitrate(source: dict[str, Any]) -> int:
        try:
            return int(source.get("bitrate") or 0)
        except (TypeError, ValueError):
            return 0

    return str(sorted(pool, key=bitrate)[0]["url"])


def transcriber(state: BuildState) -> Transcriber:
    rag = state.c.settings.get().rag
    local = state.c.local_models
    device = local.device(rag.device)
    nb, other = choose_models(local, rag.whisper_model, rag.whisper_other_language_model, device)
    return Transcriber(local, nb, other, device)


async def local_transcript(state: BuildState, item: SourceItem) -> tuple[Transcript | None, str | None]:
    """Download the media and transcribe it (cached by file hash). Returns (transcript, reason when skipped)."""
    worker = transcriber(state)
    if not worker.available():
        return None, Waiting("Videoen har ingen teksting, og lokale modeller for transkripsjon er ikke installert "
                             "(setup-emne-rag.bat).")
    if worker.downloads_needed() and not state.request.accept_downloads:
        return None, Waiting("Videoen har ingen teksting, og NB-Whisper er ikke lastet ned ennå. Beregn estimatet på "
                             "nytt og godta nedlastingen for å transkribere.")
    target, reason = await download_media(state, item, "media")
    if target is None:
        return None, reason
    sha = await asyncio.to_thread(_sha256, target)
    cached = cached_transcript(state, sha)
    if cached is not None:
        target.unlink(missing_ok=True)
        cached.notes.append("Transkripsjonen er hentet fra bufferen (samme fil er transkribert før).")
        return cached, None
    progress = state.ctx.progress

    def report(fraction: float) -> None:
        progress.set_current(item.title, operation=f"Transkriberer lokalt ({int(fraction * 100)} %)")

    loop_stop = asyncio.Event()

    def stop() -> bool:
        return state.ctx.cancelled or loop_stop.is_set()

    try:
        transcript = await asyncio.to_thread(worker.transcribe, target, stop=stop, progress=report)
    except TranscriptionStopped:
        raise asyncio.CancelledError from None
    except asyncio.CancelledError:
        loop_stop.set()
        raise
    finally:
        target.unlink(missing_ok=True)
    store_transcript(state, sha, transcript)
    return transcript, None


PIECE_ERRORS = {"no_audio": "Fant ingen lyd i videoen.",
                "no_decoder": "Lyden kunne ikke hentes ut (FFmpeg mangler). Kjør setup.bat på nytt.",
                "decode_failed": "Lyden kunne ikke leses (filen kan være skadet eller i et ukjent format).",
                "timeout": "Det tok for lang tid å hente ut lyden.", "crashed": "Lyduttrekket krasjet.",
                "memory": "Lyden krevde for mye minne."}


async def download_media(state: BuildState, item: SourceItem, name: str) -> tuple[Path | None, str | None]:
    url = media_download_url(item)
    if not url:
        return None, "Fant ingen nedlastbar versjon av videoen i Canvas."
    rag = state.c.settings.get().rag
    target = state.tmp / hashlib.sha1(item.key.encode()).hexdigest()[:12] / name  # noqa: S324 - folder name
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        await state.api.client.download(url, target, max_bytes=rag.max_video_mb * 1024 * 1024)
    except AppError as exc:
        if exc.code == "file_too_large":
            return None, Waiting(f"Videoen er større enn grensen på {rag.max_video_mb} MB (Emne-RAG → Innstillinger).")
        raise
    return target, None


async def provider_transcript(state: BuildState, item: SourceItem) -> tuple[Transcript | None, str | None]:
    """Transcription by an AI provider (OpenAI, Azure OpenAI or an own OpenAI-compatible server).

    Only the audio is sent, in pieces of 60–120 seconds cut at pauses, after the user has seen what is sent.
    Pieces give exact timestamps also when the model returns text without timestamps; the text the provider returned
    for the previous piece is passed back as ``prompt`` so names and terms are spelled the same across pieces. The
    video title is not sent (file names can contain names of people).
    """
    rag = state.c.settings.get().rag
    ai = state.c.ai
    plan = ai.transcription_plan(rag.transcription_provider_id, rag.transcription_model, summary="")
    if not plan["available"]:
        return None, Waiting("Videoen har ingen teksting, og transkripsjon via KI-leverandør er ikke tilgjengelig: "
                             f"{plan['reason']}")
    if plan["needs_confirmation"] and not state.request.confirmed:
        return None, Waiting("Videoen har ingen teksting. Lyden sendes ikke til KI-leverandøren uten samtykke – "
                             "beregn estimatet og godta sendingen.")
    target, reason = await download_media(state, item, "media")
    if target is None:
        return None, reason
    try:
        sha = await asyncio.to_thread(_sha256, target)
        cached = cached_transcript(state, sha)
        if cached is not None:
            cached.notes.append("Transkripsjonen er hentet fra bufferen (samme fil er transkribert før).")
            return cached, None
        result = await state.c.parsers.run({"job": "rag_audio_pieces", "args": {
            "path": str(target), "out_dir": str(target.parent / "lyd")}}, timeout=1800.0)
    finally:
        target.unlink(missing_ok=True)
    if result.get("error"):
        return None, PIECE_ERRORS.get(str(result["error"]), "Lyden kunne ikke hentes ut.")
    model = plan["model"] or {}
    model_id = str(model.get("id") or "")
    provider_id = rag.transcription_provider_id
    pieces = [p for p in result.get("pieces") or [] if not p.get("silent")]
    segments: list[Segment] = []
    language = None
    previous = ""
    progress = state.ctx.progress
    for index, piece in enumerate(pieces, start=1):
        await state.ctx.checkpoint()
        progress.set_current(item.title, operation=f"Transkriberer via {provider_id} ({index} av {len(pieces)} lydbiter)")
        path = Path(piece["path"])
        start, end = float(piece["start"]), float(piece["end"])
        answer = await ai.transcribe(provider_id, model_id, path.read_bytes(), path.name,
                                     segments=model.get("segments") is not False,
                                     summary=f"Lyd fra «{item.title}» ({index} av {len(pieces)})",
                                     confirmed=state.request.confirmed, seconds=end - start,
                                     language=rag.transcription_language or None, prompt=previous[-600:] or None,
                                     course_id=state.course_id)
        path.unlink(missing_ok=True)
        language = language or answer.language
        if answer.segments:
            for row in answer.segments:
                segments.append(Segment(start + row.start, min(end, start + max(row.start, row.end)), row.text))
        elif answer.text:
            segments.append(Segment(start, end, answer.text))
        previous = answer.text
    transcript = Transcript(segments, language, f"{provider_id}/{model_id}", "provider",
                            float(result.get("duration") or 0) or None,
                            notes=[f"Transkribert av {provider_id} ({model_id}). Bare lyden ble sendt, i biter."])
    if segments:
        store_transcript(state, sha, transcript)
    return transcript, None if segments else "Fant ingen tale i videoen."


async def process_media(state: BuildState, item: SourceItem) -> None:
    from emneklar.features.course_rag.builder import chunk_records, mark, store_chunks

    category = item.meta.get("category")
    transcript: Transcript | None = None
    reason: str | None = None
    if item.kind == "file" and category == "subtitle":
        target = state.tmp / hashlib.sha1(item.key.encode()).hexdigest()[:12] / "captions"  # noqa: S324
        target.parent.mkdir(parents=True, exist_ok=True)
        await state.api.client.download(str(item.meta.get("download_url") or ""), target, max_bytes=20 * 1024 * 1024)
        segments = parse_captions(decode_text(target.read_bytes()))
        transcript = Transcript(segments, None, "file", "captions") if segments else None
        reason = None if segments else "Undertekstfilen inneholder ingen tekst."
    elif item.kind == "youtube":
        transcript, reason = await youtube_captions(state, item)
    elif item.kind == "vimeo":
        reason = "Teksting fra Vimeo kan ikke hentes."
    else:
        transcript = await canvas_captions(state, item)
        if transcript is None:
            mode = state.c.settings.get().rag.transcription
            if mode == "provider":
                transcript, reason = await provider_transcript(state, item)
            elif mode == "local":
                transcript, reason = await local_transcript(state, item)
            else:
                reason = Waiting("Videoen har ingen teksting, og transkripsjon er slått av (Emne-RAG → Innstillinger).")
    if transcript is None or not transcript.segments:
        mark(state, item, "skipped", reason or "Fant ingen tale å transkribere.")
        return
    drafts = chunk_transcript(transcript.segments, title=item.title)
    for draft in drafts:
        draft.meta["url"] = timestamp_url(item, draft.start)
    records = chunk_records(item, drafts, extra_meta={"video_title": item.title, "transcript_source": transcript.source,
                                                      "language": transcript.language, "model": transcript.model,
                                                      "pages": item.parents})
    if state.request.keyframes and item.kind in ("media", "file") and category != "subtitle":
        from emneklar.features.course_rag.images import keyframe_records

        records += await keyframe_records(state, item)
    await store_chunks(state, item, records, meta={"transcript_source": transcript.source,
                                                   "notes": transcript.notes,
                                                   "duration": transcript.duration or transcript.segments[-1].end})
