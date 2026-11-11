"""«Finn alternativ lenke med KI»: up to three replacements for a link, found by real lookups and assessed by KI.

Candidates come only from real sources – never from the model's own words:

1. the address the old link now sends to (from the link check) – the same resource at a new address;
2. web search through the configured KI provider's own search tool (Anthropic or OpenAI): first the publisher's own
   site, then comparable resources – only addresses the search returned;
3. the closest archived copy in the Internet Archive (Wayback Machine availability API), marked as archived.

Each candidate is checked technically (the link checker, through the SSRF guard) and read safely for its title and a
short excerpt (:mod:`emneklar.features.accessibility.link_target`). KI then picks at most three *of these candidates*
(by id), says whether each is the same resource, an alternative or an archived copy, why it fits and what is known to
limit it. A working address is not enough: the reason says why it is a good replacement, and a candidate that does not
fit is left out – an empty list is a valid answer. Nothing is changed: the teacher picks an address in the dialog and
approves the change like any other.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.ai.base import AIError, AIMessage, AIRequest, TextPart
from emneklar.core.ai.service import AI_LABEL, SEARCH_UNAVAILABLE
from emneklar.core.ai.untrusted import DATA_RULE, wrap_untrusted_content
from emneklar.core.canvas.html import norm_text
from emneklar.core.container import AppContainer
from emneklar.core.security.guarded_http import build_guarded_client
from emneklar.core.security.ssrf import UrlBlocked, validate_url
from emneklar.features.accessibility.link_target import Target, describe_target, safe_url
from emneklar.features.content_quality.linkcheck import LinkChecker, is_checkable
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")
TASK = "link_alternatives"
MAX_CANDIDATES = 8
WAYBACK = "https://archive.org/wayback/available"
STATE_LABEL = {"WORKING": "Fungerer", "REDIRECT": "Fungerer (videresendes)", "DEAD": "Fungerer ikke",
               "AUTH_REQUIRED": "Krever innlogging", "TIMEOUT": "Kunne ikke kontrolleres",
               "UNKNOWN": "Kunne ikke kontrolleres"}
RELATION_LABEL = {"same": "Samme ressurs, ny adresse", "alternative": "Faglig alternativ",
                  "archive": "Arkivert versjon"}
SYSTEM = (
    "Du hjelper en lærer å erstatte en lenke som ikke virker i et universitetsemne i Canvas. Du får den gamle lenken og "
    "en liste med kandidater som er funnet ved søk, videresending eller i Internet Archive. Velg høyst tre kandidater "
    "som faktisk passer, i denne rekkefølgen: samme ressurs på ny adresse hos utgiveren, en tilsvarende ressurs fra en "
    "relevant og pålitelig kilde, en arkivert versjon. Bruk bare id-ene i listen – aldri en annen adresse. At en side "
    "svarer, betyr ikke at den passer: begrunn faglig hvorfor den kan erstatte lenken, og nevn kjente begrensninger "
    "(innlogging, betaling, annet språk, endret eller eldre innhold). Passer ingen, velg ingen. Skriv på norsk bokmål. "
    "Svar bare med JSON etter skjemaet. " + DATA_RULE
)
SCHEMA = {
    "type": "object",
    "properties": {
        "choices": {"type": "array", "maxItems": 3, "items": {
            "type": "object",
            "properties": {"id": {"type": "string"},
                           "relation": {"type": "string", "enum": ["same", "alternative", "archive"]},
                           "publisher": {"type": "string"}, "reason": {"type": "string"},
                           "limitations": {"type": "array", "items": {"type": "string"}, "maxItems": 3}},
            "required": ["id", "relation", "publisher", "reason", "limitations"], "additionalProperties": False}},
        "note": {"type": "string"},
    },
    "required": ["choices", "note"],
    "additionalProperties": False,
}


@dataclass
class Candidate:
    id: str
    url: str
    origin: str  # redirect | search | archive
    title: str = ""
    archived_at: str | None = None
    target: Target | None = None
    check: dict[str, Any] = field(default_factory=dict)


class AltBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    link_text: str | None = Field(default=None, max_length=300)
    page_title: str | None = Field(default=None, max_length=300)
    module: str | None = Field(default=None, max_length=300)
    confirmed: bool = False
    #: Addresses suggested before («Nye forslag»).
    avoid: list[str] = Field(default_factory=list, max_length=12)


def _client(c: AppContainer, timeout: float) -> httpx.AsyncClient:
    if c.link_transport is not None:  # tests: never the real network
        return httpx.AsyncClient(transport=c.link_transport, follow_redirects=False)
    return build_guarded_client(timeout, max_connections=4)


async def wayback(c: AppContainer, url: str) -> Candidate | None:
    """The closest archived copy (Wayback Machine availability API), or None."""
    address, _ = safe_url(url)  # the archive is asked about the address without credentials or tokens
    request = f"{WAYBACK}?url={quote(address, safe='')}"
    client = _client(c, 8.0)
    try:
        validate_url(request)
        response = await client.get(request, headers={"Accept": "application/json"})
        closest = ((response.json() or {}).get("archived_snapshots") or {}).get("closest") or {} \
            if response.status_code == 200 else {}
    except (UrlBlocked, httpx.HTTPError, ValueError):
        return None
    finally:
        await client.aclose()
    if not closest.get("available") or not str(closest.get("url") or "").startswith(("http://", "https://")):
        return None
    stamp = str(closest.get("timestamp") or "")
    archived = f"{stamp[6:8]}.{stamp[4:6]}.{stamp[0:4]}" if len(stamp) >= 8 else None
    return Candidate("", str(closest["url"]).replace("http://web.archive.org", "https://web.archive.org"), "archive",
                     title="Arkivert kopi i Internet Archive", archived_at=archived)


def _stored(c: AppContainer, course_id: str, url: str) -> dict[str, Any]:
    run = next((r for r in FindingStore(c.db).runs_for(course_id, "content_quality") if (r.scope or {}).get("links")),
               None)
    if run is None:
        return {}
    return next((dict(x) for x in (run.scope or {}).get("links") or [] if x.get("url") == url), {})


def _query(body: AltBody) -> str:
    host = urlsplit(body.url).hostname or ""
    subject = norm_text(body.link_text or "") or norm_text(body.page_title or "")
    return (f"Finn den nye adressen til ressursen «{subject or safe_url(body.url)[0]}» som lå på "
            f"{safe_url(body.url)[0]}. Søk først med site:{host}, deretter etter tilsvarende ressurser fra pålitelige "
            "kilder om samme tema.")


def _summary(c: AppContainer) -> str:
    route = c.ai.search_route(TASK)
    search = (f"Søket (lenketeksten, sidetittelen og den gamle adressen uten tilgangsopplysninger) sendes til "
              f"{route['display_name']}, som søker på nettet. " if route else "")
    return (search + "Den gamle adressen (uten tilgangsopplysninger) slås også opp i Internet Archive (archive.org) "
            "for å finne en arkivert kopi. Deretter sendes den gamle adressen, lenketeksten, sidetittelen og titler og "
            "korte utdrag fra kandidatene til KI-leverandøren for vurdering. Ingen studentdata sendes.")


async def _check(c: AppContainer, url: str) -> dict[str, Any]:
    if not is_checkable(url):
        return {"state": "UNKNOWN", "label": STATE_LABEL["UNKNOWN"], "detail": "Ikke en nettadresse.",
                "checked_at": datetime.now(UTC).isoformat()}
    timeout = float(c.settings.get().analysis.link_timeout_seconds)
    client = _client(c, timeout)
    try:
        result = await LinkChecker(client, timeout=timeout, db=c.db, cache_hours=0).check(url, use_cache=False)
    finally:
        await client.aclose()
    return {"state": result.state, "label": STATE_LABEL.get(result.state, result.state), "detail": result.detail,
            "http_status": result.http_status, "checked_at": result.checked_at.isoformat()}


async def _gather(c: AppContainer, course_id: str, body: AltBody) -> tuple[list[Candidate], bool, str | None]:
    found: list[Candidate] = []
    stored = _stored(c, course_id, body.url)
    final = str(stored.get("final_url") or "")
    if final and final != body.url and stored.get("state") in ("REDIRECT", "WORKING"):
        found.append(Candidate("", final, "redirect", title="Adressen lenken sender videre til"))
    searched, note = False, None
    if c.ai.search_route(TASK) is None:
        note = SEARCH_UNAVAILABLE
    else:
        hits, _ = await c.ai.web_search(TASK, _query(body), summary=_summary(c), confirmed=body.confirmed,
                                        course_id=course_id, max_uses=2)
        searched = True
        found += [Candidate("", h.url, "search", title=norm_text(h.title)[:200]) for h in hits]
    archived = await wayback(c, body.url)
    if archived:
        found.append(archived)
    def key_of(url: str) -> str:  # the same address with or without tokens and fragments
        return safe_url(url)[0].split("#")[0].rstrip("/")

    seen = {key_of(body.url), *(key_of(a) for a in body.avoid)}
    out: list[Candidate] = []
    for cand in found:
        key = key_of(cand.url)
        if key in seen or not is_checkable(cand.url):
            continue
        seen.add(key)
        cand.id = f"k{len(out) + 1}"
        out.append(cand)
        if len(out) >= MAX_CANDIDATES:
            break
    return out, searched, note


def _line(cand: Candidate) -> str:
    target = cand.target
    lines = [f"[{cand.id}] {cand.origin}: {safe_url(cand.url)[0]}",
             f"Tittel: {(target.title if target and target.title else cand.title) or '(ukjent)'}",
             f"Teknisk kontroll: {cand.check.get('label')} ({cand.check.get('detail')})"]
    if cand.archived_at:
        lines.append(f"Arkivert: {cand.archived_at}")
    if target and target.excerpt:
        lines.append(wrap_untrusted_content("Utdrag fra siden", target.excerpt, scrub=True))
    return "\n".join(lines)


@router.post("/courses/{course_id}/links/alternatives/prepare")
async def prepare(course_id: str, body: AltBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Whether KI and web search are available, and what would be sent – nothing is sent yet."""
    require_course_id(course_id)
    plan = c.ai.plan(TASK, input_chars=4000, images=0, summary=_summary(c))
    route = c.ai.search_route(TASK)
    return {**plan, "task": TASK, "search": {"available": route is not None,
                                             "service": route["display_name"] if route else None,
                                             "note": None if route else SEARCH_UNAVAILABLE}}


@router.post("/courses/{course_id}/links/alternatives")
async def alternatives(course_id: str, body: AltBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    plan = c.ai.plan(TASK, input_chars=4000, images=0, summary=_summary(c))
    if not plan["available"]:
        raise AIError("ai_not_configured", status=409, message=plan["reason"] or "KI er ikke tilgjengelig.")
    if plan["needs_confirmation"] and not body.confirmed:
        raise AIError("ai_consent_required", status=409)
    candidates, searched, note = await _gather(c, course_id, body)
    base = {"url": body.url, "searched": searched, "search_note": note, "considered": len(candidates),
            "label": AI_LABEL}
    if not candidates:
        return {**base, "suggestions": [], "none_found": True,
                "note": "Fant ingen kandidater å vurdere – verken ny adresse, søketreff eller arkivert kopi."}
    original, *rest = await asyncio.gather(describe_target(c, body.url),
                                           *(describe_target(c, cand.url) for cand in candidates))
    checks = await asyncio.gather(*(_check(c, cand.url) for cand in candidates))
    for cand, target, check in zip(candidates, rest, checks, strict=True):
        cand.target, cand.check = target, check
    usable = [cand for cand in candidates if cand.check.get("state") != "DEAD"]
    if not usable:
        return {**base, "suggestions": [], "none_found": True,
                "note": "Alle kandidatene fungerer ikke, så ingen er foreslått."}
    prompt = (f"Den gamle lenken: {safe_url(body.url)[0]}\nLenketekst: {body.link_text or '(ingen)'}\n"
              f"Siden lenken står på: {body.page_title or '(ukjent)'}{f' (modul: {body.module})' if body.module else ''}\n"
              f"Om den gamle lenken nå: {original.note}"
              + (f"\nTittel på den gamle ressursen: {original.title}" if original.title else "")
              + "\n\nKandidater:\n\n" + "\n\n".join(_line(cand) for cand in usable) + "\n\nVelg høyst tre.")

    def request(model: str) -> AIRequest:
        return AIRequest(model=model, system=SYSTEM, schema_name="lenkealternativer", json_schema=SCHEMA,
                         max_output_tokens=1200, messages=[AIMessage(parts=[TextPart(text=prompt)])])

    result, _ = await c.ai.run(TASK, request, input_chars=len(prompt), summary=_summary(c), confirmed=body.confirmed,
                               course_id=course_id)
    data = result.data if isinstance(result.data, dict) else {}
    by_id = {cand.id: cand for cand in usable}
    suggestions: list[dict[str, Any]] = []
    for choice in data.get("choices") or []:
        picked = by_id.pop(str(choice.get("id") or ""), None) if isinstance(choice, dict) else None
        if picked is None or len(suggestions) >= 3:
            continue  # an id that is not a candidate is never shown – the model cannot add addresses
        cand = picked
        relation = "archive" if cand.origin == "archive" else str(choice.get("relation") or "alternative")
        relation = relation if relation in ("same", "alternative") or cand.origin == "archive" else "alternative"
        limits = [norm_text(str(x))[:150] for x in choice.get("limitations") or [] if norm_text(str(x))][:3]
        if cand.check.get("state") == "AUTH_REQUIRED" and not any("innlogg" in x.lower() for x in limits):
            limits.append("Krever innlogging.")
        if cand.check.get("state") in ("TIMEOUT", "UNKNOWN"):
            limits.append("Kunne ikke kontrolleres automatisk – åpne og undersøk den selv.")
        found = cand.target
        suggestions.append({
            "url": cand.url, "title": (found.title if found and found.title else cand.title) or cand.url,
            "publisher": norm_text(str(choice.get("publisher") or ""))[:120] or (urlsplit(cand.url).hostname or ""),
            "relation": relation, "relation_label": RELATION_LABEL[relation],
            "reason": norm_text(str(choice.get("reason") or ""))[:400], "limitations": limits,
            "origin": cand.origin, "archived_at": cand.archived_at, "check": cand.check})
    return {**base, "suggestions": suggestions, "none_found": not suggestions,
            "note": norm_text(str(data.get("note") or ""))[:400] or None, "model": result.model,
            "provider": result.provider,
            "provider_name": _provider_name(c, result.provider)}


def _provider_name(c: AppContainer, provider_id: str) -> str:
    config = c.settings.get().provider(provider_id)
    return config.name if config is not None else provider_id
