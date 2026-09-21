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

## Run the local UI (optional, read-only)

~~~powershell
.\.venv\Scripts\python -m pip install -e ".[ui]"
streamlit run web/app.py
~~~

The UI reads the same Git Markdown and runtime SQLite state. It never writes, has
no authentication, and the community does not depend on it.

## Bootstrap the Discord server

~~~powershell
.\.venv\Scripts\python scripts/sync_discord.py --dry-run
.\.venv\Scripts\python scripts/sync_discord.py
~~~

The script is non-destructive: objects that exist in Discord but not in
`config/discord.yaml` are reported, never deleted.

## Test guild smoke test (required for Discord changes)

1. Create or reuse a private test guild and invite the bot. Use a separate
   throwaway remote and checkout populated with the community config, point
   `COMMUNITY_REPO_PATH` there, and use a separate `RUNTIME_DIR`.
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
9. In the throwaway checkout only, set an invalid push URL with
   `git remote set-url --push origin <nonexistent-local-path>`, leaving the fetch
   URL intact. Archive a new source: confirm a local commit exists but the command
   reports push failure. Restore the previous push URL (or unset the override
   with `git config --unset-all remote.origin.pushurl` if none existed). Confirm
   retries still fail until you explicitly push the pending commit, then confirm
   the same source returns its existing artifact without another LLM call.
10. Run `/project name:"<a real idea>" goal:"<one line>"` and confirm the bot
    replies with an artifact path and that `data/projects/<slug>.md` exists.
11. Run `/project` again with the same name, or from inside the same thread, and
    confirm it returns the existing record instead of creating a second one.
12. Run `/digest period:7d` and confirm it writes `data/digests/<date>-7d.md`
    with at least one section (including news or project activity when present)
    and pushes a commit.
13. With all digest inputs empty in the isolated test instance (Discord activity,
    news, radar and project records), run `/digest period:1d` and confirm it fails
    clearly rather than committing an empty digest.
14. Let the scheduler's weekly job run (or temporarily shorten its interval) and
    confirm it posts the actual synthesis to `#digest`, including multiple text
    chunks when needed. Induce a generation or delivery failure and verify the
    `#bot-log` notice and retry, following the recovery notes in `OPERATIONS.md`.
15. With `GITHUB_TOKEN` set, run `/digest period:7d` and confirm the Berkeley /
    OSS Radar section reflects activity from `config/watchlists.yaml`, or is
    omitted when there is nothing new.

Also test archive denial with read-history permission removed, archiving disabled
by policy, and an inaccessible private thread. Check that no artifact or LLM call
results. An authorized private-thread member and the bot must both have access.
For digest input checks, use a busy channel, an archived public thread, and a
project with distinct goal/current-state text; verify the latest messages,
thread activity and both project fields reach the synthesis. Private threads are
excluded from automatic community digests.

## Layout

See `AGENTS.md` for the module map and the repository and Git practices.
