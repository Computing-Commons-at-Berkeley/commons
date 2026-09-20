from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from commons.errors import SettingsError
from commons.settings import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.log_level == "INFO"
    assert settings.discord_token is None
    assert settings.runtime_dir.is_absolute()


def test_log_level_is_normalized_and_validated() -> None:
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="chatty")


def test_runtime_dir_must_not_live_inside_community_repo(tmp_path: Path) -> None:
    repo = tmp_path / "community"
    repo.mkdir()
    with pytest.raises(ValidationError):
        Settings(_env_file=None, community_repo_path=repo, runtime_dir=repo / "runtime")


def test_require_helpers_fail_loudly(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, runtime_dir=tmp_path / "runtime")
    with pytest.raises(SettingsError):
        settings.require_community_repo_path()
    with pytest.raises(SettingsError):
        settings.require_discord_token()
    with pytest.raises(SettingsError):
        settings.require_llm()


def test_derived_paths(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, runtime_dir=tmp_path / "runtime")
    assert settings.news_db_path == (tmp_path / "runtime" / "news.db")
    assert settings.logs_dir == (tmp_path / "runtime" / "logs")
    assert settings.community_lock_path == (tmp_path / "runtime" / "community_repo.lock")


def test_ensure_runtime_creates_directories(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, runtime_dir=tmp_path / "runtime")
    settings.ensure_runtime()
    assert settings.logs_dir.is_dir()
    assert settings.cache_dir.is_dir()


def test_blank_optional_env_values_mean_unset(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DISCORD_TOKEN=\nDISCORD_GUILD_ID=\nDISCORD_TEST_GUILD_ID=123\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert settings.discord_guild_id is None
    assert settings.discord_test_guild_id == 123


def test_effective_guild_prefers_test_guild() -> None:
    settings = Settings(_env_file=None, discord_guild_id=111, discord_test_guild_id=222)
    assert settings.effective_guild_id == 222
    assert Settings(_env_file=None, discord_guild_id=111).effective_guild_id == 111
    assert Settings(_env_file=None).effective_guild_id is None
