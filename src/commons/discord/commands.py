"""Discord command registration for v0.1.

/archive and /project are implemented here. /digest is added next, in plan
order. Commands stay thin: they translate Discord objects into DTOs and hand off
to a workflow service.
"""

from __future__ import annotations

from datetime import UTC

import discord
from discord import app_commands

from commons.community_repo.schemas import DiscordSource
from commons.discord.archive import ArchiveOutcome, ArchiveRequest, TranscriptMessage
from commons.discord.project import ProjectCreateRequest, ProjectOutcome
from commons.errors import ArchiveError, GitError, LLMError, ProjectError
from commons.logging import get_logger

log = get_logger("commons.discord.commands")


def parse_message_link(link: str) -> tuple[int, int, int]:
    """Return (guild_id, channel_id, message_id) from a Discord message URL."""

    parts = link.strip().rstrip("/").split("/")
    if len(parts) < 3:
        raise ValueError(f"not a Discord message link: {link}")
    try:
        message_id = int(parts[-1])
        channel_id = int(parts[-2])
        guild_id = int(parts[-3])
    except ValueError as exc:
        raise ValueError(f"not a Discord message link: {link}") from exc
    return guild_id, channel_id, message_id


def message_to_transcript(message: discord.Message) -> TranscriptMessage:
    created_at = None
    if message.created_at is not None:
        created_at = message.created_at.astimezone(UTC).isoformat(timespec="minutes")
    return TranscriptMessage(
        author=getattr(message.author, "display_name", str(message.author)),
        content=message.content or "",
        created_at=created_at,
    )


def _thread_for(message: discord.Message) -> discord.Thread | None:
    channel = message.channel
    if isinstance(channel, discord.Thread):
        return channel
    thread = getattr(message, "thread", None)
    return thread if isinstance(thread, discord.Thread) else None


def build_source(message: discord.Message) -> DiscordSource:
    channel = message.channel
    thread = _thread_for(message)
    parent_id = getattr(channel, "parent_id", None)
    return DiscordSource(
        guild_id=message.guild.id if message.guild else None,
        discord_channel_id=parent_id or channel.id,
        discord_channel_name=getattr(channel, "name", None),
        discord_message_id=message.id,
        discord_thread_id=thread.id if thread else None,
        discord_message_url=message.jump_url,
        discord_author=getattr(message.author, "display_name", str(message.author)),
    )


async def gather_messages(message: discord.Message) -> tuple[list[TranscriptMessage], str]:
    """Read the surrounding thread when there is one, else just the message."""

    thread = _thread_for(message)
    messages: list[discord.Message] = [message]
    title_hint = ""
    if thread is not None:
        title_hint = thread.name
        try:
            messages = [item async for item in thread.history(limit=200, oldest_first=True)]
        except discord.HTTPException:
            log.warning("could not read thread history; archiving the selected message only")
            messages = [message]
    return [message_to_transcript(item) for item in messages], title_hint


async def _run_archive(
    interaction: discord.Interaction,
    message: discord.Message,
    *,
    title_hint: str | None = None,
) -> None:
    await interaction.response.defer(thinking=True)
    service = getattr(interaction.client, "archive_service", None)
    if service is None:
        await interaction.followup.send("Archive is not configured on this bot.")
        return

    try:
        messages, thread_title = await gather_messages(message)
        request = ArchiveRequest(
            source=build_source(message),
            messages=messages,
            requested_by=interaction.user.display_name,
            title_hint=title_hint or thread_title,
            channel_name=getattr(message.channel, "name", "") or "",
        )
        outcome = await interaction.client.loop.run_in_executor(None, service.archive, request)
    except (ArchiveError, LLMError, GitError) as exc:
        log.error("archive failed: %s", exc)
        await interaction.followup.send(f"Archive failed: {exc}")
        return
    except Exception as exc:  # noqa: BLE001 - never claim success on an unknown failure
        log.exception("archive failed unexpectedly")
        await interaction.followup.send(f"Archive failed unexpectedly: {exc}")
        return

    await interaction.followup.send(embed=_outcome_embed(outcome))


def _outcome_embed(outcome: ArchiveOutcome) -> discord.Embed:
    if outcome.created:
        embed = discord.Embed(
            title="Archived",
            description=outcome.title,
            colour=discord.Colour.green(),
        )
        embed.add_field(name="Artifact", value=outcome.relative_path, inline=False)
        if outcome.commit_sha:
            embed.add_field(name="Commit", value=outcome.commit_sha[:12], inline=True)
    else:
        embed = discord.Embed(
            title="Already archived",
            description=outcome.title,
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="Artifact", value=outcome.relative_path, inline=False)
        embed.add_field(name="Note", value=outcome.detail, inline=False)
    return embed


def _split_members(value: str | None) -> list[str]:
    if not value:
        return []
    cleaned = value.replace(",", " ")
    return [item.strip() for item in cleaned.split() if item.strip()]


async def _run_project(
    interaction: discord.Interaction,
    *,
    name: str,
    goal: str | None,
    members: str | None,
) -> None:
    await interaction.response.defer(thinking=True)
    service = getattr(interaction.client, "project_service", None)
    if service is None:
        await interaction.followup.send("Projects are not configured on this bot.")
        return

    thread_id = interaction.channel.id if isinstance(interaction.channel, discord.Thread) else None
    member_list = _split_members(members) or [interaction.user.display_name]
    request = ProjectCreateRequest(
        name=name,
        goal=goal or "",
        members=member_list,
        discord_thread_id=thread_id,
    )
    try:
        outcome = await interaction.client.loop.run_in_executor(None, service.create, request)
    except (ProjectError, GitError) as exc:
        log.error("project creation failed: %s", exc)
        await interaction.followup.send(f"Project creation failed: {exc}")
        return
    except Exception as exc:  # noqa: BLE001 - never claim success on an unknown failure
        log.exception("project creation failed unexpectedly")
        await interaction.followup.send(f"Project creation failed unexpectedly: {exc}")
        return

    await interaction.followup.send(embed=_project_embed(outcome))


def _project_embed(outcome: ProjectOutcome) -> discord.Embed:
    embed = discord.Embed(
        title="Project created" if outcome.created else "Project already exists",
        description=outcome.title,
        colour=discord.Colour.green() if outcome.created else discord.Colour.blurple(),
    )
    embed.add_field(name="Status", value=outcome.status, inline=True)
    embed.add_field(name="Artifact", value=outcome.relative_path, inline=False)
    if outcome.commit_sha:
        embed.add_field(name="Commit", value=outcome.commit_sha[:12], inline=True)
    if outcome.detail:
        embed.add_field(name="Note", value=outcome.detail, inline=False)
    return embed


def register_commands(bot: discord.Client) -> None:
    context_menu = app_commands.ContextMenu(name="Archive", callback=archive_context_callback)
    bot.tree.add_command(context_menu)

    @bot.tree.command(
        name="archive", description="Archive a selected discussion into durable community memory"
    )
    @app_commands.describe(
        message_link="Link to the Discord message or thread to archive (defaults to this thread)",
        title="Optional title hint for the note",
    )
    async def archive_command(
        interaction: discord.Interaction,
        message_link: str | None = None,
        title: str | None = None,
    ) -> None:
        if message_link:
            try:
                _guild_id, channel_id, message_id = parse_message_link(message_link)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            channel = interaction.client.get_channel(channel_id)
            if channel is None:
                await interaction.response.send_message(
                    "I cannot see that channel.", ephemeral=True
                )
                return
            try:
                message = await channel.fetch_message(message_id)
            except discord.HTTPException:
                await interaction.response.send_message(
                    "I could not fetch that message.", ephemeral=True
                )
                return
        elif isinstance(interaction.channel, discord.Thread):
            async for candidate in interaction.channel.history(limit=1, oldest_first=True):
                message = candidate
                break
            else:
                await interaction.response.send_message(
                    "This thread has no readable messages.", ephemeral=True
                )
                return
        else:
            await interaction.response.send_message(
                "Provide a message link, or run /archive inside a thread.", ephemeral=True
            )
            return
        await _run_archive(interaction, message, title_hint=title)

    @bot.tree.command(
        name="project", description="Create a lightweight project record from this discussion"
    )
    @app_commands.describe(
        name="Project name",
        goal="Optional one-line goal",
        members="Optional members, comma or space separated",
    )
    async def project_command(
        interaction: discord.Interaction,
        name: str,
        goal: str | None = None,
        members: str | None = None,
    ) -> None:
        await _run_project(interaction, name=name, goal=goal, members=members)


async def archive_context_callback(
    interaction: discord.Interaction, message: discord.Message
) -> None:
    await _run_archive(interaction, message)
