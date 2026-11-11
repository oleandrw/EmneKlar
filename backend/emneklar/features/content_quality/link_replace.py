"""«Endre lenke» and «Endre flere steder» in the link overview: a new address for the places the teacher picks.

Only the address changes – the link text, images inside the link and the other attributes stay – unless the teacher
explicitly also gives a new link text. Nothing changes on its own: the teacher picks the places, previews the change and
approves it to the change queue, where publishing does the usual conflict check, backup and change log. A queued change
is rebuilt on newer content from Canvas with the same recipe (``rebase = "link_replace"``). Within one content item,
every link with the old address is changed (the overview shows how many).
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.canvas.html import parse_html
from emneklar.core.canvas.html_edit import EditPlan, escape_text
from emneklar.core.changes.appliers import HTML_KIND_BY_OBJECT, ChangeData
from emneklar.core.changes.engine import register_describer, register_rebaser
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.features.accessibility.fixes import HTML_FIELD, MEDIA_IN_LINK, display, live_html, open_change_for, where_info
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")
REBASE = "link_replace"


def _same(href: str, old: str) -> bool:
    return href.strip().split("#")[0] == old.strip().split("#")[0]


def valid_url(url: str) -> str:
    value = (url or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or any(c in value for c in " \t\r\n\"<>"):
        raise AppError("validation_error", message="Skriv en hel adresse som begynner med https:// (eller http://).")
    return value


def replace_links(html: str, old: str, new: str, text: str | None = None) -> tuple[str, int, list[dict[str, str]]]:
    """Every link (and embed) in ``html`` with the address ``old`` gets ``new``; ``text`` (when given) replaces the
    visible link text – or becomes the accessible name when the link holds an image or media, which is kept."""
    soup = parse_html(html)
    plan = EditPlan(html)
    count = 0
    for a in soup.find_all("a", href=True):
        if not _same(str(a.get("href")), old):
            continue
        count += 1
        if text and a.find(MEDIA_IN_LINK):
            plan.set_attrs(soup, a, {"href": new, "aria-label": text})
        elif text:
            plan.set_attrs_and_inner(soup, a, {"href": new}, escape_text(text))
        else:
            plan.set_attrs(soup, a, {"href": new})
    for frame in soup.find_all("iframe", src=True):
        if _same(str(frame.get("src")), old):
            count += 1
            plan.set_attrs(soup, frame, {"src": new})
    if not count:
        return html, 0, []
    return plan.apply(), count, plan.changes()


class Place(BaseModel):
    object_type: Literal["page", "assignment", "discussion", "quiz", "syllabus"]
    object_id: str = Field(min_length=1, max_length=300)
    title: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _plain_id(self) -> Place:
        pattern = r"[^/\\?#\s]+" if self.object_type == "page" else r"\d{1,20}"
        if not re.fullmatch(pattern, self.object_id) or self.object_id in (".", ".."):
            raise ValueError("Ugyldig ID for innholdet.")
        return self


class ReplaceBody(BaseModel):
    old_url: str = Field(min_length=1, max_length=2000)
    new_url: str = Field(min_length=1, max_length=2000)
    #: A new link text – only when the teacher chose to change it too.
    link_text: str | None = Field(default=None, max_length=200)
    places: list[Place] = Field(min_length=1, max_length=200)
    #: The address and/or the text come from a KI-forslag the teacher reviewed (the change is marked as KI-generated).
    ai_suggestion: bool = False


async def _base(c: AppContainer, course_id: str, place: Place) -> tuple[str, str, dict[str, Any], Any]:
    kind = HTML_KIND_BY_OBJECT[place.object_type].kind
    field = HTML_FIELD[place.object_type]
    existing = open_change_for(c, course_id, kind, place.object_id)
    if existing is not None and existing.status == "conflict":
        existing = None
    live = await live_html(c, course_id, place.object_type, place.object_id)
    if existing is not None:
        return kind, existing.proposed.get(field) or "", existing.before, existing
    return kind, live, {field: live}, None


async def _build(c: AppContainer, course_id: str, body: ReplaceBody) -> list[dict[str, Any]]:
    new = valid_url(body.new_url)
    if _same(new, body.old_url):
        raise AppError("validation_error", message="Den nye adressen er den samme som den gamle.")
    text = (body.link_text or "").strip() or None
    out = []
    for place in body.places:
        kind, base, before, existing = await _base(c, course_id, place)
        html, count, changes = replace_links(base, body.old_url, new, text)
        out.append({"place": place, "kind": kind, "field": HTML_FIELD[place.object_type], "before": before,
                    "after": html, "count": count, "existing": existing,
                    "changes": [{"before": display(ch.get("before", ""))[:2000],
                                 "after": display(ch.get("after", ""))[:2000]} for ch in changes[:20]],
                    "message": None if count else "Fant ikke lenken i innholdet slik det er i Canvas nå."})
    return out


def _public(item: dict[str, Any]) -> dict[str, Any]:
    place: Place = item["place"]
    return {"object_type": place.object_type, "object_id": place.object_id, "title": place.title, "count": item["count"],
            "changes": item["changes"], "message": item["message"]}


@router.post("/courses/{course_id}/links/replace/preview")
async def preview(course_id: str, body: ReplaceBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    built = await _build(c, course_id, body)
    return {"places": [_public(i) for i in built], "where": await where_info(c, course_id, None)}


@router.post("/courses/{course_id}/links/replace/approve")
async def approve(course_id: str, body: ReplaceBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Stage and approve one change per chosen place (nothing is published here)."""
    course_id = require_course_id(course_id)
    built = await _build(c, course_id, body)
    new = valid_url(body.new_url)
    text = (body.link_text or "").strip() or None
    current, _ = FindingStore(c.db).current(course_id, "content_quality")
    staged: list[int] = []
    skipped: list[dict[str, Any]] = []
    for item in built:
        place: Place = item["place"]
        if not item["count"]:
            skipped.append(_public(item))
            continue
        fingerprints = [f.fingerprint for f in current
                        if f.object_type == place.object_type and f.object_id == place.object_id
                        and _same(str((f.evidence or {}).get("href") or ""), body.old_url)]
        rationale = f"Ny adresse for lenken: {body.old_url} → {new}" + (f", ny lenketekst «{text}»" if text else "")
        change = c.changes.stage(
            course_id=course_id, domain="content_quality", kind=item["kind"],
            title=f"{place.title or place.object_id}: lenke endret",
            target={"object_type": place.object_type, "object_id": place.object_id, "title": place.title},
            before=item["before"], proposed={item["field"]: item["after"]},
            rationale=rationale + (" (KI-forslag, vurdert av læreren)" if body.ai_suggestion else ""), risk="low",
            ai_generated=body.ai_suggestion, editable=False, merge=True, layered=item["existing"] is not None,
            source={"feature": "link_replace", "rebase": REBASE, "finding_fingerprints": fingerprints,
                    "fixes": [{"old": body.old_url, "new": new, "text": text}]})
        staged.append(int(change["id"]))
    approved = c.changes.approve(staged) if staged else []
    return {"approved": [row["id"] for row in approved], "skipped": skipped}


def rebase(data: ChangeData, source: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    """The same new address on newer content from Canvas (for the conflict check at publishing)."""
    field = next(iter(data.proposed), None)
    if field is None or field not in current:
        return None
    html = str(current.get(field) or "")
    for recipe in source.get("fixes") or []:
        html, _, _ = replace_links(html, str(recipe.get("old") or ""), str(recipe.get("new") or ""), recipe.get("text"))
    return {field: html}


def describe_change(source: dict[str, Any]) -> list[str]:
    return [f"Lenke endret til {urlsplit(str(r.get('new') or '')).hostname or r.get('new')}"
            for r in source.get("fixes") or []]


register_rebaser(REBASE, rebase)
register_describer(REBASE, describe_change)
