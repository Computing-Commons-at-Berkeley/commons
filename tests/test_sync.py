from __future__ import annotations

from commons.config import DiscordConfig
from commons.discord.sync import GuildState, plan_sync


def make_config() -> DiscordConfig:
    return DiscordConfig.model_validate(
        {
            "roles": ["admin", "member"],
            "categories": {
                "START": {"channels": ["start-here"]},
                "SIGNAL": {"channels": ["ml-research", "infra"]},
            },
        }
    )


def test_plan_sync_creates_missing_only() -> None:
    state = GuildState(
        roles={"admin"},
        categories={"START"},
        channels={"start-here", "old-channel"},
    )
    plan = plan_sync(state, make_config())

    assert plan.create_roles == ["member"]
    assert plan.create_categories == ["SIGNAL"]
    assert ("SIGNAL", "ml-research") in plan.create_channels
    assert ("SIGNAL", "infra") in plan.create_channels
    assert plan.unknown_channels == ["old-channel"]
    assert plan.unknown_roles == []


def test_plan_sync_is_empty_when_everything_exists() -> None:
    state = GuildState(
        roles={"admin", "member"},
        categories={"START", "SIGNAL"},
        channels={"start-here", "ml-research", "infra"},
    )
    plan = plan_sync(state, make_config())
    assert plan.is_empty
    assert plan.describe() == []


def test_plan_sync_never_plans_deletions() -> None:
    state = GuildState(roles=set(), categories=set(), channels={"legacy"})
    plan = plan_sync(state, make_config())
    assert "legacy" in plan.unknown_channels
    assert not hasattr(plan, "delete_channels")
