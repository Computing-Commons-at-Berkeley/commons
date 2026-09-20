"""Minimal in-process scheduler (plan section 30).

One runtime: bot process + simple scheduler + SQLite. Jobs are plain callables
(sync or async). Synchronous work runs in a worker thread so slow HTTP cannot
block the Discord event loop. Due times are persisted so a restart neither loses
nor duplicates the intended weekly run (review R05, R06).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from commons.logging import get_logger

log = get_logger(__name__)

# An action may return this sentinel to ask for a short retry instead of the
# full interval (for example "the guild is not ready yet").
SKIP = object()
DEFAULT_RETRY = timedelta(minutes=15)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass
class ScheduledJob:
    name: str
    interval: timedelta
    action: Callable[[], Any]
    retry_interval: timedelta = DEFAULT_RETRY
    next_due: datetime | None = None
    last_success: datetime | None = None
    failures: int = 0

    def is_due(self, now: datetime) -> bool:
        return self.next_due is None or now >= self.next_due


class Scheduler:
    def __init__(
        self,
        jobs: list[ScheduledJob] | None = None,
        *,
        state_path: Path | None = None,
    ) -> None:
        self.jobs: list[ScheduledJob] = list(jobs or [])
        self.state_path = Path(state_path) if state_path is not None else None
        self._state = self._load_state()

    def add(
        self,
        name: str,
        interval: timedelta,
        action: Callable[[], Any],
        *,
        retry_interval: timedelta = DEFAULT_RETRY,
    ) -> ScheduledJob:
        job = ScheduledJob(
            name=name,
            interval=interval,
            action=action,
            retry_interval=retry_interval,
        )
        saved = self._state.get(name) or {}
        job.last_success = _parse_ts(saved.get("last_success"))
        if job.last_success is not None:
            job.next_due = job.last_success + interval
        self.jobs.append(job)
        return job

    # --- persisted schedule state --------------------------------------
    def _load_state(self) -> dict[str, dict[str, Any]]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("could not read scheduler state at %s", self.state_path)
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        payload = {
            job.name: {"last_success": job.last_success.isoformat()}
            for job in self.jobs
            if job.last_success is not None
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            log.warning("could not write scheduler state at %s", self.state_path)

    def _finish(self, job: ScheduledJob, moment: datetime, result: Any) -> None:
        if result is SKIP:
            job.next_due = moment + job.retry_interval
            return
        job.last_success = moment
        job.failures = 0
        job.next_due = moment + job.interval

    # --- running --------------------------------------------------------
    def run_pending(self, *, now: datetime | None = None) -> list[str]:
        """Run due sync jobs. Used by tests; async jobs go through run_due."""

        moment = now or datetime.now(UTC)
        ran: list[str] = []
        for job in self.jobs:
            if not job.is_due(moment):
                continue
            try:
                result = job.action()
            except Exception:  # noqa: BLE001 - one job failing must not stop the loop
                log.exception("scheduled job %s failed", job.name)
                job.failures += 1
                job.next_due = moment + job.retry_interval
                ran.append(job.name)
                continue
            self._finish(job, moment, result)
            ran.append(job.name)
        self._save_state()
        return ran

    async def run_due(self, *, now: datetime | None = None) -> list[str]:
        """Run due jobs off the event loop, awaiting genuinely async actions."""

        moment = now or datetime.now(UTC)
        ran: list[str] = []
        for job in self.jobs:
            if not job.is_due(moment):
                continue
            try:
                if inspect.iscoroutinefunction(job.action):
                    result = await job.action()
                else:
                    result = await asyncio.to_thread(job.action)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception:  # noqa: BLE001 - one job failing must not stop the loop
                log.exception("scheduled job %s failed", job.name)
                job.failures += 1
                job.next_due = moment + job.retry_interval
                ran.append(job.name)
                continue
            self._finish(job, moment, result)
            ran.append(job.name)
        self._save_state()
        return ran

    async def serve(self, *, poll_seconds: float = 60.0) -> None:
        log.info("scheduler starting with %d job(s)", len(self.jobs))
        while True:
            await self.run_due()
            await asyncio.sleep(poll_seconds)
