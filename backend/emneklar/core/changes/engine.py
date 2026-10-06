"""The shared change engine – the only path from EmneKlar to a Canvas write.

    stage → (edit/remove) → approve → apply job:
        Dry run?  → log «dry_run», nothing is sent
        conflict? → fetch live state, compare with «before» → stop and ask for review
        backup    → JSON copy of the live object
        write     → typed API + WritePermit
        verify    → read back from Canvas, log before/after/API result
    undo (where supported) → conflict check against what EmneKlar wrote → restore → log

Undo is never promised universally: each change kind declares full/partial/none.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from emneklar.core.backup.store import BackupStore
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import CanvasError, DryRunBlocked
from emneklar.core.changes.appliers import ChangeData, get_applier
from emneklar.core.changes.permits import issue_permit
from emneklar.core.errors import AppError, ConflictError, NotFoundError
from emneklar.core.jobs.manager import JobContext, JobState
from emneklar.core.storage.models import ChangeLogEntry, Finding, StagedChange

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

log = logging.getLogger(__name__)

OPEN_STATUSES = ("staged", "approved", "conflict", "failed")
READY_STATUSES = ("staged", "approved")
RISKS = ("low", "medium", "high")
BLUEPRINT_LOCK_MESSAGE = "Innholdet er låst av et Blueprint-emne og kan ikke endres i dette emnet."


def change_dict(row: StagedChange) -> dict[str, Any]:
    applier = get_applier(row.kind)
    return {
        "id": row.id, "course_id": row.course_id, "domain": row.domain, "kind": row.kind,
        "kind_label": applier.label, "title": row.title, "target": row.target, "before": row.before,
        "proposed": {k: v for k, v in (row.proposed or {}).items() if not k.startswith("_")},
        "rationale": row.rationale, "risk": row.risk, "undo_capability": row.undo_capability,
        "undo_note": row.undo_note, "conflict_status": row.conflict_status, "status": row.status,
        "requires_confirmation": row.requires_confirmation, "editable": row.editable,
        "ai_generated": row.ai_generated, "source": row.source, "result": row.result, "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def log_dict(row: ChangeLogEntry) -> dict[str, Any]:
    return {
        "id": row.id, "timestamp": row.timestamp.isoformat() if row.timestamp else None, "course_id": row.course_id,
        "change_id": row.change_id, "kind": row.kind, "object_type": row.object_type, "object_id": row.object_id,
        "object_title": row.object_title, "action": row.action, "before": row.before, "after": row.after,
        "reason": row.reason, "api_result": row.api_result, "user_action": row.user_action, "dry_run": row.dry_run,
        "backup_id": row.backup_id, "undo_of": row.undo_of, "undoable": row.undoable and row.undone_by is None,
        "undone_by": row.undone_by,
    }


def _friendly_error(exc: AppError) -> str:
    detail = (exc.detail or "").lower()
    if "locked by master course" in detail or "master course" in detail:
        return BLUEPRINT_LOCK_MESSAGE
    return exc.message


class ChangeEngine:
    def __init__(self, container: AppContainer) -> None:
        self.c = container
        self.db = container.db
        self.backups = BackupStore(container.db, container.config.backups_dir)

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
    ) -> dict[str, Any]:
        applier = get_applier(kind)
        if risk not in RISKS:
            raise AppError("validation_error", detail="Ukjent risikonivå")
        applier.validate(ChangeData(0, course_id, kind, target, before, proposed))
        source = source or {}
        with self.db.session() as session:
            existing = None
            if merge:
                candidates = session.scalars(select(StagedChange).where(
                    StagedChange.course_id == course_id, StagedChange.kind == kind,
                    StagedChange.status.in_(OPEN_STATUSES))).all()
                existing = next((c for c in candidates if c.target.get("object_id") == target.get("object_id")), None)
            if existing is not None:
                merged_source = dict(existing.source or {})
                fingerprints = list(dict.fromkeys([*(merged_source.get("finding_fingerprints") or []),
                                                   *(source.get("finding_fingerprints") or [])]))
                merged_source.update(source)
                merged_source["finding_fingerprints"] = fingerprints
                existing.proposed = proposed
                existing.rationale = f"{existing.rationale}\n{rationale}".strip()
                existing.source = merged_source
                existing.risk = max(existing.risk, risk, key=RISKS.index)
                existing.status = "staged"
                existing.conflict_status = "not_checked"
                existing.ai_generated = existing.ai_generated or ai_generated
                existing.requires_confirmation = existing.requires_confirmation or bool(requires_confirmation)
                existing.error = None
                row = existing
            else:
                row = StagedChange(
                    course_id=course_id, domain=domain, kind=kind, title=title[:500], target=target, before=before,
                    proposed=proposed, rationale=rationale, risk=risk, undo_capability=applier.undo_capability,
                    undo_note=applier.undo_note if applier.undo_capability != "none" else "Kan ikke angres automatisk.",
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
            if finding.status != "ignored":
                finding.status = status

    # -- reading ---------------------------------------------------------------------------------

    def list(self, course_id: str | None = None, statuses: tuple[str, ...] = OPEN_STATUSES) -> list[dict[str, Any]]:
        with self.db.session() as session:
            query = select(StagedChange).where(StagedChange.status.in_(statuses)).order_by(StagedChange.created_at)
            if course_id:
                query = query.where(StagedChange.course_id == course_id)
            return [change_dict(r) for r in session.scalars(query).all()]

    def summary(self, course_id: str | None = None) -> dict[str, Any]:
        with self.db.session() as session:
            query = (select(StagedChange.domain, func.count()).where(StagedChange.status.in_(READY_STATUSES))
                     .group_by(StagedChange.domain))
            if course_id:
                query = query.where(StagedChange.course_id == course_id)
            by_domain = {d: n for d, n in session.execute(query).all()}
        return {"pending": sum(by_domain.values()), "by_domain": by_domain}

    def get(self, change_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is None:
                raise NotFoundError("change_not_found")
            return change_dict(row)

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

    def discard(self, change_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is None:
                raise NotFoundError("change_not_found")
            if row.status not in OPEN_STATUSES:
                raise AppError("change_state_invalid", status=409)
            row.status = "discarded"
            self._mark_findings(session, (row.source or {}).get("finding_fingerprints") or [], "open")
            return change_dict(row)

    def approve(self, change_ids: list[int]) -> list[dict[str, Any]]:
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

    # -- conflicts ---------------------------------------------------------------------------------

    async def check_conflicts(self, change_ids: list[int]) -> list[dict[str, Any]]:
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
                results.append(change_dict(row))
        return results

    # -- applying -----------------------------------------------------------------------------------

    def _load(self, change_id: int) -> tuple[ChangeData, StagedChange]:
        with self.db.session() as session:
            row = session.get(StagedChange, change_id)
            if row is None:
                raise NotFoundError("change_not_found")
            session.expunge(row)
        return ChangeData(row.id, row.course_id, row.kind, dict(row.target), dict(row.before),
                          dict(row.proposed)), row

    def submit_apply(self, change_ids: list[int], *, confirm_high_risk: bool, course_id: str | None) -> JobState:
        if not change_ids:
            raise AppError("validation_error", detail="Ingen endringer valgt")
        for change_id in change_ids:
            _, row = self._load(change_id)
            if row.status not in (*READY_STATUSES, "failed"):
                raise AppError("change_state_invalid", status=409, detail=f"Endring {change_id}: {row.status}")
            if row.requires_confirmation and not confirm_high_risk:
                raise AppError("change_requires_confirmation", status=409, extra={"change_id": change_id})

        async def runner(ctx: JobContext) -> dict[str, Any]:
            return await self.apply_many(ctx, change_ids)

        title = "Gjennomfører endring" if len(change_ids) == 1 else f"Gjennomfører {len(change_ids)} endringer"
        return self.c.jobs.submit(kind="apply_changes", title=title, runner=runner, course_id=course_id,
                                  params={"change_ids": change_ids}, supports_pause=False, hard_cancel=False,
                                  exclusive=True)

    async def apply_many(self, ctx: JobContext, change_ids: list[int]) -> dict[str, Any]:
        api = CanvasAPI(self.c.canvas())
        progress = ctx.progress
        progress.set_phase("apply", "Gjennomfører endringer", index=1, count=1, determinate=True)
        progress.add_tasks("change", len(change_ids))
        results = []
        for change_id in change_ids:
            await ctx.checkpoint()  # cancellation only between changes – never mid-write
            data, row = self._load(change_id)
            t0 = progress.start("change", item=row.title, operation=get_applier(row.kind).label)
            outcome = await self.apply_one(api, data, row)
            progress.finish("change", t0, failed=outcome["status"] in ("failed", "conflict"))
            results.append(outcome)
        summary = {s: sum(1 for r in results if r["status"] == s) for s in {r["status"] for r in results}}
        return {"results": results, "summary": summary, "dry_run": self.c.is_dry_run()}

    async def apply_one(self, api: CanvasAPI, data: ChangeData, row: StagedChange) -> dict[str, Any]:
        applier = get_applier(data.kind)
        object_type = row.target.get("object_type") or applier.object_type
        base_log = {"course_id": data.course_id, "change_id": data.id, "kind": data.kind, "object_type": object_type,
                    "object_id": str(row.target.get("object_id") or ""), "object_title": row.target.get("title"),
                    "reason": row.rationale, "user_action": "apply"}
        if self.c.is_dry_run():
            self._log(**base_log, action="dry_run", before=data.before, after=row.proposed or {}, dry_run=True,
                      api_result={"sent": False, "message": "Dry run: ikke sendt til Canvas."})
            return {"change_id": data.id, "status": "dry_run", "message": "Dry run: ikke sendt til Canvas."}
        try:
            current = await applier.current(api, data)
        except AppError as exc:
            return self._fail(data, base_log, _friendly_error(exc))
        if applier.conflict(data.before, current):
            self._set(data.id, status="conflict", conflict_status="conflict",
                      error="Innholdet er endret i Canvas etter at forslaget ble laget.")
            self._log(**base_log, action="conflict", before=data.before, after=current,
                      api_result={"sent": False, "message": "Konflikt: innholdet var endret i Canvas."})
            return {"change_id": data.id, "status": "conflict", "message": "Innholdet er endret i Canvas."}
        backup_id = self.backups.save(course_id=data.course_id, object_type=object_type,
                                      object_id=str(row.target.get("object_id") or ""), title=row.title, state=current,
                                      change_id=data.id)
        permit = issue_permit(data.id, data.kind)
        try:
            after = await applier.apply(api, data, permit)
        except DryRunBlocked:
            return {"change_id": data.id, "status": "dry_run", "message": "Dry run ble slått på underveis."}
        except AppError as exc:
            log.warning("Endring %s feilet: %s", data.id, exc.code)
            return self._fail(data, base_log, _friendly_error(exc), backup_id=backup_id, before=current)
        proposed = dict(row.proposed or {})
        if data.kind in ("page.create", "module_item.create"):
            proposed["_created"] = after
        entry_id = self._log(**base_log, action="apply", before=current, after=after, backup_id=backup_id,
                             undoable=applier.undo_capability != "none",
                             api_result={"sent": True, "message": "Lagret i Canvas."})
        with self.db.session() as session:
            stored = session.get(StagedChange, data.id)
            assert stored is not None
            stored.status = "applied"
            stored.conflict_status = "ok"
            stored.applied_at = datetime.now(UTC)
            stored.result = {"after": after, "log_id": entry_id, "backup_id": backup_id}
            stored.proposed = proposed
            stored.target = data.target
            stored.error = None
            self._mark_findings(session, (stored.source or {}).get("finding_fingerprints") or [], "fixed")
        return {"change_id": data.id, "status": "applied", "log_id": entry_id}

    def _fail(self, data: ChangeData, base_log: dict[str, Any], message: str, *, backup_id: int | None = None,
              before: dict[str, Any] | None = None) -> dict[str, Any]:
        self._set(data.id, status="failed", error=message)
        self._log(**base_log, action="failed", before=before or data.before, after={}, backup_id=backup_id,
                  api_result={"sent": True, "error": message})
        return {"change_id": data.id, "status": "failed", "message": message}

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
        base = {"course_id": data.course_id, "change_id": data.id, "kind": data.kind,
                "object_type": row.target.get("object_type") or applier.object_type,
                "object_id": str(row.target.get("object_id") or ""), "object_title": row.target.get("title"),
                "reason": f"Angret endring: {row.title}", "user_action": "undo"}
        if self.c.is_dry_run():
            self._log(**base, action="dry_run", before=current, after=entry_before, dry_run=True, undo_of=log_id,
                      api_result={"sent": False, "message": "Dry run: angring ikke sendt til Canvas."})
            return {"status": "dry_run", "message": "Dry run: angring ikke sendt til Canvas."}
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
            return {"items": [log_dict(r) for r in rows], "total": total}

    def log_entry(self, log_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ChangeLogEntry, log_id)
            if row is None:
                raise NotFoundError("not_found")
            return log_dict(row)
