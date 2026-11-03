"""Innhenting: what Emne-RAG reads from Canvas – teacher-produced content only.

Privacy rules (requirement):

* Read: pages, assignment descriptions, quiz descriptions, the syllabus, the front page, discussion *topics* whose
  author is a teacher/TA/designer in the course, course files uploaded by teachers, and media that teacher
  content points to.
* Never read: submissions, grades, messages, discussion replies (``entries``/``view`` are never called), student
  topics, student files, or media that only appears in the course media list (it can contain student recordings).
* Teacher ids come from ``GET /courses/:id/users?enrollment_type[]=teacher|ta|designer``; only the ids are used and
  they are not stored. When they cannot be read, only graded discussions (which only teachers can create) are
  included.

Scope: «Hele emnet» includes everything above, inside or outside modules. «Valgte moduler» includes the module
items and the Canvas files and media linked from those items.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from emneklar.core.canvas.api import CanvasAPI, is_block_editor_page
from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.html import YOUTUBE_RE
from emneklar.features.course_rag.chunking import CHUNKER_VERSION
from emneklar.features.course_rag.convert.documents import (
    AUDIO_FORMATS,
    DOCUMENT_FORMATS,
    FILE_GROUPS,
    IMAGE_FORMATS,
    LEGACY_FORMATS,
    SUBTITLE_FORMATS,
    VIDEO_FORMATS,
    file_format,
    group_of,
)
from emneklar.features.course_rag.convert.html_md import HtmlResult, html_to_blocks

log = logging.getLogger(__name__)

TEXT_KINDS = ("page", "assignment", "discussion", "quiz", "syllabus")
KIND_LABELS = {"page": "Side", "assignment": "Oppgave", "discussion": "Diskusjon", "quiz": "Quiz",
               "syllabus": "Emneplan", "file": "Fil", "media": "Video/lyd i Canvas", "youtube": "YouTube-video",
               "vimeo": "Vimeo-video", "image": "Bilde", "external": "Ekstern lenke", "tool": "Eksternt verktøy",
               "module": "Modul"}
SUBMISSION_LABELS = {"online_upload": "filopplasting", "online_text_entry": "tekst i Canvas", "online_url": "nettadresse",
                     "media_recording": "medieopptak", "discussion_topic": "diskusjon", "online_quiz": "quiz",
                     "on_paper": "på papir", "none": "ingen innlevering", "external_tool": "eksternt verktøy",
                     "student_annotation": "kommentering av dokument"}
QUIZ_TYPES = {"practice_quiz": "øvingsquiz", "assignment": "vurdert quiz", "graded_survey": "vurdert undersøkelse",
              "survey": "undersøkelse"}
MAX_LINKED_FILE_LOOKUPS = 200


class SourceOptions(BaseModel):
    scope: Literal["course", "modules"] = "course"
    module_ids: list[str] = Field(default_factory=list, max_length=500)
    text: bool = True
    documents: bool = True
    images: bool = False
    video: bool = False
    file_groups: list[Literal["pdf", "word", "powerpoint", "excel", "text"]] = Field(
        default=["pdf", "word", "powerpoint", "excel", "text"])
    include_unpublished: bool = False
    contextual_enrichment: bool = False
    keyframes: bool = False

    def signature(self) -> str:
        """The options that change how an element is processed (scope does not)."""
        return f"{CHUNKER_VERSION}|ctx={int(self.contextual_enrichment)}|kf={int(self.keyframes)}"


@dataclass
class SourceItem:
    key: str
    kind: str
    canvas_id: str
    title: str
    url: str | None
    updated_at: str | None
    modules: list[dict[str, str]] = field(default_factory=list)
    body: str | None = None  # HTML (text kinds)
    meta: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None
    parents: list[str] = field(default_factory=list)  # keys of the elements that link to it
    parsed: HtmlResult | None = None

    @property
    def module_name(self) -> str | None:
        return self.modules[0]["name"] if self.modules else None

    def signature(self, options: SourceOptions) -> str:
        data = [self.kind, self.updated_at, self.content_hash, self.meta.get("size"),
                sorted(m["id"] for m in self.modules), self.title, options.signature()]
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class Skip:
    key: str
    kind: str
    title: str
    reason: str
    url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "kind": self.kind, "kind_label": KIND_LABELS.get(self.kind, self.kind),
                "title": self.title, "reason": self.reason, "url": self.url}


@dataclass
class Inventory:
    items: list[SourceItem] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    modules: list[dict[str, Any]] = field(default_factory=list)
    teacher_check: bool = True

    def by_kind(self, *kinds: str) -> list[SourceItem]:
        return [i for i in self.items if i.kind in kinds]


def _hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest()


def _abs(base: str, url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else f"{base}{url}"


def _date(value: str | None, tz_name: str | None) -> str | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    try:
        from zoneinfo import ZoneInfo

        local = moment.astimezone(ZoneInfo(tz_name or "Europe/Oslo"))
        return local.strftime("%d.%m.%Y kl. %H:%M")
    except Exception:  # noqa: BLE001 - no time zone database (Windows without tzdata)
        return moment.astimezone(UTC).strftime("%d.%m.%Y kl. %H:%M UTC")


def assignment_facts(raw: dict[str, Any], tz_name: str | None) -> str:
    facts = []
    due = _date(raw.get("due_at"), tz_name)
    if due:
        facts.append(f"Frist: {due}")
    unlock = _date(raw.get("unlock_at"), tz_name)
    if unlock:
        facts.append(f"Tilgjengelig fra: {unlock}")
    lock = _date(raw.get("lock_at"), tz_name)
    if lock:
        facts.append(f"Stenges: {lock}")
    if raw.get("points_possible") not in (None, ""):
        facts.append(f"Poeng: {raw.get('points_possible')}")
    types = [SUBMISSION_LABELS.get(str(t), str(t)) for t in raw.get("submission_types") or []]
    if types:
        facts.append(f"Innlevering: {', '.join(types)}")
    return ". ".join(facts) + ("." if facts else "")


def quiz_facts(raw: dict[str, Any], tz_name: str | None) -> str:
    facts = []
    if raw.get("quiz_type"):
        facts.append(f"Type: {QUIZ_TYPES.get(str(raw['quiz_type']), raw['quiz_type'])}")
    if raw.get("question_count"):
        facts.append(f"Antall spørsmål: {raw['question_count']}")
    if raw.get("time_limit"):
        facts.append(f"Tidsbegrensning: {raw['time_limit']} minutter")
    attempts = raw.get("allowed_attempts")
    if attempts not in (None, 0):
        facts.append("Antall forsøk: ubegrenset" if attempts == -1 else f"Antall forsøk: {attempts}")
    due = _date(raw.get("due_at"), tz_name)
    if due:
        facts.append(f"Frist: {due}")
    return ". ".join(facts) + ("." if facts else "")


ListCallback = Callable[[str, str, int | None, str | None], Any]


async def _fetch(name: str, label: str, call: Any, on_list: ListCallback | None, limitations: list[str]) -> Any:
    try:
        result = await call
        if on_list:
            on_list(name, label, len(result) if isinstance(result, list) else None, None)
        return result
    except CanvasError as exc:
        limitations.append(f"Kunne ikke hente {label.lower()} fra Canvas: {exc.message}")
        log.warning("Emne-RAG: kunne ikke hente %s: %s", name, exc.code)
        if on_list:
            on_list(name, label, None, exc.message)
        return None


async def discover(api: CanvasAPI, course_id: str, options: SourceOptions, base_url: str, *,
                   on_list: ListCallback | None = None) -> Inventory:
    base = base_url.rstrip("/")
    host = base.split("://", 1)[-1].split("/")[0].split(":")[0]
    inv = Inventory()
    need_files = options.documents or options.images or options.video
    calls: dict[str, tuple[str, Any]] = {
        "course": ("Emne og emneplan", api.get_course(course_id, include=("term", "syllabus_body"))),
        "modules": ("Moduler", api.list_modules(course_id)),
    }
    if options.text or options.images or options.video or options.scope == "modules":
        calls["pages"] = ("Sider", api.list_pages(course_id))
        calls["assignments"] = ("Oppgaver", api.list_assignments(course_id))
        calls["discussions"] = ("Diskusjoner", api.list_discussions(course_id))
        calls["quizzes"] = ("Quizer", api.list_quizzes(course_id))
        calls["teachers"] = ("Lærere i emnet", api.list_teaching_user_ids(course_id))
    if need_files:
        calls["files"] = ("Filer", api.list_files(course_id, include_user=True))
    if options.video:
        calls["media"] = ("Video og lyd", api.list_media_objects(course_id, include_sources=True))
    results = await asyncio.gather(*(_fetch(name, label, call, on_list, inv.limitations)
                                     for name, (label, call) in calls.items()))
    data = dict(zip(calls, results, strict=True))
    course = data.get("course") or {}
    tz_name = course.get("time_zone")
    teacher_ids: set[str] | None = data.get("teachers")
    if "teachers" in calls and teacher_ids is None:
        inv.teacher_check = False
        inv.limitations.append("EmneKlar fikk ikke lest hvem som er lærere i emnet. Av diskusjonene tas derfor bare "
                               "vurderte diskusjoner med (de kan bare lærere opprette).")

    # -- modules: membership and scope --------------------------------------------------------------
    member: dict[str, list[dict[str, str]]] = {}
    in_modules: set[str] = set()
    selected = set(options.module_ids)
    external: list[tuple[dict[str, Any], dict[str, str]]] = []
    for module in data.get("modules") or []:
        mod = {"id": str(module.get("id")), "name": str(module.get("name") or "")}
        module_published = module.get("published") is not False
        inv.modules.append({**mod, "published": module_published, "items_count": len(module.get("items") or [])})
        wanted = options.scope == "course" or mod["id"] in selected
        for item in module.get("items") or []:
            kind = str(item.get("type") or "")
            key = None
            if kind == "Page" and item.get("page_url"):
                key = f"page:{item['page_url']}"
            elif kind in ("Assignment", "Discussion", "Quiz", "File") and item.get("content_id") is not None:
                key = f"{kind.lower()}:{item['content_id']}"
            elif kind in ("ExternalUrl", "ExternalTool") and wanted:
                external.append((item, mod))
            if key:
                member.setdefault(key, [])
                if mod not in member[key]:
                    member[key].append(mod)
                item_published = item.get("published") is not False and module_published
                if wanted and (item_published or options.include_unpublished):
                    in_modules.add(key)

    def in_scope(key: str) -> bool:
        return options.scope == "course" or key in in_modules

    def add(item: SourceItem) -> None:
        item.modules = member.get(item.key, [])
        if item.body is not None:
            item.parsed = html_to_blocks(item.body, base_url=base, canvas_host=host)
        inv.items.append(item)

    def is_published(raw: dict[str, Any]) -> bool:
        return raw.get("published") is not False

    # -- HTML content ---------------------------------------------------------------------------------
    for raw in data.get("pages") or []:
        key = f"page:{raw.get('url')}"
        if not in_scope(key):
            continue
        title = raw.get("title") or ""
        url = _abs(base, raw.get("html_url"))
        if not is_published(raw) and not options.include_unpublished:
            continue
        if is_block_editor_page(raw):
            inv.skipped.append(Skip(key, "page", title, "Siden er laget med Canvas' blokkredigering. Canvas-API-et gir "
                                    "ikke innholdet som HTML, så siden kan ikke leses.", url))
            continue
        body = raw.get("body") or ""
        add(SourceItem(key, "page", str(raw.get("url")), title, url, raw.get("updated_at"), body=body,
                       meta={"front_page": bool(raw.get("front_page")), "page_id": raw.get("page_id")},
                       content_hash=_hash(title, body)))
    for raw in data.get("assignments") or []:
        key = f"assignment:{raw.get('id')}"
        if not in_scope(key) or (not is_published(raw) and not options.include_unpublished):
            continue
        if raw.get("quiz_id") or raw.get("is_quiz_assignment") or raw.get("discussion_topic"):
            continue  # represented by the quiz / discussion itself
        facts = assignment_facts(raw, tz_name)
        body = (raw.get("description") or "") + (f"<p>{facts}</p>" if facts else "")
        title = raw.get("name") or ""
        add(SourceItem(key, "assignment", str(raw.get("id")), title, _abs(base, raw.get("html_url")),
                       raw.get("updated_at"), body=body, content_hash=_hash(title, body)))
    for raw in data.get("discussions") or []:
        key = f"discussion:{raw.get('id')}"
        if not in_scope(key) or (not is_published(raw) and not options.include_unpublished):
            continue
        author = raw.get("author") or {}
        author_id = str(author.get("id") or "") if isinstance(author, dict) else ""
        teacher = (author_id in teacher_ids) if teacher_ids is not None else bool(raw.get("assignment_id"))
        if not teacher:
            inv.skipped.append(Skip(key, "discussion", "Diskusjonstema som ikke er skrevet av en lærer",
                                    "Bare lærerens innlegg tas med. Temaer og svar fra studenter hentes aldri."))
            continue
        title = raw.get("title") or ""
        body = raw.get("message") or ""
        add(SourceItem(key, "discussion", str(raw.get("id")), title, _abs(base, raw.get("html_url")),
                       raw.get("updated_at"), body=body, content_hash=_hash(title, body)))
    for raw in data.get("quizzes") or []:
        key = f"quiz:{raw.get('id')}"
        if not in_scope(key) or (not is_published(raw) and not options.include_unpublished):
            continue
        facts = quiz_facts(raw, tz_name)
        body = (raw.get("description") or "") + (f"<p>{facts}</p>" if facts else "")
        title = raw.get("title") or ""
        add(SourceItem(key, "quiz", str(raw.get("id")), title, _abs(base, raw.get("html_url")), raw.get("updated_at"),
                       body=body, meta={"note": "Bare quizbeskrivelsen tas med, ikke spørsmål eller fasit."},
                       content_hash=_hash(title, body)))
    syllabus = course.get("syllabus_body")
    if syllabus and options.scope == "course":
        add(SourceItem(f"syllabus:{course_id}", "syllabus", course_id, "Emneplan",
                       f"{base}/courses/{course_id}/assignments/syllabus", None, body=syllabus,
                       content_hash=_hash(syllabus)))

    if not options.text:
        # HTML content was read only to find linked files and media; it is not indexed itself.
        for item in inv.items:
            item.meta["link_source_only"] = True

    # -- files ------------------------------------------------------------------------------------------
    files = {str(f.get("id")): f for f in data.get("files") or [] if isinstance(f, dict)}
    linked: dict[str, list[str]] = {}
    for item in inv.items:
        for fid in item.parsed.file_ids if item.parsed else []:
            linked.setdefault(fid, []).append(item.key)
        if options.video and item.parsed:
            for ref in item.parsed.media:  # uploaded media files embedded with the Canvas media player
                if ref.kind == "canvas_attachment" and ref.ident:
                    linked.setdefault(ref.ident, []).append(item.key)
    if need_files:
        wanted_files: list[str] = []
        if options.scope == "course":
            wanted_files = list(files)
        wanted_files += [k.split(":", 1)[1] for k in in_modules if k.startswith("file:")]
        wanted_files += list(linked)
        missing = [fid for fid in dict.fromkeys(wanted_files) if fid not in files][:MAX_LINKED_FILE_LOOKUPS]
        if missing:
            lookups = await asyncio.gather(*(api.get_file(fid) for fid in missing), return_exceptions=True)
            for fid, meta in zip(missing, lookups, strict=True):
                if isinstance(meta, dict):
                    files[fid] = meta
        for fid in dict.fromkeys(wanted_files):
            raw = files.get(fid)
            if raw is None:
                continue
            parent_modules = [m for item in inv.items if item.key in linked.get(fid, []) for m in item.modules]
            _add_file(inv, raw, options, teacher_ids, member, linked.get(fid, []), base, course_id, parent_modules)

    if options.video:
        _add_media(inv, data.get("media") or [], external, member, base)
    if options.images:
        _add_images(inv, files)

    # -- external links / tools in modules ---------------------------------------------------------
    for item, mod in external:
        title = str(item.get("title") or "")
        url = str(item.get("external_url") or "")
        key = f"{'external' if item.get('type') == 'ExternalUrl' else 'tool'}:{item.get('id')}"
        if item.get("type") == "ExternalUrl" and YOUTUBE_RE.search(url):
            if not options.video:
                inv.skipped.append(Skip(key, "youtube", f"{title} ({mod['name']})", "YouTube-video. Velg «Video og lyd» "
                                        "for å ta med tekstingen.", url))
            continue
        if item.get("type") == "ExternalUrl":
            reason = "Ekstern lenke. Nettsider utenfor Canvas hentes ikke."
        else:
            reason = ("Eksternt verktøy (LTI, for eksempel Panopto, Kaltura eller Studio). Innholdet kan ikke hentes "
                      "via Canvas-API-et.")
        inv.skipped.append(Skip(key, "external" if item.get("type") == "ExternalUrl" else "tool",
                                f"{title} ({mod['name']})", reason, url or _abs(base, item.get("html_url"))))
    return inv


_EMBED_SRC = re.compile(r"<iframe[^>]+src=[\"']([^\"']+)", re.IGNORECASE)
_PLATFORMS = {"panopto": "Panopto", "kaltura": "Kaltura", "mediasite": "Mediasite", "instructuremedia": "Canvas Studio",
              "vimeo": "Vimeo"}


def _merge_modules(target: list[dict[str, str]], extra: list[dict[str, str]]) -> None:
    for module in extra:
        if module not in target:
            target.append(module)


def _add_media(inv: Inventory, media_objects: list[Any], external: list[tuple[dict[str, Any], dict[str, str]]],
               member: dict[str, list[dict[str, str]]], base: str) -> None:
    """Media that teacher content points to (never the whole course media list – it can hold student recordings)."""
    objects = {str(m.get("media_id")): m for m in media_objects if isinstance(m, dict)}
    found: dict[str, SourceItem] = {}
    parents = list(inv.items)
    for parent in parents:
        if parent.parsed is None:
            continue
        for ref in parent.parsed.media:
            if ref.kind not in ("canvas_media", "youtube", "vimeo") or not ref.ident:
                continue
            kind = "media" if ref.kind == "canvas_media" else ref.kind
            key = f"{kind}:{ref.ident}"
            label = parent.parsed.media_titles.get(ref.ident) or ""
            if key not in found:
                url = f"https://www.youtube.com/watch?v={ref.ident}" if kind == "youtube" else \
                    f"https://vimeo.com/{ref.ident}" if kind == "vimeo" else parent.url
                found[key] = SourceItem(key, kind, ref.ident, label, url, None, content_hash=_hash(kind, ref.ident),
                                        meta={"page_title": parent.title})
            entry = found[key]
            if not entry.title and label:
                entry.title = label
            entry.parents.append(parent.key)
            _merge_modules(entry.modules, parent.modules)
        for src in _EMBED_SRC.findall(parent.body or ""):
            platform = next((name for host, name in _PLATFORMS.items() if host in src.lower() and host != "vimeo"),
                            None)
            if platform:
                inv.skipped.append(Skip(f"embed:{_hash(src)[:12]}", "tool", f"{platform}-video på «{parent.title}»",
                                        f"{platform} er et eksternt verktøy. Videoen og tekstingen kan ikke hentes via "
                                        "Canvas-API-et.", parent.url))
    for item, mod in external:
        url = str(item.get("external_url") or "")
        match = YOUTUBE_RE.search(url) if item.get("type") == "ExternalUrl" else None
        if not match:
            continue
        key = f"youtube:{match.group(1)}"
        entry = found.setdefault(key, SourceItem(key, "youtube", match.group(1), str(item.get("title") or ""),
                                                 f"https://www.youtube.com/watch?v={match.group(1)}", None,
                                                 content_hash=_hash("youtube", match.group(1))))
        _merge_modules(entry.modules, [mod])
    for key, entry in found.items():
        if entry.kind == "vimeo":
            inv.skipped.append(Skip(key, "vimeo", entry.title or "Vimeo-video", "Teksting fra Vimeo kan ikke hentes.",
                                    entry.url))
            continue
        if entry.kind == "media":
            obj = objects.get(entry.canvas_id)
            if obj is None:
                inv.skipped.append(Skip(key, "media", entry.title or "Video i Canvas", "Fant ikke mediet i emnets "
                                        "medieliste. Det kan tilhøre et annet emne.", entry.url))
                continue
            entry.title = entry.title or str(obj.get("title") or "Video")
            entry.meta.update({"media_type": obj.get("media_type"), "tracks": obj.get("media_tracks") or [],
                               "sources": obj.get("media_sources") or []})
            entry.content_hash = _hash("media", entry.canvas_id, [(t.get("id"), t.get("updated_at"))
                                                                  for t in obj.get("media_tracks") or []])
        entry.title = entry.title or ("YouTube-video" if entry.kind == "youtube" else "Video")
        entry.modules = entry.modules or member.get(key, [])
        inv.items.append(entry)


def _add_images(inv: Inventory, files: dict[str, dict[str, Any]]) -> None:
    """Images on teacher pages (one element per image address; the pages it appears on are its parents)."""
    found: dict[str, SourceItem] = {}
    for parent in list(inv.items):
        if parent.parsed is None:
            continue
        for image in parent.parsed.images:
            key = f"image:{_hash(image.src)[:16]}"
            if key in found:
                found[key].parents.append(parent.key)
                _merge_modules(found[key].modules, parent.modules)
                continue
            name = image.src.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            file = files.get(image.file_id or "") or {}
            file_name = str(file.get("display_name") or file.get("filename") or "")
            found[key] = SourceItem(key, "image", image.file_id or key.split(":", 1)[1], f"Bilde på «{parent.title}»",
                                    parent.url, None, modules=list(parent.modules),
                                    meta={**image.as_dict(), "name": name, "file_name": file_name,
                                          "page_title": parent.title, "page_url": parent.url},
                                    content_hash=_hash(image.src, image.alt, image.context), parents=[parent.key])
    embedded = {item.meta.get("file_id") for item in found.values() if item.meta.get("file_id")}
    inv.items = [i for i in inv.items if not (i.kind == "file" and i.meta.get("category") == "image_file" and
                                              i.canvas_id in embedded)]
    inv.items.extend(found.values())


def media_duration(item: SourceItem) -> float | None:
    """Seconds, from the media source with the most information (size in KB × 8 / bitrate in kbit/s)."""
    for source in item.meta.get("sources") or []:
        try:
            size_kb, bitrate = float(source.get("size") or 0), float(source.get("bitrate") or 0)
        except (TypeError, ValueError):
            continue
        if size_kb and bitrate:
            return size_kb * 8 / bitrate
    return None


def _add_file(inv: Inventory, raw: dict[str, Any], options: SourceOptions, teacher_ids: set[str] | None,
              member: dict[str, list[dict[str, str]]], parents: list[str], base: str, course_id: str,
              parent_modules: list[dict[str, str]] | None = None) -> None:
    fid = str(raw.get("id"))
    key = f"file:{fid}"
    name = str(raw.get("display_name") or raw.get("filename") or "")
    url = f"{base}/courses/{course_id}/files/{fid}"
    fmt = file_format(name, raw.get("content-type"))
    if raw.get("locked") and not options.include_unpublished:
        return
    uploader = raw.get("user")
    if teacher_ids is not None and isinstance(uploader, dict) and uploader.get("id") is not None \
            and str(uploader.get("id")) not in teacher_ids:
        inv.skipped.append(Skip(key, "file", "Fil lastet opp av en som ikke er lærer i emnet",
                                "Bare filer fra lærere tas med."))
        return
    if fmt in LEGACY_FORMATS:
        if options.documents:
            inv.skipped.append(Skip(key, "file", name, f"{LEGACY_FORMATS[fmt]} er et gammelt binærformat som ikke kan "
                                    "leses trygt. Lagre filen som DOCX/PPTX/XLSX eller PDF.", url))
        return
    category = None
    if fmt in DOCUMENT_FORMATS:
        group = group_of(fmt)
        if options.documents and group in options.file_groups:
            category = "document"
    elif fmt in SUBTITLE_FORMATS:
        category = "subtitle" if options.video else None
    elif fmt in IMAGE_FORMATS:
        category = "image_file" if options.images else None
    elif fmt in VIDEO_FORMATS | AUDIO_FORMATS:
        category = "video_file" if options.video else None
    elif (options.documents and options.scope == "course") or (options.documents and parents):
        inv.skipped.append(Skip(key, "file", name, f"Filtypen ({name.rsplit('.', 1)[-1] if '.' in name else 'ukjent'}) "
                                "kan ikke leses.", url))
        return
    if category is None:
        return
    modules = list(member.get(key, []))
    _merge_modules(modules, parent_modules or [])
    inv.items.append(SourceItem(
        key, "file", fid, name, url, raw.get("updated_at") or raw.get("modified_at"), modules=modules,
        meta={"format": fmt, "category": category, "size": raw.get("size"), "content_type": raw.get("content-type"),
              "download_url": raw.get("url"), "media_entry_id": raw.get("media_entry_id")},
        parents=parents))


def group_counts(inv: Inventory) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in inv.items:
        if item.kind == "file":
            category = item.meta.get("category")
            if category == "document":
                group = group_of(item.meta.get("format") or "") or "other"
                counts[f"file_{group}"] = counts.get(f"file_{group}", 0) + 1
            else:
                counts[str(category)] = counts.get(str(category), 0) + 1
        elif not item.meta.get("link_source_only"):
            counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


__all__ = ["FILE_GROUPS", "Inventory", "Skip", "SourceItem", "SourceOptions", "discover", "group_counts"]
