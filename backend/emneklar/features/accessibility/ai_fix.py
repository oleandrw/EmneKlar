"""KI-forslag i rettevinduet – one pattern for every text fix where KI helps.

«Foreslå … med KI» → review and edit → preview → approve to the change queue. A suggestion is only text in the dialog:
it is never approved by itself, and «Godkjenn alle klare» never includes one (see ``fixes.ready_params``). Rule-based
fixes stay rule-based; KI writes one short text the teacher checks.

Which fix types get help (``BUILDERS``):

* ``set_link_text`` and an empty link's text (``replace_link_href``): the address (without credentials), the link's
  own text, the sentence around it, the page title and nearest heading – and what the link points to, read safely
  (:mod:`link_target`). The teacher is told whether the target was actually read or the suggestion rests on the
  address and context only.
* ``table_caption``: the column and row headers, the nearest heading and the text before the table. The data rows are
  never sent (they may hold names or results).
* ``set_iframe_title``: the embed's address and what it points to, the heading and text around it. YouTube videos use
  their own flow first (the video's real title from YouTube, :mod:`content_quality.video_api`).

Only what the task needs is sent; text from Canvas and web pages is marked as data, not instructions. The answer is
validated – plain text, sensible length, not generic, not an address – before it is shown, and the HTML fix inserts it
as text (never markup). Requests go through ``AIService`` (routing, privacy gate, consent, usage log without content).
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.ai.base import AIError, AIMessage, AIRequest, TextPart
from emneklar.core.ai.service import AI_LABEL
from emneklar.core.ai.untrusted import DATA_RULE, wrap_untrusted_content
from emneklar.core.canvas.html import context_text, is_generic_iframe_title, norm_text, parse_html, text_of
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.storage.models import Finding
from emneklar.features.accessibility.checks.structure import VAGUE
from emneklar.features.accessibility.fixes import live_html, locate
from emneklar.features.accessibility.link_target import Target, describe_target, safe_url
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")

PRIVACY = "Ingen studentdata og ingen andre sider sendes."
QUOTES = {'"': '"', "'": "'", "«": "»", "“": "”"}
BAD_ANSWER = "KI-tjenesten ga ikke et brukbart forslag. Skriv teksten selv, eller be om et nytt forslag."
PROVIDER_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "azure_openai": "Azure OpenAI",
                  "openai_compatible": "egen KI-server"}
COMMON = (DATA_RULE + " Ikke finn på innhold, egenskaper eller kvalitetsgarantier. Svar bare med JSON etter skjemaet.")
SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
    "required": ["text", "confidence"],
    "additionalProperties": False,
}


@dataclass
class Built:
    task: str
    system: str
    prompt: str
    summary: str
    basis: str
    weak: str | None
    max_len: int
    generic: Callable[[str], bool]
    content_hash: str


def _hash(el: Tag) -> str:
    return hashlib.sha256(str(el).encode("utf-8")).hexdigest()[:16]


def _heading(el: Tag) -> str:
    heading = el.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
    return text_of(heading)[:150] if isinstance(heading, Tag) else ""


def _data(label: str, text: str) -> str:
    """Course or web text as delimited data (contact details are not needed for a suggestion and are removed)."""
    return wrap_untrusted_content(label, text, scrub=True, empty="(ingen)") + "\n"


def _target_lines(target: Target) -> str:
    lines = f"Om målet: {target.note}\n"
    if target.title:
        lines += f"Tittel på målet: {target.title}\n"
    if target.excerpt:
        lines += _data("Utdrag fra målet", target.excerpt)
    return lines


def _avoid(previous: list[str]) -> str:
    return ("Gi et annet forslag enn disse: " + "; ".join(f"«{p}»" for p in previous) + "\n") if previous else ""


async def link_text_built(c: AppContainer, *, href: str, current: str, sentence: str, heading: str, page_title: str,
                          avoid: list[str], content_hash: str) -> Built:
    """The link text task for any link – from a finding's element or from the link overview (address and text)."""
    address, _ = safe_url(href) if href.lower().startswith("http") else (href, False)
    target = await describe_target(c, href)
    weak = None if target.fetched else (
        "KI har ikke lest målet – forslaget bygger på adressen og teksten rundt lenken." if sentence and sentence != current
        else "Grunnlaget er svakt: KI har ikke lest målet og har lite tekst rundt lenken. Kontroller forslaget nøye.")
    prompt = (f"Sidetittel: {page_title or '(ukjent)'}\nNærmeste overskrift: {heading or '(ingen)'}\n"
              f"Lenkeadresse: {address or '(ingen)'}\nNåværende lenketekst: {current or '(tom)'}\n"
              + _data("Teksten rundt lenken", sentence) + _target_lines(target) + _avoid(avoid)
              + "Foreslå en lenketekst.")
    return Built(
        task="link_text",
        system=("Du foreslår en kort, beskrivende lenketekst for en lenke i et universitetsemne i Canvas. Lenketeksten "
                "skal si hva lenken går til eller hva den gjør, være på samme språk som teksten rundt lenken, passe inn "
                "i setningen og være under 80 tegn. Ikke bruk «klikk her», «les mer», «lenke» eller en nettadresse som "
                "lenketekst. Har du ikke fått innhold fra målet, skal forslaget bare bygge på adressen og teksten rundt, "
                "uten å påstå noe om innholdet. " + COMMON),
        prompt=prompt,
        summary=("Lenkeadressen (uten tilgangsopplysninger), lenketeksten, teksten rundt lenken, sidetittelen og "
                 "nærmeste overskrift" + (", og tittel og et kort utdrag fra målet" if target.fetched else "")
                 + f" sendes til KI-leverandøren. {PRIVACY}"),
        basis=f"Grunnlag: {target.note}" + ("" if target.fetched else " Lenkeadressen og teksten rundt lenken."),
        weak=weak, max_len=120, generic=lambda t: t.lower().strip(" .:!»«\"'") in VAGUE, content_hash=content_hash)


async def _link(c: AppContainer, finding: Finding, el: Tag, body: SuggestBody) -> Built:
    if el.name != "a":
        raise AppError("unsupported", message="Funnet gjelder ikke en lenke.")
    return await link_text_built(c, href=(body.href or str(el.get("href") or "")).strip(), current=text_of(el),
                                 sentence=context_text(el)[:400], heading=_heading(el),
                                 page_title=finding.object_title or "", avoid=body.avoid, content_hash=_hash(el))


async def _caption(c: AppContainer, finding: Finding, el: Tag, body: SuggestBody) -> Built:
    if el.name != "table":
        raise AppError("unsupported", message="Funnet gjelder ikke en tabell.")
    headers = [text_of(th)[:40] for th in el.find_all("th")][:12]
    before = el.find_previous_sibling(["p", "h2", "h3", "h4", "ul", "ol"])
    weak = None if headers else ("Grunnlaget er svakt: tabellen har ingen overskriftsceller, så forslaget bygger bare "
                                 "på teksten rundt. Kontroller forslaget nøye.")
    prompt = (f"Sidetittel: {finding.object_title or '(ukjent)'}\nNærmeste overskrift: {_heading(el) or '(ingen)'}\n"
              + _data("Overskriftscellene i tabellen", " | ".join(h for h in headers if h))
              + _data("Teksten rett før tabellen", text_of(before)[:300] if isinstance(before, Tag) else "")
              + _avoid(body.avoid) + "Foreslå en tabelltittel.")
    return Built(
        task="table_caption",
        system=("Du foreslår en kort tabelltittel (caption) som sier hva tabellen viser, for en tabell i et "
                "universitetsemne i Canvas. Skriv på samme språk som teksten, under 100 tegn, uten «Tabell:» foran "
                "og uten å beskrive enkeltverdier. " + COMMON),
        prompt=prompt,
        summary=("Overskriftscellene i tabellen, nærmeste overskrift, teksten rett før tabellen og sidetittelen sendes "
                 f"til KI-leverandøren – ikke radene med data. {PRIVACY}"),
        basis="Grunnlag: overskriftscellene i tabellen og teksten rundt den (ikke dataradene).",
        weak=weak, max_len=150, generic=lambda t: t.lower().strip(" .:") in {"tabell", "table", "oversikt"},
        content_hash=_hash(el))


async def _embed(c: AppContainer, finding: Finding, el: Tag, body: SuggestBody) -> Built:
    if el.name != "iframe":
        raise AppError("unsupported", message="Funnet gjelder ikke innebygd innhold.")
    src = str(el.get("src") or "").strip()
    address, _ = safe_url(src) if src.lower().startswith("http") else (src, False)
    target = await describe_target(c, src)
    around = context_text(el)[:300]
    prompt = (f"Sidetittel: {finding.object_title or '(ukjent)'}\nNærmeste overskrift: {_heading(el) or '(ingen)'}\n"
              f"Adressen til det innebygde innholdet: {address or '(ingen)'}\n" + _data("Teksten rundt", around)
              + _target_lines(target) + _avoid(body.avoid) + "Foreslå en tittel.")
    return Built(
        task="embed_title",
        system=("Du foreslår en kort tittel (title-attributt) for innebygd innhold (iframe) i et universitetsemne i "
                "Canvas, slik at skjermleserbrukere vet hva rammen inneholder før de går inn i den. Begynn med typen "
                "innhold når den er kjent (for eksempel «Video:», «Quiz:», «Tavle:»), og si deretter hva det handler om. "
                "Skriv på samme språk som teksten, under 80 tegn, og ikke bare tjenestens navn. " + COMMON),
        prompt=prompt,
        summary=("Adressen til det innebygde innholdet (uten tilgangsopplysninger), teksten rundt, sidetittelen og "
                 "nærmeste overskrift" + (", og tittel og et kort utdrag fra målet" if target.fetched else "")
                 + f" sendes til KI-leverandøren. {PRIVACY}"),
        basis=f"Grunnlag: {target.note}" + ("" if target.fetched else " Adressen og teksten rundt."),
        weak=None if target.fetched else "KI har ikke lest det innebygde innholdet – forslaget bygger på adressen og "
                                         "teksten rundt.",
        max_len=120, generic=is_generic_iframe_title, content_hash=_hash(el))


Builder = Callable[[AppContainer, Finding, Tag, "SuggestBody"], Awaitable[Built]]
BUILDERS: dict[str, Builder] = {"set_link_text": _link, "replace_link_href": _link, "table_caption": _caption,
                                "set_iframe_title": _embed}


class SuggestBody(BaseModel):
    confirmed: bool = False
    #: Earlier suggestions («Nytt forslag» asks for a different one).
    avoid: list[str] = Field(default_factory=list, max_length=5)
    #: An empty link: the address the teacher is entering (otherwise the link's own address).
    href: str | None = Field(default=None, max_length=2000)


def supports(finding: Finding) -> bool:
    fix = finding.fix or {}
    if fix.get("type") == "replace_link_href":
        return bool((fix.get("params") or {}).get("empty"))
    return fix.get("type") in BUILDERS


async def _build(c: AppContainer, finding_id: int, body: SuggestBody) -> tuple[Finding, Built]:
    finding = FindingStore(c.db).get(finding_id)
    if not supports(finding) or not finding.object_type or not finding.object_id:
        raise AppError("unsupported", message="KI-forslag finnes ikke for denne rettingen.")
    html = await live_html(c, finding.course_id, finding.object_type, finding.object_id)
    soup = parse_html(html)
    fix = finding.fix or {}
    el = locate(soup, finding.location or {}, (fix.get("params") or {}).get("path"), evidence=finding.evidence)
    return finding, await BUILDERS[str(fix.get("type"))](c, finding, el, body)


def clean(text: str, built: Built) -> str:
    """The model's text as plain text, or ``AIError`` – no markup, no address, not generic, a sensible length."""
    raw = text or ""
    if "<" in raw:  # markup from the model: drop scripts and styles entirely, keep only the words
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "template"]):
            tag.decompose()
        raw = soup.get_text(" ")
    plain = norm_text(raw)
    while len(plain) > 1 and plain[0] in QUOTES and plain[-1] == QUOTES[plain[0]]:  # only quotes around it all
        plain = plain[1:-1].strip()
    if (not plain or len(plain) < 2 or len(plain) > built.max_len or plain.lower().startswith(("http://", "https://",
                                                                                               "www."))
            or built.generic(plain)):
        raise AIError("ai_bad_response", status=502, message=BAD_ANSWER)
    return plain


def _provider_name(c: AppContainer, provider_id: str) -> str:
    config = c.settings.get().provider(provider_id)
    if config is None:
        return provider_id
    return config.name or PROVIDER_NAMES.get(config.type, config.type)


@router.post("/findings/{finding_id}/ai-suggestion/prepare")
async def prepare(finding_id: int, body: SuggestBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """What would be sent, on what basis, and to which service (``AIService.plan``) – nothing is sent yet."""
    _, built = await _build(c, finding_id, body)
    plan = c.ai.plan(built.task, input_chars=len(built.prompt), images=0, summary=built.summary)
    return {**plan, "task": built.task, "basis": built.basis, "weak": built.weak}


@router.post("/findings/{finding_id}/ai-suggestion")
async def suggest(finding_id: int, body: SuggestBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """One suggestion for the finding's text field (always «KI-forslag – må vurderes»; nothing is staged)."""
    finding, built = await _build(c, finding_id, body)

    def request(model: str) -> AIRequest:
        return AIRequest(model=model, system=built.system, schema_name="tekstforslag", json_schema=SCHEMA,
                         max_output_tokens=200, messages=[AIMessage(parts=[TextPart(text=built.prompt)])])

    result, decision = await c.ai.run(built.task, request, input_chars=len(built.prompt), summary=built.summary,
                                      confirmed=body.confirmed, course_id=finding.course_id)
    data = result.data if isinstance(result.data, dict) else {}
    text = clean(str(data.get("text") or ""), built)
    return {"finding_id": finding.id, "text": text, "label": AI_LABEL, "basis": built.basis, "weak": built.weak,
            "content_hash": built.content_hash, "confidence": data.get("confidence"), "provider": result.provider,
            "provider_name": _provider_name(c, result.provider), "model": result.model, "route_reason": decision.reason}


# -- the link overview: a link text for an address (the place may have no finding, e.g. a working link) -------------


class LinkTextBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    current_text: str = Field(default="", max_length=300)
    page_title: str = Field(default="", max_length=300)
    confirmed: bool = False
    avoid: list[str] = Field(default_factory=list, max_length=5)


async def _link_text_for(c: AppContainer, body: LinkTextBody) -> Built:
    return await link_text_built(c, href=body.url.strip(), current=body.current_text, sentence="", heading="",
                                 page_title=body.page_title, avoid=body.avoid,
                                 content_hash=hashlib.sha256(body.url.encode("utf-8")).hexdigest()[:16])


@router.post("/courses/{course_id}/links/link-text-suggestion/prepare")
async def prepare_link_text(course_id: str, body: LinkTextBody,
                            c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    require_course_id(course_id)
    built = await _link_text_for(c, body)
    plan = c.ai.plan(built.task, input_chars=len(built.prompt), images=0, summary=built.summary)
    return {**plan, "task": built.task, "basis": built.basis, "weak": built.weak}


@router.post("/courses/{course_id}/links/link-text-suggestion")
async def suggest_link_text(course_id: str, body: LinkTextBody,
                            c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    built = await _link_text_for(c, body)

    def request(model: str) -> AIRequest:
        return AIRequest(model=model, system=built.system, schema_name="tekstforslag", json_schema=SCHEMA,
                         max_output_tokens=200, messages=[AIMessage(parts=[TextPart(text=built.prompt)])])

    result, decision = await c.ai.run(built.task, request, input_chars=len(built.prompt), summary=built.summary,
                                      confirmed=body.confirmed, course_id=course_id)
    data = result.data if isinstance(result.data, dict) else {}
    return {"text": clean(str(data.get("text") or ""), built), "label": AI_LABEL, "basis": built.basis,
            "weak": built.weak, "url": body.url, "provider": result.provider,
            "provider_name": _provider_name(c, result.provider), "model": result.model, "route_reason": decision.reason}
