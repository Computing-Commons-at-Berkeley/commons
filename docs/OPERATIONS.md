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

A stale lock file can be removed if no bot process is running. Stale locks are
also detected and cleared automatically after the lock timeout.

## Operational notifications

Startup, durable-write failures and LLM budget warnings are posted to `#bot-log`.
Only meaningful events are sent; routine news fetches are not.

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
