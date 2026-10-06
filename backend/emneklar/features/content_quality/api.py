"""Content quality: link overview and re-checking a single link."""

from __future__ import annotations

from collections import Counter
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.container import AppContainer
from emneklar.core.security.guarded_http import build_guarded_client
from emneklar.features.content_quality.hygiene import CLEANUP_OPTIONS
from emneklar.features.content_quality.linkcheck import LinkChecker, is_checkable
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/links")
async def links(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    runs = FindingStore(c.db).runs_for(course_id, "content_quality")
    run = next((r for r in runs if (r.scope or {}).get("links")), None)
    if run is None:
        return {"links": [], "summary": {}, "checked_at": None}
    items = list((run.scope or {}).get("links") or [])
    order = {"DEAD": 0, "TIMEOUT": 1, "AUTH_REQUIRED": 2, "UNKNOWN": 3, "REDIRECT": 4, "WORKING": 5}
    items.sort(key=lambda x: (order.get(str(x.get("state")), 9), str(x.get("url"))))
    return {"links": items, "summary": dict(Counter(str(x.get("state")) for x in items)),
            "checked_at": (run.finished_at or run.started_at).isoformat()}


class RecheckBody(BaseModel):
    url: str = Field(max_length=2000)


@router.post("/content-quality/recheck")
async def recheck(body: RecheckBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if not is_checkable(body.url):
        return {"url": body.url, "state": "UNKNOWN", "detail": "Bare http- og https-lenker kan kontrolleres."}
    settings = c.settings.get().analysis
    client = httpx.AsyncClient(transport=c.link_transport, follow_redirects=False) if c.link_transport is not None \
        else build_guarded_client(float(settings.link_timeout_seconds))
    try:
        checker = LinkChecker(client, timeout=float(settings.link_timeout_seconds), db=c.db, cache_hours=0)
        result = await checker.check(body.url, use_cache=False)
    finally:
        await client.aclose()
    return result.as_dict()


@router.get("/content-quality/cleanup-options")
async def cleanup_options() -> dict[str, Any]:
    return {"options": [{"id": k, "label": v} for k, v in CLEANUP_OPTIONS.items()]}
