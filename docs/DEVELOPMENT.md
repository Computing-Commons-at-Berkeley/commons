# Development

## Prerequisites

- Python 3.11 or newer
- Git on PATH
- A private Discord test guild (never debug against the production community)

## Setup

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
~~~

Edit `.env`:

- `DISCORD_TOKEN` - bot token from the Discord developer portal
- `DISCORD_TEST_GUILD_ID` - your private test guild
- `COMMUNITY_REPO_PATH` - absolute path to a local checkout of the private
  `community` repository
- `LLM_API_KEY` and `LLM_MODEL` - your LLM provider
- `RUNTIME_DIR` - a directory outside every Git repository (default `runtime`)

Never commit `.env`.

## Verify

~~~powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
~~~

## Run the bot

~~~powershell
.\.venv\Scripts\python -m commons.discord.bot
~~~

The bot syncs its commands to `DISCORD_TEST_GUILD_ID` when that is set, so
development commands appear immediately in the test guild without touching
production.

## Bootstrap the Discord server

~~~powershell
python scripts/sync_discord.py --dry-run   # print the plan
python scripts/sync_discord.py             # create missing roles/categories/channels
~~~

The script is non-destructive: objects that exist in Discord but not in
`config/discord.yaml` are reported, never deleted.

## Test guild smoke test (required for Discord changes)

1. Create or reuse a private test guild and invite the bot.
2. Run `scripts/sync_discord.py --dry-run`, then run it for real.
3. Start the bot and confirm the `Archive` message context action and the
   `/archive`, `/project`, and `/digest` commands appear.
4. Post a short multi-message thread.
5. Right-click the thread's first message, choose Apps, then Archive.
6. Confirm the bot replies with a title and artifact path.
7. Confirm the artifact exists under `data/knowledge/` in the community checkout
   and that a commit was pushed.
8. Invoke Archive again on the same source and confirm it reports the existing
   artifact instead of duplicating it.
9. Break the remote (point `origin` at a bad path) and confirm Archive reports a
   clear failure and does not claim success.
10. Run `/project name:"<a real idea>" goal:"<one line>"` and confirm the bot
    replies with an artifact path and that `data/projects/<slug>.md` exists.
11. Run `/project` again with the same name, or from inside the same thread, and
    confirm it returns the existing record instead of creating a second one.
12. Run `/digest period:7d` and confirm it writes `data/digests/<date>-7d.md`
    with at least one section and pushes a commit.
13. In a quiet period, run `/digest period:1d` and confirm it fails clearly
    rather than committing an empty digest.

## Layout

See `AGENTS.md` for the module map and the repository and Git practices.
