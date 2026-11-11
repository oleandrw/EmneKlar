"""The shared change engine – the only path from EmneKlar to a Canvas write.

    stage → (edit/remove) → approve → publish job («Publiser til Canvas»):
        already published? → skip (never written twice)
        conflict? → fetch live state, compare with «before»:
                      · the change is already stored in Canvas (an earlier attempt's answer was lost) → mark published
                      · EmneKlar itself just changed the same content in this publish → rebuild the change on the new
                        content (recipe-based changes only) and continue
                      · otherwise → stop and ask for review (newer work in Canvas is never overwritten)
        backup    → JSON copy of the live object
        write     → typed API + WritePermit
        verify    → read back from Canvas, log before/after/API result
    undo (where supported) → conflict check against what EmneKlar wrote → restore → log

Several changes to the same content are published one after the other in a fixed order (changes that cannot be
rebuilt first, recipe-based fixes after them, Blueprint syncs last), so one fix never overwrites another.
Undo is never promised universally: each change kind declares full/partial/none.
"""

from __future__ import annotations

import builtins
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from emneklar.core.backup.store import BackupStore
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.blueprint import blueprint_info, is_blueprint_lock_error
from emneklar.core.canvas.client import CanvasError
from emneklar.core.changes.appliers import APPLIERS, Applier, ChangeData, get_applier
from emneklar.core.changes.permits import issue_permit
from emneklar.core.errors import AppError, ConflictError, NotFoundError
from emneklar.core.jobs.manager import JobContext, JobState
from emneklar.core.storage.models import ChangeLogEntry, Course, Finding, StagedChange

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

log = logging.getLogger(__name__)

OPEN_STATUSES = ("staged", "approved", "conflict", "failed")
LISTED_STATUSES = (*OPEN_STATUSES, "applying")
READY_STATUSES = ("staged", "approved")
# Publishing takes approved changes only: a staged change is not approved yet, and a failed one must be approved again
# (approve() moves staged/failed → approved). Kept apart from READY_STATUSES, which the queue counts and conflicts use.
PUBLISHABLE_STATUSES = ("approved",)


def not_publishable(change_id: int, status: str) -> AppError:
    """The clear refusal when a change that is not approved is sent to «Publiser til Canvas»."""
    reason = {
        "staged": "er ikke godkjent ennå. Godkjenn den før du publiserer.",
        "failed": "feilet sist den ble publisert. Godkjenn den på nytt før du prøver igjen.",
    }.get(status, f"har status «{status}» og kan ikke publiseres.")
    return AppError("change_state_invalid", status=409, message=f"Endringen {reason}",
                    detail=f"Endring {change_id}: {status}", extra={"change_id": change_id, "change_status": status})
RISKS = ("low", "medium", "high")
PUBLISH_JOB = "apply_changes"
SYNC_KIND = "blueprint.sync"
#: Kinds without undo say «Kan ikke angres automatisk.» unless they explain why themselves.
UNDO_DEFAULT = Applier.undo_note

#: source["rebase"] → function(change, source, live state) → new «proposed» built on the live state, or None.
Rebaser = Callable[[ChangeData, dict[str, Any], dict[str, Any]], dict[str, Any] | None]
REBASERS: dict[str, Rebaser] = {}


def register_rebaser(name: str, rebaser: Rebaser) -> None:
    """Features whose changes can be rebuilt from recipes (e.g. targeted HTML fixes) register here."""
    REBASERS[name] = rebaser


#: source["rebase"] → function(source) → what the recorded recipes did, in the past tense («Lenketekst oppdatert»).
Describer = Callable[[dict[str, Any]], list[str]]
DESCRIBERS: dict[str, Describer] = {}


def register_describer(name: str, describer: Describer) -> None:
    """Features that record recipes with their changes say here what each recipe does (for the history)."""
    DESCRIBERS[name] = describer


def change_summary(kind: str, source: dict[str, Any] | None) -> str | None:
    """What a change did, from what was recorded: the recipes of the change (most specific), else its kind. None
    when neither is known – the history then shows only the content and the status."""
    source = source or {}
    describer = DESCRIBERS.get(str(source.get("rebase")))
    labels = list(dict.fromkeys(describer(source))) if describer and source.get("fixes") else []
    if labels:
        return ", ".join(labels[:3]) + (f" og {len(labels) - 3} til" if len(labels) > 3 else "")
    applier = APPLIERS.get(kind)
    return (applier.done_label or None) if applier is not None else None


def change_dict(row: StagedChange) -> dict[str, Any]:
    applier = get_applier(row.kind)
    source = row.source or {}
    return {
        "id": row.id, "course_id": row.course_id, "domain": row.domain, "kind": row.kind,
        "kind_label": applier.label, "title": row.title, "target": row.target, "before": row.before,
        "proposed": {k: v for k, v in (row.proposed or {}).items() if not k.startswith("_")},
        "rationale": row.rationale, "risk": row.risk, "undo_capability": row.undo_capability,
        "undo_note": row.undo_note, "conflict_status": row.conflict_status, "status": row.status,
        "requires_confirmation": row.requires_confirmation, "editable": row.editable,
        "ai_generated": row.ai_generated, "source": {k: v for k, v in source.items() if k != "fixes"},
        "fix_count": len(source.get("fixes") or []) or len(source.get("finding_fingerprints") or []),
        "rebuildable": bool(source.get("rebase") in REBASERS and source.get("fixes")),
        "result": row.result, "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def log_dict(row: ChangeLogEntry, source: dict[str, Any] | None = None) -> dict[str, Any]:
    """``source`` is the change's recorded source (recipes), when the change is still stored – for ``summary``."""
    return {
        "id": row.id, "timestamp": row.timestamp.isoformat() if row.timestamp else None, "course_id": row.course_id,
        "change_id": row.change_id, "kind": row.kind, "object_type": row.object_type, "object_id": row.object_id,
        "object_title": row.object_title, "action": row.action, "before": row.before, "after": row.after,
        "reason": row.reason, "api_result": row.api_result, "user_action": row.user_action,
        "backup_id": row.backup_id, "undo_of": row.undo_of, "undoable": row.undoable and row.undone_by is None,
        "undone_by": row.undone_by, "summary": change_summary(row.kind, source),
    }


def explain_error(exc: AppError, *, parent: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """A Canvas refusal in words the teacher can act on, and its category (for the UI's suggested next step)."""
    if is_blueprint_lock_error(exc.detail):
        name = f"«{parent['name']}»" if parent and parent.get("name") else "Blueprint-emnet"
        return (f"Canvas avviste endringen fordi innholdet er låst av Blueprint-emnet {name}. Gjør endringen i "
                "Blueprint-emnet og synkroniser – EmneKlar kan flytte rettingen dit hvis du har tilgang."), "blueprint"
    if exc.code == "canvas_forbidden":
        return ("Canvas avviste endringen: Canvas-brukeren EmneKlar er koblet til som, har ikke rettighet til å endre "
                "dette innholdet. Be en med redigeringsrett i emnet om å gjøre endringen, eller rett det i Canvas."), \
            "permission"
    if exc.code == "canvas_not_found":
        return ("Fant ikke innholdet i Canvas. Det kan være slettet eller flyttet etter analysen. Kjør en ny analyse."), \
            "not_found"
    if exc.code in ("canvas_unavailable", "canvas_rate_limited"):
        return (f"{exc.message} Prøv igjen – EmneKlar kontrollerer først om endringen allerede er lagret, så den blir "
                "ikke gjort to ganger."), "network"
    if exc.code == "canvas_token_invalid":
        return exc.message, "auth"
    return exc.message, None


class ChangeEngine:
    def __init__(self, container: AppContainer) -> None:
        self.c = container
        self.db = container.db
        self.backups = BackupStore(container.db, container.config.backups_dir)

    def recover_after_restart(self) -> int:
        """A publish interrupted by a shutdown: the change may or may not have reached Canvas. Mark it failed – the
        next attempt checks the live content first and recognises a change that was already stored."""
        with self.db.session() as session:
            rows = session.scalars(select(StagedChange).where(StagedChange.status == "applying")).all()
            for row in rows:
                row.status = "failed"
                row.error = ("Publiseringen ble avbrutt da EmneKlar ble avsluttet. Prøv igjen – EmneKlar kontrollerer "
                             "først om endringen allerede er lagret i Canvas.")
            return len(rows)

    # -- staging ---------------------------------------------------------------------------------

    def stage(
        self,
        *,
        course_id: str,
        domain: str,
        kind: str,
        title: str,
        target: dict[str, Any],
        before: dict[str, Any],
        proposed: dict[str, Any],
        rationale: str,
        risk: str = "low",
        source: dict[str, Any] | None = None,
        editable: bool = False,
        requires_confirmation: bool | None = None,
        ai_generated: bool = False,
        merge: bool = False,
        layered: bool = False,
    ) -> dict[str, Any]:
        """Stage a change. With ``merge``, an open change for the same object and kind is reused:

        * same feature and the same fields (a new choice, e.g. another start page) -> the old proposal is replaced;
        * ``layered`` proposals (built on top of the queued proposal, e.g. several HTML fixes on one page) and
          changes to other fields -> combined into one change;
        * an open change in conflict (Canvas changed since it was queued) -> replaced, its «before» is stale.
        Changes from different features to different fields of the same object stay separate changes.
        """
        applier = get_applier(kind)
        if risk not in RISKS:
            raise AppError("validation_error", detail="Ukjent risikonivå")
        applier.validate(ChangeData(0, course_id, kind, target, before, proposed))
        source = source or {}
        with self.db.session() as session:
            existing = None
            feature = source.get("feature")
            if merge:
                candidates = session.scalars(select(StagedChange).where(
                    StagedChange.course_id == course_id, StagedChange.kind == kind,
                    StagedChange.status.in_(OPEN_STATUSES))).all()
                existing = next((c for c in candidates if c.target.get("object_id") == target.get("object_id")
                                 and ((c.source or {}).get("feature") == feature
                                      or set(c.proposed or {}) & set(proposed))), None)
            if existing is not None:
                same_feature = (existing.source or {}).get("feature") == feature
                old_proposed = {k: v for k, v in (existing.proposed or {}).items() if not k.startswith("_")}
                replace = existing.status == "conflict" or (
                    not layered and same_feature and set(proposed) >= set(old_proposed))
                new_fps = list(source.get("finding_fingerprints") or [])
                old_fps = list((existing.source or {}).get("finding_fingerprints") or [])
                if replace:
                    # The old proposal no longer applies: the findings it covered are open again.
                    self._mark_findings(session, [f for f in old_fps if f not in new_fps], "open")
                    existing.title, existing.before, existing.proposed = title[:500], before, proposed
                    existing.rationale, existing.risk, existing.source = rationale, risk, source
                    existing.requires_confirmation = (risk == "high" if requires_confirmation is None
                                                      else requires_confirmation)
                    existing.ai_generated, existing.editable = ai_generated, editable
                else:
                    old_source = existing.source or {}
                    old_fixes = [f for f in old_source.get("fixes") or []
                                 if f.get("fingerprint") not in {n.get("fingerprint") for n in source.get("fixes") or []}]
                    merged = {**old_source, **source,
                              "finding_fingerprints": list(dict.fromkeys([*old_fps, *new_fps]))}
                    if old_source.get("fixes") or source.get("fixes"):
                        merged["fixes"] = [*old_fixes, *(source.get("fixes") or [])]
                    if old_source.get("rebase") != source.get("rebase"):
                        merged.pop("rebase", None)  # mixed origins cannot be rebuilt from recipes alone
                    existing.source = merged
                    existing.proposed = {**old_proposed, **proposed}
                    # Fields already queued keep the «before» their proposal was built on.
                    existing.before = {**before, **(existing.before or {})}
                    existing.rationale = f"{existing.rationale}\n{rationale}".strip()
                    existing.risk = max(existing.risk, risk, key=RISKS.index)
                    existing.ai_generated = existing.ai_generated or ai_generated
                    existing.requires_confirmation = (existing.requires_confirmation or bool(requires_confirmation)
                                                      or risk == "high")
                    if not same_feature:
                        existing.title = f"{target.get('title') or existing.target.get('title') or ''}: flere endringer"
                existing.status = "staged"
                existing.conflict_status = "not_checked"
                existing.error = None
                row = existing
            else:
                row = StagedChange(
                    course_id=course_id, domain=domain, kind=kind, title=title[:500], target=target, before=before,
                    proposed=proposed, rationale=rationale, risk=risk, undo_capability=applier.undo_capability,
                    undo_note=applier.undo_note if applier.undo_capability != "none" else (
                        applier.undo_note if applier.undo_note != UNDO_DEFAULT else "Kan ikke angres automatisk."),
                    requires_confirmation=risk == "high" if requires_confirmation is None else requires_confirmation,
                    editable=editable, ai_generated=ai_generated, source=source)
                session.add(row)
            session.flush()
            self._mark_findings(session, source.get("finding_fingerprints") or [], "staged")
            return change_dict(row)

    def _mark_findings(self, session: Any, fingerprints: list[str], status: str) -> None:
        if not fingerprints:
            return
        for finding in session.scalars(select(Finding).where(Finding.fingerprint.in_(fingerprints))).all():
            if finding.status not in ("ignored", "verified"):
                finding.status = status

    # -- reading ---------------------------------------------------------------------------------

    def list(self, course_id: str | None = None, statuses: tuple[str, ...] = LISTED_STATUSES) -> list[dict[str, Any]]:
        with self.db.session() as session:
            query = select(StagedChange).where(StagedChange.status.in_(statuses)).order_by(StagedChange.created_at)
            if course_id:
                query = query.where(StagedChange.course_id == course_id)
            return [change_dict(r) for r in session.scalars(query).all()]

    def summary(self, course_id: str | None = None) -> dict[str, Any]:
        with self.db.session() as session:
            query = (select(StagedChange.domain, StagedChange.status, StagedChange.course_id, func.count())
                     .where(StagedChange.status.in_(LISTED_STATUSES))
                     .group_by(StagedChange.domain, StagedChange.status, StagedChange.course_id))
            if course_id:
                query = query.where(StagedChange.course_id == course_id)
            rows = session.execute(query).tuples().all()
        by_domain: dict[str, int] = {}
        by_status: dict[str, int] = {}
        courses: set[str] = set()
        for domain, status, course, count in rows:
            by_status[status] = by_status.get(status, 0) + count
            courses.add(course)
            if status in READY_STATUSES:
                by_domain[domain] = by_domain.get(domain, 0) + count
        return {"pending": sum(by_domain.values()), "by_domain": by_domain, "by_status": by_status,
                "approved": by_status.get("approved", 0),
                "problems": by_status.get("failed", 0) + by_status.get("conflict", 0),
                "courses": len(courses)}

    def get(self, change_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is None:
                raise NotFoundError("change_not_found")
            return change_dict(row)

    def course_names(self, course_ids: builtins.list[str]) -> dict[str, str]:
        with self.db.session() as session:
            rows = session.scalars(select(Course).where(Course.id.in_(course_ids))).all()
            return {r.id: r.name for r in rows}

    # -- editing ---------------------------------------------------------------------------------

    def update_proposed(self, change_id: int, proposed: dict[str, Any]) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is None:
                raise NotFoundError("change_not_found")
            if not row.editable or row.status not in OPEN_STATUSES:
                raise AppError("change_not_editable", status=409)
            get_applier(row.kind).validate(ChangeData(row.id, row.course_id, row.kind, row.target, row.before, proposed))
            row.proposed = proposed
            row.status = "staged"
            return change_dict(row)

    def discard(self, change_id: int, *, note: str | None = None) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is None:
                raise NotFoundError("change_not_found")
            if row.status not in OPEN_STATUSES:
                raise AppError("change_state_invalid", status=409)
            row.status = "discarded"
            if note:
                row.error = note
            else:
                self._mark_findings(session, (row.source or {}).get("finding_fingerprints") or [], "open")
            return change_dict(row)

    def approve(self, change_ids: builtins.list[int]) -> builtins.list[dict[str, Any]]:
        result = []
        with self.db.session() as session:
            for change_id in change_ids:
                row = session.get(StagedChange, change_id)
                if row is None:
                    raise NotFoundError("change_not_found")
                if row.status in ("staged", "failed"):
                    row.status = "approved"
                result.append(change_dict(row))
        return result

    def unapprove(self, change_ids: builtins.list[int]) -> builtins.list[dict[str, Any]]:
        result = []
        with self.db.session() as session:
            for change_id in change_ids:
                row = session.get(StagedChange, change_id)
                if row is None:
                    raise NotFoundError("change_not_found")
                if row.status == "approved":
                    row.status = "staged"
                result.append(change_dict(row))
        return result

    # -- conflicts ---------------------------------------------------------------------------------

    async def check_conflicts(self, change_ids: builtins.list[int]) -> builtins.list[dict[str, Any]]:
        api = CanvasAPI(self.c.canvas())
        results = []
        for change_id in change_ids:
            data, _ = self._load(change_id)
            applier = get_applier(data.kind)
            try:
                current = await applier.current(api, data)
                conflict = applier.conflict(data.before, current)
                status = "conflict" if conflict else "ok"
            except CanvasError as exc:
                status, current = "conflict", {"error": exc.message}
            with self.db.session() as session:
                row = session.get(StagedChange, change_id)
                assert row is not None
                row.conflict_status = status
                if status == "conflict" and row.status in READY_STATUSES:
                    row.status = "conflict"
                    row.error = "Innholdet er endret i Canvas etter at forslaget ble laget."
                results.append(change_dict(row))
        return results

    async def rebuild(self, change_id: int) -> dict[str, Any]:
        """«Lag forslaget på nytt»: rebuild a recipe-based change on the live content (after a conflict)."""
        data, row = self._load(change_id)
        source = dict(row.source or {})
        rebaser = REBASERS.get(str(source.get("rebase")))
        if rebaser is None or not source.get("fixes") or row.status not in OPEN_STATUSES:
            raise AppError("change_state_invalid", status=409, message="Denne endringen kan ikke bygges på nytt "
                           "automatisk. Fjern den og lag forslaget på nytt fra funnet.")
        applier = get_applier(data.kind)
        current = await applier.current(CanvasAPI(self.c.canvas()), data)
        rebuilt = rebaser(data, source, current)
        if rebuilt is None:
            raise AppError("change_conflict", status=409, message="En eller flere rettinger passer ikke lenger med "
                           "innholdet i Canvas (elementet er endret eller fjernet). Kjør en ny analyse.")
        with self.db.session() as session:
            stored = session.get(StagedChange, change_id)
            assert stored is not None
            stored.before = {k: current.get(k) for k in rebuilt}
            stored.proposed = {**{k: v for k, v in (stored.proposed or {}).items() if k.startswith("_")}, **rebuilt}
            stored.status, stored.conflict_status, stored.error = "staged", "not_checked", None
            return change_dict(stored)

    # -- applying -----------------------------------------------------------------------------------

    def _load(self, change_id: int) -> tuple[ChangeData, StagedChange]:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is None:
                raise NotFoundError("change_not_found")
            session.expunge(row)
        return ChangeData(row.id, row.course_id, row.kind, dict(row.target), dict(row.before),
                          dict(row.proposed)), row

    def publishing(self) -> JobState | None:
        return next((j for j in self.c.jobs.list(active_only=True) if j.kind == PUBLISH_JOB), None)

    def submit_apply(self, change_ids: builtins.list[int], *, confirm_high_risk: bool,
                     course_id: str | None = None) -> JobState:
        change_ids = list(dict.fromkeys(change_ids))
        if not change_ids:
            raise AppError("validation_error", detail="Ingen endringer valgt")
        running = self.publishing()
        if running is not None:
            raise ConflictError("publish_running", job_id=running.id)
        courses: set[str] = set()
        for change_id in change_ids:
            _, row = self._load(change_id)
            if row.status not in PUBLISHABLE_STATUSES:
                raise not_publishable(change_id, row.status)
            if row.requires_confirmation and not confirm_high_risk:
                raise AppError("change_requires_confirmation", status=409, extra={"change_id": change_id})
            courses.add(row.course_id)

        async def runner(ctx: JobContext) -> dict[str, Any]:
            return await self.apply_many(ctx, change_ids)

        title = "Publiserer endring" if len(change_ids) == 1 else f"Publiserer {len(change_ids)} endringer"
        job_course = next(iter(courses)) if len(courses) == 1 else course_id
        return self.c.jobs.submit(kind=PUBLISH_JOB, title=title, runner=runner, course_id=job_course,
                                  params={"change_ids": change_ids, "courses": sorted(courses)}, supports_pause=False,
                                  hard_cancel=False, exclusive=True)

    def _publish_order(self, loaded: builtins.list[tuple[ChangeData, StagedChange]]) -> builtins.list[
            tuple[ChangeData, StagedChange]]:
        """Per course and content item: changes that cannot be rebuilt first, recipe-based fixes after them (they are
        rebuilt on the new content if needed), Blueprint syncs last (after the content they should carry)."""
        def key(item: tuple[ChangeData, StagedChange]) -> tuple[Any, ...]:
            data, row = item
            rebuildable = bool((row.source or {}).get("rebase") in REBASERS and (row.source or {}).get("fixes"))
            return (data.course_id, data.kind == SYNC_KIND, str(row.target.get("object_type") or ""),
                    str(row.target.get("object_id") or ""), rebuildable,
                    row.created_at.timestamp() if row.created_at else 0.0, data.id)

        return sorted(loaded, key=key)

    async def apply_many(self, ctx: JobContext, change_ids: builtins.list[int]) -> dict[str, Any]:
        api = CanvasAPI(self.c.canvas())
        progress = ctx.progress
        progress.set_phase("apply", "Publiserer til Canvas", index=1, count=1, determinate=True)
        progress.add_tasks("change", len(change_ids))
        loaded = self._publish_order([self._load(cid) for cid in change_ids])
        written: dict[tuple[str, str, str], dict[str, Any]] = {}
        results = []
        for data, row in loaded:
            await ctx.checkpoint()  # cancellation only between changes – never mid-write
            t0 = progress.start("change", item=row.title, operation=get_applier(row.kind).label)
            try:
                outcome = await self.apply_one(api, data, row, written=written)
            except Exception:
                log.exception("Endring %s feilet uventet", data.id)
                self._set(data.id, status="failed", error="Uventet feil under publisering. Se loggen.")
                outcome = {"change_id": data.id, "status": "failed", "message": "Uventet feil under publisering."}
            outcome.setdefault("course_id", data.course_id)
            outcome.setdefault("title", row.title)
            progress.finish("change", t0, failed=outcome["status"] in ("failed", "conflict"))
            results.append(outcome)
        summary: dict[str, int] = {}
        for r in results:
            summary[r["status"]] = summary.get(r["status"], 0) + 1
        courses = sorted({r["course_id"] for r in results})
        return {"results": results, "summary": summary, "courses": courses,
                "course_names": self.course_names(courses)}

    async def apply_one(self, api: CanvasAPI, data: ChangeData, row: StagedChange, *,
                        written: dict[tuple[str, str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
        applier = get_applier(data.kind)
        object_type = row.target.get("object_type") or applier.object_type
        object_key = (data.course_id, str(object_type), str(row.target.get("object_id") or ""))
        base_log = {"course_id": data.course_id, "change_id": data.id, "kind": data.kind, "object_type": object_type,
                    "object_id": str(row.target.get("object_id") or ""), "object_title": row.target.get("title"),
                    "reason": row.rationale, "user_action": "apply"}
        status = self._status(data.id)
        if status == "applied":
            return {"change_id": data.id, "status": "applied", "message": "Allerede publisert – ikke sendt på nytt.",
                    "skipped": True}
        if status not in PUBLISHABLE_STATUSES:
            # Checked again right before writing: a change that lost its approval meanwhile is never sent to Canvas.
            return {"change_id": data.id, "status": status, "error_code": "change_state_invalid",
                    "message": not_publishable(data.id, status).message}
        self._set(data.id, status="applying")
        try:
            current = await applier.current(api, data)
        except AppError as exc:
            return await self._fail(api, data, base_log, exc)
        if applier.conflict(data.before, current):
            if applier.already_applied(data.proposed, current):
                return self._already_stored(data, row, base_log, current, written, object_key)
            rebuilt = self._rebase(data, row, current) if written is not None and object_key in written else None
            if rebuilt is None:
                self._set(data.id, status="conflict", conflict_status="conflict",
                          error="Innholdet er endret i Canvas etter at forslaget ble laget.")
                self._log(**base_log, action="conflict", before=data.before, after=current,
                          api_result={"sent": False, "message": "Konflikt: innholdet var endret i Canvas."})
                return {"change_id": data.id, "status": "conflict", "message": "Innholdet er endret i Canvas.",
                        "rebuildable": bool((row.source or {}).get("fixes"))}
            data.before = {k: current.get(k) for k in rebuilt}
            data.proposed = {**{k: v for k, v in data.proposed.items() if k.startswith("_")}, **rebuilt}
            with self.db.session() as session:
                stored = session.get(StagedChange, data.id)
                assert stored is not None
                stored.before, stored.proposed = data.before, data.proposed
        backup_id = self.backups.save(course_id=data.course_id, object_type=object_type,
                                      object_id=str(row.target.get("object_id") or ""), title=row.title, state=current,
                                      change_id=data.id)
        permit = issue_permit(data.id, data.kind)
        try:
            after = await applier.apply(api, data, permit)
        except AppError as exc:
            log.warning("Endring %s feilet: %s", data.id, exc.code)
            return await self._fail(api, data, base_log, exc, backup_id=backup_id, before=current)
        mismatches = applier.verify(data.proposed, after)
        if mismatches:
            message = ("Canvas bekreftet lagringen, men verdiene ble ikke endret: " + ", ".join(mismatches)
                       + ". Endringen er ikke gjennomført – kontroller innstillingen i Canvas.")
            self._set(data.id, status="failed", error=message)
            self._log(**base_log, action="failed", before=current, after=after, backup_id=backup_id,
                      api_result={"sent": True, "error": message})
            return {"change_id": data.id, "status": "failed", "message": message}
        if written is not None:
            written[object_key] = after
        proposed = dict(data.proposed or {})
        if applier.stores_created:
            proposed["_created"] = after
        entry_id = self._log(**base_log, action="apply", before=current, after=after, backup_id=backup_id,
                             undoable=applier.undo_capability != "none",
                             api_result={"sent": True, "message": "Lagret i Canvas."})
        extra = await self._blueprint_note(api, data)
        with self.db.session() as session:
            stored = session.get(StagedChange, data.id)
            assert stored is not None
            stored.status = "applied"
            stored.conflict_status = "ok"
            stored.applied_at = datetime.now(UTC)
            stored.result = {"after": after, "log_id": entry_id, "backup_id": backup_id, **extra}
            stored.proposed = proposed
            stored.target = data.target
            stored.error = None
            self._mark_findings(session, (stored.source or {}).get("finding_fingerprints") or [], "fixed")
        if data.kind == SYNC_KIND:
            extra["migration_id"] = after.get("migration_id")
        return {"change_id": data.id, "status": "applied", "log_id": entry_id, "kind": data.kind, **extra}

    def _already_stored(self, data: ChangeData, row: StagedChange, base_log: dict[str, Any], current: dict[str, Any],
                        written: dict[tuple[str, str, str], dict[str, Any]] | None,
                        object_key: tuple[str, str, str]) -> dict[str, Any]:
        """The change is already in Canvas (e.g. a timeout after Canvas had saved it): record it, write nothing."""
        message = "Endringen var allerede lagret i Canvas og ble ikke sendt på nytt."
        entry_id = self._log(**base_log, action="apply", before=data.before, after=current,
                             undoable=get_applier(data.kind).undo_capability != "none",
                             api_result={"sent": False, "message": message})
        if written is not None:
            written[object_key] = current
        with self.db.session() as session:
            stored = session.get(StagedChange, data.id)
            assert stored is not None
            stored.status, stored.conflict_status = "applied", "ok"
            stored.applied_at = datetime.now(UTC)
            stored.result = {"after": current, "log_id": entry_id, "already_stored": True}
            stored.error = None
            self._mark_findings(session, (stored.source or {}).get("finding_fingerprints") or [], "fixed")
        return {"change_id": data.id, "status": "applied", "log_id": entry_id, "message": message}

    def _rebase(self, data: ChangeData, row: StagedChange, current: dict[str, Any]) -> dict[str, Any] | None:
        source = row.source or {}
        rebaser = REBASERS.get(str(source.get("rebase")))
        if rebaser is None or not source.get("fixes"):
            return None
        return rebaser(data, source, current)

    async def _blueprint_note(self, api: CanvasAPI, data: ChangeData) -> dict[str, Any]:
        """After a write in a Blueprint course: the change reaches the associated courses only after a sync."""
        if data.kind == SYNC_KIND:
            return {}
        try:
            info = await blueprint_info(api, data.course_id)
        except CanvasError:
            return {}
        if not info.get("is_blueprint"):
            return {}
        return {"blueprint": {"sync_needed": True, "associated_course_count": info.get("associated_course_count")}}

    async def _fail(self, api: CanvasAPI, data: ChangeData, base_log: dict[str, Any], exc: AppError, *,
                    backup_id: int | None = None, before: dict[str, Any] | None = None) -> dict[str, Any]:
        parent = None
        if is_blueprint_lock_error(exc.detail):
            try:
                parent = (await blueprint_info(api, data.course_id)).get("parent")
            except CanvasError:
                parent = None
        message, category = explain_error(exc, parent=parent)
        result = {"error_category": category, **({"blueprint": {"locked_by": parent}} if category == "blueprint"
                                                 else {})}
        with self.db.session() as session:
            row = session.get(StagedChange, data.id)
            if row is not None:
                row.status, row.error = "failed", message
                row.result = {**(row.result or {}), **result}
        self._log(**base_log, action="failed", before=before or data.before, after={}, backup_id=backup_id,
                  api_result={"sent": True, "error": message, "code": exc.code})
        return {"change_id": data.id, "status": "failed", "message": message, **result}

    def _status(self, change_id: int) -> str:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            return row.status if row is not None else "missing"

    def _set(self, change_id: int, **fields: Any) -> None:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is not None:
                for key, value in fields.items():
                    setattr(row, key, value)

    def _log(self, **fields: Any) -> int:
        with self.db.session() as session:
            entry = ChangeLogEntry(**fields)
            session.add(entry)
            session.flush()
            return entry.id

    # -- undo -----------------------------------------------------------------------------------------

    async def undo(self, log_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            entry = session.get(ChangeLogEntry, log_id)
            if entry is None:
                raise NotFoundError("not_found", detail="logginnslag")
            if entry.action != "apply" or not entry.undoable or entry.undone_by is not None or entry.change_id is None:
                raise AppError("undo_not_possible", status=409)
            entry_before, entry_after = dict(entry.before or {}), dict(entry.after or {})
            change_id = entry.change_id
        data, row = self._load(change_id)
        applier = get_applier(data.kind)
        api = CanvasAPI(self.c.canvas())
        current = await applier.current(api, data)
        if applier.conflict(entry_after, current):
            raise ConflictError("undo_conflict")
        base: dict[str, Any] = {"course_id": data.course_id, "change_id": data.id, "kind": data.kind,
                                "object_type": row.target.get("object_type") or applier.object_type,
                                "object_id": str(row.target.get("object_id") or ""),
                                "object_title": row.target.get("title"),
                                "reason": f"Angret endring: {row.title}", "user_action": "undo"}
        backup_id = self.backups.save(course_id=data.course_id, object_type=base["object_type"],
                                      object_id=base["object_id"], title=row.title, state=current, change_id=data.id)
        restored = await applier.undo(api, data, entry_before, issue_permit(data.id, f"undo:{data.kind}"))
        undo_id = self._log(**base, action="undo", before=current, after=restored, backup_id=backup_id,
                            undo_of=log_id, api_result={"sent": True, "message": "Endringen er angret."})
        with self.db.session() as session:
            original = session.get(ChangeLogEntry, log_id)
            assert original is not None
            original.undone_by = undo_id
            stored = session.get(StagedChange, data.id)
            if stored is not None:
                stored.status = "undone"
                stored.target = data.target
                self._mark_findings(session, (stored.source or {}).get("finding_fingerprints") or [], "open")
        return {"status": "undone", "log_id": undo_id}

    # -- change log ------------------------------------------------------------------------------------

    def changelog(self, course_id: str | None = None, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        with self.db.session() as session:
            query = select(ChangeLogEntry).order_by(ChangeLogEntry.timestamp.desc(), ChangeLogEntry.id.desc())
            count_query = select(func.count()).select_from(ChangeLogEntry)
            if course_id:
                query = query.where(ChangeLogEntry.course_id == course_id)
                count_query = count_query.where(ChangeLogEntry.course_id == course_id)
            total = session.scalar(count_query) or 0
            rows = session.scalars(query.offset(offset).limit(limit)).all()
            change_ids = {r.change_id for r in rows if r.change_id is not None}
            sources = {c.id: c.source or {} for c in session.scalars(
                select(StagedChange).where(StagedChange.id.in_(change_ids))).all()} if change_ids else {}
            return {"items": [log_dict(r, sources.get(r.change_id or -1)) for r in rows], "total": total}

    def log_entry(self, log_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ChangeLogEntry, log_id)
            if row is None:
                raise NotFoundError("not_found")
            change = session.get(StagedChange, row.change_id) if row.change_id is not None else None
            return log_dict(row, change.source if change is not None else None)

