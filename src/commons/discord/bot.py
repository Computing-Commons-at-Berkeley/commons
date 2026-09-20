"""Bot entry point: wire configuration, services, and Discord together."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
from datetime import timedelta

import discord

from commons.community_repo.git import CommunityRepo
from commons.config import PolicyConfig, load_policy_config
from commons.digest import DigestPeriod
from commons.discord.archive import ArchiveService
from commons.discord.commands import (
    collect_activity,
    news_candidates_for,
    radar_candidates_for,
    register_commands,
    send_digest,
)
from commons.discord.digest import DigestRequest, DigestService
from commons.discord.notify import notify_bot_log
from commons.discord.project import ProjectService
from commons.errors import CommonsError, DigestError, GitError, LLMError
from commons.llm import LLMClient, UsageLog
from commons.logging import get_logger, setup_logging
from commons.news.run import prune_news_items, run_ingestion
from commons.scheduler import SKIP, Scheduler
from commons.settings import Settings, load_settings

log = get_logger("commons.discord.bot")


class CommonsBot(discord.Client):
    def __init__(
        self,
        *,
        settings: Settings,
        repo: CommunityRepo,
        llm: LLMClient,
        policy: PolicyConfig,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.repo = repo
        self.llm = llm
        self.policy = policy
        # Surface the budget warning to #bot-log from wherever the call happens.
        self.llm.on_warning = self._budget_notice
        self.tree = discord.app_commands.CommandTree(self)
        self.archive_service = ArchiveService(
            repo,
            llm,
            max_context_messages=policy.llm.max_context_messages,
            max_article_chars=policy.llm.max_article_chars,
        )
        self.project_service = ProjectService(repo)
        self.digest_service = DigestService(
            repo,
            llm,
            max_article_chars=policy.llm.max_article_chars,
            max_news=policy.news.max_items_per_digest,
        )
        self.scheduler = build_scheduler(settings, policy)
        if policy.digest.scheduled_weekly:
            self.scheduler.add(
                "weekly-digest",
                timedelta(days=7),
                functools.partial(self._scheduled_digest_job, "7d"),
            )
        if policy.digest.scheduled_daily:
            self.scheduler.add(
                "daily-digest",
                timedelta(days=1),
                functools.partial(self._scheduled_digest_job, "1d"),
            )
        self._scheduler_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        register_commands(self)
        guild_id = self.settings.effective_guild_id
        if guild_id is not None:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("synced application commands to guild %s", guild_id)
        else:
            await self.tree.sync()
            log.info("synced global application commands")

    def _budget_notice(self, message: str) -> None:
        """Called from a worker thread when the LLM budget is reached."""

        def schedule() -> None:
            asyncio.ensure_future(notify_bot_log(self, message))

        try:
            self.loop.call_soon_threadsafe(schedule)
        except Exception:  # noqa: BLE001 - notification is best-effort
            log.warning("could not schedule the budget notice")

    async def on_ready(self) -> None:
        log.info("bot online as %s", self.user)
        # Start scheduling only once the gateway has populated the guild cache, so
        # the first scheduled run does not skip and lose a week (R06).
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self.scheduler.serve())
            await notify_bot_log(self, "bot started")

    async def close(self) -> None:
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None
        await super().close()

    async def _scheduled_digest_job(self, period_label: str) -> object:
        """One scheduled digest path, sharing /digest rendering, posted to #digest."""

        guild_id = self.settings.effective_guild_id
        if guild_id is None:
            log.warning("scheduled digest skipped: no guild configured")
            return SKIP
        guild = self.get_guild(guild_id)
        if guild is None:
            log.warning("scheduled digest deferred: guild %s is not ready", guild_id)
            return SKIP

        period = DigestPeriod.from_label(period_label)
        activity = await collect_activity(guild, set(self.policy.digest.channels), period)
        request = DigestRequest(
            period=period_label,
            activity=activity,
            news=await asyncio.to_thread(news_candidates_for, self.settings, period),
            radar=await asyncio.to_thread(radar_candidates_for, self.settings, period),
            requested_by="scheduler",
        )
        try:
            outcome = await asyncio.to_thread(self.digest_service.generate, request)
        except (DigestError, LLMError, GitError) as exc:
            log.error("scheduled digest failed: %s", exc)
            raise  # let the scheduler retry promptly rather than losing the period

        channel = discord.utils.get(guild.text_channels, name="digest")
        if channel is None:
            log.warning(
                "scheduled digest wrote %s but #digest was not found", outcome.relative_path
            )
            return SKIP
        await send_digest(channel, outcome)
        return None


def build_scheduler(settings: Settings, policy: PolicyConfig) -> Scheduler:
    """In-process jobs. v0.1 does not run a separate scheduler service."""

    scheduler = Scheduler(state_path=settings.scheduler_state_path)
    scheduler.add(
        "news-ingestion",
        timedelta(minutes=policy.news.ingest_interval_minutes),
        functools.partial(run_ingestion, settings),
    )
    scheduler.add(
        "news-cleanup",
        timedelta(days=1),
        functools.partial(prune_news_items, settings, policy.news.retention_days),
    )
    return scheduler


def build_services(settings: Settings) -> tuple[CommunityRepo, LLMClient, PolicyConfig]:
    repo_path = settings.require_community_repo_path()
    policy = load_policy_config(repo_path / "config" / "policy.yaml")
    repo = CommunityRepo(repo_path, lock_path=settings.community_lock_path)

    api_key, base_url = settings.require_llm()
    llm = LLMClient(
        api_key=api_key,
        model=settings.llm_model,
        base_url=base_url,
        usage_log=UsageLog(settings.llm_usage_path),
        monthly_soft_limit_usd=policy.llm.monthly_soft_limit_usd,
        budget_action=policy.llm.on_limit,
        input_price_per_mtok=settings.llm_input_price_per_mtok,
        output_price_per_mtok=settings.llm_output_price_per_mtok,
    )
    return repo, llm, policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Technical Commons Discord bot.")
    parser.parse_args(argv)

    settings = load_settings()
    settings.ensure_runtime()
    setup_logging(settings.log_level, log_file=settings.logs_dir / "commons.log", force=True)

    try:
        repo, llm, policy = build_services(settings)
    except CommonsError as exc:
        log.error("configuration error: %s", exc)
        return 2

    bot = CommonsBot(settings=settings, repo=repo, llm=llm, policy=policy)
    bot.run(settings.require_discord_token())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
