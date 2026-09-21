"""Post operational events to #bot-log (plan sections 39 and 45).

Only meaningful events belong here: startup, durable-write failures, repeated
source failures, and budget warnings. Never raw conversation.
"""

from __future__ import annotations

import discord

from commons.logging import get_logger

log = get_logger(__name__)

BOT_LOG_CHANNEL = "bot-log"
MAX_MESSAGE_CHARS = 1900


async def notify_bot_log(client: discord.Client, message: str) -> bool:
    """Best-effort operational notification. It never raises to the caller."""

    settings = getattr(client, "settings", None)
    guild_id = settings.effective_guild_id if settings is not None else None
    if guild_id is None:
        return False
    guild = client.get_guild(guild_id)
    if guild is None:
        return False
    channel = discord.utils.get(guild.text_channels, name=BOT_LOG_CHANNEL)
    if channel is None:
        log.warning("no #%s channel to notify: %s", BOT_LOG_CHANNEL, message)
        return False
    try:
        await channel.send(
            message[:MAX_MESSAGE_CHARS], allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException:
        log.warning("could not post an operational notice to #%s", BOT_LOG_CHANNEL)
        return False
    return True
