"""Truthful, structured progress for long-running jobs.

Counts are only ever increased by real work: a task is added to a total when
it is known to exist and marked done when it has actually finished. During
discovery (before the totals are known) the phase is reported as such and no
percentage is shown.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from emneklar.core.jobs.eta import EtaEstimator

# Labels for task types shown in the progress panel (Norwegian UI text).
TYPE_LABELS: dict[str, str] = {
    "list": "Innholdslister",
    "page": "Sider",
    "assignment": "Oppgaver",
    "discussion": "Diskusjoner",
    "quiz": "Quiz",
    "syllabus": "Emneplan",
    "image": "Bilder",
    "link": "Lenker",
    "media": "Video og lyd",
    "document": "Dokumenter",
    "module": "Moduler",
    "structure": "Emnestruktur",
    "question": "Quizspørsmål",
    "ai": "KI-forespørsler",
}


@dataclass
class TypeCount:
    total: int = 0
    done: int = 0
    failed: int = 0


@dataclass
class ProgressTracker:
    phase: str = "queued"
    phase_label: str = "Venter …"
    phase_index: int = 0
    phase_count: int = 1
    determinate: bool = False
    current_item: str | None = None
    current_operation: str | None = None
    eta: EtaEstimator = field(default_factory=EtaEstimator)
    _types: dict[str, TypeCount] = field(default_factory=lambda: defaultdict(TypeCount))
    _findings: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _version: int = 0
    _messages: list[str] = field(default_factory=list)

    # -- mutations -----------------------------------------------------------------

    def _bump(self) -> None:
        self._version += 1

    def set_phase(self, phase: str, label: str, *, index: int, count: int, determinate: bool) -> None:
        with self._lock:
            self.phase, self.phase_label = phase, label
            self.phase_index, self.phase_count = index, count
            self.determinate = determinate
            self._bump()

    def add_tasks(self, task_type: str, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            self._types[task_type].total += count
            self._bump()

    def start(self, task_type: str, item: str | None = None, operation: str | None = None) -> float:
        with self._lock:
            self._in_flight += 1
            if item is not None:
                self.current_item = item
            if operation is not None:
                self.current_operation = operation
            self._bump()
        return time.monotonic()

    def finish(self, task_type: str, started: float, *, failed: bool = False) -> None:
        duration = time.monotonic() - started
        with self._lock:
            counts = self._types[task_type]
            counts.done += 1
            if failed:
                counts.failed += 1
            self._in_flight = max(0, self._in_flight - 1)
            self.eta.observe(task_type, duration)
            self._bump()

    def set_current(self, item: str | None = None, operation: str | None = None) -> None:
        with self._lock:
            self.current_item = item
            if operation is not None:
                self.current_operation = operation
            self._bump()

    def add_findings(self, key: str, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            self._findings[key] += count
            self._bump()

    def note(self, message: str) -> None:
        with self._lock:
            self._messages.append(message)
            self._messages = self._messages[-20:]
            self._bump()

    # -- reads ---------------------------------------------------------------------

    @property
    def version(self) -> int:
        return self._version

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            types = {k: {"label": TYPE_LABELS.get(k, k), "total": v.total, "done": v.done, "failed": v.failed}
                     for k, v in self._types.items() if v.total > 0}
            total = sum(v.total for v in self._types.values())
            done = sum(v.done for v in self._types.values())
            remaining = {k: v.total - v.done for k, v in self._types.items()}
            percent = None
            if self.determinate and total > 0:
                percent = min(100, int(done * 100 / total))
            eta = self.eta.estimate(remaining) if self.determinate else None
            return {
                "phase": self.phase,
                "phase_label": self.phase_label,
                "phase_index": self.phase_index,
                "phase_count": self.phase_count,
                "determinate": self.determinate,
                "percent": percent,
                "done": done,
                "total": total,
                "types": types,
                "current_item": self.current_item,
                "current_operation": self.current_operation,
                "findings": dict(self._findings),
                "eta": eta.as_dict() if eta else {"state": "calculating"},
                "in_flight": self._in_flight,
                "messages": list(self._messages),
                "version": self._version,
            }
