"""Bot entry point: wire configuration, services, and Discord together."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import timedelta

import discord

from commons.community_repo.git import CommunityRepo
from commons.config import PolicyConfig, load_policy_config
from commons.discord.archive import ArchiveService
from commons.discord.commands import register_commands
from commons.discord.digest import DigestService
from commons.discord.project import ProjectService
from commons.errors import CommonsError
from commons.llm import LLMClient, UsageLog
from commons.logging import get_logger, setup_logging
from commons.news.run import run_ingestion
from commons.scheduler import Scheduler
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
        )
        self.scheduler = build_scheduler(settings, policy)
        self._scheduler_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        register_commands(self)
        guild_id = self.settings.discord_test_guild_id or self.settings.discord_guild_id
        if guild_id is not None:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("synced application commands to guild %s", guild_id)
        else:
            await self.tree.sync()
            log.info("synced global application commands")
        self._scheduler_task = asyncio.create_task(self.scheduler.serve())

    async def close(self) -> None:
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None
        await super().close()

    async def on_ready(self) -> None:
        log.info("bot online as %s", self.user)


def build_scheduler(settings: Settings, policy: PolicyConfig) -> Scheduler:
    """In-process jobs. v0.1 does not run a separate scheduler service."""

    scheduler = Scheduler()
    scheduler.add(
        "news-ingestion",
        timedelta(minutes=policy.news.ingest_interval_minutes),
        lambda: run_ingestion(settings),
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
