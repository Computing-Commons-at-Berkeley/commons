"""Shared exception types.

Keeping these in one place lets callers distinguish recoverable operational
failures (e.g. a transient Git push failure) from programming errors, without
introducing an error framework.
"""

from __future__ import annotations


class CommonsError(Exception):
    """Base class for expected, operational failures."""


class ConfigError(CommonsError):
    """A community configuration file is missing, malformed, or invalid."""


class SettingsError(CommonsError):
    """Required environment configuration is missing or invalid."""


class GitError(CommonsError):
    """A Git operation against the community repository failed."""


class GitPushError(GitError):
    """The commit succeeded locally but the push did not.

    Callers must not report success in this case.
    """


class ArtifactError(CommonsError):
    """A durable artifact could not be built or parsed."""


class LLMError(CommonsError):
    """The LLM call failed or returned an unusable response."""


class ArchiveError(CommonsError):
    """The /archive workflow could not be completed."""


class ProjectError(CommonsError):
    """The /project workflow could not be completed."""
