"""Overview (Oversikt): domain cards, recommended next steps, activity and content statistics.

No single «accessibility percentage» is computed – automated checks cannot support one. Every number shown is a count
of real open findings (open or in the change queue). A finding has exactly one classification (Avvik, Sannsynlig avvik,
Bør vurderes, Forbedringsforslag, Manuell kontroll), so the counts per class never overlap and add up to the total.
Classification says how certain a finding is; severity says how much it matters – they are kept apart.

Times: each card says which analysis runs its findings come from (the newest run of an area wins per content item,
so an area can combine a full analysis with later partial ones). The page shows the newest analysis once and marks
areas whose results are older or combined.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.changes.engine import PUBLISH_JOB
from emneklar.core.container import AppContainer
from emneklar.core.storage.models import AnalysisRun, Finding, Snapshot, SnapshotObject
from emneklar.features.content_quality.api import dead_link_count
from emneklar.features.findings.api import CLASS_ORDER, SEVERITY_ORDER
from emneklar.features.findings.store import FindingStore

router = APIRouter(prefix="/api")

DOMAINS = ("accessibility", "content_quality", "structure", "quiz")
QUIZ_AI_DOMAIN = "quiz_ai"  # the AI review of quiz questions (counted on the Quizassistent page with «quiz»)
#: The findings behind «Fungerer ikke» in the Lenker tab (for the step's priority; the figure counts addresses there).
DEAD_LINK_RULES = ("CQ-LINK-DEAD", "CQ-EMBED-BROKEN", "CQ-LINK-INTERNAL-MISSING")
#: Where the dead links figure opens: Innholdskvalitet → Lenker, «Fungerer ikke» – the rows the figure counts.
DEAD_LINKS_PATH = "/innholdskvalitet?fane=lenker&lenker=broken"
MEDIA_RULES = ("CQ-MEDIA-UNAVAILABLE",)
PLACEMENT_RULES = ("ST-MISPLACED", "ST-ORPHAN")
HIGH = ("critical", "serious")
OPEN = ("open", "staged")
SCOPE_LABELS = {"course": "hele emnet", "modules": "valgte moduler", "items": "valgte elementer"}
DOMAIN_NAMES = {"accessibility": "universell utforming", "content_quality": "innholdskvalitet",
                "structure": "emnestruktur", "quiz": "quizkvalitet"}
JOB_STATUS = {"completed": "Fullført", "failed": "Feilet", "cancelled": "Avbrutt",
              "interrupted": "Avbrutt fordi EmneKlar ble avsluttet", "running": "Pågår", "queued": "Venter",
              "paused": "Satt på pause"}


def num(n: int) -> str:
    """1110 → «1 110» (Norwegian thousands separator, as Intl.NumberFormat("nb-NO") in the browser)."""
    return f"{n:,}".replace(",", " ")


def _n(count: int, one: str, many: str) -> str:
    return f"{num(count)} {one if count == 1 else many}"


def _and(parts: list[str]) -> str:
    """«a, b og c»."""
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " og " + parts[-1]


def _run_info(run: AnalysisRun) -> dict[str, Any]:
    when = run.finished_at or run.started_at
    return {"id": run.id, "scope_type": (run.scope or {}).get("type") or "course", "status": run.status,
            "time": when.isoformat() if when else None,
            # Which areas the run analysed: a full analysis of one area is not a full analysis of every area.
            "domains": [d for d in (run.domains or []) if d in DOMAINS]}


def _latest_full(c: AppContainer, course_id: str) -> dict[str, Any] | None:
    """The newest analysis of the whole course (scope «hele emnet») that finished, whatever areas it covered – so the
    page can tell a later partial analysis apart from the last full one."""
    with c.db.session() as session:
        runs = session.scalars(select(AnalysisRun).where(
            AnalysisRun.course_id == course_id, AnalysisRun.status.in_(("complete", "partial")))
            .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc()).limit(200)).all()
        full = next((r for r in runs if ((r.scope or {}).get("type") or "course") == "course"), None)
        return _run_info(full) if full is not None else None


def _open(store: FindingStore, course_id: str, domain: str) -> tuple[list[Finding], list[AnalysisRun]]:
    rows, runs = store.current(course_id, domain)
    return [r for r in rows if r.status in OPEN], runs


def _domain_card(domain: str, open_rows: list[Finding], runs: list[AnalysisRun]) -> dict[str, Any]:
    by_class = Counter(r.classification for r in open_rows)

    def high(cls: str) -> int:
        return sum(1 for r in open_rows if r.classification == cls and r.severity in HIGH)

    info = [_run_info(r) for r in runs]
    return {
        "domain": domain,
        "analyzed": bool(runs),
        "last_run": info[0]["time"] if info else None,
        "run_id": info[0]["id"] if info else None,
        # Every run that contributed (newest first): more than one means the area combines analyses.
        "runs": info,
        "total": len(open_rows),
        "by_classification": dict(by_class),
        "by_rule": dict(Counter(r.rule_id for r in open_rows)),
        "by_category": dict(Counter(r.category for r in open_rows)),
        "violations_high": high("violation"),
        "likely_high": high("likely_violation"),
        "objects": len({f"{r.object_type}:{r.object_id}" for r in open_rows}),
    }


def _rank(rows: list[Finding]) -> tuple[int, int]:
    """The findings list's own priority (class, then severity – findings/api.py) of the most important finding."""
    return min(((CLASS_ORDER.get(r.classification, 9), SEVERITY_ORDER.get(r.severity, 9)) for r in rows),
               default=(9, 9))


def _path(base: str, **params: str) -> str:
    return f"{base}?{urlencode(params)}" if params else base


def _step(key: str, count: int, rank: tuple[int, int], *, title: str, description: str, action: str,
          path: str | None, tone: str) -> dict[str, Any]:
    return {"key": key, "count": count, "rank": list(rank), "title": title, "description": description,
            "action": action, "path": path, "tone": tone}


def next_steps(rows: dict[str, list[Finding]], changes: dict[str, int], *, dead_links: int = 0) -> list[dict[str, Any]]:
    """Recommended steps, most important first: what the finding means (classification – how certain), then how much it
    matters (severity), then how concrete the follow-up is. A large number of uncertain findings never outranks
    confirmed problems: the order is by class and severity, not by count. Every step opens exactly the findings it
    counts (the list's filters in the path). ``dead_links`` is the «Fungerer ikke» total of the Lenker tab, which the
    dead links step opens."""
    steps: list[dict[str, Any]] = []
    a = rows["accessibility"]
    confirmed = [r for r in a if r.classification == "violation" and r.severity in HIGH]
    if confirmed:
        steps.append(_step(
            "uu-violations", len(confirmed), _rank(confirmed),
            title=f"{_n(len(confirmed), 'avvik', 'avvik')} med høy alvorlighet",
            description=("Bekreftede brudd på et suksesskriterium (kritisk eller alvorlig). Mange kan rettes direkte i "
                         "EmneKlar."),
            action="Se alvorlige avvik", tone="danger",
            path=_path("/universell-utforming", klasse="violation", alvorlighet="critical,serious",
                       utvalg="Avvik med høy alvorlighet")))
    cq = rows["content_quality"]
    dead = [r for r in cq if r.rule_id in DEAD_LINK_RULES]
    if dead_links:
        steps.append(_step(
            "dead-links", dead_links, _rank(dead) if dead else (CLASS_ORDER["violation"], SEVERITY_ORDER["serious"]),
            title=f"{_n(dead_links, 'lenke fungerer', 'lenker fungerer')} ikke",
            description="Adresser som er påvist døde: eksterne lenker som gir en feil (for eksempel 404) og lenker til "
                        "innhold som ikke finnes i emnet.",
            action="Se døde lenker", tone="warning", path=DEAD_LINKS_PATH))
    media = [r for r in cq if r.rule_id in MEDIA_RULES]
    if media:
        steps.append(_step(
            "media", len(media), _rank(media), title=_n(len(media), "video er utilgjengelig", "videoer er utilgjengelige"),
            description="Innebygd video som er fjernet eller privat.", action="Se utilgjengelige videoer", tone="warning",
            path=_path("/innholdskvalitet", regel=",".join(MEDIA_RULES), utvalg="Utilgjengelige videoer")))
    if changes.get("pending"):
        approved = changes.get("approved", 0)
        steps.append(_step(
            "changes", changes["pending"], (0, 5),
            title=(_n(approved, "godkjent endring er klar", "godkjente endringer er klare") + " til publisering"
                   if approved else _n(changes["pending"], "endring venter", "endringer venter") + " i endringskøen"),
            description=("Publiser dem til Canvas fra endringskøen." if approved
                         else "Godkjenn og publiser, eller fjern forslag du ikke vil bruke."),
            action="Åpne endringskøen", tone="success", path=None))
    likely = [r for r in a if r.classification == "likely_violation" and r.severity in HIGH]
    if likely:
        steps.append(_step(
            "uu-likely", len(likely), _rank(likely),
            title=f"{_n(len(likely), 'sannsynlig avvik', 'sannsynlige avvik')} med høy alvorlighet bør kontrolleres",
            description="Sterke indikasjoner, men ikke bekreftet. Kontroller funnet før du retter.",
            action="Se sannsynlige avvik", tone="warning",
            path=_path("/universell-utforming", klasse="likely_violation", alvorlighet="critical,serious",
                       utvalg="Sannsynlige avvik med høy alvorlighet")))
    quiz = rows["quiz"] + rows[QUIZ_AI_DOMAIN]
    if quiz:
        steps.append(_step(
            "quiz", len(quiz), _rank(quiz),
            title=f"{_n(len(quiz), 'mulig feil', 'mulige feil')} i quizene bør kontrolleres",
            description="Fasit, svaralternativer eller duplikater. Antallet står som «åpne funn» i Quizassistenten.",
            action="Se quizene", tone="info", path="/quizassistent"))
    placement = [r for r in rows["structure"] if r.rule_id in PLACEMENT_RULES]
    if placement:
        steps.append(_step(
            "placement", len(placement), _rank(placement),
            title=_n(len(placement), "element kan være feilplassert", "elementer kan være feilplassert"),
            description="Innhold som ikke ligger i en modul eller ser ut til å høre hjemme et annet sted.",
            action="Se plasseringsforslag", tone="info",
            path=_path("/emnestruktur", regel=",".join(PLACEMENT_RULES), utvalg="Mulig feilplassert innhold")))
    manual = [r for r in a if r.classification == "manual_check"]
    if manual:
        steps.append(_step(
            "uu-manual", len(manual), _rank(manual),
            title=f"{_n(len(manual), 'punkt krever', 'punkter krever')} manuell kontroll",
            description="Kan ikke avgjøres automatisk, for eksempel teksting av video og innhold i eksterne verktøy.",
            action="Se manuelle kontroller", tone="violet",
            path=_path("/universell-utforming", klasse="manual_check", utvalg="Manuell kontroll")))
    order = {s["key"]: i for i, s in enumerate(steps)}
    return sorted(steps, key=lambda s: (s["rank"][0], s["rank"][1], order[s["key"]]))


def _analysis_entry(job: dict[str, Any]) -> dict[str, Any]:
    params = job.get("params") or {}
    scope = SCOPE_LABELS.get(str(params.get("scope") or "course"), "emnet")
    domains = _and([DOMAIN_NAMES[d] for d in params.get("domains") or [] if d in DOMAIN_NAMES])
    status = job["status"]
    if status == "completed":
        title, detail = f"{scope[0].upper()}{scope[1:]} analysert", (domains[0].upper() + domains[1:]) if domains else None
    else:
        title, detail = f"Analyse av {scope}", JOB_STATUS.get(status, status)
    return {"type": "analysis", "time": job["finished_at"] or job["created_at"], "title": title, "detail": detail,
            "status": status}


def activity(jobs: list[dict[str, Any]], log: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Analyses, other jobs and published changes, newest first. A publish job and the change-log entries it wrote are
    the same event: the entries (what was changed, in which content, with what result) are shown, not the job. A job
    whose entries are not in the list (e.g. it failed before writing any) is still shown. Nothing is deleted."""
    logged = {e["id"] for e in log}
    items: list[dict[str, Any]] = []
    for job in jobs:
        if job["kind"] == PUBLISH_JOB:
            log_ids = {r.get("log_id") for r in (job.get("result") or {}).get("results") or [] if r.get("log_id")}
            if log_ids & logged:
                continue
            count = len((job.get("params") or {}).get("change_ids") or []) or 1
            items.append({"type": "job", "time": job["finished_at"] or job["created_at"],
                          "title": "Publisering av " + _n(count, "endring", "endringer"),
                          "detail": JOB_STATUS.get(job["status"], job["status"]), "status": job["status"]})
        elif job["kind"] == "analysis":
            items.append(_analysis_entry(job))
        else:
            items.append({"type": "job", "time": job["finished_at"] or job["created_at"], "title": job["title"],
                          "detail": JOB_STATUS.get(job["status"], job["status"]), "status": job["status"]})
    for e in log:
        items.append({"type": "change", "time": e["timestamp"], "title": e["object_title"] or e["summary"] or "Endring",
                      "object_type": e["object_type"], "summary": e["summary"], "status": e["action"],
                      "detail": None})
    return sorted(items, key=lambda x: x["time"] or "", reverse=True)[:limit]


def _stats(c: AppContainer, course_id: str) -> dict[str, Any] | None:
    """Course content from the snapshot of the newest analysis (a snapshot always reads the whole course, also for an
    analysis of selected items). Dated with that analysis, like the rest of the page."""
    with c.db.session() as session:
        run = session.scalars(select(AnalysisRun).where(
            AnalysisRun.course_id == course_id, AnalysisRun.snapshot_id.is_not(None),
            AnalysisRun.status.in_(("complete", "partial", "cancelled")))
            .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc()).limit(1)).first()
        snap = session.get(Snapshot, run.snapshot_id) if run is not None and run.snapshot_id else None
        if run is None or snap is None or snap.status not in ("complete", "partial"):
            return None
        rows = session.execute(select(SnapshotObject.object_type, SnapshotObject.meta)
                               .where(SnapshotObject.snapshot_id == snap.id)).all()
        when = run.finished_at or run.started_at
        run_id = run.id
    counts = Counter(t for t, _ in rows)
    unpublished = sum(1 for t, meta in rows if t in ("page", "assignment", "quiz", "discussion")
                      and (meta or {}).get("published") is False)
    return {"run_id": run_id, "analysed_at": when.isoformat() if when else None, "pages": counts.get("page", 0),
            "modules": counts.get("module", 0), "module_items": counts.get("module_item", 0),
            "assignments": counts.get("assignment", 0), "quizzes": counts.get("quiz", 0),
            "discussions": counts.get("discussion", 0), "files": counts.get("file", 0),
            "media": counts.get("media", 0), "unpublished": unpublished}


@router.get("/courses/{course_id}/overview")
async def overview(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    store = FindingStore(c.db)
    rows: dict[str, list[Finding]] = {}
    cards: dict[str, dict[str, Any]] = {}
    for domain in (*DOMAINS, QUIZ_AI_DOMAIN):
        open_rows, runs = _open(store, course_id, domain)
        rows[domain] = open_rows
        if domain in DOMAINS:
            cards[domain] = _domain_card(domain, open_rows, runs)
    # The Quizassistent page counts the AI review with the deterministic quiz checks – so does the card.
    quiz_all = rows["quiz"] + rows[QUIZ_AI_DOMAIN]
    cards["quiz"]["total_with_ai"] = len(quiz_all)
    cards["quiz"]["objects"] = len({f"{r.object_type}:{r.object_id}" for r in quiz_all})
    # The same findings by what they are about: whole quizzes, and single questions (both carry the quiz they are in).
    cards["quiz"]["quizzes_affected"] = len({str((r.evidence or {}).get("quiz_id") or r.object_id) for r in quiz_all
                                             if r.object_type in ("quiz", "quiz_question")})
    cards["quiz"]["questions_affected"] = len({r.object_id for r in quiz_all if r.object_type == "quiz_question"})
    # The same figure as «Fungerer ikke» in Innholdskvalitet → Lenker: addresses, external and internal.
    dead_links = dead_link_count(c, course_id) if cards["content_quality"]["analyzed"] else 0
    cards["content_quality"]["dead_links"] = dead_links
    analysed = [card for card in cards.values() if card["analyzed"]]
    newest = max(analysed, key=lambda card: card["last_run"] or "", default=None)
    latest = next((r for r in newest["runs"] if r["id"] == newest["run_id"]), None) if newest else None
    changes = c.changes.summary(course_id)
    jobs = c.jobs.history(course_id=course_id, limit=8)
    log = c.changes.changelog(course_id, limit=12)["items"]
    return {"cards": cards, "analysis": latest, "full_analysis": _latest_full(c, course_id),
            "next_steps": next_steps(rows, changes, dead_links=dead_links), "activity": activity(jobs, log),
            "stats": _stats(c, course_id), "pending_changes": changes["pending"]}
