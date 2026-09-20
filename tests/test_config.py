from __future__ import annotations

from pathlib import Path

import pytest

from commons.config import (
    load_community_config,
    load_discord_config,
    load_policy_config,
    load_sources_config,
    load_watchlist_config,
)
from commons.errors import ConfigError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_example_configs_load() -> None:
    discord = load_discord_config(EXAMPLES / "discord.example.yaml")
    assert "SIGNAL" in discord.categories
    assert discord.categories["SIGNAL"].channels[0].name == "ml-research"

    sources = load_sources_config(EXAMPLES / "sources.example.yaml")
    assert {source.category for source in sources.sources} == {"ml", "infra"}

    watchlists = load_watchlist_config(EXAMPLES / "watchlists.example.yaml")
    assert watchlists.repositories[0].repo == "example/project"
    assert watchlists.repositories[0].reason

    policy = load_policy_config(EXAMPLES / "policy.example.yaml")
    assert policy.privacy.persist_raw_discord_messages is False
    assert policy.llm.monthly_soft_limit_usd == pytest.approx(20.0)


def test_channel_entries_accept_string_or_mapping(tmp_path: Path) -> None:
    path = tmp_path / "discord.yaml"
    path.write_text(
        "categories:\n  START:\n    channels:\n      - start-here\n"
        "      - name: introductions\n        topic: hi\n",
        encoding="utf-8",
    )
    config = load_discord_config(path)
    assert config.categories["START"].channels[0].name == "start-here"
    assert config.categories["START"].channels[1].topic == "hi"


def test_duplicate_channel_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "discord.yaml"
    path.write_text(
        "categories:\n  A:\n    channels:\n      - general\n  B:\n    channels:\n      - general\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_discord_config(path)


def test_watchlist_requires_reason(tmp_path: Path) -> None:
    path = tmp_path / "watchlists.yaml"
    path.write_text(
        "repositories:\n  - repo: owner/name\n    reason: ''\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_watchlist_config(path)


def test_sources_reject_unknown_category(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n  - id: bad\n    type: rss\n    url: https://example.com/f.xml\n"
        "    category: sports\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_sources_config(path)


def test_duplicate_source_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - id: dup\n    type: rss\n    url: https://example.com/a.xml\n    category: ml\n"
        "  - id: dup\n    type: rss\n    url: https://example.com/b.xml\n    category: ml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_sources_config(path)


def test_missing_file_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_policy_config(tmp_path / "policy.yaml")


def test_load_community_config_bundle(tmp_path: Path) -> None:
    for name in ("discord", "sources", "watchlists", "policy"):
        (tmp_path / f"{name}.yaml").write_text(
            (EXAMPLES / f"{name}.example.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
    bundle = load_community_config(tmp_path)
    assert bundle.discord.roles[0].name == "admin"
    assert bundle.policy.archive.allow_members is True


def test_raw_discord_persistence_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("privacy:\n  persist_raw_discord_messages: true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_policy_config(path)


def test_llm_on_limit_accepts_warn_and_block(tmp_path: Path) -> None:
    for value in ("warn", "block"):
        path = tmp_path / f"policy-{value}.yaml"
        path.write_text(f"llm:\n  on_limit: {value}\n", encoding="utf-8")
        assert load_policy_config(path).llm.on_limit == value


def test_llm_on_limit_rejects_unknown_value(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("llm:\n  on_limit: explode\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_policy_config(path)
