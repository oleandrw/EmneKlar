"""Local data housekeeping: snapshot retention, storage overview and «Slett lokale data».

Only local EmneKlar data is touched – never Canvas. The change log and backups are
the safety net for undo and are never deleted from here.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete, func, select

from emneklar.config import RuntimeConfig
from emneklar.core.jobs.manager import FINAL
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import (
    AnalysisRun,
    Backup,
    ChangeLogEntry,
    Finding,
    FindingDecision,
    HomepageDraft,
    Job,
    LinkCheck,
    QuestionBankItem,
    Report,
    Snapshot,
    SnapshotObject,
)

ClearTarget = Literal["cache", "analysis", "reports"]


def _count(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def prune_snapshots(db: Database, retention_days: int, *, now: datetime | None = None) -> int:
    """Delete snapshots older than the retention period, but always keep the newest one per course."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    with db.session() as session:
        newest = dict(session.execute(
            select(Snapshot.course_id, func.max(Snapshot.id)).group_by(Snapshot.course_id)).tuples().all())
        old = [sid for sid, cid in session.execute(
            select(Snapshot.id, Snapshot.course_id).where(Snapshot.created_at < cutoff)).tuples().all()
            if newest.get(cid) != sid]
        if old:
            session.execute(delete(SnapshotObject).where(SnapshotObject.snapshot_id.in_(old)))
            session.execute(delete(Snapshot).where(Snapshot.id.in_(old)))
    return len(old)


def _dir_size(path: Path) -> tuple[int, int]:
    size = files = 0
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                size += item.stat().st_size
    return size, files


def storage_overview(config: RuntimeConfig, db: Database) -> dict[str, Any]:
    folders = []
    for key, label, path in (("data", "Datamappe", config.data_dir), ("backups", "Sikkerhetskopier", config.backups_dir),
                             ("reports", "Rapporter", config.reports_dir), ("logs", "Logger", config.logs_dir),
                             ("cache", "Hurtigbuffer", config.cache_dir)):
        size, files = _dir_size(path) if key != "data" else (config.db_path.stat().st_size
                                                             if config.db_path.exists() else 0, 1)
        folders.append({"key": key, "label": label, "path": str(path), "size": size, "files": files})
    with db.session() as session:
        counts = {name: session.scalar(select(func.count()).select_from(model)) or 0 for name, model in (
            ("snapshots", Snapshot), ("analysis_runs", AnalysisRun), ("findings", Finding), ("reports", Report),
            ("backups", Backup), ("change_log", ChangeLogEntry), ("link_checks", LinkCheck),
            ("question_bank", QuestionBankItem), ("homepage_drafts", HomepageDraft))}
    return {"data_dir": str(config.data_dir), "database": str(config.db_path), "folders": folders, "counts": counts}


def clear(config: RuntimeConfig, db: Database, target: ClearTarget) -> dict[str, int]:
    removed: dict[str, int] = {}
    with db.session() as session:
        if target == "cache":
            removed["link_checks"] = _count(session.execute(delete(LinkCheck)))
        elif target == "analysis":
            removed["findings"] = _count(session.execute(delete(Finding)))
            removed["decisions"] = _count(session.execute(delete(FindingDecision)))
            removed["analysis_runs"] = _count(session.execute(delete(AnalysisRun)))
            session.execute(delete(SnapshotObject))
            removed["snapshots"] = _count(session.execute(delete(Snapshot)))
            removed["jobs"] = _count(session.execute(delete(Job).where(Job.status.in_(FINAL))))
        elif target == "reports":
            removed["reports"] = _count(session.execute(delete(Report)))
    if target == "cache" and config.cache_dir.is_dir():
        for item in config.cache_dir.iterdir():
            shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
    if target == "reports" and config.reports_dir.is_dir():
        for item in config.reports_dir.iterdir():
            shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
    return removed
