"""Normalised course snapshot: download a course once, share it between analyzers.

The builder fetches each Canvas content list once (pages with bodies, modules
with items, assignments, discussions, quizzes, files, media objects, course +
syllabus) and stores the objects in ``snapshot_objects``. Failures are
isolated per content type (e.g. no permission for quizzes) and recorded as
limitations instead of aborting the whole analysis.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from emneklar.core.canvas.api import CanvasAPI, is_block_editor_page
from emneklar.core.canvas.client import CanvasError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import Snapshot, SnapshotObject

log = logging.getLogger(__name__)

HTML_TYPES = ("page", "assignment", "discussion", "quiz", "syllabus")


@dataclass
class SnapObj:
    object_type: str
    canvas_id: str
    title: str
    parent_id: str | None = None
    html_url: str | None = None
    body: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    canvas_updated_at: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.object_type}:{self.canvas_id}"


def content_hash(body: str | None) -> str | None:
    return hashlib.sha256(body.encode("utf-8")).hexdigest() if body is not None else None


def _abs(base: str, url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else f"{base}{url}"


def normalise(kind: str, raw: dict[str, Any], base: str) -> list[SnapObj]:
    """Convert one Canvas API object into snapshot objects."""
    if kind == "pages":
        block = is_block_editor_page(raw)
        return [SnapObj("page", str(raw.get("url")), raw.get("title") or "", html_url=_abs(base, raw.get("html_url")),
                        body=None if block else (raw.get("body") or ""),
                        meta={"page_id": str(raw.get("page_id") or ""), "published": raw.get("published"),
                              "front_page": raw.get("front_page"), "editor": raw.get("editor") or "rce",
                              "block_editor": block, "editing_roles": raw.get("editing_roles"),
                              "restricted_by_master_course": raw.get("restricted_by_master_course"),
                              "master_course_restrictions": raw.get("master_course_restrictions"),
                              "is_master_course_child_content": raw.get("is_master_course_child_content")},
                        canvas_updated_at=raw.get("updated_at"))]
    if kind == "modules":
        out = [SnapObj("module", str(raw["id"]), raw.get("name") or "",
                       meta={k: raw.get(k) for k in ("position", "require_sequential_progress", "requirement_type",
                                                     "prerequisite_module_ids", "published", "unlock_at",
                                                     "items_count")})]
        for item in raw.get("items") or []:
            out.append(SnapObj("module_item", str(item["id"]), item.get("title") or "", parent_id=str(raw["id"]),
                               html_url=_abs(base, item.get("html_url")),
                               meta={k: item.get(k) for k in ("type", "content_id", "page_url", "external_url",
                                                              "position", "indent", "completion_requirement",
                                                              "published", "new_tab", "content_details")}))
        return out
    if kind == "assignments":
        return [SnapObj("assignment", str(raw["id"]), raw.get("name") or "", html_url=_abs(base, raw.get("html_url")),
                        body=raw.get("description") or "",
                        meta={k: raw.get(k) for k in ("published", "due_at", "unlock_at", "lock_at", "points_possible",
                                                      "submission_types", "quiz_id", "is_quiz_assignment",
                                                      "discussion_topic", "restricted_by_master_course",
                                                      "master_course_restrictions", "grading_type")},
                        canvas_updated_at=raw.get("updated_at"))]
    if kind == "discussions":
        return [SnapObj("discussion", str(raw["id"]), raw.get("title") or "", html_url=_abs(base, raw.get("html_url")),
                        body=raw.get("message") or "",
                        meta={k: raw.get(k) for k in ("published", "assignment_id", "locked", "pinned",
                                                      "restricted_by_master_course", "master_course_restrictions")},
                        canvas_updated_at=raw.get("updated_at"))]
    if kind == "quizzes":
        return [SnapObj("quiz", str(raw["id"]), raw.get("title") or "", html_url=_abs(base, raw.get("html_url")),
                        body=raw.get("description") or "",
                        meta={k: raw.get(k) for k in ("quiz_type", "published", "question_count", "points_possible",
                                                      "time_limit", "shuffle_answers", "hide_results",
                                                      "show_correct_answers", "allowed_attempts", "scoring_policy",
                                                      "one_question_at_a_time", "cant_go_back", "due_at", "lock_at",
                                                      "unlock_at", "assignment_id", "restricted_by_master_course",
                                                      "master_course_restrictions")},
                        canvas_updated_at=raw.get("updated_at"))]
    if kind == "files":
        return [SnapObj("file", str(raw["id"]), raw.get("display_name") or raw.get("filename") or "",
                        meta={"filename": raw.get("filename"), "content_type": raw.get("content-type"),
                              "size": raw.get("size"), "url": raw.get("url"), "created_at": raw.get("created_at"),
                              "folder_id": raw.get("folder_id"), "hidden": raw.get("hidden"),
                              "locked": raw.get("locked"), "media_entry_id": raw.get("media_entry_id")},
                        canvas_updated_at=raw.get("updated_at"))]
    if kind == "media":
        tracks = raw.get("media_tracks") or []
        return [SnapObj("media", str(raw.get("media_id")), raw.get("title") or "",
                        meta={"media_type": raw.get("media_type"), "tracks": tracks,
                              "has_captions": any(str(t.get("kind")) in ("captions", "subtitles")
                                                  and t.get("workflow_state", "ready") == "ready" for t in tracks)})]
    raise ValueError(kind)


ListFetcher = Callable[[CanvasAPI, str], Awaitable[Any]]

CONTENT_LISTS: list[tuple[str, str, ListFetcher]] = [
    ("course", "Emne og emneplan", lambda api, cid: api.get_course(cid, include=("term", "syllabus_body"))),
    ("modules", "Moduler", lambda api, cid: api.list_modules(cid)),
    ("pages", "Sider", lambda api, cid: api.list_pages(cid)),
    ("assignments", "Oppgaver", lambda api, cid: api.list_assignments(cid)),
    ("discussions", "Diskusjoner", lambda api, cid: api.list_discussions(cid)),
    ("quizzes", "Quizer", lambda api, cid: api.list_quizzes(cid)),
    ("files", "Filer", lambda api, cid: api.list_files(cid)),
    ("media", "Video og lyd", lambda api, cid: api.list_media_objects(cid)),
]

KIND_LABELS = {kind: label for kind, label, _ in CONTENT_LISTS}


class SnapshotBuilder:
    def __init__(self, db: Database, api: CanvasAPI, base_url: str) -> None:
        self.db = db
        self.api = api
        self.base = base_url.rstrip("/")

    async def build(
        self,
        course_id: str,
        *,
        scope: dict[str, Any],
        on_start: Callable[[str, str], Any] | None = None,
        on_done: Callable[[str, str, int, str | None], Any] | None = None,
        checkpoint: Callable[[], Awaitable[None]] | None = None,
    ) -> int:
        with self.db.session() as session:
            snap = Snapshot(course_id=course_id, status="building", scope=scope)
            session.add(snap)
            session.flush()
            snapshot_id = snap.id
        stats: dict[str, int] = {}
        errors: list[dict[str, Any]] = []
        objects: list[SnapObj] = []
        for kind, label, fetch in CONTENT_LISTS:
            if checkpoint is not None:
                await checkpoint()
            if on_start:
                on_start(kind, label)
            error: str | None = None
            count = 0
            try:
                data = await fetch(self.api, course_id)
                if kind == "course":
                    course = data or {}
                    objects.append(SnapObj("course", course_id, course.get("name") or "", meta={
                        k: course.get(k) for k in ("name", "course_code", "default_view", "locale", "blueprint",
                                                   "workflow_state", "is_public", "term", "time_zone",
                                                   "public_syllabus")}))
                    syllabus = course.get("syllabus_body")
                    if syllabus:
                        objects.append(SnapObj("syllabus", course_id, "Emneplan (syllabus)", body=syllabus,
                                               html_url=f"{self.base}/courses/{course_id}/assignments/syllabus"))
                    count = 1
                else:
                    for raw in data or []:
                        if isinstance(raw, dict):
                            new = normalise(kind, raw, self.base)
                            objects.extend(new)
                            count += 1
            except CanvasError as exc:
                if kind == "course":
                    raise
                error = exc.message
                errors.append({"kind": kind, "label": label, "code": exc.code, "message": exc.message})
                log.warning("Kunne ikke hente %s for emne %s: %s", kind, course_id, exc.code)
            stats[kind] = count
            if on_done:
                on_done(kind, label, count, error)
        with self.db.session() as session:
            session.add_all(SnapshotObject(
                snapshot_id=snapshot_id, object_type=o.object_type, canvas_id=o.canvas_id, parent_id=o.parent_id,
                title=o.title[:1000], html_url=o.html_url, body=o.body, meta=o.meta,
                canvas_updated_at=o.canvas_updated_at, content_hash=content_hash(o.body)) for o in objects)
            stored = session.get(Snapshot, snapshot_id)
            assert stored is not None
            stored.status = "partial" if errors else "complete"
            stored.stats = stats
            stored.errors = errors
        return snapshot_id


@dataclass
class SnapshotView:
    """In-memory, indexed view of one snapshot (for analyzers)."""

    snapshot_id: int
    course_id: str
    created_at: datetime
    status: str
    errors: list[dict[str, Any]]
    objects: list[SnapObj]
    by_type: dict[str, list[SnapObj]] = field(default_factory=dict)
    by_ref: dict[str, SnapObj] = field(default_factory=dict)
    module_of: dict[str, list[str]] = field(default_factory=dict)  # content ref -> module names

    @classmethod
    def load(cls, db: Database, snapshot_id: int) -> SnapshotView:
        with db.session() as session:
            snap = session.get(Snapshot, snapshot_id)
            if snap is None:
                raise KeyError(snapshot_id)
            rows = session.scalars(select(SnapshotObject).where(SnapshotObject.snapshot_id == snapshot_id)).all()
            objects = [SnapObj(r.object_type, r.canvas_id, r.title, r.parent_id, r.html_url, r.body, r.meta or {},
                               r.canvas_updated_at) for r in rows]
            view = cls(snapshot_id, snap.course_id, snap.created_at, snap.status, list(snap.errors or []), objects)
        view._index()
        return view

    def _index(self) -> None:
        by_type: dict[str, list[SnapObj]] = defaultdict(list)
        for obj in self.objects:
            by_type[obj.object_type].append(obj)
            self.by_ref[obj.ref] = obj
        self.by_type = dict(by_type)
        modules = {m.canvas_id: m for m in by_type.get("module", [])}
        module_of: dict[str, list[str]] = defaultdict(list)
        for item in by_type.get("module_item", []):
            module = modules.get(item.parent_id or "")
            ref = self.item_content_ref(item)
            if module is not None and ref:
                module_of[ref].append(module.title)
        self.module_of = dict(module_of)

    def item_content_ref(self, item: SnapObj) -> str | None:
        kind = str(item.meta.get("type") or "")
        content_id = item.meta.get("content_id")
        if kind == "Page":
            return f"page:{item.meta.get('page_url')}"
        mapping = {"Assignment": "assignment", "Discussion": "discussion", "Quiz": "quiz", "File": "file"}
        if kind in mapping and content_id is not None:
            return f"{mapping[kind]}:{content_id}"
        return None

    def get(self, object_type: str) -> list[SnapObj]:
        return self.by_type.get(object_type, [])

    def course_meta(self) -> dict[str, Any]:
        course = self.get("course")
        return course[0].meta if course else {}

    def modules(self) -> list[SnapObj]:
        return sorted(self.get("module"), key=lambda m: int(m.meta.get("position") or 0))

    def items_of(self, module_id: str) -> list[SnapObj]:
        return sorted((i for i in self.get("module_item") if i.parent_id == module_id),
                      key=lambda i: int(i.meta.get("position") or 0))

    def location_label(self, obj: SnapObj) -> str:
        names = self.module_of.get(obj.ref)
        kind = {"page": "Side", "assignment": "Oppgave", "discussion": "Diskusjon", "quiz": "Quiz",
                "syllabus": "Emneplan", "file": "Fil"}.get(obj.object_type, obj.object_type)
        prefix = f"{names[0]} › " if names else ""
        return f"{prefix}{kind}: {obj.title}"

    def age_seconds(self) -> float:
        created = self.created_at if self.created_at.tzinfo else self.created_at.replace(tzinfo=UTC)
        return (datetime.now(UTC) - created).total_seconds()
