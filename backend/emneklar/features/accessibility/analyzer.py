"""Accessibility analyzer for the global analysis."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from emneklar.core.canvas.blueprint import is_locked
from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.html import MediaRef, canvas_ref, find_media
from emneklar.core.canvas.snapshot import SnapObj
from emneklar.core.errors import AppError
from emneklar.core.flags import is_enabled
from emneklar.features.accessibility.checks import ContentDoc, Issue, run_html_checks
from emneklar.features.accessibility.documents import document_format, document_issues
from emneklar.features.accessibility.media_assessments import load_assessments
from emneklar.features.accessibility.media_kinds import MediaKind, canvas_file_kind, canvas_media_kind
from emneklar.features.accessibility.rules import get_rule, load_ruleset
from emneklar.features.accessibility.youtube_captions import CACHE_HOURS as CAPTION_CACHE_HOURS
from emneklar.features.accessibility.youtube_captions import YoutubeCaptionChecker
from emneklar.features.analysis.core import AnalysisContext, AnalysisTask, ObjectCheck
from emneklar.features.findings.store import FindingDraft, make_fingerprint

log = logging.getLogger(__name__)
EDITABLE_TYPES = {"page", "assignment", "discussion", "quiz", "syllabus"}
DOCUMENT_TIMEOUT = 90.0


def blueprint_evidence(obj: SnapObj) -> dict[str, Any] | None:
    """Blueprint lock status as Canvas reported it. Recorded for the user – it never removes a fix: Canvas decides
    whether the connected user may change the content (see core/canvas/blueprint.py)."""
    meta = obj.meta
    if meta.get("restricted_by_master_course") is None and not meta.get("is_master_course_child_content"):
        return None
    return {"locked": is_locked(meta), "restrictions": meta.get("master_course_restrictions") or None,
            "child_content": bool(meta.get("is_master_course_child_content")),
            "master_content": bool(meta.get("is_master_course_master_content"))}


def to_draft(ctx: AnalysisContext, issue: Issue, obj: SnapObj, *, domain: str = "accessibility") -> FindingDraft:
    rule = get_rule(issue.rule_id)
    location = issue.location()
    location.update(ctx.view.module_location(obj))
    evidence = dict(issue.evidence)
    blueprint = blueprint_evidence(obj)
    if blueprint:
        evidence["blueprint"] = blueprint
    fix = issue.fix if obj.object_type in EDITABLE_TYPES and obj.body is not None else None
    return FindingDraft(
        domain=domain, rule_id=rule.id, category=rule.category,
        classification=issue.classification or rule.classification, test_method=rule.testability,
        severity=issue.severity or rule.severity, confidence=issue.confidence, title=rule.title,
        message=issue.message, remediation=rule.remediation,
        fingerprint=make_fingerprint(ctx.course_id, domain, rule.id, obj.ref, issue.identity()),
        object_type=obj.object_type, object_id=obj.canvas_id, object_title=obj.title, object_url=obj.html_url,
        location=location, evidence=evidence, fix=fix, ruleset_version=load_ruleset().version)


class CaptionCache:
    """Caption status per Canvas media id / attachment id (None = could not be determined).

    Canvas keeps caption tracks of uploaded media on the *file* (attachment): ``GET /media_attachments/:id/
    media_tracks`` lists them, while the course's media list often shows ``media_tracks: []`` for the same video
    (observed on a real course: 170 media objects, none with tracks in the list, although they were captioned). So
    only a *positive* answer from the media list is trusted. Otherwise the tracks are read from the attachment – the
    one in the embed, or the course file whose ``media_entry_id`` is the media id. When neither is possible the status
    stays unknown (reported as «kunne ikke kontrolleres», never as missing captions).
    """

    def __init__(self, ctx: AnalysisContext) -> None:
        self.ctx = ctx
        self.status: dict[str, bool | None] = {}
        #: What each recording is according to Canvas (media object ``media_type``, file ``content-type``) – the
        #: requirement depends on it (media_kinds.py). The teacher's own statement (``assessed``) wins.
        self.kinds: dict[str, MediaKind] = {}
        for media in ctx.view.get("media"):
            if media.meta.get("has_captions"):
                self.status[media.canvas_id] = True
            kind = canvas_media_kind(media.meta.get("media_type"))
            if kind:
                self.kinds[f"media:{media.canvas_id}"] = kind
        for f in ctx.view.get("file"):
            kind = canvas_file_kind(f.meta.get("content_type"))
            if kind:
                self.kinds.setdefault(f"attachment:{f.canvas_id}", kind)
                if f.meta.get("media_entry_id"):
                    self.kinds.setdefault(f"media:{f.meta['media_entry_id']}", kind)
        self.attachment_of: dict[str, str] = {
            str(f.meta["media_entry_id"]): f.canvas_id for f in ctx.view.get("file") if f.meta.get("media_entry_id")}
        self.assessed = load_assessments(ctx.container.db, ctx.course_id)

    def attachment_for(self, ref: MediaRef) -> str | None:
        if ref.kind == "canvas_attachment" and ref.ident:
            return ref.ident
        return self.attachment_of.get(str(ref.media_id or ref.ident or "")) or None

    async def attachment(self, attachment_id: str) -> bool | None:
        key = f"attachment:{attachment_id}"
        if key in self.status:
            return self.status[key]
        async with self.ctx.lock(key):
            if key in self.status:
                return self.status[key]
            try:
                tracks = await self.ctx.api.media_attachment_tracks(attachment_id)
                value: bool | None = any(str(t.get("kind")) in ("captions", "subtitles")
                                         and t.get("workflow_state", "ready") == "ready" for t in tracks)
            except CanvasError:
                value = None
            self.status[key] = value
            return value

    async def resolve(self, ref: MediaRef) -> bool | None:
        if ref.media_id and self.status.get(ref.media_id) is True:
            return True
        attachment = self.attachment_for(ref)
        return await self.attachment(attachment) if attachment else None

    async def for_doc(self, doc: ContentDoc) -> dict[str, bool | None]:
        """Status per media id and attachment id of the media in this content (the keys check_media looks up)."""
        result: dict[str, bool | None] = {}
        for _el, ref in find_media(doc.soup):
            if ref.kind not in ("canvas_media", "canvas_attachment"):
                continue
            value = await self.resolve(ref)
            for key in (ref.media_id, ref.ident):
                if key and result.get(key) is not True:
                    result[key] = value
        return result


class AccessibilityAnalyzer:
    domain = "accessibility"

    def _captions(self, ctx: AnalysisContext) -> CaptionCache:
        if "captions" not in ctx.shared:
            ctx.shared["captions"] = CaptionCache(ctx)
        return ctx.shared["captions"]

    def _youtube(self, ctx: AnalysisContext) -> YoutubeCaptionChecker | None:
        """Caption check of embedded YouTube videos – only when external checks are on (Innstillinger → Analyse)."""
        if not ctx.settings.analysis.check_external_links:
            return None
        if "youtube_captions" not in ctx.shared:
            ctx.shared["youtube_captions"] = YoutubeCaptionChecker(
                ctx.container, cache_hours=max(ctx.settings.analysis.link_cache_hours, CAPTION_CACHE_HOURS))
        return ctx.shared["youtube_captions"]

    def object_check(self, ctx: AnalysisContext) -> ObjectCheck:
        captions = self._captions(ctx)
        youtube = self._youtube(ctx)

        async def check(doc: ContentDoc, obj: SnapObj) -> list[FindingDraft]:
            media = await captions.for_doc(doc)
            videos: dict[str, str | None] = {}
            if youtube is not None:
                for _el, ref in find_media(doc.soup):
                    if ref.kind == "youtube" and ref.ident and ref.ident not in videos:
                        info = await youtube.status(ref.ident)
                        videos[ref.ident] = info.state if info else None
            issues = run_html_checks(doc, media, videos, media_kinds=captions.kinds, assessed=captions.assessed)
            return [to_draft(ctx, issue, obj) for issue in issues]

        return check

    def finish(self, ctx: AnalysisContext) -> None:
        youtube = ctx.shared.get("youtube_captions")
        note = youtube.limitation() if youtube is not None else None
        if note:
            ctx.limitations.append(note)
        if not ctx.settings.analysis.check_external_links and any(
                ref.kind == "youtube" for obj in ctx.html_objects() if obj.body
                for _el, ref in find_media(ctx.content_doc(obj).soup)):
            ctx.limitations.append("Teksting av YouTube-videoer ble ikke kontrollert (eksterne kontroller er slått av "
                                   "under Innstillinger → Analyse).")

    def tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        tasks: list[AnalysisTask] = []
        for page in ctx.view.get("page"):
            if page.body is None and ctx.in_scope(page):
                tasks.append(self._block_editor_task(ctx, page))
        tasks.extend(self._media_tasks(ctx))
        tasks.extend(self._youtube_tasks(ctx))
        if ctx.settings.analysis.check_documents and is_enabled(ctx.settings, "document_checks"):
            tasks.extend(self._document_tasks(ctx))
        else:
            ctx.limitations.append("Dokumentkontroll var slått av i denne analysen.")
        return tasks

    def _block_editor_task(self, ctx: AnalysisContext, page: SnapObj) -> AnalysisTask:
        async def run() -> list[FindingDraft]:
            issue = Issue("UU-BLOCK-EDITOR", f"«{page.title}» er laget med blokkredigering.", key="block-editor")
            return [to_draft(ctx, issue, page)]

        return AnalysisTask(type="page", item=ctx.view.location_label(page), operation="Sidetype", domain=self.domain,
                            run=run, objects=[page.ref])

    def _media_tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        captions = self._captions(ctx)
        seen: set[str] = set()
        tasks = []
        for obj in ctx.html_objects():
            if not obj.body:
                continue
            for _el, ref in find_media(ctx.content_doc(obj).soup):
                if ref.kind not in ("canvas_media", "canvas_attachment"):
                    continue
                if ref.media_id and captions.status.get(ref.media_id) is True:
                    continue
                found = captions.attachment_for(ref)
                if not found or found in seen:
                    continue
                seen.add(found)
                attachment_id = found

                async def run(attachment_id: str = attachment_id) -> list[FindingDraft]:
                    await captions.attachment(attachment_id)
                    return []

                tasks.append(AnalysisTask(type="media", item=ctx.view.location_label(obj),
                                          operation="Kontrollerer teksting i Canvas", domain=self.domain, run=run))
        return tasks

    def _youtube_tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        """One task per embedded YouTube video (progress, and the lookups run ahead of the pages that need them)."""
        youtube = self._youtube(ctx)
        if youtube is None:
            return []
        seen: set[str] = set()
        tasks = []
        for obj in ctx.html_objects():
            if not obj.body:
                continue
            for _el, ref in find_media(ctx.content_doc(obj).soup):
                if ref.kind != "youtube" or not ref.ident or ref.ident in seen:
                    continue
                seen.add(ref.ident)

                async def run(video_id: str = ref.ident) -> list[FindingDraft]:
                    await youtube.status(video_id)
                    return []

                tasks.append(AnalysisTask(type="media", item=f"YouTube-video {ref.ident}",
                                          operation="Kontrollerer teksting på YouTube", domain=self.domain, run=run))
        return tasks

    def _document_files(self, ctx: AnalysisContext) -> list[SnapObj]:
        files = {f.canvas_id: f for f in ctx.view.get("file")}
        wanted: list[str] = []
        for item in ctx.view.get("module_item"):
            if item.meta.get("type") == "File" and ctx.in_scope(item):
                wanted.append(str(item.meta.get("content_id")))
        for obj in ctx.html_objects():
            if not obj.body:
                continue
            for a in ctx.content_doc(obj).soup.find_all("a", href=True):
                ref = canvas_ref(str(a.get("href")), ctx.canvas_host)
                if ref and ref.kind == "files" and ref.ident and ref.ident.isdigit() and ref.course_id == ctx.course_id:
                    wanted.append(ref.ident)
        result = []
        seen: set[str] = set()
        for file_id in wanted:
            file_obj = files.get(file_id)
            if file_obj is None or file_id in seen:
                continue
            seen.add(file_id)
            if document_format(str(file_obj.meta.get("filename") or file_obj.title), file_obj.meta.get("content_type")):
                result.append(file_obj)
        unlinked = len([f for f in files.values() if document_format(str(f.meta.get("filename") or f.title),
                                                                     f.meta.get("content_type"))]) - len(result)
        if unlinked > 0 and ctx.request.scope == "course":
            ctx.limitations.append(f"{unlinked} dokument(er) i Filer er ikke lenket fra innhold eller moduler og "
                                   "ble ikke kontrollert.")
        return result

    def _document_tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        tasks = []
        max_bytes = ctx.settings.analysis.max_document_mb * 1024 * 1024
        for file_obj in self._document_files(ctx):
            tasks.append(AnalysisTask(type="document", item=f"Dokument: {file_obj.title}",
                                      operation="Leser dokumentet", domain=self.domain,
                                      run=self._document_runner(ctx, file_obj, max_bytes), objects=[file_obj.ref]))
        return tasks

    def _document_runner(self, ctx: AnalysisContext, file_obj: SnapObj, max_bytes: int) -> Any:
        async def run() -> list[FindingDraft]:
            name = file_obj.title
            fmt = document_format(str(file_obj.meta.get("filename") or name), file_obj.meta.get("content_type"))
            created = file_obj.meta.get("created_at")
            size = int(file_obj.meta.get("size") or 0)
            if fmt is None:
                return []
            if fmt in ("pdf", "docx", "pptx", "xlsx") and size <= max_bytes:
                result = await self._inspect(ctx, file_obj, fmt, max_bytes)
            elif size > max_bytes:
                result = {"format": fmt, "error": "limits"}
            else:
                result = {"format": fmt}
            return [to_draft(ctx, i, file_obj) for i in document_issues(result, name=name, created_at=created)]

        return run

    async def _inspect(self, ctx: AnalysisContext, file_obj: SnapObj, fmt: str, max_bytes: int) -> dict[str, Any]:
        url = str(file_obj.meta.get("url") or "")
        if not url:
            return {"format": fmt, "error": "parse"}
        path = ctx.container.config.cache_dir / f"doc-{secrets.token_hex(8)}.{fmt}"
        try:
            try:
                await ctx.api.client.download(url, path, max_bytes=max_bytes)
            except AppError as exc:
                return {"format": fmt, "error": "limits" if exc.code == "file_too_large" else "parse"}
            result = await ctx.container.parsers.run(
                {"job": "inspect_document", "args": {"path": str(path), "fmt": fmt}}, DOCUMENT_TIMEOUT)
            if result.get("error") == "timeout":
                return {"format": fmt, "error": "timeout"}
            return result
        finally:
            path.unlink(missing_ok=True)
