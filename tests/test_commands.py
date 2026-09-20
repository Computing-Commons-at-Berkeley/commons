from __future__ import annotations

import pytest

from commons.discord.commands import parse_message_link


def test_parse_message_link() -> None:
    guild, channel, message = parse_message_link("https://discord.com/channels/111/222/333")
    assert (guild, channel, message) == (111, 222, 333)


def test_parse_message_link_allows_trailing_slash() -> None:
    assert parse_message_link("https://discord.com/channels/1/2/3/") == (1, 2, 3)


def test_parse_message_link_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_message_link("not-a-link")
