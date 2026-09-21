"""Environment configuration.

Secrets and deployment-specific values come from the environment (or a local
.env). Nothing here is ever committed. See .env.example for the contract.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from commons.errors import SettingsError

LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"


class Settings(BaseSettings):
    """Process configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # A blank optional value (for example an unused guild ID) means "unset",
        # not "invalid integer" (R13).
        env_ignore_empty=True,
    )

    # --- Discord ---
    discord_token: SecretStr | None = None
    discord_guild_id: int | None = None
    discord_test_guild_id: int | None = None

    # --- GitHub ---
    github_token: SecretStr | None = None
    github_org: str | None = None

    # --- Community repo ---
    community_repo_path: Path | None = None

    # --- LLM ---
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    # Provider thinking toggle (DeepSeek: enabled|disabled). Blank = provider default.
    llm_thinking: str | None = None
    # Optional explicit pricing for providers/models not in the built-in table.
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None

    # --- Runtime ---
    runtime_dir: Path = Path("runtime")
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> Settings:
        self.runtime_dir = Path(self.runtime_dir).expanduser().resolve()

        level = (self.log_level or "").strip().upper()
        if level not in LOG_LEVELS:
            raise ValueError(
                f"LOG_LEVEL must be one of {sorted(LOG_LEVELS)}, got {self.log_level!r}"
            )
        self.log_level = level

        if self.community_repo_path is not None:
            repo = Path(self.community_repo_path).expanduser().resolve()
            self.community_repo_path = repo
            if self.runtime_dir == repo or repo in self.runtime_dir.parents:
                raise ValueError(
                    "RUNTIME_DIR must not live inside COMMUNITY_REPO_PATH; "
                    "runtime state is rebuildable and must never be committed"
                )
        return self

    # --- derived runtime paths (none of these are committed) ---
    @property
    def logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.runtime_dir / "cache"

    @property
    def news_db_path(self) -> Path:
        return self.runtime_dir / "news.db"

    @property
    def community_lock_path(self) -> Path:
        return self.runtime_dir / "community_repo.lock"

    @property
    def llm_usage_path(self) -> Path:
        return self.runtime_dir / "llm_usage.jsonl"

    @property
    def scheduler_state_path(self) -> Path:
        return self.runtime_dir / "scheduler_state.json"

    @property
    def effective_llm_base_url(self) -> str:
        return (self.llm_base_url or DEFAULT_LLM_BASE_URL).rstrip("/")

    @property
    def effective_guild_id(self) -> int | None:
        """The one guild this process operates on (R08).

        The test guild intentionally wins when both are configured so a developer
        cannot accidentally read production activity.
        """

        return self.discord_test_guild_id or self.discord_guild_id

    # --- requirement helpers: fail loudly and early ---
    def ensure_runtime(self) -> Path:
        for directory in (self.runtime_dir, self.logs_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self.runtime_dir

    def require_community_repo_path(self) -> Path:
        if self.community_repo_path is None:
            raise SettingsError("COMMUNITY_REPO_PATH is not configured")
        return self.community_repo_path

    def require_discord_token(self) -> str:
        if self.discord_token is None:
            raise SettingsError("DISCORD_TOKEN is not configured")
        return self.discord_token.get_secret_value()

    def require_llm(self) -> tuple[str, str]:
        if self.llm_api_key is None:
            raise SettingsError("LLM_API_KEY is not configured")
        return self.llm_api_key.get_secret_value(), self.effective_llm_base_url


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load settings once per process."""

    return Settings()
