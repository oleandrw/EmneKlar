"""Overview (Oversikt): domain cards, recommended next steps, activity and content statistics.

No single «accessibility percentage» is computed – automated checks cannot
support one. Every number shown is a count of real findings.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.container import AppContainer
from emneklar.core.storage.models import Snapshot, SnapshotObject
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")

DOMAINS = ("accessibility", "content_quality", "structure", "quiz")
DEAD_LINK_RULES = {"CQ-LINK-DEAD", "CQ-LINK-INTERNAL-MISSING"}
MEDIA_RULES = {"CQ-MEDIA-UNAVAILABLE"}
PLACEMENT_RULES = {"ST-MISPLACED", "ST-ORPHAN"}


def _domain_card(store: FindingStore, course_id: str, domain: str) -> dict[str, Any]:
    rows, runs = store.current(course_id, domain)
    open_rows = [r for r in rows if r.status in ("open", "staged")]
    by_class = Counter(r.classification for r in open_rows)
    by_rule = Counter(r.rule_id for r in open_rows)
    serious = sum(1 for r in open_rows if r.classification in ("violation", "likely_violation")
                  and r.severity in ("critical", "serious"))
    last = runs[0] if runs else None
    return {
        "domain": domain,
        "analyzed": last is not None,
        "last_run": (last.finished_at or last.started_at).isoformat() if last else None,
        "total": len(open_rows),
        "by_classification": dict(by_class),
        "by_rule": dict(by_rule),
        "serious": serious,
        "objects": len({f"{r.object_type}:{r.object_id}" for r in open_rows}),
    }


def _next_steps(cards: dict[str, dict[str, Any]], pending_changes: int) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    a = cards["accessibility"]
    if a["serious"]:
        steps.append({"key": "uu-serious", "count": a["serious"], "domain": "accessibility",
                      "title": f"{a['serious']} alvorlige UU-funn bør gjennomgås",
                      "description": "Avvik og sannsynlige avvik med høy alvorlighet.",
                      "path": "/universell-utforming", "tone": "danger"})
    manual = a["by_classification"].get("manual_check", 0)
    if manual:
        steps.append({"key": "uu-manual", "count": manual, "domain": "accessibility",
                      "title": f"{_n(manual, 'punkt krever', 'punkter krever')} manuell kontroll",
                      "description": "For eksempel teksting av ekstern video og innhold i eksterne verktøy.",
                      "path": "/universell-utforming", "tone": "violet"})
    c = cards["content_quality"]
    dead = sum(c["by_rule"].get(r, 0) for r in DEAD_LINK_RULES)
    if dead:
        steps.append({"key": "dead-links", "count": dead, "domain": "content_quality",
                      "title": f"{_n(dead, 'lenke fungerer', 'lenker fungerer')} ikke",
                      "description": "Døde eksterne eller interne lenker.",
                      "path": "/innholdskvalitet", "tone": "warning"})
    media = sum(c["by_rule"].get(r, 0) for r in MEDIA_RULES)
    if media:
        steps.append({"key": "media", "count": media, "domain": "content_quality",
                      "title": f"{_n(media, 'video er utilgjengelig', 'videoer er utilgjengelige')}",
                      "description": "Innebygd video som er fjernet eller privat.",
                      "path": "/innholdskvalitet", "tone": "warning"})
    s = cards["structure"]
    placement = sum(s["by_rule"].get(r, 0) for r in PLACEMENT_RULES)
    if placement:
        steps.append({"key": "placement", "count": placement, "domain": "structure",
                      "title": f"{_n(placement, 'element kan være feilplassert', 'elementer kan være feilplassert')}",
                      "description": "Innhold som ikke ligger i en modul eller ser ut til å høre hjemme et annet sted.",
                      "path": "/emnestruktur", "tone": "info"})
    q = cards["quiz"]
    if q["objects"]:
        steps.append({"key": "quiz", "count": q["objects"], "domain": "quiz",
                      "title": f"{q['objects']} quizspørsmål bør kvalitetssikres",
                      "description": "Fasit, svaralternativer eller duplikater bør kontrolleres.",
                      "path": "/quizassistent", "tone": "info"})
    if pending_changes:
        steps.append({"key": "changes", "count": pending_changes, "domain": "changes",
                      "title": f"{_n(pending_changes, 'endring venter', 'endringer venter')} i endringskøen",
                      "description": "Godkjenn og gjennomfør, eller fjern forslag du ikke vil bruke.",
                      "path": None, "tone": "success"})
    return steps


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _stats(c: AppContainer, course_id: str) -> dict[str, Any] | None:
    with c.db.session() as session:
        snap = session.scalars(select(Snapshot).where(Snapshot.course_id == course_id,
                                                      Snapshot.status.in_(("complete", "partial")))
                               .order_by(Snapshot.created_at.desc()).limit(1)).first()
        if snap is None:
            return None
        rows = session.execute(select(SnapshotObject.object_type, SnapshotObject.meta)
                               .where(SnapshotObject.snapshot_id == snap.id)).all()
    counts = Counter(t for t, _ in rows)
    unpublished = sum(1 for t, meta in rows if t in ("page", "assignment", "quiz", "discussion")
                      and (meta or {}).get("published") is False)
    return {"snapshot_at": snap.created_at.isoformat(), "pages": counts.get("page", 0),
            "modules": counts.get("module", 0), "module_items": counts.get("module_item", 0),
            "assignments": counts.get("assignment", 0), "quizzes": counts.get("quiz", 0),
            "discussions": counts.get("discussion", 0), "files": counts.get("file", 0),
            "media": counts.get("media", 0), "unpublished": unpublished}


@router.get("/courses/{course_id}/overview")
async def overview(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    store = FindingStore(c.db)
    cards = {d: _domain_card(store, course_id, d) for d in DOMAINS}
    pending = c.changes.summary(course_id)["pending"]
    jobs = c.jobs.history(course_id=course_id, limit=6)
    log = c.changes.changelog(course_id, limit=6)["items"]
    activity = sorted(
        [{"type": "job", "time": j["finished_at"] or j["created_at"], "title": j["title"], "status": j["status"]}
         for j in jobs]
        + [{"type": "change", "time": e["timestamp"], "title": e["object_title"] or e["kind"], "status": e["action"],
            "dry_run": e["dry_run"]} for e in log],
        key=lambda x: x["time"] or "", reverse=True)[:8]
    return {"cards": cards, "next_steps": _next_steps(cards, pending), "activity": activity,
            "stats": _stats(c, course_id), "pending_changes": pending}
