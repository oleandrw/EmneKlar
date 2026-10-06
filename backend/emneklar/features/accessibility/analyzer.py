"""Accessibility analyzer for the global analysis."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.html import canvas_ref, find_media
from emneklar.core.canvas.snapshot import SnapObj
from emneklar.core.errors import AppError
from emneklar.core.flags import is_enabled
from emneklar.features.accessibility.checks import ContentDoc, Issue, run_html_checks
from emneklar.features.accessibility.documents import document_format, document_issues
from emneklar.features.accessibility.rules import get_rule, load_ruleset
from emneklar.features.analysis.core import AnalysisContext, AnalysisTask, ObjectCheck
from emneklar.features.findings.store import FindingDraft, make_fingerprint

log = logging.getLogger(__name__)
EDITABLE_TYPES = {"page", "assignment", "discussion", "quiz", "syllabus"}
DOCUMENT_TIMEOUT = 90.0


def blueprint_locked(obj: SnapObj) -> bool:
    restrictions = obj.meta.get("master_course_restrictions") or {}
    return bool(obj.meta.get("restricted_by_master_course")) and bool(
        restrictions.get("content") or restrictions.get("all"))


def to_draft(ctx: AnalysisContext, issue: Issue, obj: SnapObj, *, domain: str = "accessibility") -> FindingDraft:
    rule = get_rule(issue.rule_id)
    modules = ctx.view.module_of.get(obj.ref)
    location = issue.location()
    if modules:
        location["module"] = modules[0]
    evidence = dict(issue.evidence)
    fix = issue.fix if obj.object_type in EDITABLE_TYPES and obj.body is not None else None
    if fix and blueprint_locked(obj):
        evidence["blueprint_locked"] = True
        fix = None
    return FindingDraft(
        domain=domain, rule_id=rule.id, category=rule.category,
        classification=issue.classification or rule.classification, test_method=rule.testability,
        severity=issue.severity or rule.severity, confidence=issue.confidence, title=rule.title,
        message=issue.message, remediation=rule.remediation,
        fingerprint=make_fingerprint(ctx.course_id, domain, rule.id, obj.ref, issue.identity()),
        object_type=obj.object_type, object_id=obj.canvas_id, object_title=obj.title, object_url=obj.html_url,
        location=location, evidence=evidence, fix=fix, ruleset_version=load_ruleset().version)


class CaptionCache:
    """Caption status per Canvas media id / attachment id (None = could not be determined)."""

    def __init__(self, ctx: AnalysisContext) -> None:
        self.ctx = ctx
        self.status: dict[str, bool | None] = {}
        for media in ctx.view.get("media"):
            self.status[media.canvas_id] = bool(media.meta.get("has_captions"))

    async def attachment(self, attachment_id: str) -> bool | None:
        if attachment_id in self.status:
            return self.status[attachment_id]
        async with self.ctx.lock(f"attachment:{attachment_id}"):
            if attachment_id in self.status:
                return self.status[attachment_id]
            try:
                tracks = await self.ctx.api.media_attachment_tracks(attachment_id)
                value: bool | None = any(str(t.get("kind")) in ("captions", "subtitles")
                                         and t.get("workflow_state", "ready") == "ready" for t in tracks)
            except CanvasError:
                value = None
            self.status[attachment_id] = value
            return value

    async def for_doc(self, doc: ContentDoc) -> dict[str, bool | None]:
        for _el, ref in find_media(doc.soup):
            if ref.kind == "canvas_attachment" and ref.ident and not (ref.media_id and ref.media_id in self.status):
                await self.attachment(ref.ident)
        return dict(self.status)


class AccessibilityAnalyzer:
    domain = "accessibility"

    def _captions(self, ctx: AnalysisContext) -> CaptionCache:
        if "captions" not in ctx.shared:
            ctx.shared["captions"] = CaptionCache(ctx)
        return ctx.shared["captions"]

    def object_check(self, ctx: AnalysisContext) -> ObjectCheck:
        captions = self._captions(ctx)

        async def check(doc: ContentDoc, obj: SnapObj) -> list[FindingDraft]:
            media = await captions.for_doc(doc)
            return [to_draft(ctx, issue, obj) for issue in run_html_checks(doc, media)]

        return check

    def tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        tasks: list[AnalysisTask] = []
        for page in ctx.view.get("page"):
            if page.body is None and ctx.in_scope(page):
                tasks.append(self._block_editor_task(ctx, page))
        tasks.extend(self._media_tasks(ctx))
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
                if ref.kind != "canvas_attachment" or not ref.ident or ref.ident in seen:
                    continue
                if ref.media_id and ref.media_id in captions.status:
                    continue
                seen.add(ref.ident)
                attachment_id = ref.ident

                async def run(attachment_id: str = attachment_id) -> list[FindingDraft]:
                    await captions.attachment(attachment_id)
                    return []

                tasks.append(AnalysisTask(type="media", item=ctx.view.location_label(obj),
                                          operation="Kontrollerer teksting i Canvas", domain=self.domain, run=run))
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
