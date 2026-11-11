"""Content quality: link overview and re-checking a single link.

The overview groups the checker's states into what they mean for the teacher – «Fungerer» (WORKING, REDIRECT),
«Fungerer ikke» (DEAD: a concrete error such as 404/410 or a domain that does not exist), «Krever innlogging»
(AUTH_REQUIRED: 401/407 or a redirect to a login page) and «Kunne ikke kontrolleres» (TIMEOUT, UNKNOWN: 403, 429, 5xx,
no answer – not proof of a broken link). Totals, filters and rows use the same grouping; the technical state, HTTP status
and method stay in the details. «Sjekk på nytt» stores the new result, so the row and the totals agree.

A **dead link** is one address the analysis proved does not work: an external address with the state DEAD, or an
internal link to course content that does not exist (CQ-LINK-INTERNAL-MISSING – one row per address, from the open
findings). Both are «Fungerer ikke» here, and Oversikt counts the same rows (``dead_link_count``).
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.canvas.html import norm_text
from emneklar.core.canvas.links import content_links
from emneklar.core.container import AppContainer
from emneklar.core.security.guarded_http import build_guarded_client
from emneklar.core.storage.models import AnalysisRun, Finding
from emneklar.features.accessibility.checks.structure import VAGUE
from emneklar.features.content_quality.hygiene import CLEANUP_OPTIONS
from emneklar.features.content_quality.linkcheck import LinkChecker, is_checkable
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")
CATEGORY = {"WORKING": "working", "REDIRECT": "working", "DEAD": "broken", "AUTH_REQUIRED": "login",
            "TIMEOUT": "unchecked", "UNKNOWN": "unchecked"}
CATEGORY_LABEL = {"broken": "Fungerer ikke", "login": "Krever innlogging", "unchecked": "Kunne ikke kontrolleres",
                  "working": "Fungerer"}
METHOD = "Automatisk kontroll uten innlogging: først HEAD, deretter GET når svaret er en feil."
INTERNAL_MISSING = "CQ-LINK-INTERNAL-MISSING"
INTERNAL_DETAIL = "Peker til innhold som ikke finnes i emnet (slettet, flyttet eller feil adresse)."
INTERNAL_METHOD = "Kontrollert mot emnets eget innhold i Canvas under analysen."
LOCATION_KEYS = ("module", "module_id", "module_item_id", "modules")


def _title(item: dict[str, Any]) -> str | None:
    """A descriptive title from the link text in the content – never made up; None means «show the address»."""
    for use in item.get("uses") or []:
        text = norm_text(str(use.get("text") or ""))
        if len(text) >= 3 and text.lower().strip(" .:!»«\"'") not in VAGUE and \
                not text.lower().startswith(("http://", "https://", "www.")):
            return text
    return None


def _decorate(item: dict[str, Any]) -> dict[str, Any]:
    category = CATEGORY.get(str(item.get("state")), "unchecked")
    uses = item.get("uses") or []
    return {**item, "category": category, "category_label": CATEGORY_LABEL[category], "method": METHOD,
            "title": _title(item), "places": len(uses),
            "occurrences": sum(int(u.get("count") or 1) for u in uses)}


def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(CATEGORY.get(str(x.get("state")), "unchecked") for x in items))


def _internal_links(current: list[Finding], base_url: str | None, checked_at: str | None) -> list[dict[str, Any]]:
    """Internal links to content that does not exist, one row per address (as written in the content, so «Endre lenke»
    finds it), with the places it is used. There is no web check behind them: the analysis compared them with the
    course's own content."""
    rows: dict[str, dict[str, Any]] = {}
    for f in current:
        href = str((f.evidence or {}).get("href") or "").strip()
        if f.rule_id != INTERNAL_MISSING or f.status not in ("open", "staged") or not href:
            continue
        row = rows.setdefault(href, {
            "url": href, "open_url": urljoin(f"{base_url.rstrip('/')}/", href) if base_url else None, "kind": "internal",
            "state": "DEAD", "detail": INTERNAL_DETAIL, "method": INTERNAL_METHOD, "http_status": None,
            "final_url": None, "checked_at": checked_at, "confidence": "high", "uses": []})
        location = f.location or {}
        row["uses"].append({"object_type": f.object_type, "object_id": f.object_id, "title": f.object_title or "",
                            "url": f.object_url, "count": 1, "kind": "link",
                            "text": (f.evidence or {}).get("link_text"),
                            **{k: location[k] for k in LOCATION_KEYS if k in location}})
    return list(rows.values())


def link_rows(c: AppContainer, course_id: str) -> tuple[list[dict[str, Any]], AnalysisRun | None, list[Finding]]:
    """The rows of the Lenker tab before they are decorated: the last link check, plus internal dead links. Also the
    run the check comes from (the newest content quality run when there is no check) and the current findings."""
    store = FindingStore(c.db)
    runs = store.runs_for(course_id, "content_quality")
    with_links = [r for r in runs if (r.scope or {}).get("links")]
    # A cancelled check only reached some of the links: the last finished check is kept while there is one.
    run = next((r for r in with_links if r.status != "cancelled"), with_links[0] if with_links else None)
    items = [dict(x) for x in (run.scope or {}).get("links") or []] if run is not None else []
    current, _ = store.current(course_id, "content_quality")
    source = run or (runs[0] if runs else None)
    checked_at = (source.finished_at or source.started_at).isoformat() if source is not None else None
    items += _internal_links(current, c.settings.get().canvas.base_url, checked_at)
    return items, source, current


def dead_link_count(c: AppContainer, course_id: str) -> int:
    """How many addresses do not work – the «Fungerer ikke» total of the Lenker tab, which Oversikt shows."""
    items, _, _ = link_rows(c, course_id)
    return sum(1 for x in items if CATEGORY.get(str(x.get("state"))) == "broken")


@router.get("/courses/{course_id}/links")
async def links(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    items, run, current = link_rows(c, course_id)
    if run is None or not items:
        return {"links": [], "summary": {}, "checked_at": None, "run_status": None}
    order = {"broken": 0, "login": 1, "unchecked": 2, "working": 3}
    items.sort(key=lambda x: (order[CATEGORY.get(str(x.get("state")), "unchecked")], str(x.get("url"))))
    base_url = c.settings.get().canvas.base_url
    # The open finding for each (address, content) pair, so «Brukt i» can open the fix directly.
    finding_of = {(str((f.evidence or {}).get("href")), f"{f.object_type}:{f.object_id}"): f.id for f in current
                  if f.status in ("open", "staged") and (f.evidence or {}).get("href")}
    for item in items:
        uses = item.get("uses") or [_use_from_legacy(ref) for ref in item.get("used_in") or []]
        for use in uses:
            links_for = content_links(base_url, course_id, use.get("object_type"), use.get("object_id"),
                                      object_url=use.get("url"), location=use,
                                      evidence={"link_text": use.get("text")})
            use["canvas"] = links_for
            use["finding_id"] = finding_of.get((str(item.get("url")), f"{use.get('object_type')}:{use.get('object_id')}"))
        item["uses"] = uses
    return {"links": [_decorate(item) for item in items], "summary": _summary(items),
            "category_labels": CATEGORY_LABEL, "states": dict(Counter(str(x.get("state")) for x in items)),
            "checked_at": (run.finished_at or run.started_at).isoformat(), "run_status": run.status}


def _use_from_legacy(ref: str) -> dict[str, Any]:
    """Older analyses stored «type:id|title» only."""
    head, _, title = ref.partition("|")
    object_type, _, object_id = head.partition(":")
    return {"object_type": object_type, "object_id": object_id, "title": title or head, "count": None}


class RecheckBody(BaseModel):
    url: str = Field(max_length=2000)
    #: The course whose overview stores the new result (the row and the totals then agree).
    course_id: str | None = Field(default=None, max_length=32)


def _store_result(c: AppContainer, course_id: str, result: dict[str, Any]) -> dict[str, int] | None:
    runs = FindingStore(c.db).runs_for(course_id, "content_quality")
    run_id = next((r.id for r in runs if (r.scope or {}).get("links")), None)
    if run_id is None:
        return None
    with c.db.session() as session:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            return None
        scope = dict(run.scope or {})
        links_now = [dict(x) for x in scope.get("links") or []]
        for item in links_now:
            if item.get("url") == result["url"]:
                item.update({k: result[k] for k in ("state", "detail", "http_status", "final_url", "checked_at",
                                                     "confidence") if k in result}, from_cache=False)
        scope["links"] = links_now
        run.scope = scope
    # The totals of the tab: the re-checked external links and the internal dead links (which have no web check).
    current, _ = FindingStore(c.db).current(course_id, "content_quality")
    return _summary(links_now + _internal_links(current, c.settings.get().canvas.base_url, None))


@router.post("/content-quality/recheck")
async def recheck(body: RecheckBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if not is_checkable(body.url):
        return {"url": body.url, "state": "UNKNOWN", "category": "unchecked",
                "category_label": CATEGORY_LABEL["unchecked"], "detail": "Bare http- og https-lenker kan kontrolleres."}
    settings = c.settings.get().analysis
    client = httpx.AsyncClient(transport=c.link_transport, follow_redirects=False) if c.link_transport is not None \
        else build_guarded_client(float(settings.link_timeout_seconds))
    try:
        checker = LinkChecker(client, timeout=float(settings.link_timeout_seconds), db=c.db, cache_hours=0)
        result = await checker.check(body.url, use_cache=False)
    finally:
        await client.aclose()
    data = result.as_dict()
    category = CATEGORY.get(result.state, "unchecked")
    summary = _store_result(c, require_course_id(body.course_id), data) if body.course_id else None
    return {**data, "category": category, "category_label": CATEGORY_LABEL[category], "method": METHOD,
            "summary": summary}


@router.get("/content-quality/cleanup-options")
async def cleanup_options() -> dict[str, Any]:
    return {"options": [{"id": k, "label": v} for k, v in CLEANUP_OPTIONS.items()]}
