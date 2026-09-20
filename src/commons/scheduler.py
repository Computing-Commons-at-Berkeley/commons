"""Minimal in-process scheduler (plan section 30).

One runtime: bot process + simple scheduler + SQLite. This is deliberately not a
job framework. Jobs are plain callables (sync or async); due-time logic is
trivially testable and one failing job never stops the loop.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from commons.logging import get_logger

log = get_logger(__name__)


@dataclass
class ScheduledJob:
    name: str
    interval: timedelta
    action: Callable[[], Any]
    last_run: datetime | None = None

    def is_due(self, now: datetime) -> bool:
        return self.last_run is None or (now - self.last_run) >= self.interval


class Scheduler:
    def __init__(self, jobs: list[ScheduledJob] | None = None) -> None:
        self.jobs: list[ScheduledJob] = list(jobs or [])

    def add(self, name: str, interval: timedelta, action: Callable[[], Any]) -> ScheduledJob:
        job = ScheduledJob(name=name, interval=interval, action=action)
        self.jobs.append(job)
        return job

    def run_pending(self, *, now: datetime | None = None) -> list[str]:
        """Run due sync jobs. Used by tests; async jobs go through run_due."""

        moment = now or datetime.now(UTC)
        ran: list[str] = []
        for job in self.jobs:
            if not job.is_due(moment):
                continue
            try:
                job.action()
            except Exception:  # noqa: BLE001 - one job failing must not stop the loop
                log.exception("scheduled job %s failed", job.name)
            job.last_run = moment
            ran.append(job.name)
        return ran

    async def run_due(self, *, now: datetime | None = None) -> list[str]:
        """Run due jobs, awaiting any coroutine actions."""

        moment = now or datetime.now(UTC)
        ran: list[str] = []
        for job in self.jobs:
            if not job.is_due(moment):
                continue
            try:
                result = job.action()
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - one job failing must not stop the loop
                log.exception("scheduled job %s failed", job.name)
            job.last_run = moment
            ran.append(job.name)
        return ran

    async def serve(self, *, poll_seconds: float = 60.0) -> None:
        log.info("scheduler starting with %d job(s)", len(self.jobs))
        while True:
            await self.run_due()
            await asyncio.sleep(poll_seconds)
