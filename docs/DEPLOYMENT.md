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
| `LLM_INPUT_PRICE_PER_MTOK` | no | Explicit input USD/1M tokens for an unlisted model |
| `LLM_OUTPUT_PRICE_PER_MTOK` | no | Explicit output USD/1M tokens for an unlisted model |
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
  news.db            SQLite news state
  cache/
  logs/commons.log
  community_repo.lock
  llm_usage.jsonl
  scheduler_state.json
~~~

`RUNTIME_DIR` must not live inside `COMMUNITY_REPO_PATH`; startup validation
rejects that configuration. Deleting `runtime/` causes inconvenience. Deleting
the community repository is a disaster.

## Starting the bot

Foreground:

~~~bash
tc-bot
~~~

On Windows, `scripts/start_bot.cmd` does the same with the working directory
fixed and the window kept open on exit, so it works well as a desktop shortcut.
Use `scripts/run_bot.cmd` for unattended startup instead.

Persistent process. Run the bot as the account that owns the Git credentials, so
that `git push` to the private community repository works.

### Windows (Task Scheduler)

`scripts/run_bot.cmd` fixes the working directory and starts the bot. Open an
**Administrator** PowerShell once and register a log-on task:

~~~powershell
$action = New-ScheduledTaskAction -Execute "C:\path\to\commons\scripts\run_bot.cmd"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "Technical Commons Bot" -Action $action -Trigger $trigger -Settings $settings -Force
~~~

Equivalent cmd.exe one-liner (without restart-on-failure settings):

~~~cmd
schtasks /Create /TN "Technical Commons Bot" /TR "C:\path\to\commons\scripts\run_bot.cmd" /SC ONLOGON /F
~~~

Manage it with `Start-ScheduledTask -TaskName "Technical Commons Bot"`,
`Get-ScheduledTask`, or `Unregister-ScheduledTask -TaskName "Technical Commons Bot"`.
Console output is appended to `logs/bot-console.log`.

Two caveats: the task cannot be created without elevation, and running the bot as
SYSTEM breaks `git push` because the stored credential belongs to your user
profile.

### Linux (systemd)

~~~ini
# /etc/systemd/system/commons-bot.service
[Unit]
Description=Technical Commons bot
After=network-online.target

[Service]
WorkingDirectory=/srv/commons
ExecStart=/srv/commons/.venv/bin/python -m commons.discord.bot
User=commonsbot
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
~~~

Then `sudo systemctl enable --now commons-bot`. On a server the Git credential
must be a deploy key or a PAT for that account; the Windows credential manager
does not exist there.

The bot is stateless apart from the community checkout and SQLite, so restarts
are safe. If the bot is offline the community continues to function as a normal
Discord server plus Git repository.

## Scheduled work

Scheduling runs in-process (`commons/scheduler.py`); there is no separate service.

- news ingestion, on `policy.news.ingest_interval_minutes`
- the weekly digest, which uses the same code path as `/digest` and posts to
  `#digest` when `policy.digest.scheduled_weekly` is true

Blocking work runs off the event loop, and one failing job never stops the loop.
Failures/deferred work retry after 15 minutes. Last successful runs are persisted;
retry deadlines themselves are not, so restarting may retry sooner.
Use a fixed working directory and absolute repository/runtime paths in the
service configuration. See `OPERATIONS.md` for alerts, partial digest delivery
and the requirement to stop old processes when upgrading the lock implementation.

## Local UI

The Streamlit UI is optional and runs on a developer machine:

~~~bash
pip install -e ".[ui]"
streamlit run web/app.py
~~~

It is read-only and requires no authentication. v0.1 does not deploy it as a
shared service (see V0.2_BACKLOG.md in the community repository).
