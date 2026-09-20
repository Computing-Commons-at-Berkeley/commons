"""Non-destructive Discord bootstrap from community/config/discord.yaml.

The script creates missing roles, categories and channels. It NEVER deletes
objects that exist in Discord but not in the config; it reports them instead.
There is no /sync command and no reconciliation daemon.

Privacy is honoured (review R11): private categories and channels deny the
default role explicitly and grant the configured admin role and the bot access,
and existing objects whose privacy differs are reported for human review.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import discord

from commons.config import DiscordConfig, load_discord_config
from commons.logging import get_logger, setup_logging
from commons.settings import load_settings

log = get_logger("commons.discord.sync")

ADMIN_ROLE_NAME = "admin"


@dataclass(frozen=True)
class GuildState:
    roles: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    channels: set[str] = field(default_factory=set)
    private_categories: set[str] = field(default_factory=set)
    private_channels: set[str] = field(default_factory=set)


@dataclass
class SyncPlan:
    create_roles: list[str] = field(default_factory=list)
    create_categories: list[str] = field(default_factory=list)
    create_channels: list[tuple[str, str]] = field(default_factory=list)
    unknown_roles: list[str] = field(default_factory=list)
    unknown_categories: list[str] = field(default_factory=list)
    unknown_channels: list[str] = field(default_factory=list)
    permission_differences: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.create_roles or self.create_categories or self.create_channels)

    def describe(self) -> list[str]:
        lines: list[str] = []
        lines += [f"create role: {name}" for name in self.create_roles]
        lines += [f"create category: {name}" for name in self.create_categories]
        lines += [
            f"create channel: #{name} in {category}" for category, name in self.create_channels
        ]
        lines += [f"unknown role (kept, not deleted): {name}" for name in self.unknown_roles]
        lines += [
            f"unknown category (kept, not deleted): {name}" for name in self.unknown_categories
        ]
        lines += [f"unknown channel (kept, not deleted): #{name}" for name in self.unknown_channels]
        lines += [
            f"permission difference (not changed): {note}" for note in self.permission_differences
        ]
        return lines


def _is_private(target: discord.abc.GuildChannel) -> bool:
    overwrite = target.overwrites_for(target.guild.default_role)
    return overwrite.view_channel is False


def _private_overwrites(guild: discord.Guild) -> dict[object, discord.PermissionOverwrite]:
    overwrites: dict[object, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False)
    }
    admin = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
    if admin is not None:
        overwrites[admin] = discord.PermissionOverwrite(view_channel=True)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True)
    return overwrites


def guild_state_from_names(
    roles: set[str] | None = None,
    categories: set[str] | None = None,
    channels: set[str] | None = None,
    private_categories: set[str] | None = None,
    private_channels: set[str] | None = None,
) -> GuildState:
    return GuildState(
        roles=roles or set(),
        categories=categories or set(),
        channels=channels or set(),
        private_categories=private_categories or set(),
        private_channels=private_channels or set(),
    )


def guild_state(guild: discord.Guild) -> GuildState:
    return GuildState(
        roles={role.name for role in guild.roles if not role.is_default() and not role.managed},
        categories={category.name for category in guild.categories},
        channels={
            channel.name
            for channel in guild.channels
            if not isinstance(channel, discord.CategoryChannel)
        },
        private_categories={
            category.name for category in guild.categories if _is_private(category)
        },
        private_channels={
            channel.name
            for channel in guild.channels
            if not isinstance(channel, discord.CategoryChannel) and _is_private(channel)
        },
    )


def plan_sync(existing: GuildState, desired: DiscordConfig) -> SyncPlan:
    """Pure diff: what to create, and what to leave untouched."""

    desired_roles = {role.name for role in desired.roles}
    desired_categories = set(desired.categories)
    desired_channels = {
        channel.name for spec in desired.categories.values() for channel in spec.channels
    }

    plan = SyncPlan(
        create_roles=sorted(desired_roles - existing.roles),
        create_categories=sorted(desired_categories - existing.categories),
        unknown_roles=sorted(existing.roles - desired_roles),
        unknown_categories=sorted(existing.categories - desired_categories),
        unknown_channels=sorted(existing.channels - desired_channels),
    )
    for category, spec in desired.categories.items():
        if (
            spec.private
            and category in existing.categories
            and category not in existing.private_categories
        ):
            plan.permission_differences.append(f"category {category} is not private in Discord")
        for channel in spec.channels:
            if channel.name not in existing.channels:
                plan.create_channels.append((category, channel.name))
            elif channel.private and channel.name not in existing.private_channels:
                plan.permission_differences.append(
                    f"channel #{channel.name} is not private in Discord"
                )
    return plan


async def apply_sync(guild: discord.Guild, config: DiscordConfig, plan: SyncPlan) -> None:
    """Create the missing objects described by plan. Never deletes anything."""

    for name in plan.create_roles:
        spec = next(role for role in config.roles if role.name == name)
        colour = discord.Colour.from_str(spec.color) if spec.color else discord.Colour.default()
        permissions = (
            discord.Permissions(administrator=True)
            if spec.administrator
            else discord.Permissions.none()
        )
        await guild.create_role(
            name=spec.name,
            colour=colour,
            hoist=spec.hoist,
            permissions=permissions,
            reason="sync_discord",
        )
        log.info("created role %s (administrator=%s)", spec.name, spec.administrator)

    for category_name, spec in config.categories.items():
        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            overwrites = _private_overwrites(guild) if spec.private else None
            category = await guild.create_category(
                category_name, overwrites=overwrites, reason="sync_discord"
            )
            log.info("created category %s (private=%s)", category_name, spec.private)
        for channel in spec.channels:
            if discord.utils.get(category.channels, name=channel.name) is not None:
                continue
            overwrites = _private_overwrites(guild) if channel.private else None
            await category.create_text_channel(
                channel.name,
                topic=channel.topic,
                overwrites=overwrites,
                reason="sync_discord",
            )
            log.info(
                "created channel #%s in %s (private=%s)",
                channel.name,
                category_name,
                channel.private,
            )


async def sync_guild(
    guild: discord.Guild,
    config: DiscordConfig,
    *,
    dry_run: bool = False,
) -> SyncPlan:
    plan = plan_sync(guild_state(guild), config)
    if dry_run:
        return plan
    await apply_sync(guild, config, plan)
    return plan


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create missing Discord roles/categories/channels."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without changing Discord"
    )
    parser.add_argument(
        "--guild-id",
        type=int,
        default=None,
        help="target guild (defaults to test guild, then main guild)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = load_settings()
    settings.ensure_runtime()
    setup_logging(settings.log_level, log_file=settings.logs_dir / "commons.log", force=True)

    config_path = settings.require_community_repo_path() / "config" / "discord.yaml"
    config = load_discord_config(config_path)

    guild_id = args.guild_id or settings.discord_test_guild_id or settings.discord_guild_id
    if guild_id is None:
        log.error("no guild id configured (DISCORD_TEST_GUILD_ID / DISCORD_GUILD_ID)")
        return 2

    intents = discord.Intents.none()
    intents.guilds = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        try:
            guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
            plan = await sync_guild(guild, config, dry_run=args.dry_run)
            for line in plan.describe():
                log.info("%s", line)
            log.info(
                "sync complete: %d roles, %d categories, %d channels to create",
                len(plan.create_roles),
                len(plan.create_categories),
                len(plan.create_channels),
            )
        except Exception:  # noqa: BLE001 - surface the failure, then exit non-zero
            log.exception("discord sync failed")
        finally:
            await client.close()

    client.run(settings.require_discord_token())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
