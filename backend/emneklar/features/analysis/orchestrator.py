"""The global analysis job: snapshot → plan → run analyzers → store findings.

Progress is real: during discovery the bar shows content lists fetched (not a
percentage of unknown work); the determinate phase counts actual tasks per
content type, and the ETA comes from observed task durations.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.snapshot import CONTENT_LISTS, SnapshotBuilder, SnapshotView
from emneklar.core.jobs.manager import JobCancelled, JobContext
from emneklar.core.storage.models import AnalysisRun
from emneklar.features.accessibility.profiles import get_profile
from emneklar.features.accessibility.rules import load_ruleset
from emneklar.features.analysis.core import AnalysisContext, AnalysisRequest, AnalysisTask, Analyzer
from emneklar.features.findings.store import FindingDraft, FindingStore

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

log = logging.getLogger(__name__)

TASK_CONCURRENCY = 6
OBJECT_TYPE_LABEL = {"page": "Sider", "assignment": "Oppgaver", "discussion": "Diskusjoner", "quiz": "Quiz",
                     "syllabus": "Emneplan"}
GENERAL_LIMITATION = ("Automatiske kontroller kan ikke bevise at innholdet er universelt utformet. Funn merket "
                      "«Manuell kontroll» og innhold i eksterne verktøy må vurderes av et menneske.")


ANALYZERS = {
    "accessibility": "emneklar.features.accessibility.analyzer:AccessibilityAnalyzer",
    "content_quality": "emneklar.features.content_quality.analyzer:ContentQualityAnalyzer",
    "structure": "emneklar.features.course_structure.analyzer:StructureAnalyzer",
    "quiz": "emneklar.features.quiz_assistant.analyzer:QuizAnalyzer",
}


def analyzers_for(domains: list[str]) -> list[Analyzer]:
    import importlib

    result: list[Analyzer] = []
    for domain in domains:
        module_name, class_name = ANALYZERS[domain].split(":")
        result.append(getattr(importlib.import_module(module_name), class_name)())
    return result


def interleave(tasks: list[AnalysisTask]) -> list[AnalysisTask]:
    """Round-robin over task types so the ETA learns every type's cost early."""
    queues: dict[str, deque[AnalysisTask]] = defaultdict(deque)
    order: list[str] = []
    for task in tasks:
        if task.type not in queues:
            order.append(task.type)
        queues[task.type].append(task)
    result: list[AnalysisTask] = []
    while any(queues.values()):
        for kind in order:
            if queues[kind]:
                result.append(queues[kind].popleft())
    return result


async def run_analysis(job: JobContext, container: AppContainer, request: AnalysisRequest) -> dict[str, Any]:
    settings = container.settings.get()
    progress = job.progress
    client = container.canvas()
    api = CanvasAPI(client)
    store = FindingStore(container.db)

    # -- phase 1: one download of the course -------------------------------------------------
    progress.set_phase("discover", "Henter innhold fra Canvas", index=1, count=2, determinate=False)
    progress.add_tasks("list", len(CONTENT_LISTS))
    started: dict[str, float] = {}

    def on_start(kind: str, label: str) -> None:
        started[kind] = progress.start("list", item=label, operation="Henter innholdsliste")

    def on_done(kind: str, label: str, count: int, error: str | None) -> None:
        progress.finish("list", started.pop(kind), failed=error is not None)
        if error:
            progress.note(f"{label}: {error}")

    builder = SnapshotBuilder(container.db, api, client.base_url)
    snapshot_id = await builder.build(request.course_id, scope=request.model_dump(), on_start=on_start,
                                      on_done=on_done, checkpoint=job.checkpoint)
    view = SnapshotView.load(container.db, snapshot_id)
    profile = get_profile(settings.analysis.regulatory_profile)
    ruleset = load_ruleset()

    with container.db.session() as session:
        run = AnalysisRun(job_id=job.job_id, course_id=request.course_id, snapshot_id=snapshot_id,
                          domains=list(request.domains), scope={"type": request.scope},
                          ruleset_version=ruleset.version, profile_id=profile.id, profile_version=profile.version)
        session.add(run)
        session.flush()
        run_id = run.id

    ctx = AnalysisContext(container=container, course_id=request.course_id, run_id=run_id, view=view,
                          request=request, settings=settings, profile=profile, api=api,
                          canvas_base=client.base_url)
    for error in view.errors:
        ctx.limitations.append(f"{error['label']} kunne ikke hentes: {error['message']}")

    # -- phase 2: plan ---------------------------------------------------------------------------
    analyzers = analyzers_for(list(request.domains))
    tasks: list[AnalysisTask] = []
    object_checks = [(a.domain, check) for a in analyzers if (check := a.object_check(ctx)) is not None]
    covered: dict[str, set[str]] = {d: set() for d in request.domains}
    if object_checks:
        for obj in ctx.html_objects():
            if obj.body is None:
                continue  # block-editor pages: handled by the accessibility analyzer as manual checks
            tasks.append(_object_task(ctx, obj, object_checks))
            for domain, _ in object_checks:
                covered[domain].add(obj.ref)
    for analyzer in analyzers:
        for task in analyzer.tasks(ctx):
            tasks.append(task)
            covered[analyzer.domain].update(task.objects)
    tasks = interleave(tasks)

    progress.set_phase("analyze", "Analyserer innholdet", index=2, count=2, determinate=True)
    for task in tasks:
        progress.add_tasks(task.type)

    status = "complete"
    failures = 0
    queue: deque[AnalysisTask] = deque(tasks)

    async def worker() -> None:
        nonlocal failures
        while queue:
            await job.checkpoint()
            if not queue:
                return
            task = queue.popleft()
            t0 = progress.start(task.type, item=task.item, operation=task.operation)
            failed = False
            drafts: list[FindingDraft] = []
            try:
                drafts = await task.run()
            except (JobCancelled, asyncio.CancelledError):
                progress.finish(task.type, t0, failed=True)
                raise
            except Exception as exc:  # one broken object must not stop the analysis
                failed = True
                failures += 1
                log.warning("Analyseoppgave feilet (%s, %s): %s", task.type, task.item, type(exc).__name__,
                            exc_info=not hasattr(exc, "code"))
                progress.note(f"Kunne ikke analysere {task.item}")
            progress.finish(task.type, t0, failed=failed)
            if drafts:
                await asyncio.to_thread(store.save, run_id, request.course_id, drafts)
                for draft in drafts:
                    progress.add_findings(f"{draft.domain}:{draft.classification}")

    try:
        async with asyncio.TaskGroup() as group:
            for _ in range(max(1, min(TASK_CONCURRENCY, len(tasks)))):
                group.create_task(worker())
    except* (JobCancelled, asyncio.CancelledError):
        status = "cancelled"
    finally:
        for close in ctx.shared.get("closers", []):
            try:
                await close()
            except Exception:  # noqa: BLE001 - closing must never fail the analysis
                log.debug("Kunne ikke lukke klient", exc_info=True)
    if failures:
        ctx.limitations.append(f"{failures} element(er) kunne ikke analyseres. Se loggen for detaljer.")
    if status == "complete" and (failures or view.errors):
        status = "partial"
    ctx.limitations.append(GENERAL_LIMITATION)

    counts = dict(progress.snapshot()["findings"])
    with container.db.session() as session:
        row = session.get(AnalysisRun, run_id)
        assert row is not None
        row.status = status
        row.finished_at = datetime.now(UTC)
        row.counts = counts
        row.limitations = ctx.limitations
        row.scope = {"type": request.scope, "module_ids": request.module_ids,
                     "items": [i.model_dump() for i in request.items],
                     "objects": {d: sorted(v) for d, v in covered.items()},
                     "links": list(ctx.shared.get("link_results", {}).values()),
                     "stats": {k: len(view.get(k)) for k in ("page", "assignment", "discussion", "quiz", "file",
                                                              "module", "module_item", "media")}}
    if status == "cancelled":
        raise JobCancelled
    return {"run_id": run_id, "snapshot_id": snapshot_id, "status": status, "counts": counts,
            "limitations": ctx.limitations}


def _object_task(ctx: AnalysisContext, obj: Any, checks: list[tuple[str, Any]]) -> AnalysisTask:
    async def run() -> list[FindingDraft]:
        doc = ctx.content_doc(obj)
        drafts: list[FindingDraft] = []
        for _domain, check in checks:
            drafts.extend(await check(doc, obj))
        return drafts

    domains = {d for d, _ in checks}
    operation = "Bilder, lenker og HTML" if "accessibility" in domains else "HTML og lenker"
    return AnalysisTask(type=obj.object_type, item=ctx.view.location_label(obj), operation=operation,
                        domain="accessibility" if "accessibility" in domains else next(iter(domains)), run=run,
                        objects=[obj.ref])
