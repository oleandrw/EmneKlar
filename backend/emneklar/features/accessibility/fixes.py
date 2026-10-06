"""Quick fixes for accessibility findings → previewable, staged page changes.

A fix never writes to Canvas. It transforms the *current* HTML of the object
(fetched live from Canvas, or the proposal already in the change set so that
several fixes to one page merge into one change) and returns before/after for
the diff and preview. Staging goes through the shared change engine.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.dammit import EntitySubstitution
from bs4.formatter import HTMLFormatter
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.html import find_by_path, norm_text, parse_html, text_of
from emneklar.core.changes.appliers import HTML_KIND_BY_OBJECT
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.security.sanitize import preview_html
from emneklar.core.storage.models import Finding, StagedChange
from emneklar.features.accessibility.checks.base import element_signature
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")

LOW_RISK = {"set_alt", "set_iframe_title", "set_lang", "set_link_text", "remove_autoplay", "table_caption",
            "table_scope"}
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
MARKER = re.compile(r"^\s*([-–—•*·▪◦●]|\d{1,2}[.)]|[a-zA-Z][.)])\s+")
BLOCK_TAGS = r"(p|h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|div|figure|figcaption|iframe|blockquote|section|caption)"


class FixParams(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    decorative: bool = False
    level: int | None = Field(default=None, ge=2, le=6)
    lang: str | None = Field(default=None, max_length=20)


# ----------------------------------------------------------------------------------- helpers


# Keeps æøå and other characters as-is, writes <br> (not <br/>) and keeps alt="" explicit.
CANVAS_FORMATTER = HTMLFormatter(entity_substitution=EntitySubstitution.substitute_xml,
                                 void_element_close_prefix=None, empty_attributes_are_booleans=False)


def serialize(soup: BeautifulSoup) -> str:
    return soup.decode(formatter=CANVAS_FORMATTER)


def display(html: str) -> str:
    """Line-broken HTML for the diff view only (never sent to Canvas)."""
    text = re.sub(rf"(?i)(<{BLOCK_TAGS}\b)", r"\n\1", html)
    text = re.sub(rf"(?i)(</{BLOCK_TAGS}>)", r"\1\n", text)
    return "\n".join(line for line in (ln.rstrip() for ln in text.split("\n")) if line.strip())


def locate(soup: BeautifulSoup, location: dict[str, Any], path: str | None = None) -> Tag:
    path = path or location.get("selector")
    sig = location.get("sig")
    el = find_by_path(soup, path) if path else None
    if el is not None and (not sig or element_signature(el) == sig):
        return el
    if sig:
        matches = [e for e in soup.find_all(True) if element_signature(e) == sig]
        if len(matches) == 1:
            return matches[0]
    raise AppError("conflict", status=409, message="Fant ikke elementet i det nåværende innholdet. "
                   "Innholdet kan være endret – kjør en ny analyse.")


def _require_text(params: FixParams, what: str, max_len: int = 500) -> str:
    text = norm_text(params.text or "")
    if not text:
        raise AppError("validation_error", message=f"Skriv inn {what}.")
    if len(text) > max_len:
        raise AppError("validation_error", message=f"Teksten er for lang (maks {max_len} tegn).")
    return text


# ------------------------------------------------------------------------------- transforms


def transform(html: str, finding: Finding, params: FixParams) -> str:
    fix = finding.fix or {}
    ftype = fix.get("type")
    fparams = fix.get("params") or {}
    soup = parse_html(html)
    location = finding.location or {}

    if ftype == "demote_headings":
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5"])
        if soup.find("h6"):
            raise AppError("validation_error", message="Siden har overskrifter på nivå 6 og kan ikke senkes automatisk.")
        for h in headings:
            h.name = f"h{int(h.name[1]) + 1}"
        return serialize(soup)

    if ftype == "convert_fake_list":
        paths = list(fparams.get("paths") or [])
        first = locate(soup, location, paths[0] if paths else None)
        elements = [first] + [find_by_path(soup, p) for p in paths[1:]]
        if any(e is None for e in elements):
            raise AppError("conflict", status=409, message="Fant ikke alle listepunktene. Kjør en ny analyse.")
        lst = soup.new_tag("ol" if fparams.get("ordered") else "ul")
        if fparams.get("mode") == "br":
            fragments: list[list[Any]] = [[]]
            for child in list(first.children):
                if isinstance(child, Tag) and child.name == "br":
                    fragments.append([])
                else:
                    fragments[-1].append(child)
            for fragment in fragments:
                li = soup.new_tag("li")
                for node in fragment:
                    li.append(node.extract())
                _strip_marker(li)
                if text_of(li):
                    lst.append(li)
        else:
            for p in elements:
                li = soup.new_tag("li")
                for node in list(p.children):  # type: ignore[union-attr]
                    li.append(node.extract())
                _strip_marker(li)
                lst.append(li)
        first.replace_with(lst)
        for extra in elements[1:]:
            extra.decompose()  # type: ignore[union-attr]
        return serialize(soup)

    el = locate(soup, location)
    if ftype == "set_alt":
        if params.decorative:
            el["alt"] = ""
            el["role"] = "presentation"
        else:
            el["alt"] = _require_text(params, "en alternativ tekst")
            if el.get("role") in ("presentation", "none"):
                del el["role"]
    elif ftype == "set_link_text":
        text = _require_text(params, "lenketekst", 200)
        for child in list(el.children):
            child.extract()
        el.append(NavigableString(text))
    elif ftype == "set_iframe_title":
        el["title"] = _require_text(params, "en tittel", 200)
    elif ftype == "remove_element":
        el.decompose()
    elif ftype == "unwrap_element":
        el.unwrap()
    elif ftype == "change_heading_level":
        el.name = f"h{params.level or int(fparams.get('level') or 2)}"
    elif ftype == "convert_to_heading":
        level = params.level or int(fparams.get("level") or 2)
        heading = soup.new_tag(f"h{level}")
        heading.string = text_of(el)
        el.replace_with(heading)
    elif ftype == "table_headers":
        rows = [tr for tr in el.find_all("tr") if tr.find_parent("table") is el]
        if not rows:
            raise AppError("validation_error", message="Tabellen har ingen rader.")
        first_row = rows[0]
        for cell in first_row.find_all(["td", "th"], recursive=False):
            cell.name = "th"
            cell["scope"] = "col"
        if first_row.parent is not None and first_row.parent.name != "thead":
            thead = soup.new_tag("thead")
            first_row.insert_before(thead)
            thead.append(first_row.extract())
    elif ftype == "table_scope":
        rows = [tr for tr in el.find_all("tr") if tr.find_parent("table") is el]
        for index, tr in enumerate(rows):
            for c_index, cell in enumerate(tr.find_all("th", recursive=False)):
                if not cell.get("scope"):
                    cell["scope"] = "col" if index == 0 else ("row" if c_index == 0 else "col")
    elif ftype == "table_caption":
        caption = soup.new_tag("caption")
        caption.string = _require_text(params, "en tabelltittel", 200)
        existing = el.find("caption")
        if existing:
            existing.replace_with(caption)
        else:
            el.insert(0, caption)
    elif ftype == "fix_list_nesting":
        for child in list(el.children):
            if isinstance(child, Tag) and child.name not in ("li", "script", "template"):
                previous = child.find_previous_sibling("li")
                if previous is not None:
                    previous.append(child.extract())
                else:
                    li = soup.new_tag("li")
                    child.wrap(li)
    elif ftype == "set_lang":
        lang = (params.lang or fparams.get("lang") or "").strip()
        if not LANG_RE.match(lang):
            raise AppError("validation_error", message="Ugyldig språkkode (bruk for eksempel en, nb, nn eller se).")
        el["lang"] = lang
    elif ftype == "remove_autoplay":
        if el.has_attr("autoplay"):
            del el["autoplay"]
        src = str(el.get("src") or "")
        if src:
            parts = urlsplit(src)
            query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "autoplay"]
            el["src"] = urlunsplit(parts._replace(query=urlencode(query)))
    elif ftype == "remove_underline":
        if el.name == "u":
            el.unwrap()
        else:
            style = ";".join(p for p in str(el.get("style") or "").split(";")
                             if p.strip() and not p.strip().lower().startswith("text-decoration"))
            if style:
                el["style"] = style
            else:
                del el["style"]
    else:
        raise AppError("unsupported", message="Denne rettingen kan ikke gjøres automatisk.")
    return serialize(soup)


def _strip_marker(li: Tag) -> None:
    for node in li.descendants:
        if isinstance(node, NavigableString) and node.strip():
            node.replace_with(MARKER.sub("", str(node), count=1))
            return


# ------------------------------------------------------------------------------------- API

HTML_FIELD = {"page": "body", "assignment": "description", "discussion": "message", "quiz": "description",
              "syllabus": "syllabus_body"}


async def live_html(c: AppContainer, course_id: str, object_type: str, object_id: str) -> str:
    api = CanvasAPI(c.canvas())
    if object_type == "page":
        return (await api.get_page(course_id, object_id)).get("body") or ""
    if object_type == "assignment":
        return (await api.get_assignment(course_id, object_id)).get("description") or ""
    if object_type == "discussion":
        return (await api.get_discussion(course_id, object_id)).get("message") or ""
    if object_type == "quiz":
        return (await api.get_quiz(course_id, object_id)).get("description") or ""
    if object_type == "syllabus":
        return (await api.get_course(course_id, include=("syllabus_body",))).get("syllabus_body") or ""
    raise AppError("unsupported", message="Denne typen innhold kan ikke rettes automatisk.")


def open_change_for(c: AppContainer, course_id: str, kind: str, object_id: str) -> StagedChange | None:
    with c.db.session() as session:
        rows = session.scalars(select(StagedChange).where(
            StagedChange.course_id == course_id, StagedChange.kind == kind,
            StagedChange.status.in_(("staged", "approved", "conflict", "failed")))).all()
        row = next((r for r in rows if r.target.get("object_id") == object_id), None)
        if row is not None:
            session.expunge(row)
        return row


async def build_fix(c: AppContainer, finding: Finding, params: FixParams) -> dict[str, Any]:
    if not finding.fix or finding.object_type not in HTML_FIELD or not finding.object_id:
        raise AppError("unsupported", message="Dette funnet har ingen automatisk retting.")
    kind = HTML_KIND_BY_OBJECT[finding.object_type].kind
    field = HTML_FIELD[finding.object_type]
    existing = open_change_for(c, finding.course_id, kind, finding.object_id)
    live = await live_html(c, finding.course_id, finding.object_type, finding.object_id)
    if existing is not None:
        base = existing.proposed.get(field) or ""
        before_state = existing.before
    else:
        base = live
        before_state = {field: live}
    after = transform(base, finding, params)
    original = serialize(parse_html(before_state.get(field) or ""))
    return {
        "kind": kind, "field": field, "before_state": before_state, "after": after, "existing_change_id":
        existing.id if existing else None, "before_display": display(original), "after_display": display(after),
        "preview_html": preview_html(after, c.settings.get().canvas.base_url),
        "risk": "low" if (finding.fix or {}).get("type") in LOW_RISK else "medium",
    }


@router.post("/findings/{finding_id}/fix/preview")
async def fix_preview(finding_id: int, params: FixParams, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    finding = FindingStore(c.db).get(finding_id)
    result = await build_fix(c, finding, params)
    return {k: result[k] for k in ("kind", "before_display", "after_display", "preview_html", "risk",
                                   "existing_change_id")}


@router.post("/findings/{finding_id}/fix/stage")
async def fix_stage(finding_id: int, params: FixParams, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    finding = FindingStore(c.db).get(finding_id)
    result = await build_fix(c, finding, params)
    label = (finding.fix or {}).get("label") or finding.title
    return c.changes.stage(
        course_id=finding.course_id, domain="accessibility", kind=result["kind"],
        title=f"{finding.object_title}: universell utforming",
        target={"object_type": finding.object_type, "object_id": finding.object_id, "title": finding.object_title,
                "url": finding.object_url},
        before=result["before_state"], proposed={result["field"]: result["after"]},
        rationale=f"{label} – {finding.message}", risk=result["risk"],
        source={"feature": "accessibility", "finding_fingerprints": [finding.fingerprint], "rule_ids": [finding.rule_id]},
        editable=False, merge=True)
