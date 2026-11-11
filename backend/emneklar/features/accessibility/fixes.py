"""Fixes for findings (universell utforming, innholdskvalitet) → previewable, staged page changes.

A fix never writes to Canvas. It transforms the *current* HTML of the object (fetched live from Canvas, or the
proposal already in the change set so that several fixes to one page merge into one change) and returns before/after
for the diff and preview. Staging goes through the shared change engine.

**Targeted edits.** Element fixes (alt text, link address/text, removing a link, heading level, iframe title, …) change
only the element in question (:mod:`emneklar.core.canvas.html_edit`): every other byte of the page – other links,
images, embedded content, formatting – stays exactly as it was. Whole-document fixes (code cleanup, lists, tables)
and markup too broken to map safely use the older parse-and-serialise path.

**Recipes.** Each staged fix stores how it was made (fix, location, parameters). The change engine can therefore
rebuild a change on newer content (e.g. after another change to the same page was published first) instead of
overwriting it – see :func:`rebase_html_fixes`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.dammit import EntitySubstitution
from bs4.formatter import HTMLFormatter
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.blueprint import blueprint_info, describe
from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.html import find_by_path, norm_text, parse_html, text_of
from emneklar.core.canvas.html_edit import EditError, EditPlan, escape_text
from emneklar.core.canvas.links import href_problem
from emneklar.core.changes.appliers import HTML_KIND_BY_OBJECT, ChangeData
from emneklar.core.changes.engine import register_describer, register_rebaser
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.security.sanitize import preview_html
from emneklar.core.storage.models import Finding, StagedChange
from emneklar.features.accessibility.checks.base import element_signature
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")

LOW_RISK = {"set_alt", "set_iframe_title", "set_lang", "set_link_text", "remove_autoplay", "table_caption",
            "table_scope", "change_heading_level"}
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
MARKER = re.compile(r"^\s*([-–—•*·▪◦●]|\d{1,2}[.)]|[a-zA-Z][.)])\s+")
BLOCK_TAGS = r"(p|h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|div|figure|figcaption|iframe|blockquote|section|caption)"
#: Fix types that change one element and therefore use targeted edits.
ELEMENT_FIXES = {"set_alt", "set_link_text", "set_iframe_title", "replace_link_href", "remove_element",
                 "unwrap_element", "change_heading_level", "convert_to_heading", "set_lang", "remove_autoplay",
                 "remove_underline"}
MEDIA_IN_LINK = ["img", "svg", "picture", "iframe", "video", "audio"]
REBASER = "html_fixes"

LinkAction = Literal["replace", "unlink", "remove"]
Scope = Literal["this", "page", "course"]


class FixParams(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    decorative: bool = False
    level: int | None = Field(default=None, ge=2, le=6)
    lang: str | None = Field(default=None, max_length=20)
    url: str | None = Field(default=None, max_length=2000)
    unlink: bool = False  # older clients: «remove the link, keep the text»
    link_action: LinkAction | None = None
    link_text: str | None = Field(default=None, max_length=200)
    scope: Scope = "this"
    options: list[str] | None = Field(default=None, max_length=10)
    #: The text is (based on) a KI-forslag the teacher reviewed in the dialog – the change is marked as KI-generated.
    ai_suggestion: bool = False

    def action(self) -> LinkAction:
        return self.link_action or ("unlink" if self.unlink else "replace")


@dataclass
class FixTarget:
    """What a fix needs from a finding – also stored in the change («recipe») so it can be re-applied later."""

    fix: dict[str, Any]
    location: dict[str, Any]
    evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, finding: Finding) -> FixTarget:
        evidence = finding.evidence or {}
        return cls(dict(finding.fix or {}), dict(finding.location or {}),
                   {k: evidence[k] for k in ("href", "src", "alt") if k in evidence})


@dataclass
class FixOutcome:
    html: str
    changes: list[dict[str, str]]  # element before/after (targeted edits only)
    targeted: bool
    count: int


def _valid_href(url: str) -> str:
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and parts.hostname:
        problem = href_problem(url)
        if problem:
            raise AppError("validation_error", message=f"{problem} Skriv hele adressen, for eksempel https://www.uio.no/…")
        return url
    if parts.scheme in ("mailto", "tel") and parts.path:
        return url
    if not parts.scheme and url.startswith("/") and not url.startswith("//"):
        return url
    raise AppError("validation_error", message="Skriv en gyldig adresse som starter med https:// (eller /courses/… "
                   "for innhold i Canvas).")


# ----------------------------------------------------------------------------------- helpers


# Keeps æøå and other characters as-is, writes <br> (not <br/>) and keeps alt="" explicit.
CANVAS_FORMATTER = HTMLFormatter(entity_substitution=EntitySubstitution.substitute_xml,
                                 void_element_close_prefix=None,  # type: ignore[arg-type]  # None = write <br>
                                 empty_attributes_are_booleans=False)


def serialize(soup: BeautifulSoup) -> str:
    return soup.decode(formatter=CANVAS_FORMATTER)


def display(html: str) -> str:
    """Line-broken HTML for the diff view only (never sent to Canvas)."""
    text = re.sub(rf"(?i)(<{BLOCK_TAGS}\b)", r"\n\1", html)
    text = re.sub(rf"(?i)(</{BLOCK_TAGS}>)", r"\1\n", text)
    return "\n".join(line for line in (ln.rstrip() for ln in text.split("\n")) if line.strip())


def _snippet_tag(location: dict[str, Any]) -> str | None:
    match = re.match(r"\s*<([a-zA-Z][a-zA-Z0-9]*)", str(location.get("snippet") or ""))
    return match.group(1).lower() if match else None


def locate(soup: BeautifulSoup, location: dict[str, Any], path: str | None = None, *, relaxed: bool = False,
           evidence: dict[str, Any] | None = None) -> Tag:
    """Find the element again: by path + signature, or by a unique signature anywhere.

    ``relaxed`` (moving a fix to the Blueprint course, where Canvas has rewritten course and file ids) also accepts
    the element at the same path when its tag and key attribute (link address / alt text) agree.
    """
    path = path or location.get("selector")
    sig = location.get("sig")
    el = find_by_path(soup, path) if path else None
    if el is not None and (not sig or element_signature(el) == sig):
        return el
    if sig:
        matches = [e for e in soup.find_all(True) if element_signature(e) == sig]
        if len(matches) == 1:
            return matches[0]
    if relaxed and el is not None and el.name == _snippet_tag(location):
        evidence = evidence or {}
        if el.name == "a" and evidence.get("href") and str(el.get("href") or "").strip() == evidence["href"]:
            return el
        if el.name == "img" and str(el.get("alt")) == str(evidence.get("alt")):
            return el
        if el.name not in ("a", "img"):
            return el
    raise AppError("conflict", status=409, message="Fant ikke elementet i det nåværende innholdet. "
                   "Innholdet kan være endret – kjør en ny analyse.")


def _require_text(text: str | None, what: str, max_len: int = 500) -> str:
    value = norm_text(text or "")
    if not value:
        raise AppError("validation_error", message=f"Skriv inn {what}.")
    if len(value) > max_len:
        raise AppError("validation_error", message=f"Teksten er for lang (maks {max_len} tegn).")
    return value


def _same_href(soup: BeautifulSoup, href: str) -> list[Tag]:
    return [a for a in soup.find_all("a") if str(a.get("href") or "").strip() == href.strip()]


def _link_targets(soup: BeautifulSoup, el: Tag, params: FixParams) -> list[Tag]:
    if params.scope in ("page", "course"):
        same = _same_href(soup, str(el.get("href") or ""))
        return same or [el]
    return [el]


def _check_link_params(el: Tag, params: FixParams, fparams: dict[str, Any] | None = None
                       ) -> tuple[LinkAction, str | None, str | None]:
    action = params.action()
    url = text = None
    if action == "replace":
        url = _valid_href(params.url or "")
        text = norm_text(params.link_text or "") or None
        if text and len(text) > 200:
            raise AppError("validation_error", message="Lenketeksten er for lang (maks 200 tegn).")
        if (fparams or {}).get("empty") and not text and not el.find(MEDIA_IN_LINK):
            raise AppError("validation_error", message="Skriv en lenketekst – ellers er lenken fortsatt tom og usynlig. "
                           "Eller velg å fjerne den tomme lenken.")
        if url == str(el.get("href") or "").strip() and not text:
            raise AppError("validation_error", message="Den nye adressen er lik den gamle. Skriv en ny adresse, endre "
                           "lenketeksten eller velg å fjerne lenken.")
    return action, url, text


# ------------------------------------------------------------------------------- transforms


def apply_fix(html: str, target: FixTarget | Finding, params: FixParams, *, relaxed: bool = False) -> FixOutcome:
    if isinstance(target, Finding):
        target = FixTarget.of(target)
    if (target.fix or {}).get("type") in ELEMENT_FIXES:
        try:
            return _targeted(html, target, params, relaxed=relaxed)
        except EditError:
            pass  # markup that cannot be mapped safely: fall back to the whole-document path below
    return FixOutcome(_whole_document(html, target, params, relaxed=relaxed), [], False, 1)


def transform(html: str, target: FixTarget | Finding, params: FixParams) -> str:
    return apply_fix(html, target, params).html


def _targeted(html: str, target: FixTarget, params: FixParams, *, relaxed: bool) -> FixOutcome:
    ftype = target.fix.get("type")
    fparams = target.fix.get("params") or {}
    soup = parse_html(html)
    plan = EditPlan(html)
    el = locate(soup, target.location, relaxed=relaxed, evidence=target.evidence)
    if ftype == "set_alt":
        if params.decorative:
            plan.set_attrs(soup, el, {"alt": "", "role": "presentation"})
        else:
            changes: dict[str, str | None] = {"alt": _require_text(params.text, "en alternativ tekst")}
            if el.get("role") in ("presentation", "none"):
                changes["role"] = None
            plan.set_attrs(soup, el, changes)
    elif ftype == "set_link_text":
        _set_link_text(plan, soup, el, _require_text(params.text or params.link_text, "lenketekst", 200))
    elif ftype == "set_iframe_title":
        plan.set_attrs(soup, el, {"title": _require_text(params.text, "en tittel", 200)})
    elif ftype == "replace_link_href":
        action, url, text = _check_link_params(el, params, fparams)
        for a in _link_targets(soup, el, params):
            if action == "unlink":
                plan.unwrap(soup, a)
            elif action == "remove":
                plan.remove(soup, a)
            elif text:
                if a.find(MEDIA_IN_LINK):
                    plan.set_attrs(soup, a, {"href": url, "aria-label": text})
                else:
                    plan.set_attrs_and_inner(soup, a, {"href": url}, escape_text(text))
            else:
                plan.set_attrs(soup, a, {"href": url})
    elif ftype == "remove_element":
        plan.remove(soup, el)
    elif ftype == "unwrap_element":
        plan.unwrap(soup, el)
    elif ftype == "change_heading_level":
        plan.rename(soup, el, f"h{params.level or int(fparams.get('level') or 2)}")
    elif ftype == "convert_to_heading":
        level = params.level or int(fparams.get("level") or 2)
        plan.replace_outer(soup, el, f"<h{level}>{escape_text(text_of(el))}</h{level}>")
    elif ftype == "set_lang":
        plan.set_attrs(soup, el, {"lang": _lang(params, fparams)})
    elif ftype == "remove_autoplay":
        changes = {"autoplay": None} if el.has_attr("autoplay") else {}
        src = str(el.get("src") or "")
        if src:
            changes["src"] = _without_autoplay(src)
        if not changes:
            raise AppError("validation_error", message="Elementet spiller ikke av automatisk lenger.")
        plan.set_attrs(soup, el, changes)
    elif ftype == "remove_underline":
        if el.name == "u":
            plan.unwrap(soup, el)
        else:
            plan.set_attrs(soup, el, {"style": _without_text_decoration(str(el.get("style") or "")) or None})
    else:  # pragma: no cover - guarded by ELEMENT_FIXES
        raise EditError(str(ftype))
    return FixOutcome(plan.apply(), plan.changes(), True, len(plan.edits))


def _set_link_text(plan: EditPlan, soup: BeautifulSoup, a: Tag, text: str) -> None:
    """Visible link text replaces the content – unless the link holds an image or embedded media, which is kept and the
    text becomes the link's accessible name (``aria-label``)."""
    if a.find(MEDIA_IN_LINK):
        plan.set_attrs(soup, a, {"aria-label": text})
    else:
        plan.replace_inner(soup, a, escape_text(text))


def _lang(params: FixParams, fparams: dict[str, Any]) -> str:
    lang = (params.lang or fparams.get("lang") or "").strip()
    if not LANG_RE.match(lang):
        raise AppError("validation_error", message="Ugyldig språkkode (bruk for eksempel en, nb, nn eller se).")
    return lang


def _without_autoplay(src: str) -> str:
    parts = urlsplit(src)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "autoplay"]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _without_text_decoration(style: str) -> str:
    return ";".join(p for p in style.split(";") if p.strip() and not p.strip().lower().startswith("text-decoration"))


def _whole_document(html: str, target: FixTarget, params: FixParams, *, relaxed: bool) -> str:
    fix = target.fix or {}
    ftype = fix.get("type")
    fparams = fix.get("params") or {}
    soup = parse_html(html)
    location = target.location or {}

    if ftype == "cleanup":
        from emneklar.features.content_quality.hygiene import CLEANUP_OPTIONS, cleanup, protected_signature

        options = set(params.options or CLEANUP_OPTIONS) & set(CLEANUP_OPTIONS)
        cleaned, _counts = cleanup(html, options)
        result = serialize(cleaned)
        if protected_signature(html) != protected_signature(result):
            raise AppError("conflict", status=409, message="Oppryddingen ville endret lenker, innebygd innhold eller "
                           "tekst, og ble stoppet. Rydd opp manuelt i Canvas.")
        return result

    if ftype == "demote_headings":
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5"])
        if soup.find("h6"):
            raise AppError("validation_error", message="Siden har overskrifter på nivå 6 og kan ikke senkes automatisk.")
        for h in headings:
            h.name = f"h{int(h.name[1]) + 1}"
        return serialize(soup)

    if ftype == "convert_fake_list":
        paths = list(fparams.get("paths") or [])
        first = locate(soup, location, paths[0] if paths else None, relaxed=relaxed, evidence=target.evidence)
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

    el = locate(soup, location, relaxed=relaxed, evidence=target.evidence)
    if ftype == "set_alt":
        if params.decorative:
            el["alt"] = ""
            el["role"] = "presentation"
        else:
            el["alt"] = _require_text(params.text, "en alternativ tekst")
            if el.get("role") in ("presentation", "none"):
                del el["role"]
    elif ftype == "set_link_text":
        text = _require_text(params.text or params.link_text, "lenketekst", 200)
        if el.find(MEDIA_IN_LINK):
            el["aria-label"] = text
        else:
            for child in list(el.children):
                child.extract()
            el.append(NavigableString(text))
    elif ftype == "set_iframe_title":
        el["title"] = _require_text(params.text, "en tittel", 200)
    elif ftype == "replace_link_href":
        action, url, new_text = _check_link_params(el, params, fparams)
        for a in _link_targets(soup, el, params):
            if action == "unlink":
                a.unwrap()
            elif action == "remove":
                a.decompose()
            else:
                a["href"] = url or ""
                if new_text and a.find(MEDIA_IN_LINK):
                    a["aria-label"] = new_text
                elif new_text:
                    for child in list(a.children):
                        child.extract()
                    a.append(NavigableString(new_text))
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
        caption.string = _require_text(params.text, "en tabelltittel", 200)
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
        el["lang"] = _lang(params, fparams)
    elif ftype == "remove_autoplay":
        if el.has_attr("autoplay"):
            del el["autoplay"]
        src = str(el.get("src") or "")
        if src:
            el["src"] = _without_autoplay(src)
    elif ftype == "remove_underline":
        if el.name == "u":
            el.unwrap()
        else:
            style = _without_text_decoration(str(el.get("style") or ""))
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


# ------------------------------------------------------------------------------- recipes / rebase

HTML_FIELD = {"page": "body", "assignment": "description", "discussion": "message", "quiz": "description",
              "syllabus": "syllabus_body"}


def recipe(finding: Finding, params: FixParams) -> dict[str, Any]:
    target = FixTarget.of(finding)
    return {"finding_id": finding.id, "fingerprint": finding.fingerprint, "rule_id": finding.rule_id,
            "fix": target.fix, "location": target.location, "evidence": target.evidence,
            "params": params.model_dump(exclude_none=True, exclude_defaults=True)}


def apply_recipes(html: str, recipes: list[dict[str, Any]], *, relaxed: bool = False) -> str:
    for item in recipes:
        target = FixTarget(dict(item.get("fix") or {}), dict(item.get("location") or {}),
                           dict(item.get("evidence") or {}))
        html = apply_fix(html, target, FixParams(**(item.get("params") or {})), relaxed=relaxed).html
    return html


def rebase_html_fixes(data: ChangeData, source: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild an HTML fix change on newer content (engine hook). None when a fix no longer applies."""
    field_name = HTML_FIELD.get(str(data.target.get("object_type")))
    recipes = list(source.get("fixes") or [])
    if field_name is None or not recipes or not isinstance(current.get(field_name), str):
        return None
    try:
        return {field_name: apply_recipes(current[field_name], recipes, relaxed=bool(source.get("relaxed")))}
    except (AppError, EditError):
        return None


register_rebaser(REBASER, rebase_html_fixes)

#: What each recorded fix type did, in the past tense, for the history (Canvas-verktøy → Siste handlinger).
DONE_LABELS = {
    "set_link_text": "Lenketekst oppdatert",
    "set_iframe_title": "Tittel på innebygd innhold oppdatert",
    "unwrap_element": "Formatering fjernet",
    "change_heading_level": "Overskriftsnivå endret",
    "convert_to_heading": "Tekst gjort om til overskrift",
    "table_headers": "Tabelloverskrifter lagt til",
    "table_scope": "Tabelloverskrifter knyttet til cellene",
    "table_caption": "Tabelltittel lagt til",
    "fix_list_nesting": "Listestruktur rettet",
    "set_lang": "Språk angitt",
    "remove_autoplay": "Autoavspilling slått av",
    "remove_underline": "Understreking fjernet",
    "cleanup": "Kode ryddet",
    "demote_headings": "Overskriftsnivåer justert",
    "convert_fake_list": "Tekst gjort om til liste",
}


def describe_recipe(item: dict[str, Any]) -> str | None:
    """The recorded fix type and parameters in words; None for a type without a known description."""
    ftype = str((item.get("fix") or {}).get("type") or "")
    params = dict(item.get("params") or {})
    if ftype == "set_alt":
        return "Bilde merket som dekorativt" if params.get("decorative") else "Alt-tekst oppdatert"
    if ftype == "replace_link_href":
        action = params.get("link_action") or ("unlink" if params.get("unlink") else "replace")
        if action == "unlink":
            return "Lenke fjernet, teksten beholdt"
        if action == "remove":
            return "Lenke og lenketekst fjernet"
        return "Lenkeadresse og lenketekst oppdatert" if params.get("link_text") else "Lenkeadresse oppdatert"
    if ftype == "remove_element":
        return "Lenke fjernet" if str(item.get("rule_id") or "").startswith(("UU-LINK", "CQ-LINK")) else "Element fjernet"
    return DONE_LABELS.get(ftype)


def describe_html_fixes(source: dict[str, Any]) -> list[str]:
    return [label for item in source.get("fixes") or [] if (label := describe_recipe(dict(item)))]


register_describer(REBASER, describe_html_fixes)


# ------------------------------------------------------------------------------------- API


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


async def where_info(c: AppContainer, course_id: str, evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Which course the change is made in, and what Blueprint means for it (never a block – see blueprint.py)."""
    course_name = None
    from emneklar.core.storage.models import Course

    with c.db.session() as session:
        row = session.get(Course, course_id)
        course_name = row.name if row else None
    try:
        info = await blueprint_info(CanvasAPI(c.canvas()), course_id)
    except CanvasError:
        info = {}
    return {"course_id": course_id, "course_name": course_name, **describe(info, (evidence or {}).get("blueprint"))}


def related_link_findings(c: AppContainer, finding: Finding) -> list[Finding]:
    """Open findings in other content of the course for the same broken address (course-wide link fix)."""
    href = (finding.evidence or {}).get("href")
    if not href or (finding.fix or {}).get("type") != "replace_link_href":
        return []
    rows, _ = FindingStore(c.db).current(finding.course_id, finding.domain)
    seen: set[str] = set()
    out = []
    for row in rows:
        ref = f"{row.object_type}:{row.object_id}"
        if row.id == finding.id or ref == f"{finding.object_type}:{finding.object_id}" or ref in seen:
            continue
        if row.status not in ("open", "staged") or (row.fix or {}).get("type") != "replace_link_href":
            continue
        if (row.evidence or {}).get("href") != href or row.object_type not in HTML_FIELD or not row.object_id:
            continue
        seen.add(ref)
        out.append(row)
    return out


async def build_fix(c: AppContainer, finding: Finding, params: FixParams) -> dict[str, Any]:
    if not finding.fix or finding.object_type not in HTML_FIELD or not finding.object_id:
        raise AppError("unsupported", message="Dette funnet har ingen automatisk retting.")
    kind = HTML_KIND_BY_OBJECT[finding.object_type].kind
    field_name = HTML_FIELD[finding.object_type]
    existing = open_change_for(c, finding.course_id, kind, finding.object_id)
    if existing is not None and existing.status == "conflict":
        # The queued change was built on content that has since changed in Canvas: start again from the live
        # content (staging replaces the stale change, and the fixes it covered become open again).
        existing = None
    live = await live_html(c, finding.course_id, finding.object_type, finding.object_id)
    if existing is not None:
        base = existing.proposed.get(field_name) or ""
        before_state = existing.before
    else:
        base = live
        before_state = {field_name: live}
    scoped = params.model_copy(update={"scope": "page"}) if params.scope == "course" else params
    outcome = apply_fix(base, finding, scoped)
    original = before_state.get(field_name) or ""
    occurrences = len(_same_href(parse_html(base), str((finding.evidence or {}).get("href") or ""))) \
        if (finding.fix or {}).get("type") == "replace_link_href" else 0
    return {
        "kind": kind, "field": field_name, "before_state": before_state, "after": outcome.html,
        "existing_change_id": existing.id if existing else None,
        # Targeted edits keep the original markup, so the diff compares raw HTML; the whole-document path
        # re-serialises, so it is compared with the re-serialised original (no false differences either way).
        "before_display": display(original if outcome.targeted else serialize(parse_html(original))),
        "after_display": display(outcome.html), "changes": [{k: v[:4000] for k, v in ch.items()}
                                                           for ch in outcome.changes[:50]],
        "targeted": outcome.targeted, "count": outcome.count, "occurrences": occurrences,
        "preview_html": preview_html(outcome.html, c.settings.get().canvas.base_url),
        "risk": "low" if (finding.fix or {}).get("type") in LOW_RISK else "medium",
    }


def _public(result: dict[str, Any]) -> dict[str, Any]:
    return {k: result[k] for k in ("kind", "before_display", "after_display", "preview_html", "risk",
                                   "existing_change_id", "changes", "targeted", "count", "occurrences")}


@router.post("/findings/{finding_id}/fix/preview")
async def fix_preview(finding_id: int, params: FixParams, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    finding = FindingStore(c.db).get(finding_id)
    result = await build_fix(c, finding, params)
    related = related_link_findings(c, finding)
    return {**_public(result), "where": await where_info(c, finding.course_id, finding.evidence),
            "related": [{"finding_id": r.id, "object_type": r.object_type, "object_id": r.object_id,
                         "object_title": r.object_title, "module": (r.location or {}).get("module")}
                        for r in related[:200]]}


def stage_built(c: AppContainer, finding: Finding, params: FixParams, result: dict[str, Any]) -> dict[str, Any]:
    label = (finding.fix or {}).get("label") or finding.title
    suffix = {"accessibility": "universell utforming", "content_quality": "innholdskvalitet"}.get(
        finding.domain, finding.domain)
    return c.changes.stage(
        course_id=finding.course_id, domain=finding.domain, kind=result["kind"],
        title=f"{finding.object_title}: {suffix}",
        target={"object_type": finding.object_type, "object_id": finding.object_id, "title": finding.object_title,
                "url": finding.object_url, "module": (finding.location or {}).get("module")},
        before=result["before_state"], proposed={result["field"]: result["after"]},
        rationale=f"{label} – {finding.message}" + (" (KI-forslag, vurdert av læreren)" if params.ai_suggestion else ""),
        risk=result["risk"], ai_generated=params.ai_suggestion,
        source={"feature": finding.domain, "finding_fingerprints": [finding.fingerprint],
                "rule_ids": [finding.rule_id], "rebase": REBASER, "fixes": [recipe(finding, params)]},
        editable=False, merge=True, layered=result["existing_change_id"] is not None)


async def stage_fix(c: AppContainer, finding: Finding, params: FixParams, *, approve: bool = False) -> dict[str, Any]:
    """Stage (and optionally approve) a fix. A course-wide link fix stages one change per affected content item."""
    result = await build_fix(c, finding, params)
    scoped = params.model_copy(update={"scope": "page"}) if params.scope == "course" else params
    change = stage_built(c, finding, scoped, result)
    also: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if params.scope == "course":
        for other in related_link_findings(c, finding):
            try:
                built = await build_fix(c, other, scoped)
                also.append(stage_built(c, other, scoped, built))
            except AppError as exc:
                errors.append({"finding_id": other.id, "object_title": other.object_title, "message": exc.message})
    ids = [change["id"], *(a["id"] for a in also)]
    if approve:
        approved = {row["id"]: row for row in c.changes.approve(ids)}
        change = approved.get(change["id"], change)
        also = [approved.get(a["id"], a) for a in also]
    return {**change, "also_staged": also, "errors": errors}


@router.post("/findings/{finding_id}/fix/stage")
async def fix_stage(finding_id: int, params: FixParams, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return await stage_fix(c, FindingStore(c.db).get(finding_id), params)


@router.post("/findings/{finding_id}/fix/approve")
async def fix_approve(finding_id: int, params: FixParams, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Godkjenn»: the reviewed fix goes into the change queue as approved, ready for «Publiser til Canvas»."""
    return await stage_fix(c, FindingStore(c.db).get(finding_id), params, approve=True)


# ---------------------------------------------------------------------- «Godkjenn alle klare»

#: Fixes that need no input from the teacher: what will happen is fully determined by the finding.
AUTOMATIC = {"demote_headings", "convert_fake_list", "change_heading_level", "convert_to_heading", "table_headers",
             "table_scope", "fix_list_nesting", "remove_autoplay", "remove_underline", "cleanup", "set_lang",
             "remove_element"}


def ready_params(finding: Finding, suggestion: dict[str, Any] | None, *, include_text: bool) -> FixParams | None:
    """The parameters a fix can be approved with as it stands, or None if the teacher must decide first.

    Rule-based text suggestions (link text from the link itself, a redirect's new address) are only included when the
    teacher asks for them – they are shown as suggestions in the change queue and can still be rejected there.
    KI-forslag (alt text from the background queue, «Foreslå … med KI» in the dialog) are never included: a generated
    suggestion has not been reviewed, so it is approved one by one in the dialog.
    """
    fix = finding.fix or {}
    ftype = fix.get("type")
    fparams = fix.get("params") or {}
    if finding.status != "open" or not ftype or finding.confidence == "low":
        return None
    if ftype == "remove_element" and finding.rule_id.startswith(("UU-LINK", "CQ-LINK")):
        return None  # removing a link is always the teacher's own choice
    if ftype in AUTOMATIC:
        if ftype == "set_lang" and not fparams.get("lang"):
            return None
        return FixParams()
    if not include_text:
        return None
    if ftype == "set_link_text" and fparams.get("suggestion"):
        return FixParams(text=str(fparams["suggestion"]))
    if ftype == "replace_link_href" and fparams.get("suggestion") and not fparams.get("empty"):
        return FixParams(url=str(fparams["suggestion"]))  # an empty link needs text (or removal): the teacher decides
    return None


def readiness(finding: Finding, suggestion: dict[str, Any] | None) -> str | None:
    """«automatic» (no input needed), «suggestion» (a text suggestion is ready) or None."""
    if ready_params(finding, suggestion, include_text=False) is not None:
        return "automatic"
    if ready_params(finding, suggestion, include_text=True) is not None:
        return "suggestion"
    return None


class BulkBody(BaseModel):
    course_id: str
    finding_ids: list[int] = Field(default_factory=list, max_length=5000)
    include_text_suggestions: bool = False


@router.post("/findings/fix/bulk")
async def bulk_approve(body: BulkBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Godkjenn valgte / alle klare»: build, stage and approve every ready fix – one change per page – as a job."""
    from emneklar.api.deps import require_course_id
    from emneklar.core.jobs.manager import JobContext
    from emneklar.features.accessibility.alt_suggestions import suggestions_for

    course_id = require_course_id(body.course_id)
    store = FindingStore(c.db)
    findings = [store.get(i) for i in dict.fromkeys(body.finding_ids)]
    findings = [f for f in findings if f.course_id == course_id]
    suggestions = suggestions_for(c, course_id, [f.fingerprint for f in findings])
    plan: dict[tuple[str, str], list[tuple[Finding, FixParams]]] = defaultdict(list)
    skipped = []
    for f in findings:
        params = ready_params(f, suggestions.get(f.fingerprint), include_text=body.include_text_suggestions)
        if params is None or f.object_type not in HTML_FIELD or not f.object_id:
            ai_ready = (suggestions.get(f.fingerprint) or {}).get("status") == "ready"
            skipped.append({"finding_id": f.id, "reason": "KI-forslaget må gjennomgås og godkjennes i funnet." if ai_ready
                            else "Krever at du tar stilling til rettingen."})
            continue
        plan[(f.object_type or "", f.object_id or "")].append((f, params))
    if not plan:
        raise AppError("validation_error", message="Ingen av de valgte funnene har en retting som er klar til å "
                       "godkjennes. Åpne funnene og ta stilling til dem ett for ett.")

    async def runner(ctx: JobContext) -> dict[str, Any]:
        progress = ctx.progress
        progress.set_phase("approve", "Godkjenner forslag", index=1, count=1, determinate=True)
        progress.add_tasks("object", len(plan))
        approved: list[int] = []
        failed: list[dict[str, Any]] = []
        changes: set[int] = set()
        for (_kind, _object_id), items in plan.items():
            await ctx.checkpoint()
            t0 = progress.start("object", item=items[0][0].object_title or "", operation="Lager retting")
            ok = True
            for f, params in items:
                try:
                    change = await stage_fix(c, f, params, approve=True)
                    changes.add(change["id"])
                    approved.append(f.id)
                except AppError as exc:
                    ok = False
                    failed.append({"finding_id": f.id, "object_title": f.object_title, "message": exc.message})
            progress.finish("object", t0, failed=not ok)
        return {"approved": approved, "failed": failed, "skipped": skipped, "change_ids": sorted(changes)}

    job = c.jobs.submit(kind="approve_fixes", title=f"Godkjenner {sum(len(v) for v in plan.values())} forslag",
                        runner=runner, course_id=course_id, params={"count": len(findings)}, hard_cancel=False)
    return {"job": job.public(), "planned": sum(len(v) for v in plan.values()), "skipped": skipped}
