"""ETA estimation and job control (pause/resume/cancel)."""

from __future__ import annotations

import asyncio

import pytest

from emneklar.core.container import AppContainer
from emneklar.core.jobs.eta import EtaEstimator
from emneklar.core.jobs.manager import JobContext, JobManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_eta_waits_for_enough_observations() -> None:
    clock = FakeClock()
    eta = EtaEstimator(clock=clock)
    eta.resume()
    clock.now = 1.0
    eta.observe("page", 0.5)
    assert eta.estimate({"page": 10}).state == "calculating"


def test_eta_uses_per_type_cost_and_parallelism() -> None:
    clock = FakeClock()
    eta = EtaEstimator(clock=clock)
    eta.resume()
    # 4 workers in parallel: 40 link checks of 1 s each finish in 10 s of wall time.
    for i in range(40):
        clock.now = (i + 1) * 0.25
        eta.observe("link", 1.0)
    for _ in range(40):
        eta.observe("page", 0.01)
    estimate = eta.estimate({"link": 20, "page": 100})
    assert estimate.state in {"estimate", "range"}
    assert estimate.seconds is not None
    # ≈ 20 links × 1 s / parallelism (~4-8) – far below the naive 20 s, far above 0.
    assert 1.5 < estimate.seconds < 12


def test_eta_shows_range_for_unobserved_task_types() -> None:
    clock = FakeClock()
    eta = EtaEstimator(clock=clock)
    eta.resume()
    for i in range(10):
        clock.now = i + 1.0
        eta.observe("page", 1.0)
    estimate = eta.estimate({"page": 5, "document": 50})
    assert estimate.state == "range"
    assert estimate.low_seconds is not None and estimate.high_seconds is not None
    assert estimate.low_seconds < estimate.high_seconds


def test_eta_paused_time_is_not_counted() -> None:
    clock = FakeClock()
    eta = EtaEstimator(clock=clock)
    eta.resume()
    clock.now = 5.0
    eta.pause()
    clock.now = 500.0
    assert eta.active_seconds() == pytest.approx(5.0)


async def _wait_for(predicate, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timeout")
        await asyncio.sleep(0.01)


async def test_job_pause_resume_and_cancel(container: AppContainer) -> None:
    container.migrate()
    manager = JobManager(container.db)
    processed: list[int] = []
    release = asyncio.Event()

    async def runner(ctx: JobContext) -> dict:
        ctx.progress.set_phase("analyze", "Analyserer", index=1, count=1, determinate=True)
        ctx.progress.add_tasks("page", 50)
        for i in range(50):
            await ctx.checkpoint()
            started = ctx.progress.start("page", item=f"Side {i}")
            await release.wait()
            await asyncio.sleep(0.001)
            ctx.progress.finish("page", started)
            processed.append(i)
        return {"processed": len(processed)}

    state = manager.submit(kind="test", title="Test", runner=runner, course_id="1", supports_pause=True)
    release.set()
    await _wait_for(lambda: len(processed) >= 3)
    manager.pause(state.id)
    await _wait_for(lambda: state.status == "paused")
    count_when_paused = len(processed)
    await asyncio.sleep(0.05)
    assert len(processed) == count_when_paused, "no new task may start while paused"
    manager.resume(state.id)
    await _wait_for(lambda: len(processed) > count_when_paused)
    manager.cancel(state.id)
    await _wait_for(lambda: state.status == "cancelled")
    assert len(processed) < 50
    history = manager.history(course_id="1")
    assert history[0]["status"] == "cancelled"


async def test_only_one_job_of_a_kind_per_course(container: AppContainer) -> None:
    container.migrate()
    manager = JobManager(container.db)
    block = asyncio.Event()

    async def runner(ctx: JobContext) -> dict:
        await block.wait()
        return {}

    manager.submit(kind="analysis", title="A", runner=runner, course_id="7")
    from emneklar.core.errors import ConflictError

    with pytest.raises(ConflictError):
        manager.submit(kind="analysis", title="B", runner=runner, course_id="7")
    block.set()


async def test_failed_job_reports_norwegian_message(container: AppContainer) -> None:
    container.migrate()
    manager = JobManager(container.db)

    async def runner(ctx: JobContext) -> dict:
        from emneklar.core.errors import AppError

        raise AppError("canvas_unavailable")

    state = manager.submit(kind="x", title="X", runner=runner)
    await _wait_for(lambda: state.status == "failed")
    assert state.error and "Canvas" in state.error
