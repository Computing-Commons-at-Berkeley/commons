"""Validated contracts for the community YAML configuration files.

These models are the single place where config shape is defined. They are
deliberately strict (extra fields are rejected) so typos fail loudly instead of
silently doing nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from commons.errors import ConfigError
from commons.text import normalize_channel_name, normalize_role_name

SourceType = Literal["rss", "github_release"]
NewsCategory = Literal["ml", "infra", "economics", "berkeley"]

_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# discord.yaml
# --------------------------------------------------------------------------
class ChannelSpec(StrictModel):
    name: str
    topic: str | None = None
    private: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @field_validator("name")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_channel_name(value)


class RoleSpec(StrictModel):
    name: str
    color: str | None = None
    hoist: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @field_validator("name")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_role_name(value)

    @field_validator("color")
    @classmethod
    def _check_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if len(text) != 7 or not text.startswith("#"):
            raise ValueError(f"color must look like #rrggbb, got {value!r}")
        int(text[1:], 16)
        return text.lower()


class CategorySpec(StrictModel):
    private: bool = False
    channels: list[ChannelSpec] = Field(default_factory=list)


class DiscordConfig(StrictModel):
    roles: list[RoleSpec] = Field(default_factory=list)
    categories: dict[str, CategorySpec] = Field(default_factory=dict)

    @field_validator("categories")
    @classmethod
    def _normalize_category_names(cls, value: dict[str, CategorySpec]) -> dict[str, CategorySpec]:
        return {name.strip().upper(): spec for name, spec in value.items()}

    @model_validator(mode="after")
    def _channels_are_unique(self) -> DiscordConfig:
        seen: dict[str, str] = {}
        for category, spec in self.categories.items():
            for channel in spec.channels:
                if channel.name in seen:
                    raise ValueError(
                        f"channel {channel.name!r} appears in both "
                        f"{seen[channel.name]!r} and {category!r}"
                    )
                seen[channel.name] = category
        return self


# --------------------------------------------------------------------------
# sources.yaml
# --------------------------------------------------------------------------
class SourceSpec(StrictModel):
    id: str
    type: SourceType
    url: str
    category: NewsCategory
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        value = value.strip()
        if not _ID_RE.fullmatch(value):
            raise ValueError(f"source id must be lowercase slug-like, got {value!r}")
        return value

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"source url must be http(s), got {value!r}")
        return value


class SourcesConfig(StrictModel):
    sources: list[SourceSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> SourcesConfig:
        seen: set[str] = set()
        for source in self.sources:
            if source.id in seen:
                raise ValueError(f"duplicate source id {source.id!r}")
            seen.add(source.id)
        return self


# --------------------------------------------------------------------------
# watchlists.yaml
# --------------------------------------------------------------------------
class WatchSpec(StrictModel):
    releases: bool = True
    issues: bool = True


class WatchEntry(StrictModel):
    repo: str
    category: str = "berkeley"
    reason: str
    watch: WatchSpec = Field(default_factory=WatchSpec)
    issue_labels: list[str] = Field(default_factory=list)

    @field_validator("repo")
    @classmethod
    def _check_repo(cls, value: str) -> str:
        value = value.strip()
        if not _REPO_RE.fullmatch(value):
            raise ValueError(f"repo must look like owner/name, got {value!r}")
        return value

    @field_validator("reason")
    @classmethod
    def _require_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("every watched repository must have a reason")
        return value


class WatchlistConfig(StrictModel):
    repositories: list[WatchEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _repos_are_unique(self) -> WatchlistConfig:
        seen: set[str] = set()
        for entry in self.repositories:
            key = entry.repo.lower()
            if key in seen:
                raise ValueError(f"duplicate watched repository {entry.repo!r}")
            seen.add(key)
        return self


# --------------------------------------------------------------------------
# policy.yaml
# --------------------------------------------------------------------------
class DigestPolicy(StrictModel):
    channels: list[str] = Field(default_factory=list)
    scheduled_weekly: bool = True
    scheduled_daily: bool = False

    @field_validator("channels")
    @classmethod
    def _normalize_channels(cls, value: list[str]) -> list[str]:
        return [normalize_channel_name(item) for item in value]


class ArchivePolicy(StrictModel):
    allow_members: bool = True
    require_explicit_selection: bool = True


class PrivacyPolicy(StrictModel):
    persist_raw_discord_messages: bool = False


class LLMPolicy(StrictModel):
    monthly_soft_limit_usd: float = 0.0
    max_context_messages: int = 100
    max_article_chars: int = 12000


class NewsPolicy(StrictModel):
    retention_days: int = 90
    max_items_per_digest: int = 40
    ingest_interval_minutes: int = 60


class PolicyConfig(StrictModel):
    digest: DigestPolicy = Field(default_factory=DigestPolicy)
    archive: ArchivePolicy = Field(default_factory=ArchivePolicy)
    privacy: PrivacyPolicy = Field(default_factory=PrivacyPolicy)
    llm: LLMPolicy = Field(default_factory=LLMPolicy)
    news: NewsPolicy = Field(default_factory=NewsPolicy)


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping, converting every failure into ConfigError."""

    path = Path(path)
    if not path.exists():
        raise ConfigError(f"configuration file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def _load_model(path: Path, model: type[StrictModel]) -> Any:
    try:
        return model.model_validate(read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {path}:\n{exc}") from exc


def load_discord_config(path: Path) -> DiscordConfig:
    return _load_model(Path(path), DiscordConfig)


def load_sources_config(path: Path) -> SourcesConfig:
    return _load_model(Path(path), SourcesConfig)


def load_watchlist_config(path: Path) -> WatchlistConfig:
    return _load_model(Path(path), WatchlistConfig)


def load_policy_config(path: Path) -> PolicyConfig:
    return _load_model(Path(path), PolicyConfig)


class CommunityConfig(StrictModel):
    discord: DiscordConfig
    sources: SourcesConfig
    watchlists: WatchlistConfig
    policy: PolicyConfig


def load_community_config(config_dir: Path) -> CommunityConfig:
    config_dir = Path(config_dir)
    return CommunityConfig(
        discord=load_discord_config(config_dir / "discord.yaml"),
        sources=load_sources_config(config_dir / "sources.yaml"),
        watchlists=load_watchlist_config(config_dir / "watchlists.yaml"),
        policy=load_policy_config(config_dir / "policy.yaml"),
    )
