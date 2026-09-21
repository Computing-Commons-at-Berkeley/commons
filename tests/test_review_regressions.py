"""Regression tests for the 2026-09-19 code review findings (R01-R14)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from commons.community_repo.git import CommunityRepo
from commons.community_repo.schemas import DigestSection
from commons.digest import (
    ChannelActivity,
    DigestMessage,
    NewsCandidate,
    ProjectCandidate,
    RadarCandidate,
    build_candidate_text,
)
from commons.discord.commands import (
    AccessContext,
    check_archive_access,
    digest_chunks,
    merge_context,
)
from commons.discord.digest import DigestOutcome
from commons.errors import GitError
from commons.scheduler import SKIP, Scheduler


# --- R01: archive authorization -------------------------------------------
def allow(**overrides: object) -> AccessContext:
    base: dict[str, object] = {
        "effective_guild_id": 1,
        "source_guild_id": 1,
        "allow_members": True,
        "invoker_is_member": True,
        "invoker_can_view": True,
        "bot_can_view": True,
        "invoker_can_read_history": True,
    }
    base.update(overrides)
    return AccessContext(**base)  # type: ignore[arg-type]


def test_access_allows_only_the_intended_member_and_source() -> None:
    assert check_archive_access(allow()) is None


def test_access_denies_other_guild_without_reading() -> None:
    reason = check_archive_access(allow(source_guild_id=999))
    assert reason is not None and "different server" in reason


def test_access_denies_unreadable_or_disallowed_member() -> None:
    assert check_archive_access(allow(invoker_can_view=False)) is not None
    assert check_archive_access(allow(bot_can_view=False)) is not None
    assert check_archive_access(allow(allow_members=False)) is not None
    assert check_archive_access(allow(invoker_is_member=False)) is not None


# --- R03: never commit unrelated staged work ------------------------------
def test_write_refuses_a_dirty_index(repo_with_remote, tmp_path: Path) -> None:
    path = repo_with_remote.path
    (path / "unrelated.txt").write_text("human work", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "unrelated.txt"], check=True)

    repo = CommunityRepo(path, lock_path=tmp_path / "lock")
    with pytest.raises(GitError):
        repo.write_artifact("data/knowledge/a.md", "x\n", commit_message="archive: add a")

    status = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "unrelated.txt" in status.stdout
    assert not (path / "data" / "knowledge" / "a.md").exists()


# --- R05: slow sync jobs must not block the event loop --------------------
async def test_slow_sync_job_does_not_block_the_event_loop() -> None:
    scheduler = Scheduler()
    scheduler.add("slow", timedelta(seconds=0), lambda: time.sleep(0.2))

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    beat = asyncio.create_task(heartbeat())
    await scheduler.run_due()
    beat.cancel()
    with pytest.raises(asyncio.CancelledError):
        await beat

    assert ticks > 5


# --- R06: retry/readiness/restart -----------------------------------------
def test_failure_schedules_a_prompt_retry() -> None:
    def boom() -> None:
        raise RuntimeError("boom")

    scheduler = Scheduler()
    job = scheduler.add("flaky", timedelta(days=7), boom, retry_interval=timedelta(minutes=5))
    moment = datetime(2026, 1, 1, tzinfo=UTC)

    scheduler.run_pending(now=moment)

    assert job.failures == 1
    assert not job.is_due(moment + timedelta(minutes=1))
    assert job.is_due(moment + timedelta(minutes=5))


def test_skip_sentinel_schedules_a_prompt_retry() -> None:
    scheduler = Scheduler()
    job = scheduler.add(
        "not-ready", timedelta(days=7), lambda: SKIP, retry_interval=timedelta(minutes=5)
    )
    moment = datetime(2026, 1, 1, tzinfo=UTC)

    scheduler.run_pending(now=moment)

    assert job.last_success is None
    assert job.is_due(moment + timedelta(minutes=5))


def test_scheduler_state_survives_a_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "scheduler_state.json"
    moment = datetime(2026, 1, 1, tzinfo=UTC)

    first = Scheduler(state_path=state_path)
    first.add("weekly", timedelta(days=7), lambda: None)
    first.run_pending(now=moment)
    assert state_path.exists()

    second = Scheduler(state_path=state_path)
    restored = second.add("weekly", timedelta(days=7), lambda: None)
    assert not restored.is_due(moment + timedelta(days=3))
    assert restored.is_due(moment + timedelta(days=8))


# --- R07: real digest content reaches Discord -----------------------------
def make_outcome(body: str) -> DigestOutcome:
    return DigestOutcome(
        period="7d",
        relative_path="data/digests/2026-01-01-7d.md",
        section_headings=["ML Research"],
        commit_sha="abcdef",
        sections=[DigestSection(heading="ML Research", body=body)],
    )


def test_digest_chunks_carry_the_synthesized_body() -> None:
    chunks = digest_chunks(make_outcome("SYNTHESIS_BODY_MARKER"))
    assert any("SYNTHESIS_BODY_MARKER" in chunk for chunk in chunks)
    assert any("ML Research" in chunk for chunk in chunks)


def test_digest_chunks_are_bounded() -> None:
    chunks = digest_chunks(make_outcome("x" * 5000), limit=1000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)


# --- R09: stale lock reclamation ------------------------------------------
def test_leftover_lock_file_does_not_block_a_new_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    lock_path.write_text("{}", encoding="utf-8")
    stale = time.time() - 10_000
    os.utime(lock_path, (stale, stale))

    repo = CommunityRepo(tmp_path, lock_path=lock_path, lock_timeout=1.0)
    with repo.lock():
        pass
    # The OS owns exclusion; the stable file must never be unlinked by a writer.
    assert lock_path.exists()


# --- R10: selected message and parent survive the context window ----------
class FakeMessage:
    def __init__(self, id: int) -> None:
        self.id = id


def test_merge_context_keeps_parent_and_selected() -> None:
    parent = FakeMessage(1)
    selected = FakeMessage(2)
    thread = [FakeMessage(1), FakeMessage(2), FakeMessage(3)]
    assert [m.id for m in merge_context(selected, thread, parent)] == [1, 2, 3]


def test_merge_context_keeps_selected_beyond_the_window() -> None:
    selected = FakeMessage(9)
    thread = [FakeMessage(1), FakeMessage(3)]
    assert [m.id for m in merge_context(selected, thread, None)] == [9, 1, 3]


# --- R14: every source class survives the candidate budget ----------------
def test_candidate_budget_keeps_every_source_class() -> None:
    activity = [
        ChannelActivity(
            channel="loud",
            messages=[
                DigestMessage(channel="loud", author="alice", content="x" * 5000, jump_url="u")
            ],
        )
    ]
    text = build_candidate_text(
        activity,
        news=[NewsCandidate(title="Paper", url="https://e.test/p", category="ml")],
        projects=[ProjectCandidate(title="Alpha", status="active", goal="ship it")],
        radar=[RadarCandidate(repo="o/r", title="v1", url="https://e.test/r", kind="release")],
        max_chars=2000,
    )
    assert "## News: ml" in text
    assert "## Projects" in text
    assert "## OSS Radar" in text
    assert "Paper" in text
    assert "ship it" in text
