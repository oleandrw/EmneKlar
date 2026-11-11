"""API for «Standardiser videoavspillere» (Innholdskvalitet → Media).

ANALYSER → FORKLAR → FORESLÅ → FORHÅNDSVIS → GODKJENN → LEGG I ENDRINGSKØ → UTFØR. Changes are only ever staged in
the global change set (approval, conflict check, backup and log as for every other change) – never written here.

Titles follow a strict order: a good existing title, YouTube metadata (oEmbed, no API key), the nearby Canvas
context, then an AI suggestion on request (existing router, cheapest suitable model) and finally manual entry.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.ai.base import AIError, AIMessage, AIRequest, TextPart
from emneklar.core.ai.service import AI_LABEL
from emneklar.core.ai.untrusted import DATA_RULE, wrap_untrusted_content
from emneklar.core.canvas.html import element_path, is_generic_iframe_title, norm_text
from emneklar.core.canvas.snapshot import SnapObj, SnapshotView
from emneklar.core.changes.appliers import HTML_KIND_BY_OBJECT
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.jobs.manager import JobContext
from emneklar.core.security.guarded_http import build_guarded_client
from emneklar.core.security.sanitize import preview_html
from emneklar.core.security.ssrf import UrlBlocked, validate_url
from emneklar.core.storage.models import Finding, Job, StagedChange
from emneklar.features.accessibility.fixes import HTML_FIELD, display, live_html, open_change_for
from emneklar.features.content_quality.video import (
    ISSUE_LABEL,
    PLAYLIST_ID,
    TITLE_SOURCE_LABEL,
    Embed,
    TitleProposal,
    TitleSource,
    VideoOptions,
    find_embed,
    find_embeds,
    find_unsupported,
    format_video_title,
    has_autoplay,
    is_poor_title,
    parse_youtube_url,
    preview_markup,
    propose,
    resolve_title,
    splice,
    validate_title,
)
from emneklar.features.course_structure.api import latest_snapshot
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")

SCAN_KIND = "video_scan"
OEMBED_URL = "https://www.youtube.com/oembed"
METADATA_HOSTS = {"www.youtube.com", "youtube.com"}
METADATA_TIMEOUT = 8.0
METADATA_TTL = 24 * 3600
METADATA_CACHE_MAX = 2000
MAX_REDIRECTS = 3
HTML_TYPES = ("page", "assignment", "discussion", "quiz", "syllabus")
NO_SNAPSHOT = "Kjør en analyse av emnet først. EmneKlar finner videoene ut fra siste analyse."
UNAVAILABLE = ("YouTube-metadata kunne ikke hentes. Videoen kan fortsatt standardiseres, men title må vurderes "
               "manuelt.")
METADATA_MESSAGE = {
    "not_found": "Videoen finnes ikke hos YouTube (slettet eller feil adresse). Title må vurderes manuelt.",
    "forbidden": "Videoen er privat eller kan ikke bygges inn. Title må vurderes manuelt.",
    "unavailable": UNAVAILABLE,
    "playlist": "Spillelister har ingen enkelt videotittel. Title må vurderes manuelt.",
}
STATUS_LABEL = {
    "no_change": "Ingen endring nødvendig",
    "safe": "Kan standardiseres trygt",
    "needs_title": "Trenger godkjenning av title",
    "manual": "Krever manuell kontroll",
}
DETERMINISTIC = (TitleSource.EXISTING, TitleSource.YOUTUBE_METADATA)


# ------------------------------------------------------------------------------------- metadata


@dataclass(frozen=True)
class Metadata:
    status: str  # ok | not_found | forbidden | unavailable | playlist
    title: str | None = None

    @property
    def message(self) -> str | None:
        return METADATA_MESSAGE.get(self.status)


_cache: dict[str, tuple[float, Metadata]] = {}


def clear_metadata_cache() -> None:
    _cache.clear()


def metadata_url(video_id: str) -> str:
    watch = f"https://www.youtube.com/watch?v={video_id}"
    return f"{OEMBED_URL}?format=json&url={quote(watch, safe='')}"


def check_metadata_url(url: str) -> None:
    """Only YouTube's oEmbed service over https – checked before every request, redirects included – and the general
    SSRF rules on top (the guarded client also checks the resolved address when it connects)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in METADATA_HOSTS or parts.path != "/oembed":
        raise UrlBlocked("metadata_host", "Bare YouTubes metadata-tjeneste brukes.")
    validate_url(url)


def metadata_client(c: AppContainer) -> httpx.AsyncClient:
    if c.link_transport is not None:  # tests: never the real network
        return httpx.AsyncClient(transport=c.link_transport, follow_redirects=False)
    return build_guarded_client(METADATA_TIMEOUT, max_connections=4)


async def _request_metadata(client: httpx.AsyncClient, video_id: str) -> Metadata:
    url = metadata_url(video_id)
    for _ in range(MAX_REDIRECTS + 1):
        check_metadata_url(url)
        response = await client.get(url, headers={"Accept": "application/json"})
        location = response.headers.get("location")
        if response.status_code in (301, 302, 303, 307, 308) and location:
            url = urljoin(url, location)
            continue
        if response.status_code == 200:
            data = response.json()
            title = norm_text(str(data.get("title") or "")) if isinstance(data, dict) else ""
            return Metadata("ok", title[:300] or None)
        if response.status_code in (400, 404):
            return Metadata("not_found")
        if response.status_code in (401, 403):
            return Metadata("forbidden")
        return Metadata("unavailable")
    return Metadata("unavailable")  # too many redirects


async def fetch_metadata(client: httpx.AsyncClient, video_id: str) -> Metadata:
    """The video's title from YouTube's oEmbed service, cached per video ID. Never raises: a failure is a status."""
    if video_id == PLAYLIST_ID:
        return Metadata("playlist")
    cached = _cache.get(video_id)
    if cached and time.monotonic() - cached[0] < METADATA_TTL:
        return cached[1]
    try:
        result = await asyncio.wait_for(_request_metadata(client, video_id), timeout=METADATA_TIMEOUT + 2)
    except (UrlBlocked, httpx.HTTPError, ValueError, TimeoutError):
        result = Metadata("unavailable")
    if result.status != "unavailable":  # a timeout or network error is tried again next time
        if len(_cache) >= METADATA_CACHE_MAX:
            _cache.clear()
        _cache[video_id] = (time.monotonic(), result)
    return result


async def metadata_for(c: AppContainer, video_id: str) -> Metadata:
    client = metadata_client(c)
    try:
        return await fetch_metadata(client, video_id)
    finally:
        await client.aclose()


# --------------------------------------------------------------------------------------- inputs


class OptionsIn(BaseModel):
    max_width: int | None = Field(default=960, ge=320, le=1920)  # null = full available width
    keep_ratio: bool = False
    responsive: bool = True
    center: bool = True
    lazy: bool = True
    fix_title: bool = True

    def to_options(self) -> VideoOptions:
        return VideoOptions(max_width=self.max_width, keep_ratio=self.keep_ratio, responsive=self.responsive,
                            center=self.center, lazy=self.lazy, fix_title=self.fix_title)


class ScanBody(BaseModel):
    module_ids: list[str] = Field(default_factory=list, max_length=500)  # empty = the whole course
    options: OptionsIn = Field(default_factory=OptionsIn)


class ItemRef(BaseModel):
    object_type: Literal["page", "assignment", "discussion", "quiz", "syllabus"]
    object_id: str = Field(min_length=1, max_length=300)
    object_title: str = Field(default="", max_length=300)
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{6,20}$")
    occurrence: int = Field(default=0, ge=0, le=200)

    @model_validator(mode="after")
    def _plain_object_id(self) -> ItemRef:
        """The ID becomes part of a Canvas API path: a page slug without path characters, otherwise a number."""
        pattern = r"[^/\\?#\s]+" if self.object_type == "page" else r"\d{1,20}"
        if not re.fullmatch(pattern, self.object_id) or self.object_id in (".", ".."):
            raise ValueError("Ugyldig ID for innholdet.")
        return self


class ItemBody(ItemRef):
    options: OptionsIn = Field(default_factory=OptionsIn)
    title: str | None = Field(default=None, max_length=300)
    title_source: Literal["existing", "youtube_metadata", "page_context", "ai_suggestion", "manual"] | None = None


class BulkBody(BaseModel):
    items: list[ItemRef] = Field(min_length=1, max_length=500)
    options: OptionsIn = Field(default_factory=OptionsIn)
    standardise_size: bool = True
    center: bool = True
    add_title_from_metadata: bool = True
    replace_generic_title: bool = True
    overwrite_existing_title: bool = False


class TitleAIBody(ItemRef):
    confirmed: bool = False
    #: The teacher asked to see a KI-forslag although YouTube or the page already gives a good title (to compare).
    even_with_title: bool = False


# ----------------------------------------------------------------------------------------- scan


def layout_label(options: VideoOptions) -> str:
    if not options.responsive:
        return "Størrelsen endres ikke"
    parts = ["Responsiv 16:9" if not options.keep_ratio else "Responsiv, eksisterende format"]
    parts.append(f"Maks {options.max_width} px" if options.max_width else "Full tilgjengelig bredde")
    if options.center:
        parts.append("Sentrert")
    return " · ".join(parts)


def _objects(view: SnapshotView, module_ids: list[str]) -> list[SnapObj]:
    objects = [o for kind in HTML_TYPES for o in view.get(kind) if o.body and "youtu" in o.body.lower()]
    if module_ids:
        refs = {view.item_content_ref(i) for m in module_ids for i in view.items_of(m)}
        objects = [o for o in objects if o.ref in refs]
    return objects


def _queued(c: AppContainer, course_id: str, obj: SnapObj) -> bool:
    existing = open_change_for(c, course_id, HTML_KIND_BY_OBJECT[obj.object_type].kind, obj.canvas_id)
    return existing is not None and existing.status != "conflict"


def _base_item(view: SnapshotView, obj: SnapObj, queued: bool) -> dict[str, Any]:
    return {"object_type": obj.object_type, "object_id": obj.canvas_id, "object_title": obj.title,
            "location": view.location_label(obj), "modules": view.module_of.get(obj.ref, []),
            "html_url": obj.html_url, "queued": queued}


def scan_item(embed: Embed, metadata: Metadata, options: VideoOptions) -> dict[str, Any]:
    """Explain one embed and what the standardiser proposes for it."""
    resolved = resolve_title(embed.title, metadata.title, embed.context)
    title_ok = resolved.source in DETERMINISTIC
    proposal = propose(embed, options, resolved.title if title_ok else None)
    issues = list(embed.issues)
    if proposal.markup is not None and not {"fixed_size", "old_embed", "missing_title", "generic_title"} & set(issues):
        issues.append("not_standard")
    if embed.manual_reason:
        status = "manual"
    elif options.fix_title and not title_ok:
        status = "needs_title"
    elif proposal.markup is None:
        status = "no_change"
    else:
        status = "safe"
    return {
        "video_id": embed.video_id, "occurrence": embed.occurrence, "supported": True,
        "src": str(embed.iframe.get("src") or "")[:500],
        "youtube_title": metadata.title, "metadata_status": metadata.status, "metadata_message": metadata.message,
        "current": {"title": embed.title, "size": embed.size_label, "layout": embed.layout_label},
        "issues": [{"code": code, "label": ISSUE_LABEL[code]} for code in issues],
        "autoplay": has_autoplay(embed.url),
        "proposed": {"title": resolved.as_dict(), "layout": layout_label(options),
                     "changes_markup": proposal.markup is not None},
        "status": status, "status_label": STATUS_LABEL[status], "manual_reason": embed.manual_reason,
        "context": {"page_title": embed.context.page_title, "heading": embed.context.heading},
    }


def unsupported_item(src: str, reason: str, index: int) -> dict[str, Any]:
    url = parse_youtube_url(src)
    return {
        "video_id": url.video_id if url else "", "occurrence": index, "supported": False, "src": src[:500],
        "youtube_title": None, "metadata_status": None, "metadata_message": None,
        "current": {"title": "", "size": None, "layout": "Kan ikke leses automatisk"},
        "issues": [{"code": "manual", "label": ISSUE_LABEL["manual"]}], "autoplay": False,
        "proposed": {"title": TitleProposal(None, None, True).as_dict(), "layout": "Ingen automatisk endring",
                     "changes_markup": False},
        "status": "manual", "status_label": STATUS_LABEL["manual"], "manual_reason": reason,
        "context": {"page_title": "", "heading": ""},
    }


def summarise(items: list[dict[str, Any]]) -> dict[str, int]:
    """Headline numbers: every embed is counted once; an embed with several issues appears under each issue."""

    def has(item: dict[str, Any], *codes: str) -> bool:
        return any(issue["code"] in codes for issue in item["issues"])

    def status(name: str) -> int:
        return sum(1 for i in items if i["status"] == name)

    return {
        "videos": len(items),
        "unique_videos": len({i["video_id"] for i in items if i["video_id"]}),
        "standard": status("no_change"),
        "safe": status("safe"),
        "needs_title": status("needs_title"),
        "manual": status("manual"),
        "fixed_size": sum(1 for i in items if has(i, "fixed_size")),
        "missing_title": sum(1 for i in items if has(i, "missing_title", "generic_title")),
        "old_embed": sum(1 for i in items if has(i, "old_embed")),
        "autoplay": sum(1 for i in items if i["autoplay"]),
    }


async def _scan(ctx: JobContext, c: AppContainer, course_id: str, body: ScanBody) -> dict[str, Any]:
    progress = ctx.progress
    view = latest_snapshot(c, course_id)
    if view is None:
        raise AppError("snapshot_missing", status=409, message=NO_SNAPSHOT)
    options = body.options.to_options()
    candidates = _objects(view, body.module_ids)

    # 1. The pages that had a YouTube video at the last analysis, fetched again: the result shows Canvas as it is now.
    progress.set_phase("fetch", "Henter sider med video fra Canvas", index=1, count=2, determinate=True)
    for obj in candidates:
        progress.add_tasks(obj.object_type)
    pages: list[tuple[SnapObj, str]] = []
    errors: list[dict[str, str]] = []
    for obj in candidates:
        await ctx.checkpoint()
        started = progress.start(obj.object_type, item=obj.title, operation="Henter innholdet")
        try:
            pages.append((obj, await live_html(c, course_id, obj.object_type, obj.canvas_id)))
            progress.finish(obj.object_type, started)
        except AppError as exc:
            errors.append({"object_title": obj.title, "location": view.location_label(obj),
                           "message": exc.message or "Kunne ikke hente innholdet fra Canvas."})
            progress.finish(obj.object_type, started, failed=True)

    found = [(obj, embed) for obj, html in pages for embed in find_embeds(html, page_title=obj.title)]
    video_ids = sorted({e.video_id for _, e in found})

    # 2. One metadata lookup per video, however many times it is used.
    progress.set_phase("metadata", "Henter videotitler fra YouTube", index=2, count=2, determinate=True)
    progress.add_tasks("media", len(video_ids))
    metadata: dict[str, Metadata] = {}
    limit = asyncio.Semaphore(4)
    client = metadata_client(c)

    async def one(video_id: str) -> None:
        async with limit:
            await ctx.checkpoint()
            started = progress.start("media", item=video_id, operation="Henter videotittel")
            metadata[video_id] = await fetch_metadata(client, video_id)
            progress.finish("media", started, failed=metadata[video_id].status == "unavailable")

    try:
        await asyncio.gather(*(one(v) for v in video_ids))
    finally:
        await client.aclose()

    items: list[dict[str, Any]] = []
    queued = {obj.ref: _queued(c, course_id, obj) for obj, _ in pages}
    for obj, embed in found:
        item = _base_item(view, obj, queued[obj.ref]) | scan_item(embed, metadata[embed.video_id], options)
        item["key"] = f"{obj.object_type}:{obj.canvas_id}:{embed.video_id}:{embed.occurrence}"
        items.append(item)
    for obj, html in pages:
        for index, (src, reason) in enumerate(find_unsupported(html)):
            item = _base_item(view, obj, queued[obj.ref]) | unsupported_item(src, reason, index)
            item["key"] = f"{obj.object_type}:{obj.canvas_id}:unsupported:{index}"
            items.append(item)
    _dedupe_context_titles(items)
    return {"snapshot_at": view.created_at.isoformat(), "items": items, "summary": summarise(items),
            "errors": errors, "options": body.options.model_dump(),
            "scope": "modules" if body.module_ids else "course", "module_ids": body.module_ids}


def _dedupe_context_titles(items: list[dict[str, Any]]) -> None:
    """Two videos on the same page should not get the same context title."""
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for item in items:
        title = item["proposed"]["title"]
        if title["source"] != TitleSource.PAGE_CONTEXT.value or not title["title"]:
            continue
        key = (item["object_id"], title["title"])
        seen[key] += 1
        if seen[key] > 1:
            title["title"] = f"{title['title']} ({seen[key]})"


@router.post("/courses/{course_id}/videos/scan")
async def scan(course_id: str, body: ScanBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    if latest_snapshot(c, course_id) is None:
        raise AppError("snapshot_missing", status=409, message=NO_SNAPSHOT)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        return await _scan(ctx, c, course_id, body)

    return c.jobs.submit(kind=SCAN_KIND, title="Standardiser videoavspillere", runner=runner, course_id=course_id,
                         params={"feature": "video_standard", "module_ids": body.module_ids}).public()


@router.get("/courses/{course_id}/videos/latest")
async def latest_scan(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """The result of the last completed scan of this course (kept with the job)."""
    course_id = require_course_id(course_id)
    with c.db.session() as session:
        row = session.scalars(select(Job).where(Job.course_id == course_id, Job.kind == SCAN_KIND,
                                                Job.status == "completed")
                              .order_by(Job.created_at.desc()).limit(1)).first()
        if row is None or not row.result:
            return {"job_id": None, "finished_at": None, "result": None}
        return {"job_id": row.id, "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "result": row.result}


# ------------------------------------------------------------------------------ preview and staging


async def _base(c: AppContainer, course_id: str, object_type: str,
                object_id: str) -> tuple[str, str, dict[str, Any], StagedChange | None]:
    """The HTML to build on, re-fetched from Canvas: a queued change for the same object is built upon (like the
    other HTML fixes), otherwise the live content."""
    kind = HTML_KIND_BY_OBJECT[object_type].kind
    field = HTML_FIELD[object_type]
    existing = open_change_for(c, course_id, kind, object_id)
    if existing is not None and existing.status == "conflict":
        existing = None  # built on content that has changed since – start again from the live content
    live = await live_html(c, course_id, object_type, object_id)
    if existing is not None:
        return kind, existing.proposed.get(field) or "", existing.before, existing
    return kind, live, {field: live}, None


def _locate(base: str, ref: ItemRef) -> Embed:
    embed = find_embed(find_embeds(base, page_title=ref.object_title), ref.video_id, ref.occurrence)
    if embed is None:
        raise AppError("conflict", status=409, message="Fant ikke videoen i innholdet slik det er i Canvas nå. "
                       "Innholdet kan være endret – skann videoene på nytt.")
    return embed


async def _title_for(c: AppContainer, embed: Embed, body: ItemBody) -> tuple[str | None, TitleSource | None]:
    """The teacher's approved title when given, else the deterministic order (existing title, YouTube metadata)."""
    if body.title is not None and body.title.strip():
        if body.title_source == TitleSource.EXISTING.value and norm_text(body.title) == embed.title and embed.title:
            return embed.title, TitleSource.EXISTING  # kept as it is, whatever its length
        try:
            return validate_title(body.title), TitleSource(body.title_source or TitleSource.MANUAL)
        except ValueError as exc:
            raise AppError("validation_error", message=str(exc)) from exc
    metadata = await metadata_for(c, embed.video_id)
    resolved = resolve_title(embed.title, metadata.title, embed.context)
    if resolved.source in DETERMINISTIC:
        return resolved.title, resolved.source
    return None, None  # the title needs review – the layout can still be standardised


async def _build(c: AppContainer, course_id: str, body: ItemBody) -> dict[str, Any]:
    kind, base, before_state, existing = await _base(c, course_id, body.object_type, body.object_id)
    embed = _locate(base, body)
    title, source = await _title_for(c, embed, body)
    options = body.options.to_options()
    proposal = propose(embed, options, title)
    label = proposal.title or f"YouTube-video {embed.video_id}"
    canvas_base = c.settings.get().canvas.base_url
    before_region = embed.root.decode()
    result: dict[str, Any] = {
        "kind": kind, "field": HTML_FIELD[body.object_type], "existing": existing,
        "existing_change_id": existing.id if existing else None, "before_state": before_state,
        "no_change": proposal.markup is None, "title": proposal.title,
        "title_source": source.value if source else None,
        "title_source_label": TITLE_SOURCE_LABEL[source] if source else None,
        "layout": "Størrelsen endres ikke (manuell kontroll)" if embed.layout_manual else layout_label(options),
        "manual_reason": embed.manual_reason, "autoplay": has_autoplay(embed.url),
        "before_display": display(before_region),
        "before_preview": preview_html(preview_markup(before_region, label), canvas_base),
    }
    if proposal.markup is None or proposal.span is None or embed.span is None:
        result.update(after=base, after_display=result["before_display"], after_preview=result["before_preview"])
        return result
    # The region after the change: the new standard markup, or the region with only the iframe tag replaced.
    offset = embed.span[0]
    after_region = proposal.markup if proposal.layout_changed else splice(
        before_region, [((proposal.span[0] - offset, proposal.span[1] - offset), proposal.markup)])
    result.update(after=splice(base, [(proposal.span, proposal.markup)]), after_display=display(after_region),
                  after_preview=preview_html(preview_markup(after_region, label), canvas_base))
    return result


PUBLIC_PREVIEW = ("kind", "existing_change_id", "no_change", "title", "title_source", "title_source_label", "layout",
                  "manual_reason", "autoplay", "before_display", "after_display", "before_preview", "after_preview")


@router.post("/courses/{course_id}/videos/preview")
async def preview(course_id: str, body: ItemBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    result = await _build(c, require_course_id(course_id), body)
    return {k: result[k] for k in PUBLIC_PREVIEW}


def _stage(c: AppContainer, course_id: str, ref: ItemRef, kind: str, before_state: dict[str, Any], after: str,
           existing: StagedChange | None, *, rationale: str, titles: dict[str, str | None]) -> dict[str, Any]:
    field = HTML_FIELD[ref.object_type]
    previous = (existing.source or {}) if existing is not None else {}
    video_titles = {**(previous.get("video_title_sources") or {}), **titles}
    return c.changes.stage(
        course_id=course_id, domain="content_quality", kind=kind, title=f"{ref.object_title or ref.object_id}: video",
        target={"object_type": ref.object_type, "object_id": ref.object_id, "title": ref.object_title or ref.object_id},
        before=before_state, proposed={field: after}, rationale=rationale, risk="low",
        source={"feature": "video_standard", "video_title_sources": video_titles}, editable=False, merge=True,
        layered=existing is not None,
        ai_generated=any(s == TitleSource.AI_SUGGESTION.value for s in titles.values()))


@router.post("/courses/{course_id}/videos/stage")
async def stage(course_id: str, body: ItemBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    result = await _build(c, course_id, body)
    if result["no_change"]:
        raise AppError("validation_error", message="Ingen endring nødvendig – videoen følger allerede standarden.")
    title = (f"title «{result['title']}» (kilde: {result['title_source_label']})" if result["title_source_label"]
             else "title uendret")
    return _stage(c, course_id, body, result["kind"], result["before_state"], result["after"], result["existing"],
                  rationale=(f"Standardiserer YouTube-videoen {body.video_id}: {result['layout']}, {title}. "
                             "Video-ID og parametere er uendret; resten av innholdet endres ikke."),
                  titles={body.video_id: result["title_source"]})


def bulk_title(embed: Embed, metadata: Metadata, body: BulkBody) -> str | None:
    """Bulk titles come only from YouTube metadata – context and AI titles are always approved one by one."""
    if not metadata.title or is_poor_title(metadata.title):
        return None
    if not embed.title:
        return format_video_title(metadata.title) if body.add_title_from_metadata else None
    if is_generic_iframe_title(embed.title):
        return format_video_title(metadata.title) if body.replace_generic_title else None
    return format_video_title(metadata.title) if body.overwrite_existing_title else None


@router.post("/courses/{course_id}/videos/stage-bulk")
async def stage_bulk(course_id: str, body: BulkBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Standardiser alle kompatible videoer»: one change per page in the change queue, nothing written to Canvas."""
    course_id = require_course_id(course_id)
    chosen = body.options.to_options()
    options = VideoOptions(max_width=chosen.max_width, keep_ratio=chosen.keep_ratio, responsive=body.standardise_size,
                           center=body.center, lazy=chosen.lazy, fix_title=True)
    groups: dict[tuple[str, str], list[ItemRef]] = defaultdict(list)
    for item in body.items:
        groups[(item.object_type, item.object_id)].append(item)
    changes, videos, titled, unchanged = 0, 0, 0, 0
    skipped: list[dict[str, str]] = []
    client = metadata_client(c)
    try:
        for (object_type, object_id), refs in groups.items():
            page = refs[0].object_title or object_id
            try:
                kind, base, before_state, existing = await _base(c, course_id, object_type, object_id)
            except AppError as exc:
                skipped.extend({"object_title": page, "video_id": r.video_id, "reason": exc.message or exc.code}
                               for r in refs)
                continue
            embeds = find_embeds(base, page_title=refs[0].object_title)
            edits: list[tuple[tuple[int, int], str]] = []
            titles: dict[str, str | None] = {}
            for ref in refs:
                embed = find_embed(embeds, ref.video_id, ref.occurrence)
                if embed is None:
                    skipped.append({"object_title": page, "video_id": ref.video_id,
                                    "reason": "Fant ikke videoen i innholdet slik det er i Canvas nå."})
                    continue
                if embed.manual_reason:
                    skipped.append({"object_title": page, "video_id": ref.video_id, "reason": embed.manual_reason})
                    continue
                new_title = bulk_title(embed, await fetch_metadata(client, embed.video_id), body)
                proposal = propose(embed, options, new_title)
                if proposal.markup is None or proposal.span is None:
                    unchanged += 1
                    continue
                edits.append((proposal.span, proposal.markup))
                if new_title and new_title != embed.title:
                    titles[ref.video_id] = TitleSource.YOUTUBE_METADATA.value
                    titled += 1
            if not edits:
                continue
            count = len(edits)
            _stage(c, course_id, refs[0], kind, before_state, splice(base, edits), existing,
                   rationale=(f"Standardiserer {count} YouTube-video{'er' if count != 1 else ''} "
                              f"({layout_label(options)}). Video-ID og parametere er uendret; nye titler kommer bare "
                              "fra YouTube-metadata. Resten av innholdet endres ikke."),
                   titles=titles)
            changes += 1
            videos += count
    finally:
        await client.aclose()
    return {"changes": changes, "videos": videos, "titles": titled, "unchanged": unchanged, "skipped": skipped}


# ------------------------------------------------------------------------------------ AI fallback

SYSTEM = (
    "Du foreslår en kort, beskrivende tittel (title-attributt) for en innebygd video i et universitetsemne i Canvas. "
    "Skriv på norsk bokmål, eller behold originalspråket hvis videoens tittel er på et annet språk. Tittelen skal si hva "
    "videoen handler om, være under 80 tegn og ikke inneholde «YouTube», «video» eller anførselstegn. Begynn ikke "
    "med «Video:» – det legges til automatisk. " + DATA_RULE
)
SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
    "required": ["title", "confidence"],
    "additionalProperties": False,
}
AI_SUMMARY = ("YouTube-tittelen (hvis kjent), sidetittelen, nærmeste overskrift og inntil 400 tegn tekst rett før og "
              "etter videoen sendes til KI-leverandøren. Ingen studentdata og ingen andre sider sendes.")


async def _ai_prompt(c: AppContainer, course_id: str, body: TitleAIBody) -> str:
    """Only the minimal context around this one video – and only when no deterministic title exists, unless the
    teacher explicitly asked to compare (``even_with_title``)."""
    embed = _locate(await live_html(c, course_id, body.object_type, body.object_id), body)
    metadata = await metadata_for(c, embed.video_id)
    resolved = resolve_title(embed.title, metadata.title, embed.context)
    if resolved.source in DETERMINISTIC and not body.even_with_title:
        raise AppError("validation_error", message=(
            f"KI trengs ikke: videoen har allerede en god tittel ({TITLE_SOURCE_LABEL[resolved.source]}: "
            f"«{resolved.title}»)."))
    context = embed.context
    return (f"YouTube-tittel: {metadata.title or '(ukjent)'}\n"
            f"Sidetittel: {context.page_title or '(ukjent)'}\n"
            f"Nærmeste overskrift: {context.heading or '(ingen)'}\n"
            + wrap_untrusted_content("Tekst før videoen", context.before, scrub=True, empty="(ingen)") + "\n"
            + wrap_untrusted_content("Tekst etter videoen", context.after, scrub=True, empty="(ingen)") + "\n"
            "Foreslå en tittel.")


@router.post("/courses/{course_id}/videos/title-suggestion/prepare")
async def title_prepare(course_id: str, body: TitleAIBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    prompt = await _ai_prompt(c, require_course_id(course_id), body)
    return c.ai.plan("text_simple", input_chars=len(prompt), images=0, summary=AI_SUMMARY)


@router.post("/courses/{course_id}/videos/title-suggestion")
async def title_suggestion(course_id: str, body: TitleAIBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    prompt = await _ai_prompt(c, course_id, body)

    def build(model: str) -> AIRequest:
        return AIRequest(model=model, system=SYSTEM, schema_name="videotittel", json_schema=SCHEMA, max_output_tokens=200,
                         messages=[AIMessage(parts=[TextPart(text=prompt)])])

    result, decision = await c.ai.run("text_simple", build, input_chars=len(prompt), summary=AI_SUMMARY,
                                      confirmed=body.confirmed, course_id=course_id)
    data = result.data if isinstance(result.data, dict) else {}
    suggestion = norm_text(str(data.get("title") or ""))
    if not suggestion or is_poor_title(suggestion):
        raise AIError("ai_bad_response", status=502, detail="Tomt eller generelt forslag")
    return {"title": format_video_title(suggestion), "source": TitleSource.AI_SUGGESTION.value,
            "source_label": TITLE_SOURCE_LABEL[TitleSource.AI_SUGGESTION], "label": AI_LABEL,
            "confidence": data.get("confidence"), "provider": result.provider, "model": result.model,
            "route_reason": decision.reason}


# --------------------------------------------------------------- a title for «Tittel på innebygd innhold» (UU)

FINDING_TITLE_HINT = {
    TitleSource.EXISTING: "Iframen har allerede denne tittelen i Canvas.",
    TitleSource.YOUTUBE_METADATA: "Videoens egen tittel hos YouTube. Kontroller at den sier hva videoen handler om.",
    TitleSource.PAGE_CONTEXT: "Laget ut fra sidetittelen og overskriften rundt videoen – må vurderes.",
}


def _finding_embed(html: str, finding: Finding) -> Embed | None:
    """The YouTube iframe the finding is about: at the finding's path with the same address, otherwise the only
    iframe in the content with that address."""
    src = str((finding.evidence or {}).get("src") or "")
    params = (finding.fix or {}).get("params") or {}
    path = str(params.get("path") or (finding.location or {}).get("selector") or "")
    embeds = [e for e in find_embeds(html, page_title=finding.object_title or "")
              if str(e.iframe.get("src") or "") == src]
    at_path = [e for e in embeds if path and element_path(e.iframe) == path]
    if at_path:
        return at_path[0]
    return embeds[0] if len(embeds) == 1 else None


@router.get("/findings/{finding_id}/video-title")
async def finding_video_title(finding_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """A title for an iframe finding that shows a YouTube video – the same order as «Standardiser videoavspillere»
    (YouTube metadata, then the Canvas context), and the reference the KI-forslag endpoints above take. Reads only:
    the content from Canvas and the video's title from YouTube's oEmbed service (no course content is sent)."""
    finding = FindingStore(c.db).get(finding_id)
    src = str((finding.evidence or {}).get("src") or "")
    if ((finding.fix or {}).get("type") != "set_iframe_title" or finding.object_type not in HTML_TYPES
            or not finding.object_id):
        return {"available": False, "reason": "Funnet gjelder ikke tittelen på innebygd innhold."}
    if parse_youtube_url(src) is None:
        return {"available": False, "not_video": True,
                "reason": "Forslag fra YouTube hentes bare for YouTube-videoer."}
    embed = _finding_embed(await live_html(c, finding.course_id, finding.object_type, finding.object_id), finding)
    if embed is None:
        return {"available": False, "reason": "Fant ikke videoen i innholdet slik det er i Canvas nå. Innholdet kan "
                "være endret – kjør en ny analyse."}
    metadata = await metadata_for(c, embed.video_id)
    resolved = resolve_title(embed.title, metadata.title, embed.context)
    return {
        "available": True, "title": resolved.title,
        "source": resolved.source.value if resolved.source else None,
        "source_label": TITLE_SOURCE_LABEL[resolved.source] if resolved.source else None,
        "hint": FINDING_TITLE_HINT.get(resolved.source) if resolved.source else None,
        "metadata_message": metadata.message if resolved.source not in DETERMINISTIC else None,
        "ai_possible": resolved.source not in DETERMINISTIC,
        "ref": {"object_type": finding.object_type, "object_id": finding.object_id,
                "object_title": finding.object_title or "", "video_id": embed.video_id,
                "occurrence": embed.occurrence},
    }
