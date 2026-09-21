"""Exercise launch/recovery boundaries, rather than isolated policy predicates."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands

from commons.community_repo.git import CommandResult, CommunityRepo
from commons.community_repo.projects import render_project_artifact
from commons.community_repo.schemas import DiscordSource, ProjectArtifact
from commons.config import DiscordConfig, PolicyConfig
from commons.digest import DigestPeriod, ProjectCandidate, build_candidate_text
from commons.discord import bot as bot_module
from commons.discord import sync
from commons.discord.archive import ArchiveRequest, ArchiveService, TranscriptMessage
from commons.discord.bot import CommonsBot
from commons.discord.commands import (
    archive_access_denial,
    archive_context_callback,
    collect_activity,
    register_commands,
)
from commons.discord.digest import DigestService
from commons.errors import GitError, GitPushError, LLMError
from commons.news.ingest import IngestionResult
from commons.settings import Settings
from fakes import FakeLLMClient, FakeRepo


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout.strip()


def commit(path: Path, filename: str, text: str) -> None:
    (path / filename).write_text(text, encoding="utf-8")
    git(path, "add", filename)
    git(path, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", filename)


@pytest.fixture
def pushed_repo(repo_with_remote, local_push_supported, tmp_path):
    if not local_push_supported:
        pytest.skip("local bare-remote transport unavailable")
    git(repo_with_remote.path, "push", "-u", "origin", "main")
    repo = CommunityRepo(repo_with_remote.path, lock_path=tmp_path / "writer.lock")
    repo.write_artifact("data/knowledge/first.md", "first", commit_message="archive: first")
    return repo


def test_remote_maintainer_update_does_not_block_writer(pushed_repo, tmp_path):
    other = tmp_path / "maintainer"
    git(tmp_path, "clone", git(pushed_repo.path, "remote", "get-url", "origin"), str(other))
    commit(other, "human.md", "maintainer change")
    git(other, "push", "origin", "main")
    result = pushed_repo.write_artifact(
        "data/knowledge/next.md", "next", commit_message="archive: next"
    )
    assert result.pushed
    assert (pushed_repo.path / "human.md").exists()


def test_digest_reads_remote_project_edits_before_synthesis(pushed_repo, tmp_path):
    other = tmp_path / "maintainer"
    git(tmp_path, "clone", git(pushed_repo.path, "remote", "get-url", "origin"), str(other))
    (other / "data/projects").mkdir(parents=True)
    commit(
        other,
        "data/projects/p.md",
        render_project_artifact(
            ProjectArtifact(title="Project", goal="Goal", current_state="Remote update")
        ),
    )
    git(other, "push", "origin", "main")
    projects = DigestService(pushed_repo, FakeLLMClient()).current_projects()
    assert len(projects) == 1 and projects[0].current_state == "Remote update"


def test_manual_push_recovers_failed_write_without_marker_edit(pushed_repo, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(pushed_repo, "push", lambda: CommandResult(1, "", "offline"))
        with pytest.raises(GitPushError):
            pushed_repo.write_artifact(
                "data/knowledge/pending.md", "pending", commit_message="archive: pending"
            )
    with pytest.raises(GitPushError):
        pushed_repo.write_artifact(
            "data/knowledge/unrelated.md", "x", commit_message="archive: unrelated"
        )
    assert not (pushed_repo.path / "data/knowledge/unrelated.md").exists()
    git(pushed_repo.path, "push", "origin", "main")
    result = pushed_repo.write_artifact(
        "data/knowledge/pending.md", "pending", commit_message="archive: retry"
    )
    assert not result.committed
    assert pushed_repo.write_artifact(
        "data/knowledge/new.md", "new", commit_message="archive: new"
    ).pushed


def request(source_id=1):
    return ArchiveRequest(
        source=DiscordSource(discord_message_id=source_id),
        messages=[TranscriptMessage(author="a", content="discussion")],
    )


@pytest.mark.parametrize("same_source", [True, False])
def test_concurrent_archives_keep_atomic_identity_and_filenames(pushed_repo, same_source):
    barrier = threading.Barrier(2)

    class LLM(FakeLLMClient):
        def complete_json(self, **kwargs):
            barrier.wait(timeout=30)
            return super().complete_json(**kwargs)

    service = ArchiveService(pushed_repo, LLM())
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(service.archive, [request(1), request(1 if same_source else 2)]))
    assert sum(outcome.created for outcome in outcomes) == (1 if same_source else 2)
    assert len({outcome.relative_path for outcome in outcomes}) == (1 if same_source else 2)


def test_existing_archive_needs_no_llm_even_when_budget_blocks(tmp_path):
    repo = FakeRepo(tmp_path)
    first = ArchiveService(repo, FakeLLMClient()).archive(request())
    unavailable = FakeLLMClient(error=LLMError("budget exhausted"))
    second = ArchiveService(repo, unavailable).archive(request())
    assert first.relative_path == second.relative_path
    assert not second.created and unavailable.operations == []


def test_old_live_lock_is_not_stolen_by_same_process_thread(tmp_path):
    path = tmp_path / "lock"
    owner = CommunityRepo(tmp_path, lock_path=path, lock_timeout=0.03)
    with owner.lock():
        os.utime(path, (time.time() - 10000, time.time() - 10000))
        with ThreadPoolExecutor(max_workers=1) as pool:

            def contender():
                with CommunityRepo(tmp_path, lock_path=path, lock_timeout=0.03).lock():
                    pytest.fail("live lock was stolen")

            with pytest.raises(GitError):
                pool.submit(contender).result(timeout=5)
    with owner.lock(timeout=0):
        pass


def test_process_exit_releases_os_lock(tmp_path):
    path = tmp_path / "lock"
    source = str(Path(__file__).resolve().parents[1] / "src")
    code = (
        f"import sys, os; sys.path.insert(0, {source!r}); "
        "from pathlib import Path; from commons.community_repo.git import CommunityRepo; "
        f"repo=CommunityRepo(Path({str(tmp_path)!r}), lock_path=Path({str(path)!r})); "
        "held=repo.lock(); held.__enter__(); os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=20)
    with CommunityRepo(tmp_path, lock_path=path).lock(timeout=0):
        pass


async def test_bootstrap_uses_real_sdk_overwrite_validation():
    class Guild:
        id = 1

        def __init__(self):
            self._channels = {}
            self._state = NS(http=NS(create_channel=AsyncMock(side_effect=self.response)))
            self.roles = [
                discord.Role(
                    guild=self,
                    state=self._state,
                    data={
                        "id": "1",
                        "name": "@everyone",
                        "permissions": "0",
                        "position": 0,
                    },
                )
            ]
            self.default_role = self.roles[0]
            self.me = discord.Object(id=2)

        @property
        def channels(self):
            return list(self._channels.values())

        @property
        def categories(self):
            return [c for c in self.channels if isinstance(c, discord.CategoryChannel)]

        async def response(self, guild_id, kind, **kwargs):
            overwrites = kwargs["permission_overwrites"]
            if not overwrites and kwargs["parent_id"] is not None:
                # Discord synchronizes unspecified overwrites with the category.
                parent = self._channels[kwargs["parent_id"]]
                overwrites = [item._asdict() for item in parent._overwrites]
            return {
                "id": str(100 + len(self._channels)),
                "type": kind,
                "position": 0,
                "name": kwargs["name"],
                "parent_id": kwargs["parent_id"],
                "permission_overwrites": overwrites,
            }

        _create_channel = discord.Guild._create_channel
        create_category = discord.Guild.create_category
        create_text_channel = discord.Guild.create_text_channel

    guild = Guild()
    config = DiscordConfig.model_validate(
        {
            "categories": {
                "START": {"channels": ["start-here"]},
                "PRIVATE": {"private": True, "channels": ["ops"]},
            }
        }
    )
    # The plan is authoritative: what a dry run reports is what apply creates.
    plan = sync.plan_sync(sync.guild_state(guild), config)
    assert len(plan.create_channels) == 2
    await sync.apply_sync(guild, config, plan)
    assert len(guild.channels) == 4
    private = next(c for c in guild.categories if c.name == "PRIVATE")
    ops = next(c for c in guild.channels if c.name == "ops")
    assert ops.overwrites_for(guild.default_role).view_channel is False
    assert [item._asdict() for item in ops._overwrites] == [
        item._asdict() for item in private._overwrites
    ]


def test_sync_failure_returns_nonzero(tmp_path, monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        def event(self, callback):
            self.callback = callback
            return callback

        def get_guild(self, guild_id):
            return object()

        async def close(self):
            pass

        def run(self, token):
            asyncio.run(self.callback())

    settings = Settings(
        _env_file=None,
        discord_token="fake",
        discord_test_guild_id=1,
        runtime_dir=tmp_path / "runtime",
        community_repo_path=tmp_path / "repo",
    )
    monkeypatch.setattr(sync, "load_settings", lambda: settings)
    monkeypatch.setattr(sync, "load_discord_config", lambda path: DiscordConfig())
    monkeypatch.setattr(sync, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(sync.discord, "Client", Client)
    monkeypatch.setattr(sync, "sync_guild", AsyncMock(side_effect=RuntimeError("failed")))
    assert sync.main([]) == 1


def interaction_fixture(*, history=True, allow=True, private=False):
    perms = discord.Permissions(view_channel=True, read_message_history=history)
    guild = NS(id=1, me=NS(id=100))
    user = NS(id=10, guild=guild, display_name="a")
    if private:
        channel = MagicMock(spec=discord.Thread)
        channel.is_private.return_value = True
        channel.fetch_member = AsyncMock(
            side_effect=discord.NotFound(NS(status=404, reason="missing"), "missing")
        )
        channel.parent = None
    else:
        channel = NS()
    channel.guild = guild
    channel.permissions_for = lambda member: perms
    channel.fetch_message = AsyncMock()
    channel.history = MagicMock()
    channel.id = 2
    client = discord.Client(intents=discord.Intents.none())
    client.tree = app_commands.CommandTree(client)
    register_commands(client)
    client.settings = NS(effective_guild_id=1)
    client.policy = PolicyConfig()
    client.policy.archive.allow_members = allow
    client.get_channel = lambda channel_id: channel
    interaction = NS(
        guild=guild,
        user=user,
        channel=channel,
        client=client,
        response=NS(is_done=lambda: False, send_message=AsyncMock(), defer=AsyncMock()),
        followup=NS(send=AsyncMock()),
    )
    return interaction, channel


@pytest.mark.parametrize("mode", ["slash", "context", "thread"])
@pytest.mark.parametrize("denial", ["history", "policy", "private", "guild"])
async def test_denied_command_never_reads_source(mode, denial):
    interaction, channel = interaction_fixture(
        history=denial != "history",
        allow=denial != "policy",
        private=denial == "private" or mode == "thread",
    )
    if denial == "guild":
        channel.guild = NS(id=999)
    if mode == "context":
        message = NS(channel=channel, guild=channel.guild, thread=None)
        await archive_context_callback(interaction, message)
    else:
        await interaction.client.tree.get_command("archive").callback(
            interaction,
            message_link=None if mode == "thread" else "https://discord.com/channels/1/2/3",
        )
    channel.fetch_message.assert_not_awaited()
    channel.history.assert_not_called()
    interaction.response.send_message.assert_awaited_once()


async def test_private_thread_checks_both_members_and_allows_verified_access():
    interaction, channel = interaction_fixture(private=True)
    channel.fetch_member.side_effect = None
    assert await archive_access_denial(interaction, channel) is None
    assert [call.args[0] for call in channel.fetch_member.await_args_list] == [10, 100]
    channel.fetch_member.reset_mock()
    channel.fetch_member.side_effect = [
        NS(id=10),
        discord.NotFound(NS(status=404, reason="missing"), "missing"),
    ]
    assert await archive_access_denial(interaction, channel) is not None
    channel.history.assert_not_called()


async def test_bot_history_permission_is_required():
    interaction, channel = interaction_fixture()
    channel.permissions_for = lambda member: discord.Permissions(
        view_channel=True, read_message_history=member.id != 100
    )
    assert await archive_access_denial(interaction, channel) is not None
    channel.history.assert_not_called()


async def test_final_digest_input_keeps_recent_parent_and_archived_thread():
    now = datetime.now(UTC)

    def message(i, content):
        return NS(
            author=NS(display_name="a"),
            content=content,
            created_at=now - timedelta(minutes=200 - i),
            jump_url=f"https://example.test/{i}",
        )

    async def parent_history(**kwargs):
        for i in reversed(range(200)):
            yield message(i, f"PARENT_{i:03d}")

    async def thread_history(**kwargs):
        yield message(200, "THREAD_MARKER")

    archived = NS(
        id=99,
        last_message_id=100,
        name="archived",
        archive_timestamp=now,
        is_private=lambda: False,
        history=thread_history,
    )

    async def archived_threads(**kwargs):
        yield archived

    private = NS(is_private=lambda: True, history=MagicMock())
    channel = NS(
        name="infra", history=parent_history, threads=[private], archived_threads=archived_threads
    )
    activity = await collect_activity(
        NS(text_channels=[channel]), {"infra"}, DigestPeriod.from_label("7d")
    )
    text = build_candidate_text(activity)
    assert "PARENT_199" in text and "THREAD_MARKER" in text
    assert "PARENT_000" not in text
    private.history.assert_not_called()


def test_project_goal_does_not_hide_current_state():
    text = build_candidate_text(
        [],
        projects=[ProjectCandidate(title="p", status="active", goal="GOAL", current_state="STATE")],
    )
    assert "GOAL" in text and "STATE" in text


@pytest.fixture
def bot(tmp_path):
    return CommonsBot(
        settings=Settings(
            _env_file=None,
            runtime_dir=tmp_path / "runtime",
            community_repo_path=tmp_path / "repo",
            discord_test_guild_id=1,
        ),
        repo=FakeRepo(tmp_path / "repo"),
        llm=FakeLLMClient(),
        policy=PolicyConfig(),
    )


async def test_scheduled_failure_notifies_once_then_recovers(bot, monkeypatch):
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "notify_bot_log", notify)
    bot._generate_and_send_digest = AsyncMock(
        side_effect=[RuntimeError("send failed"), RuntimeError("again"), None]
    )
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await bot._scheduled_digest_job("7d")
    assert notify.await_count == 1
    await bot._scheduled_digest_job("7d")
    assert notify.await_count == 2 and "recovered" in notify.call_args.args[1]


@pytest.mark.parametrize("stage", ["generation", "delivery"])
async def test_real_scheduled_path_reports_generation_or_delivery_failure(bot, monkeypatch, stage):
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "notify_bot_log", notify)
    monkeypatch.setattr(bot, "get_guild", lambda guild_id: NS(text_channels=[NS(name="digest")]))
    monkeypatch.setattr(bot_module, "collect_activity", AsyncMock(return_value=[]))
    monkeypatch.setattr(bot_module, "news_candidates_for", lambda *args: [])
    monkeypatch.setattr(bot_module, "radar_candidates_for", lambda *args: [])
    generate = MagicMock(side_effect=RuntimeError("generate") if stage == "generation" else None)
    monkeypatch.setattr(bot.digest_service, "generate", generate)
    send = AsyncMock(side_effect=RuntimeError("delivery"))
    monkeypatch.setattr(bot_module, "send_digest", send)
    with pytest.raises(RuntimeError):
        await bot._scheduled_digest_job("7d")
    notify.assert_awaited_once()
    assert send.await_count == (0 if stage == "generation" else 1)


async def test_repeated_source_failure_and_recovery_are_notified(bot, monkeypatch):
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_module, "notify_bot_log", notify)
    for count in (1, 2, 3, 4):
        result = IngestionResult("feed", 0, 0, 0, error="offline", consecutive_failures=count)
        monkeypatch.setattr(bot_module, "run_ingestion", lambda settings, result=result: [result])
        await bot._ingestion_job()
    assert notify.await_count == 1
    monkeypatch.setattr(
        bot_module, "run_ingestion", lambda settings: [IngestionResult("feed", 0, 0, 0)]
    )
    await bot._ingestion_job()
    assert notify.await_count == 2 and "recovered" in notify.call_args.args[1]
