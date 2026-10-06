"""Background jobs (analyses, link checks, AI generation, applying changes).

* Jobs are asyncio tasks inside the local server process, so they keep
  running when the browser tab is closed ("Kjør i bakgrunnen") and stop when
  EmneKlar stops. No external queue (Redis/Celery) is needed.
* **Pause** is real and safe: workers call :meth:`JobContext.checkpoint`
  between tasks; when paused, no new task starts and in-flight tasks finish.
  Only jobs whose tasks are independent and read-only declare
  ``supports_pause``; the UI shows «Pause» only for those.
* **Cancel** is cooperative. Read-only jobs are additionally hard-cancelled
  after a short grace period; jobs that write to Canvas are never interrupted
  in the middle of a write.
* State is persisted to the ``jobs`` table on every status change; jobs that
  were running when the app stopped are marked «avbrutt» on the next start.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from emneklar.core.errors import AppError, ConflictError, NotFoundError
from emneklar.core.jobs.progress import ProgressTracker
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import Job

log = logging.getLogger(__name__)

ACTIVE = {"queued", "running", "pausing", "paused", "cancelling"}
FINAL = {"completed", "failed", "cancelled", "interrupted"}
CANCEL_GRACE_SECONDS = 2.0


class JobCancelled(Exception):
    """Raised inside a job when the user cancelled it."""


@dataclass
class JobState:
    id: str
    kind: str
    course_id: str | None
    title: str
    params: dict[str, Any]
    supports_pause: bool
    hard_cancel: bool
    status: str = "queued"
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tracker: ProgressTracker = field(default_factory=ProgressTracker)
    gate: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: bool = False
    task: asyncio.Task[Any] | None = None
    status_version: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "course_id": self.course_id,
            "title": self.title,
            "status": self.status,
            "params": self.params,
            "supports_pause": self.supports_pause,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "progress": self.tracker.snapshot(),
        }


class JobContext:
    def __init__(self, state: JobState, manager: JobManager) -> None:
        self._state = state
        self._manager = manager

    @property
    def job_id(self) -> str:
        return self._state.id

    @property
    def progress(self) -> ProgressTracker:
        return self._state.tracker

    @property
    def cancelled(self) -> bool:
        return self._state.cancel_requested

    async def checkpoint(self) -> None:
        """Call between tasks: waits while paused, raises :class:`JobCancelled` if cancelled."""
        state = self._state
        if state.cancel_requested:
            raise JobCancelled
        if not state.gate.is_set():
            if state.status == "pausing" and state.tracker.in_flight == 0:
                self._manager._set_status(state, "paused")
            await state.gate.wait()
        if state.cancel_requested:
            raise JobCancelled


Runner = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobManager:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._jobs: dict[str, JobState] = {}

    # -- lifecycle -------------------------------------------------------------------

    def recover_after_restart(self) -> int:
        """Jobs that were active when the app stopped cannot be resumed – mark them."""
        with self._db.session() as session:
            rows = session.scalars(select(Job).where(Job.status.in_(ACTIVE))).all()
            for row in rows:
                row.status = "interrupted"
                row.error = "EmneKlar ble avsluttet mens jobben kjørte."
                row.finished_at = datetime.now(UTC)
            return len(rows)

    async def shutdown(self) -> None:
        for state in list(self._jobs.values()):
            if state.status in ACTIVE and state.task is not None:
                state.cancel_requested = True
                state.gate.set()
                state.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(state.task, timeout=5)
                self._finish(state, "interrupted", error="EmneKlar ble avsluttet mens jobben kjørte.")

    # -- submission ----------------------------------------------------------------

    def submit(
        self,
        *,
        kind: str,
        title: str,
        runner: Runner,
        course_id: str | None = None,
        params: dict[str, Any] | None = None,
        supports_pause: bool = False,
        hard_cancel: bool = True,
        exclusive: bool = True,
    ) -> JobState:
        if exclusive and course_id is not None:
            for other in self._jobs.values():
                if other.kind == kind and other.course_id == course_id and other.status in ACTIVE:
                    raise ConflictError("job_already_running", job_id=other.id)
        state = JobState(id=str(uuid.uuid4()), kind=kind, course_id=course_id, title=title, params=params or {},
                         supports_pause=supports_pause, hard_cancel=hard_cancel)
        state.gate.set()
        self._jobs[state.id] = state
        with self._db.session() as session:
            session.add(Job(id=state.id, kind=kind, course_id=course_id, title=title, status="queued",
                            params=state.params, created_at=state.created_at))
        state.task = asyncio.create_task(self._run(state, runner), name=f"job-{kind}-{state.id[:8]}")
        return state

    async def _run(self, state: JobState, runner: Runner) -> None:
        state.started_at = datetime.now(UTC)
        self._set_status(state, "running")
        state.tracker.eta.resume()
        context = JobContext(state, self)
        try:
            result = await runner(context)
        except (JobCancelled, asyncio.CancelledError):
            self._finish(state, "cancelled", error=None)
            return
        except AppError as exc:
            log.warning("Jobb %s feilet: %s", state.id, exc.code)
            self._finish(state, "failed", error=exc.message, result={"error_code": exc.code})
            return
        except Exception as exc:
            log.exception("Jobb %s feilet uventet", state.id)
            self._finish(state, "failed", error=f"Uventet feil ({type(exc).__name__}).")
            return
        if state.cancel_requested:
            self._finish(state, "cancelled", result=result or {})
        else:
            self._finish(state, "completed", result=result or {})

    def _set_status(self, state: JobState, status: str) -> None:
        state.status = status
        state.status_version += 1
        with self._db.session() as session:
            row = session.get(Job, state.id)
            if row is not None:
                row.status = status
                if status == "running" and row.started_at is None:
                    row.started_at = state.started_at

    def _finish(self, state: JobState, status: str, *, error: str | None = None,
                result: dict[str, Any] | None = None) -> None:
        if state.status in FINAL:
            return
        state.tracker.eta.pause()
        state.finished_at = datetime.now(UTC)
        state.error = error
        if result is not None:
            state.result = result
        state.tracker.set_current(None)
        self._set_status(state, status)
        with self._db.session() as session:
            row = session.get(Job, state.id)
            if row is not None:
                row.finished_at = state.finished_at
                row.error = error
                row.result = state.result
                row.progress = state.tracker.snapshot()

    # -- control -----------------------------------------------------------------------

    def get(self, job_id: str) -> JobState:
        state = self._jobs.get(job_id)
        if state is None:
            raise NotFoundError("job_not_found")
        return state

    def pause(self, job_id: str) -> JobState:
        state = self.get(job_id)
        if not state.supports_pause or state.status != "running":
            raise AppError("job_not_pausable", status=409)
        state.gate.clear()
        state.tracker.eta.pause()
        self._set_status(state, "pausing" if state.tracker.in_flight else "paused")
        return state

    def resume(self, job_id: str) -> JobState:
        state = self.get(job_id)
        if state.status not in {"paused", "pausing"}:
            raise AppError("job_not_pausable", status=409)
        state.tracker.eta.resume()
        self._set_status(state, "running")
        state.gate.set()
        return state

    def cancel(self, job_id: str) -> JobState:
        state = self.get(job_id)
        if state.status in FINAL:
            return state
        state.cancel_requested = True
        self._set_status(state, "cancelling")
        state.gate.set()
        if state.hard_cancel and state.task is not None:
            asyncio.get_running_loop().call_later(CANCEL_GRACE_SECONDS, self._hard_cancel, state)
        return state

    def _hard_cancel(self, state: JobState) -> None:
        if state.task is not None and not state.task.done():
            state.task.cancel()

    def list(self, *, course_id: str | None = None, active_only: bool = False) -> list[JobState]:
        jobs = [j for j in self._jobs.values() if course_id is None or j.course_id == course_id]
        if active_only:
            jobs = [j for j in jobs if j.status in ACTIVE]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def history(self, *, course_id: str | None = None, limit: int = 20) -> builtins.list[dict[str, Any]]:
        with self._db.session() as session:
            query = select(Job).order_by(Job.created_at.desc()).limit(limit)
            if course_id is not None:
                query = query.where(Job.course_id == course_id)
            return [
                {"id": r.id, "kind": r.kind, "course_id": r.course_id, "title": r.title, "status": r.status,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                 "error": r.error, "result": r.result}
                for r in session.scalars(query).all()
            ]

    async def stream(self, job_id: str, *, poll: float = 0.3, heartbeat: float = 15.0) -> AsyncIterator[dict[str, Any]]:
        """Yield job snapshots whenever progress or status changes (for SSE)."""
        state = self.get(job_id)
        last: tuple[int, int] | None = None
        idle = 0.0
        while True:
            key = (state.tracker.version, state.status_version)
            if key != last:
                last = key
                idle = 0.0
                yield state.public()
                if state.status in FINAL:
                    return
            else:
                idle += poll
                if idle >= heartbeat:
                    idle = 0.0
                    yield {"heartbeat": True}
            await asyncio.sleep(poll)
