from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands

from commons.config import PolicyConfig
from commons.discord.bot import build_scheduler
from commons.discord.commands import register_commands
from commons.settings import Settings


def bare_client() -> discord.Client:
    client = discord.Client(intents=discord.Intents.none())
    client.tree = app_commands.CommandTree(client)
    return client


def test_slash_commands_and_context_menu_register() -> None:
    client = bare_client()
    register_commands(client)

    names = {command.name for command in client.tree.get_commands()}
    assert {"archive", "project", "digest"} <= names

    menus = [
        command
        for command in client.tree.get_commands()
        if isinstance(command, app_commands.ContextMenu)
    ]
    assert [menu.name for menu in menus] == ["Archive"]


def test_digest_period_choices_are_declared() -> None:
    client = bare_client()
    register_commands(client)

    digest = client.tree.get_command("digest")
    assert digest is not None
    period = next(param for param in digest.parameters if param.name == "period")
    assert [choice.value for choice in period.choices] == ["1d", "7d", "30d"]


def test_scheduler_registers_ingestion_job(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        community_repo_path=tmp_path / "community",
        runtime_dir=tmp_path / "runtime",
    )
    scheduler = build_scheduler(settings, PolicyConfig())
    assert {job.name for job in scheduler.jobs} == {"news-ingestion", "news-cleanup"}
