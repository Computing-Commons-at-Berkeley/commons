# Operations

Principle: automation failure reduces convenience, it does not break the
community. Discord and Git remain canonical even when the bot is down.

## Restarting the bot

Stop the process and start it again. There is no migration step: runtime state is
SQLite plus files under `RUNTIME_DIR`. On startup the bot re-syncs its
application commands to the configured guild.

## Logs

- Application log: `RUNTIME_DIR/logs/commons.log` plus stderr
- Level controlled by `LOG_LEVEL`

Logs record operational metadata (command success/failure, Git writes, ingestion
runs, LLM failures, cost warnings). They must not contain raw private
conversation.

## Runtime state locations

- News database: `RUNTIME_DIR/news.db` (created by the news pipeline)
- Cache: `RUNTIME_DIR/cache/`
- LLM usage: `RUNTIME_DIR/llm_usage.jsonl`
- Write lock: `RUNTIME_DIR/community_repo.lock`
- Scheduler last successful runs: `RUNTIME_DIR/scheduler_state.json`

These are rebuildable. They are not backed up as if they were community memory.

## Git write failure recovery

The bot performs, in order: lock, `git pull --rebase`, write, `git add`,
commit, push, unlock.

If the push fails:

- the local commit is kept - nothing is lost
- the command reports a failure and does not claim success
- the error is logged and is intended to reach `#bot-log`

Recovery:

1. Inspect the checkout: `git -C <COMMUNITY_REPO_PATH> status` and `git log`.
2. Resolve the cause (credentials, network, branch protection, divergence).
3. Push manually if appropriate: `git -C <COMMUNITY_REPO_PATH> push origin main`.
4. Retry the Discord action only if the artifact truly was not created; otherwise
   the idempotency check returns the existing note.

The lock file stays on disk. The operating system releases ownership when the
holder exits; file age never makes a live lock safe to steal. Do not delete the
file while a bot is running. Stop all older bot processes before upgrading from
the previous stale-file locking implementation. Every writer sharing a checkout
must use the same lock path on the same host.

Pending commits are checked against the synchronized remote branch. A manual
push needs no edit to the legacy `refs/tc/last-pushed` marker. A later command
will not silently push a previous failed command's commit.

## Operational notifications

Startup, durable-write failures and LLM budget warnings are posted to `#bot-log`.
Scheduled digest failures/deferred delivery and news sources failing three times
consecutively also produce notices. These recurring alerts are deduplicated
until recovery within one process lifetime; a restart may repeat an alert.
Recovery produces a notice. Routine successful news fetches are not reported.

Failed or deferred scheduled work retries after 15 minutes. A Discord delivery
failure can leave an already-pushed digest or partially delivered chunks. Check
`#digest` and the artifact before manual retries; delivery is not exactly-once,
and automatic retry can regenerate/repost content. Completed successes are saved
after the job batch and determine due times after restart. Retry deadlines are
in memory only, so a restart may retry sooner. Deleting scheduler state makes
jobs due again. A crash before the state save can also repeat a completed job.

## LLM budget

Usage is appended to `RUNTIME_DIR/llm_usage.jsonl` with token counts and an
estimated cost. When the monthly soft limit in `config/policy.yaml` is reached
the bot logs a warning and posts an operational notice to `#bot-log`.
`llm.on_limit: warn` (default) keeps calling; `llm.on_limit: block` refuses
further calls until the month rolls over. Models not in the built-in price table
are estimated at zero unless `LLM_INPUT_PRICE_PER_MTOK` / `LLM_OUTPUT_PRICE_PER_MTOK`
are set. The limit detects implementation bugs; it is not a billing system.

## News retention

`news.retention_days` prunes the news SQLite database daily; Git never stores the
news corpus.

## Token rotation

1. Generate a new Discord token in the developer portal.
2. Update the deployment environment and restart the bot.
3. Revoke the old token.
4. Repeat for `LLM_API_KEY` and `GITHUB_TOKEN` as needed.

If a token is ever committed, rotate it. Deleting the commit is not sufficient.

## Offboarding

- Remove Discord access.
- Remove GitHub organization and team access.
- Rotate shared secrets only when necessary.

At least two people should remain Discord admins and GitHub organization owners.
The bot may be maintained by one person, but the bot being offline must never
disable the community.

## Backup expectations

- Durable community memory: the private `community` Git repository, including
  its remote.
- Runtime SQLite and logs: rebuildable; a periodic copy is convenient, not
  critical.
- Secrets: stored in the deployment environment, not in Git.
