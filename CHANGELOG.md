# Changelog

All notable changes to `commons` are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Python project skeleton: `pyproject.toml`, `src/commons`, `tests/`, Ruff and
  pytest configuration, `.gitignore`, `.env.example`.
- Environment settings with validation (`commons/settings.py`).
- Structured application logging with a single configuration point
  (`commons/logging.py`).
- Validated contracts for the community YAML configuration files
  (`commons/config.py`).
- Durable artifact schemas, Markdown rendering/parsing, slug planning and
  idempotency lookup (`commons/community_repo/`).
- Safe community-repository Git writer: process lock, `git pull --rebase`,
  scoped `git add`, explicit bot identity, commit, push, and a hard failure when
  the push fails (`commons/community_repo/git.py`).
- Thin LLM module with usage/cost logging and a monthly soft-limit check
  (`commons/llm.py`, `commons/prompts.py`).
- `/archive` workflow and the Archive message context action
  (`commons/discord/archive.py`, `commons/discord/commands.py`).
- Discord bot entry point (`commons/discord/bot.py`).
- Non-destructive Discord bootstrap that creates missing roles/categories/
  channels and never deletes unknown objects (`commons/discord/sync.py`,
  `scripts/sync_discord.py`).
- `AGENTS.md` with repository and Git practices.
- `/project` workflow and command: idempotent project records at
  `data/projects/<slug>.md` with status changes
  (`commons/discord/project.py`, `commons/community_repo/projects.py`).
- Shared Markdown/frontmatter helpers for durable artifacts
  (`commons/community_repo/markdown.py`).
- `/digest` workflow and command: one code path for manual and scheduled digests,
  with deterministic candidate selection before synthesis and durable digests at
  `data/digests/<date>-<period>.md` (`commons/digest.py`,
  `commons/discord/digest.py`, `commons/community_repo/digests.py`).

### Changed

- Durable artifact writes force LF line endings and `.gitattributes` normalizes
  text files to LF, so artifacts are byte-stable across platforms (see
  `community/docs/DECISIONS.md` D006).
