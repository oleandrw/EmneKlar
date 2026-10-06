"""Remaining-time estimation from observed work – never from guesses.

* Each task type (page, link, document, quiz …) has its own exponentially
  weighted moving average (EWMA) of observed duration and variance, so a
  remaining mix of slow link checks and fast page checks is estimated from
  what those task types actually cost in *this* run.
* Tasks run concurrently, so summed task time is converted to wall-clock
  time with the observed parallelism (busy time / active wall time, EWMA).
* Until enough observations exist, no number is produced («Beregner …»).
* When the estimate is uncertain (few observations, high variance, task types
  not yet observed) a range is returned instead of false precision.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class _TypeStats:
    mean: float = 0.0
    var: float = 0.0
    count: int = 0

    def add(self, value: float, alpha: float) -> None:
        if self.count == 0:
            self.mean = value
            self.var = 0.0
        else:
            diff = value - self.mean
            incr = alpha * diff
            self.mean += incr
            self.var = (1 - alpha) * (self.var + diff * incr)
        self.count += 1


@dataclass(frozen=True)
class Eta:
    state: Literal["calculating", "estimate", "range", "done"]
    seconds: float | None = None
    low_seconds: float | None = None
    high_seconds: float | None = None
    confidence: Literal["low", "medium", "high"] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "seconds": None if self.seconds is None else round(self.seconds),
            "low_seconds": None if self.low_seconds is None else round(self.low_seconds),
            "high_seconds": None if self.high_seconds is None else round(self.high_seconds),
            "confidence": self.confidence,
        }


@dataclass
class EtaEstimator:
    alpha: float = 0.2
    min_observations: int = 5
    min_active_seconds: float = 3.0
    range_threshold: float = 0.35
    clock: object = field(default=time.monotonic, repr=False)
    _stats: dict[str, _TypeStats] = field(default_factory=dict, repr=False)
    _busy: float = 0.0
    _active: float = 0.0
    _active_since: float | None = None
    _parallelism: float | None = None

    def _now(self) -> float:
        return self.clock()  # type: ignore[operator]

    # -- activity (wall-clock time while work is actually running) ---------------

    def resume(self) -> None:
        if self._active_since is None:
            self._active_since = self._now()

    def pause(self) -> None:
        if self._active_since is not None:
            self._active += self._now() - self._active_since
            self._active_since = None

    def active_seconds(self) -> float:
        running = (self._now() - self._active_since) if self._active_since is not None else 0.0
        return self._active + running

    # -- observations ------------------------------------------------------------

    def observe(self, task_type: str, duration: float) -> None:
        duration = max(0.0, float(duration))
        self._stats.setdefault(task_type, _TypeStats()).add(duration, self.alpha)
        self._busy += duration
        active = self.active_seconds()
        if active > 0.5:
            observed = max(1.0, self._busy / active)
            self._parallelism = observed if self._parallelism is None else (
                (1 - self.alpha) * self._parallelism + self.alpha * observed
            )

    def observations(self) -> int:
        return sum(s.count for s in self._stats.values())

    # -- estimate ------------------------------------------------------------------

    def estimate(self, remaining: dict[str, int]) -> Eta:
        remaining = {k: v for k, v in remaining.items() if v > 0}
        if not remaining:
            return Eta(state="done", seconds=0.0)
        if self.observations() < self.min_observations or self.active_seconds() < self.min_active_seconds:
            return Eta(state="calculating")

        observed = [s for s in self._stats.values() if s.count > 0]
        overall_mean = sum(s.mean * s.count for s in observed) / max(1, sum(s.count for s in observed))
        parallelism = self._parallelism or 1.0

        work = 0.0
        variance = 0.0
        unobserved = 0
        for task_type, count in remaining.items():
            stats = self._stats.get(task_type)
            if stats is None or stats.count == 0:
                # No observation for this type yet: use the run's overall mean, but
                # treat it as highly uncertain (relative SD of 1).
                unobserved += count
                work += count * overall_mean
                variance += count * overall_mean**2
            else:
                work += count * stats.mean
                variance += count * stats.var
        seconds = work / parallelism
        sd = math.sqrt(variance) / parallelism

        total_remaining = sum(remaining.values())
        relative = sd / seconds if seconds > 0 else 0.0
        # Systematic drift (later items larger, network slower) is not captured by
        # the variance above – keep a floor that shrinks as evidence accumulates.
        floor = max(0.1, 0.6 / math.sqrt(self.observations()))
        if unobserved:
            floor = max(floor, 0.25 + 0.5 * unobserved / total_remaining)
        uncertainty = max(relative, floor)

        if uncertainty > self.range_threshold:
            low = max(1.0, seconds * (1 - min(uncertainty, 0.8)))
            high = seconds * (1 + uncertainty)
            return Eta(state="range", seconds=seconds, low_seconds=low, high_seconds=high, confidence="low")
        confidence: Literal["medium", "high"] = "high" if uncertainty <= 0.2 else "medium"
        return Eta(state="estimate", seconds=seconds, confidence=confidence)
