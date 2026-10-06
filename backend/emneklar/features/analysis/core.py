"""Shared types for the global analysis (one snapshot, many analyzers)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.snapshot import HTML_TYPES, SnapObj, SnapshotView
from emneklar.core.storage.settings import AppSettings
from emneklar.features.accessibility.checks.base import ContentDoc
from emneklar.features.accessibility.profiles import Profile
from emneklar.features.findings.store import FindingDraft

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

Domain = Literal["accessibility", "content_quality", "structure", "quiz"]
DOMAINS: tuple[str, ...] = ("accessibility", "content_quality", "structure", "quiz")


class ItemRef(BaseModel):
    object_type: Literal["page", "assignment", "discussion", "quiz", "file", "syllabus"]
    object_id: str = Field(max_length=300)


class AnalysisRequest(BaseModel):
    course_id: str
    scope: Literal["course", "modules", "items"] = "course"
    module_ids: list[str] = Field(default_factory=list, max_length=500)
    items: list[ItemRef] = Field(default_factory=list, max_length=2000)
    domains: list[Domain] = Field(default_factory=lambda: ["accessibility", "content_quality", "structure"])


@dataclass
class AnalysisTask:
    type: str  # progress bucket (page, link, document, media, structure, question …)
    item: str  # «Modul 4 – Bildebehandling › Side: Fargelære»
    operation: str  # «Bilder, lenker og HTML»
    domain: str
    run: Callable[[], Awaitable[list[FindingDraft]]]
    objects: list[str] = field(default_factory=list)


ObjectCheck = Callable[[ContentDoc, SnapObj], Awaitable[list[FindingDraft]]]


@dataclass
class AnalysisContext:
    container: AppContainer
    course_id: str
    run_id: int
    view: SnapshotView
    request: AnalysisRequest
    settings: AppSettings
    profile: Profile
    api: CanvasAPI
    canvas_base: str
    limitations: list[str] = field(default_factory=list)
    shared: dict[str, Any] = field(default_factory=dict)
    _scope_refs: set[str] | None = None
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    @property
    def canvas_host(self) -> str:
        from urllib.parse import urlsplit

        return (urlsplit(self.canvas_base).hostname or "").lower()

    def scope_refs(self) -> set[str] | None:
        """Object refs in scope, or None for the whole course."""
        if self.request.scope == "course":
            return None
        if self._scope_refs is None:
            refs: set[str] = set()
            if self.request.scope == "modules":
                wanted = set(self.request.module_ids)
                for module in self.view.get("module"):
                    if module.canvas_id in wanted:
                        refs.add(module.ref)
                        for item in self.view.items_of(module.canvas_id):
                            refs.add(item.ref)
                            content = self.view.item_content_ref(item)
                            if content:
                                refs.add(content)
            else:
                refs = {f"{i.object_type}:{i.object_id}" for i in self.request.items}
            self._scope_refs = refs
        return self._scope_refs

    def in_scope(self, obj: SnapObj) -> bool:
        refs = self.scope_refs()
        return refs is None or obj.ref in refs

    def html_objects(self) -> list[SnapObj]:
        out = []
        for kind in HTML_TYPES:
            for obj in self.view.get(kind):
                if kind == "syllabus" and self.request.scope != "course":
                    continue
                if self.in_scope(obj):
                    out.append(obj)
        return out

    def content_doc(self, obj: SnapObj) -> ContentDoc:
        modules = self.view.module_of.get(obj.ref)
        return ContentDoc(object_type=obj.object_type, object_id=obj.canvas_id, title=obj.title, html=obj.body or "",
                          url=obj.html_url, canvas_host=self.canvas_host, module=modules[0] if modules else None,
                          course_id=self.course_id, language=str(self.view.course_meta().get("locale") or "nb"))

    def lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]


class Analyzer(Protocol):
    domain: str

    def object_check(self, ctx: AnalysisContext) -> ObjectCheck | None: ...

    def tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]: ...
