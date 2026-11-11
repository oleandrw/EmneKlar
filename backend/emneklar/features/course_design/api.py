"""Emnedesign: one design for the whole course or one module.

Flow: choose scope → choose design and treatment → preview → approve to the change queue. Nothing is written to Canvas
here: approved proposals are published with «Publiser til Canvas» (conflict check, backup, change log, undo – the
change engine). Only the content field is sent (page body, assignment/quiz description, syllabus), so deadlines,
points, answers, grading rules and submission settings are never part of a design change.

What Canvas allows (docs/CANVAS_API.md, «Emnedesign»):
* pages (incl. the front page and module introductions), assignment descriptions, the syllabus and Classic Quiz
  descriptions are rich-content HTML – formatted with inline styles Canvas keeps;
* New Quizzes keep their instructions in the New Quizzes tool (own API) – not included; quiz questions, answers and
  all of Canvas' own interface (navigation, submit buttons, quiz controls) are never changed.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core import flags
from emneklar.core.ai.base import AIMessage, AIRequest, TextPart
from emneklar.core.ai.untrusted import DATA_RULE, wrap_untrusted_content
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.blueprint import blueprint_info, describe, describe_selection, is_locked
from emneklar.core.canvas.client import CanvasError
from emneklar.core.changes.appliers import HTML_KIND_BY_OBJECT, ChangeData
from emneklar.core.changes.engine import register_describer, register_rebaser
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.security.sanitize import canvas_safe, preview_html
from emneklar.core.storage.models import CourseDesign, CourseDesignExclusion
from emneklar.features.course_design import profiles as profile_mod
from emneklar.features.course_design.transform import (
    ALLOWED_LABELS,
    SECTION_ROLES,
    Plan,
    apply_design,
    describe_blocks,
    detect,
    preservation_problems,
    strip_design,
    validate_plan,
)

router = APIRouter(prefix="/api")
FEATURE = "course_design"
KIND_LABELS = {"front_page": "Forside", "syllabus": "Emneplan", "module_intro": "Modulintroduksjon", "page": "Side",
               "assignment": "Oppgave", "quiz": "Quiz (klassisk)"}
MODE_LABELS = {"keep": "oppbyggingen beholdt", "structure": "ny oppbygging"}
MAX_PREVIEW = 40
SAMPLE_HTML = (
    "<p>I denne modulen ser vi på hvordan tilbakemeldinger kan støtte læring. Les teksten og gjør aktiviteten til "
    "slutt.</p><h2>Læringsmål</h2><ul><li>Forklare forskjellen på vurdering for og av læring</li><li>Gi konkrete "
    "tilbakemeldinger</li></ul><h2>Fagstoff</h2><p>Les <a href=\"https://example.org/artikkel\">artikkelen om "
    "tilbakemeldinger</a> før seminaret. Den viktigste ideen er at tilbakemeldingen skal peke framover.</p>"
    "<table><caption>Fire nivåer av tilbakemelding</caption><thead><tr><th scope=\"col\">Nivå</th><th scope=\"col\">"
    "Eksempel</th></tr></thead><tbody><tr><td>Oppgave</td><td>Svaret er riktig.</td></tr><tr><td>Prosess</td><td>"
    "Prøv å sjekke kildene først.</td></tr></tbody></table><blockquote><p>Tilbakemelding er informasjon om avstanden "
    "mellom der eleven er og der eleven skal.</p></blockquote><h3>Aktivitet</h3><p>Skriv tre tilbakemeldinger til "
    "eksempelteksten og del dem i diskusjonen.</p>")
#: A compact sample for the small example in the first step: a short introduction and one section, styled as
#: «Behold oppbyggingen» (the default treatment) does it.
SAMPLE_COMPACT_HTML = (
    "<p>I denne modulen ser vi på hvordan tilbakemeldinger kan støtte læring.</p><h2>Læringsmål</h2><ul><li>Forklare "
    "forskjellen på vurdering for og av læring</li><li>Gi konkrete tilbakemeldinger</li></ul>"
)
SAMPLE_TITLE = "Uke 3: Tilbakemelding"
SAMPLE_PLAN = {"sections": [{"role": "intro", "label": None, "blocks": ["b1"]},
                            {"role": "goals", "label": None, "blocks": ["b2", "b3"]},
                            {"role": "content", "label": None, "blocks": ["b4", "b5", "b6", "b7"]},
                            {"role": "activity", "label": None, "blocks": ["b8", "b9"]}]}
NOT_INCLUDED = [
    {"label": "Canvas' eget grensesnitt",
     "reason": "Navigasjon, sidetitler, innleveringsknapper, quizkontroller, frister og poeng vises av Canvas og kan "
               "ikke formateres. De endres ikke."},
    {"label": "Quizspørsmål og svar",
     "reason": "Bare innledningen (beskrivelsen) i klassiske quizer formateres. Spørsmål, svaralternativer, fasit, "
               "poeng og innstillinger endres aldri."},
]


def _flag(c: AppContainer) -> None:
    flags.require(c.settings.get(), FEATURE)


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# -- the course's design choice ----------------------------------------------------------------------------------


def saved_design(c: AppContainer, course_id: str) -> dict[str, Any] | None:
    with c.db.session() as session:
        row = session.get(CourseDesign, course_id)
        if row is None:
            return None
        return {"profile_id": row.profile_id, "profile_version": row.profile_version, "mode": row.mode,
                "illustrations": row.illustrations, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def exclusions(c: AppContainer, course_id: str) -> set[str]:
    with c.db.session() as session:
        return set(session.scalars(select(CourseDesignExclusion.item_key)
                                   .where(CourseDesignExclusion.course_id == course_id)).all())


class DesignChoice(BaseModel):
    profile_id: str = Field(max_length=40)
    mode: Literal["keep", "structure"] = "keep"
    illustrations: bool = False


@router.get("/course-design/profiles")
async def list_profiles(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """The four profiles with the same sample content – as it looks with the structure kept and with sections."""
    _flag(c)
    base = c.settings.get().canvas.base_url
    blocks = describe_blocks(SAMPLE_HTML)
    plan = validate_plan(SAMPLE_PLAN, blocks)
    out = []
    for p in profile_mod.profiles():
        keep = apply_design(SAMPLE_HTML, p, kind="module_intro").html
        structured = apply_design(SAMPLE_HTML, p, kind="module_intro", plan=plan).html
        compact = apply_design(SAMPLE_COMPACT_HTML, p, kind="module_intro").html
        out.append({**p.public(), "sample_keep": preview_html(keep, base),
                    "sample_structure": preview_html(structured, base),
                    # The top of a page: Canvas shows the page title itself; the body is what the design produces.
                    "sample_title": SAMPLE_TITLE, "sample_compact": preview_html(compact, base)})
    return {"profiles": out, "default": profile_mod.default_profile().id, "labels": sorted(ALLOWED_LABELS),
            "roles": list(SECTION_ROLES)}


@router.get("/courses/{course_id}/course-design")
async def get_design(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    return {"design": saved_design(c, course_id), "excluded": sorted(exclusions(c, course_id))}


@router.put("/courses/{course_id}/course-design")
async def save_design(course_id: str, body: DesignChoice, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Store the profile (and its version) as the course's design. No content is changed."""
    _flag(c)
    course_id = require_course_id(course_id)
    profile = profile_mod.get(body.profile_id)
    with c.db.session() as session:
        row = session.get(CourseDesign, course_id)
        if row is None:
            row = CourseDesign(course_id=course_id, profile_id=profile.id, profile_version=profile.version)
            session.add(row)
        row.profile_id, row.profile_version, row.mode, row.illustrations = (
            profile.id, profile.version, body.mode, body.illustrations)
    return {"design": saved_design(c, course_id)}


class Exclusion(BaseModel):
    excluded: bool


@router.put("/courses/{course_id}/course-design/items/{item_key}/exclusion")
async def set_exclusion(course_id: str, item_key: str, body: Exclusion,
                        c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Behold eksisterende design» – the course design is not proposed for this item until it is included again."""
    _flag(c)
    course_id = require_course_id(course_id)
    _split_key(item_key)
    with c.db.session() as session:
        row = session.get(CourseDesignExclusion, (course_id, item_key))
        if body.excluded and row is None:
            session.add(CourseDesignExclusion(course_id=course_id, item_key=item_key))
        elif not body.excluded and row is not None:
            session.delete(row)
    return {"item_key": item_key, "excluded": body.excluded}


# -- inventory ---------------------------------------------------------------------------------------------------


def _split_key(key: str) -> tuple[str, str]:
    object_type, _, object_id = key.partition(":")
    if object_type not in ("page", "assignment", "quiz", "syllabus") or not object_id or len(key) > 200:
        raise AppError("validation_error", status=422, detail=f"Ukjent innholdselement: {key}")
    return object_type, object_id


async def _course(api: CanvasAPI, course_id: str) -> dict[str, Any]:
    return await api.get_course(course_id, include=("syllabus_body", "term"))


def _course_text(course: dict[str, Any]) -> tuple[str, str]:
    name = str(course.get("name") or "")
    sub = " · ".join(x for x in (str(course.get("course_code") or ""), str((course.get("term") or {}).get("name") or ""))
                     if x and x != name)
    return name, sub


async def inventory(c: AppContainer, course_id: str, module_id: str | None) -> dict[str, Any]:
    """What a design can be applied to in the scope (the whole course or one module), and what is left out and why."""
    api = CanvasAPI(c.canvas())
    modules, pages, assignments, quizzes, course = await asyncio.gather(
        api.list_modules(course_id), api.list_pages(course_id, include_body=True), api.list_assignments(course_id),
        api.list_quizzes(course_id), _course(api, course_id))
    if module_id and not any(str(m.get("id")) == module_id for m in modules):
        raise AppError("not_found", status=404, detail="Fant ikke modulen")
    excluded = exclusions(c, course_id)
    member: dict[str, list[str]] = {}
    intro_pages: set[str] = set()
    module_keys: dict[str, set[str]] = {}
    module_totals: dict[str, int] = {}
    # Left out, unique per content (a file in two modules is one file): label → identities.
    left_out: dict[str, set[str]] = {}
    for module in modules:
        pages_seen = False
        for item in module.get("items") or []:
            if str(item.get("type") or "") != "SubHeader":
                module_totals[str(module.get("id"))] = module_totals.get(str(module.get("id")), 0) + 1
            itype = str(item.get("type") or "")
            key = None
            if itype == "Page":
                key = f"page:{item.get('page_url')}"
                if not pages_seen:
                    intro_pages.add(key)
                    pages_seen = True
            elif itype == "Assignment":
                key = f"assignment:{item.get('content_id')}"
            elif itype == "Quiz":
                key = f"quiz:{item.get('content_id')}"
            elif str(module.get("id")) == module_id or module_id is None:
                label = {"Discussion": "Diskusjoner", "ExternalTool": "Eksterne verktøy", "ExternalUrl": "Nettadresser",
                         "File": "Filer", "SubHeader": "Tekstoverskrifter i moduler"}.get(itype)
                if label:
                    identity = str(item.get("content_id") or item.get("external_url") or item.get("id"))
                    left_out.setdefault(label, set()).add(f"{itype}:{identity}")
            if key:
                member.setdefault(key, []).append(str(module.get("name") or ""))
                module_keys.setdefault(str(module.get("id")), set()).add(key)
    every: list[dict[str, Any]] = []  # everything a design can be applied to in the course (counts per module)

    def add(key: str, object_type: str, object_id: str, title: str, kind: str, body: str, raw: dict[str, Any]) -> None:
        mods = member.get(key, [])
        every.append({"key": key, "object_type": object_type, "object_id": object_id, "title": title, "kind": kind,
                      "kind_label": KIND_LABELS[kind], "modules": mods, "shared": len(mods) > 1,
                      "locked": is_locked(raw), "published": raw.get("published"), "design": detect(body),
                      "empty": not strip_design(body).strip(), "excluded": key in excluded,
                      "url": raw.get("html_url")})

    for page in pages:
        key = f"page:{page.get('url')}"
        kind = "front_page" if page.get("front_page") else "module_intro" if key in intro_pages else "page"
        add(key, "page", str(page.get("url")), str(page.get("title") or ""), kind, str(page.get("body") or ""), page)
    in_scope = module_keys.get(module_id or "", set()) if module_id else None
    new_quizzes = 0
    for a in assignments:
        if a.get("is_quiz_lti_assignment"):
            new_quizzes += in_scope is None or f"assignment:{a.get('id')}" in in_scope
            continue
        if a.get("is_quiz_assignment") or a.get("quiz_id") or a.get("discussion_topic") or \
                "discussion_topic" in (a.get("submission_types") or []):
            continue  # the quiz or discussion itself holds the text (a classic quiz is listed as a quiz)
        add(f"assignment:{a.get('id')}", "assignment", str(a.get("id")), str(a.get("name") or ""), "assignment",
            str(a.get("description") or ""), a)
    for q in quizzes:
        add(f"quiz:{q.get('id')}", "quiz", str(q.get("id")), str(q.get("title") or ""), "quiz",
            str(q.get("description") or ""), q)
    if module_id is None:
        add(f"syllabus:{course_id}", "syllabus", course_id, "Emneplan", "syllabus", str(course.get("syllabus_body") or ""),
            {"published": True, "html_url": None})
    order = {"front_page": 0, "syllabus": 1, "module_intro": 2, "page": 3, "assignment": 4, "quiz": 5}
    items = [i for i in every if in_scope is None or i["key"] in in_scope]
    items.sort(key=lambda i: (order[i["kind"]], i["title"].lower()))
    supported = {i["key"] for i in every}
    not_included = list(NOT_INCLUDED)
    if new_quizzes:
        not_included.insert(0, {"label": f"New Quizzes ({new_quizzes})",
                                "reason": "Instruksjonene i New Quizzes ligger i New Quizzes-verktøyet og har et eget API "
                                          "som EmneKlar ikke bruker. De endres ikke."})
    for label, ids in sorted(left_out.items()):
        count = len(ids)
        reason = ("Diskusjoner er ikke med i Emnedesign; innleggene vises i Canvas' diskusjonsvisning."
                  if label == "Diskusjoner" else "Har ikke innhold EmneKlar kan formatere.")
        not_included.append({"label": f"{label} ({count})", "reason": reason})
    try:
        info = await blueprint_info(api, course_id)
    except CanvasError:
        info = {}
    ready = [i for i in items if not i["empty"] and not i["excluded"]]
    # Per module, in Canvas' order: «count» = content a design can be applied to (pages, assignments, classic
    # quizzes), «total» = everything in the module except text headers (files, links … included).
    return {"modules": [{"id": str(m.get("id")), "name": m.get("name"), "position": index,
                         "published": m.get("published"),
                         "count": len(module_keys.get(str(m.get("id")), set()) & supported),
                         "total": module_totals.get(str(m.get("id")), 0)} for index, m in enumerate(modules, start=1)],
            "items": items,
            "not_included": not_included, "where": describe(info),
            "blueprint": describe_selection(info, total=len(ready), locked=sum(1 for i in ready if i["locked"])),
            "course": {"name": course.get("name")}}


@router.get("/courses/{course_id}/course-design/inventory")
async def get_inventory(course_id: str, module_id: str | None = None,
                        c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    return await inventory(c, require_course_id(course_id), module_id or None)


# -- preview and approval ----------------------------------------------------------------------------------------


def _change_data(course_id: str, object_type: str, object_id: str) -> tuple[Any, ChangeData]:
    applier = HTML_KIND_BY_OBJECT[object_type]()
    return applier, ChangeData(0, course_id, applier.kind, {"object_type": object_type, "object_id": object_id},
                               {}, {})


async def _live(api: CanvasAPI, course_id: str, key: str) -> tuple[Any, str, dict[str, Any]]:
    object_type, object_id = _split_key(key)
    applier, data = _change_data(course_id, object_type, object_id)
    current = await applier.current(api, data)
    return applier, str(current.get(applier.field) or ""), current


def _plan(raw: dict[str, Any] | None, html: str) -> Plan | None:
    return validate_plan(raw, describe_blocks(html)) if raw else None


def build(html: str, profile: profile_mod.Profile, *, kind: str, course: tuple[str, str],
          plan_raw: dict[str, Any] | None) -> dict[str, Any]:
    plan = _plan(plan_raw, html)
    result = apply_design(html, profile, kind=kind, course_name=course[0], course_sub=course[1], plan=plan)
    problems = preservation_problems(html, result.html, structure=plan is not None)
    _, canvas_warnings = canvas_safe(result.html)
    return {"html": result.html, "notes": result.notes + canvas_warnings, "structure_changes": result.structure_changes,
            "problems": problems, "unchanged": result.html == html}


class PreviewRequest(BaseModel):
    profile_id: str = Field(max_length=40)
    items: list[str] = Field(max_length=MAX_PREVIEW)
    kinds: dict[str, str] = Field(default_factory=dict)  # item key → content kind (from the inventory)
    plans: dict[str, dict[str, Any]] = Field(default_factory=dict)  # item key → accepted structure plan


@router.post("/courses/{course_id}/course-design/preview")
async def preview(course_id: str, body: PreviewRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Before and after for each item, read live from Canvas (read-only), with what changes and what is kept."""
    _flag(c)
    course_id = require_course_id(course_id)
    profile = profile_mod.get(body.profile_id)
    api = CanvasAPI(c.canvas())
    base = c.settings.get().canvas.base_url
    course = _course_text(await _course(api, course_id))
    limit = asyncio.Semaphore(4)

    async def one(key: str) -> dict[str, Any]:
        async with limit:
            try:
                _, html, _ = await _live(api, course_id, key)
            except CanvasError as exc:
                return {"key": key, "error": exc.message}
        kind = body.kinds.get(key) or key.split(":", 1)[0]
        try:
            built = build(html, profile, kind=kind if kind in KIND_LABELS else "page", course=course,
                          plan_raw=body.plans.get(key))
        except AppError as exc:
            return {"key": key, "error": exc.message}
        return {"key": key, "content_hash": _hash(html), "before": preview_html(html, base),
                "after": preview_html(built["html"], base), "notes": built["notes"],
                "structure_changes": built["structure_changes"], "problems": built["problems"],
                "unchanged": built["unchanged"], "structured": key in body.plans}

    return {"profile": profile.public(), "items": await asyncio.gather(*(one(k) for k in body.items))}


STRUCTURE_SYSTEM = (
    "Du foreslår en tydeligere oppbygging av én side i et Canvas-emne. Du får sidens blokker (id, type og et kort "
    "utdrag). " + DATA_RULE + "\n"
    "Regler: Bruk hver blokk-id nøyaktig én gang. Ikke skriv nytt innhold, og ikke finn på læringsmål, kriterier eller "
    "fagstoff. Seksjonstyper: intro, goals, content, example, activity, resources, summary. Bruk «goals» bare når "
    "blokkene allerede inneholder læringsmål, «example» bare for eksempler og «activity» bare for oppgaver eller "
    "aktiviteter. «label» er en kort seksjonsoverskrift og må være en av: " + ", ".join(sorted(ALLOWED_LABELS)) +
    " – eller null. Bruk null når seksjonen starter med en eksisterende overskrift. Behold rekkefølgen med mindre en "
    "flytting gjør siden tydeligere for studentene. Ikke lag tomme seksjoner. Skriv i «note» kort (norsk) hvorfor.")
STRUCTURE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["sections", "note"],
    "properties": {
        "note": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["role", "label", "blocks"],
            "properties": {"role": {"type": "string", "enum": list(SECTION_ROLES)},
                           "label": {"type": ["string", "null"]},
                           "blocks": {"type": "array", "items": {"type": "string"}}}}}},
}


def _structure_input(title: str, blocks: list[dict[str, str]]) -> str:
    lines = [f"{b['id']} [{b['tag']}]: {b['text']}" for b in blocks]
    return f"Side: {title}\n" + wrap_untrusted_content("Sidens blokker", "\n".join(lines), scrub=True)


class StructureRequest(BaseModel):
    item: str = Field(max_length=200)
    title: str = Field(default="", max_length=300)
    confirmed: bool = False


@router.post("/courses/{course_id}/course-design/structure/prepare")
async def prepare_structure(course_id: str, body: StructureRequest,
                            c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """What would be sent to the AI provider for a structure suggestion – shown before anything is sent."""
    _flag(c)
    course_id = require_course_id(course_id)
    _, html, _ = await _live(CanvasAPI(c.canvas()), course_id, body.item)
    blocks = describe_blocks(html)
    summary = (f"Type og et kort utdrag (inntil 280 tegn) fra hver av de {len(blocks)} delene av «{body.title}» sendes "
               "til KI-leverandøren. Ingen studentdata sendes. KI-en foreslår bare plassering og faste "
               "seksjonsoverskrifter – den skriver ikke nytt innhold.")
    return c.ai.plan("course_design_structure", input_chars=len(_structure_input(body.title, blocks)), images=0,
                     summary=summary)


@router.post("/courses/{course_id}/course-design/structure")
async def suggest_structure(course_id: str, body: StructureRequest,
                            c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Foreslå bedre oppbygging»: a validated plan for one item (KI-forslag – må vurderes)."""
    _flag(c)
    course_id = require_course_id(course_id)
    _, html, _ = await _live(CanvasAPI(c.canvas()), course_id, body.item)
    blocks = describe_blocks(html)
    if len(blocks) < 2:
        raise AppError("validation_error", status=422, message="Innholdet er for kort til å deles i seksjoner.")
    prompt = _structure_input(body.title, blocks)

    def request(model: str) -> AIRequest:
        return AIRequest(model=model, system=STRUCTURE_SYSTEM, schema_name="oppbygging", json_schema=STRUCTURE_SCHEMA,
                         max_output_tokens=1500, messages=[AIMessage(parts=[TextPart(text=prompt)])])

    result, _ = await c.ai.run("course_design_structure", request, input_chars=len(prompt),
                               summary=f"Deler og korte utdrag fra «{body.title}»", confirmed=body.confirmed,
                               course_id=course_id)
    raw = result.data or {}
    plan = validate_plan(raw, blocks)  # refuses anything that drops, repeats or invents content
    return {"item": body.item, "plan": {"sections": plan.sections}, "note": str(raw.get("note") or "")[:600],
            "content_hash": _hash(html)}


class ApproveItem(BaseModel):
    key: str = Field(max_length=200)
    content_hash: str = Field(max_length=64)
    kind: str = Field(default="page", max_length=20)
    title: str = Field(default="", max_length=300)
    plan: dict[str, Any] | None = None


class ApproveRequest(BaseModel):
    profile_id: str = Field(max_length=40)
    items: list[ApproveItem] = Field(max_length=500)


def _source(profile: profile_mod.Profile, item: ApproveItem, course: tuple[str, str]) -> dict[str, Any]:
    mode = "structure" if item.plan else "keep"
    return {"feature": FEATURE, "rebase": FEATURE, "profile": profile.ref,
            "fixes": [{"profile_id": profile.id, "profile_version": profile.version, "mode": mode, "kind": item.kind,
                       "course_name": course[0], "course_sub": course[1], "plan": item.plan}]}


@router.post("/courses/{course_id}/course-design/approve")
async def approve(course_id: str, body: ApproveRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Approve the previewed proposals to the change queue (one change per item). An item whose content changed in
    Canvas after the preview is not queued – preview it again so newer work is never overwritten unnoticed."""
    _flag(c)
    course_id = require_course_id(course_id)
    profile = profile_mod.get(body.profile_id)
    api = CanvasAPI(c.canvas())
    course = _course_text(await _course(api, course_id))
    results = []
    for item in body.items:
        try:
            applier, html, _current = await _live(api, course_id, item.key)
        except CanvasError as exc:
            results.append({"key": item.key, "status": "error", "message": exc.message})
            continue
        if _hash(html) != item.content_hash:
            results.append({"key": item.key, "status": "changed",
                            "message": "Innholdet er endret i Canvas etter forhåndsvisningen. Forhåndsvis på nytt."})
            continue
        try:
            built = build(html, profile, kind=item.kind if item.kind in KIND_LABELS else "page", course=course,
                          plan_raw=item.plan)
        except AppError as exc:
            results.append({"key": item.key, "status": "refused", "message": exc.message})
            continue
        if built["problems"]:
            results.append({"key": item.key, "status": "refused",
                            "message": "Forslaget er stoppet fordi det ville endret " + ", ".join(built["problems"]) + "."})
            continue
        if built["unchanged"]:
            results.append({"key": item.key, "status": "unchanged", "message": "Har allerede dette designet."})
            continue
        object_type, object_id = _split_key(item.key)
        mode = "structure" if item.plan else "keep"
        change = c.changes.stage(
            course_id=course_id, domain=FEATURE, kind=applier.kind,
            title=f"{item.title or object_id}: emnedesign",
            target={"object_type": object_type, "object_id": object_id, "title": item.title or object_id},
            before={applier.field: html}, proposed={applier.field: built["html"]},
            rationale=(f"Emnedesign «{profile.label}» ({MODE_LABELS[mode]}). Faginnhold, lenker, bilder, innebygd innhold "
                       "og innstillinger er beholdt." + (" Ny oppbygging: " + "; ".join(built["structure_changes"])
                                                         if built["structure_changes"] else "")),
            risk="medium" if mode == "structure" else "low", source=_source(profile, item, course),
            ai_generated=mode == "structure", merge=True)
        c.changes.approve([change["id"]])
        results.append({"key": item.key, "status": "approved", "change_id": change["id"]})
    return {"results": results}


# -- change engine hooks -----------------------------------------------------------------------------------------


def rebase(data: ChangeData, source: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    """«Lag forslaget på nytt» after a conflict: the style is applied again to the live content. A suggested structure
    belongs to the old content and cannot be rebuilt – it must be suggested again."""
    recipe = (source.get("fixes") or [{}])[0]
    if recipe.get("mode") != "keep":
        return None
    applier = HTML_KIND_BY_OBJECT.get(str(data.target.get("object_type")))
    if applier is None or not isinstance(current.get(applier.field), str):
        return None
    try:
        profile = profile_mod.get(str(recipe.get("profile_id")))
    except AppError:
        return None
    html = str(current[applier.field])
    result = apply_design(html, profile, kind=str(recipe.get("kind") or "page"),
                          course_name=recipe.get("course_name"), course_sub=recipe.get("course_sub"))
    if preservation_problems(html, result.html, structure=False):
        return None
    return {applier.field: result.html}


def describe_change(source: dict[str, Any]) -> list[str]:
    labels = []
    for recipe in source.get("fixes") or []:
        try:
            label = profile_mod.get(str(recipe.get("profile_id"))).label
        except AppError:
            label = str(recipe.get("profile_id"))
        labels.append(f"Emnedesign «{label}» brukt" + (" med ny oppbygging" if recipe.get("mode") == "structure" else ""))
    return labels


register_rebaser(FEATURE, rebase)
register_describer(FEATURE, describe_change)
