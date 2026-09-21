# commons

Public, reusable infrastructure for the **Computing Commons at Berkeley**: a
Discord bot plus the workflows that turn conversations and external sources into
durable community memory.

This repository is the *mechanism*. It contains no community state, no member
data and no secrets. The private instance lives in the separate community
repository; cloning this one lets you run your own community with it.

## What it does

- **/archive** - turn a selected Discord message or thread into a durable
  Markdown note with provenance back to Discord, committed to the private
  community repository. A message context action (Apps -> Archive) does the same.
- **/project** - create a lightweight project record from a discussion.
- **/digest** - synthesize recent activity from configured Discord channels,
  stored news items, project records and the curated OSS radar.
- **News pipeline** - RSS and GitHub-release ingestion into SQLite with
  deterministic deduplication and 24h / 7d / 30d views over one corpus.
- **OSS radar** - a hand-curated watchlist polled for releases and selected
  issues. No commit-by-commit feed.
- **Scheduler** - one in-process scheduler for ingestion, retention cleanup and
  the weekly digest.
- **Optional read-only UI** - Streamlit pages over the same Git and SQLite state.

## How it fits together

~~~
Discord conversation --> bot --> durable Markdown --> private community repo (Git)
                                    |
external feeds --> ingestion --> SQLite (runtime) --> digest --> Discord / UI
~~~

Rules of the design: Git stores durable community memory, SQLite stores
operational news state, Discord stores conversation. Automation failure degrades
convenience; it never disables the community.

## Quick start

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env      # then fill it in
~~~

Fill in .env (see Configuration below), then:

~~~powershell
.\.venv\Scripts\python scripts\sync_discord.py --dry-run   # inspect the plan first
.\.venv\Scripts\python scripts\sync_discord.py             # create missing roles/channels
.\.venv\Scripts\python -m commons.discord.bot              # run the bot
~~~

Verify:

~~~powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
~~~

## Configuration

Secrets and paths come from the environment only. .env.example documents every
variable; the ones that matter most:

| Variable | Purpose |
|---|---|
| DISCORD_TOKEN | Bot token |
| DISCORD_GUILD_ID | The one guild this process operates on (production) |
| DISCORD_TEST_GUILD_ID | Test guild; takes precedence when both are set |
| COMMUNITY_REPO_PATH | Local checkout of the private community repository |
| RUNTIME_DIR | SQLite, logs, locks; must be outside every Git repository |
| LLM_API_KEY / LLM_MODEL / LLM_BASE_URL | One OpenAI-compatible provider |
| LLM_THINKING | Optional provider thinking toggle (DeepSeek: enabled/disabled) |
| LLM_INPUT_PRICE_PER_MTOK / LLM_OUTPUT_PRICE_PER_MTOK | Explicit pricing for unlisted models |
| GITHUB_TOKEN | Read-only token for the OSS radar (higher rate limits) |

Community-level configuration lives in the private repository under config/:
discord.yaml (desired channels and roles), sources.yaml (news sources),
watchlists.yaml (OSS radar), policy.yaml (digest channels, budgets, retention).
Validated examples are in examples/.

## Layout

~~~
src/commons/
  settings.py          environment configuration (pydantic-settings)
  logging.py           application logging
  config.py            validated community YAML contracts
  errors.py            shared exception types
  text.py              slug and name helpers
  llm.py               one thin LLM module (no provider framework)
  prompts.py           prompt text
  digest.py            digest periods, candidate selection, synthesis
  community_repo/      git writer, artifact schemas, Markdown rendering
  discord/             bot, commands, archive/project/digest, bootstrap, alerts
  news/                SQLite news pipeline (ingest, dedup, temporal queries)
  github/              curated OSS watchlist radar
  web/                 read-only data layer for the optional UI
web/                   Streamlit pages (optional, read-only)
scripts/sync_discord.py
tests/                 pytest suite
docs/                  DEVELOPMENT, DEPLOYMENT, OPERATIONS
~~~

## Documentation

- docs/DEVELOPMENT.md - local setup, test guild, smoke test procedure
- docs/DEPLOYMENT.md - environment variables, service installation, scheduling
- docs/OPERATIONS.md - restart, logs, Git failure recovery, budget, retention
- AGENTS.md - repository and Git practices
- CHANGELOG.md - notable changes

## Licence

MIT.
