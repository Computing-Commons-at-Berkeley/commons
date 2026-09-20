from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from commons.scheduler import Scheduler


def test_jobs_run_when_due() -> None:
    calls: list[str] = []
    scheduler = Scheduler()
    scheduler.add("ingest", timedelta(minutes=10), lambda: calls.append("ingest"))
    moment = datetime(2026, 1, 1, tzinfo=UTC)

    assert scheduler.run_pending(now=moment) == ["ingest"]
    assert scheduler.run_pending(now=moment + timedelta(minutes=5)) == []
    assert scheduler.run_pending(now=moment + timedelta(minutes=10)) == ["ingest"]
    assert calls == ["ingest", "ingest"]


def test_failing_job_does_not_stop_the_loop() -> None:
    calls: list[str] = []

    def boom() -> None:
        raise RuntimeError("source exploded")

    scheduler = Scheduler()
    scheduler.add("bad", timedelta(seconds=1), boom)
    scheduler.add("good", timedelta(seconds=1), lambda: calls.append("good"))

    ran = scheduler.run_pending()
    assert ran == ["bad", "good"]
    assert calls == ["good"]


async def test_serve_runs_async_actions() -> None:
    calls: list[str] = []

    async def action() -> None:
        calls.append("async")

    scheduler = Scheduler()
    scheduler.add("async-job", timedelta(seconds=0), action)

    task = asyncio.create_task(scheduler.serve(poll_seconds=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls
