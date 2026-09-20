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


def private_config() -> DiscordConfig:
    return DiscordConfig.model_validate(
        {
            "roles": ["admin", "member"],
            "categories": {
                "START": {"channels": ["start-here"]},
                "PRIVATE": {"private": True, "channels": [{"name": "ops", "private": True}]},
            },
        }
    )


def test_plan_reports_privacy_differences() -> None:
    state = GuildState(
        roles={"admin", "member"},
        categories={"START", "PRIVATE"},
        channels={"start-here", "ops"},
    )
    plan = plan_sync(state, private_config())

    assert any("PRIVATE" in note for note in plan.permission_differences)
    assert any("#ops" in note for note in plan.permission_differences)
    assert any("not changed" in line for line in plan.describe())


def test_plan_accepts_existing_private_objects() -> None:
    state = GuildState(
        roles={"admin", "member"},
        categories={"START", "PRIVATE"},
        channels={"start-here", "ops"},
        private_categories={"PRIVATE"},
        private_channels={"ops"},
    )
    plan = plan_sync(state, private_config())
    assert plan.permission_differences == []


def test_private_config_is_loadable() -> None:
    config = private_config()
    assert config.categories["PRIVATE"].private is True
    assert config.categories["PRIVATE"].channels[0].private is True
