# Deployment

The v0.1 runtime is one bot process plus in-process scheduling and SQLite. There
are no microservices.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | yes | Bot token |
| `DISCORD_GUILD_ID` | yes in production | Production guild for command sync |
| `DISCORD_TEST_GUILD_ID` | no | Test guild; takes precedence for command sync |
| `GITHUB_TOKEN` | recommended | GitHub API for the OSS radar (higher rate limits) |
| `GITHUB_ORG` | later | Organization name |
| `COMMUNITY_REPO_PATH` | yes | Local checkout of the private community repository |
| `LLM_API_KEY` | yes | LLM provider key |
| `LLM_MODEL` | yes | Model name |
| `LLM_BASE_URL` | no | OpenAI-compatible endpoint |
| `RUNTIME_DIR` | recommended | Rebuildable state (defaults to `runtime/`); must be outside every Git repository |
| `LOG_LEVEL` | no | Defaults to `INFO` |

Secrets are supplied through the environment only. Nothing is stored in Git.

## Community repository checkout

The bot writes durable artifacts into a real clone of the private repository:

~~~bash
git clone git@github.com:<org>/community.git /srv/community
~~~

Point `COMMUNITY_REPO_PATH` at that path. The bot needs push access. Commits use
the explicit identity `Technical Commons Bot`; your own Git configuration is not
modified.

Every durable write is serialized with a lock file under `RUNTIME_DIR` and runs
`git pull --rebase` before writing and `git push` after committing.

## Runtime directory

~~~text
runtime/
  news.db            SQLite news state (later milestone)
  cache/
  logs/commons.log
  community_repo.lock
  llm_usage.jsonl
~~~

`RUNTIME_DIR` must not live inside `COMMUNITY_REPO_PATH`; startup validation
rejects that configuration. Deleting `runtime/` causes inconvenience. Deleting
the community repository is a disaster.

## Starting the bot

Foreground:

~~~bash
tc-bot
~~~

Persistent process (choose one appropriate to the host):

- systemd unit with `Restart=on-failure`
- Windows Service or Task Scheduler job
- any process supervisor (for example supervisord)

The bot is stateless apart from the community checkout and SQLite, so restarts
are safe. If the bot is offline the community continues to function as a normal
Discord server plus Git repository.

## Scheduled work

Scheduling runs in-process (`commons/scheduler.py`); there is no separate service.

- news ingestion, on `policy.news.ingest_interval_minutes`
- the weekly digest, which uses the same code path as `/digest` and posts to
  `#digest` when `policy.digest.scheduled_weekly` is true

Blocking work runs off the event loop, and one failing job never stops the loop.
