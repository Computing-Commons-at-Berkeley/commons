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
- News pipeline foundation: SQLite runtime schema (`sources`, `news_items`,
  `watch_state`, `llm_usage`), deterministic URL canonicalization and dedup, RSS
  and GitHub-release ingestion, and 24h/7d/30d temporal queries (`commons/news/`).
- In-process scheduling: news ingestion runs on the configured interval as part of
  the single runtime (`commons/scheduler.py`, `commons/news/run.py`).
- Unified digest: one code path combines Discord activity, stored news items, and
  project records into a single digest for `/digest` and the scheduled weekly
  digest, which posts to `#digest` (`commons/digest.py`,
  `commons/discord/digest.py`, `commons/discord/bot.py`).
- Berkeley / OSS radar: curated `watchlists.yaml` activity (releases and selected
  issues) fetched from the GitHub API, tracked in SQLite `watch_state`, and
  included as the Berkeley / OSS Radar digest section (`commons/github/`).
- Optional read-only local UI: Streamlit pages (Home, Feed, Projects, Berkeley,
  Knowledge, Resources, Search) over the same Git and SQLite state, plus a
  tested read-only data layer (`commons/web/`, `web/`).

### Changed

- Durable artifact writes force LF line endings and `.gitattributes` normalizes
  text files to LF, so artifacts are byte-stable across platforms (see
  `community/docs/DECISIONS.md` D006).

### Fixed

- Follow-up review B01-B08: valid Discord bootstrap overwrite arguments and
  nonzero failure exit; remote-graph push recovery; real history/private-thread
  authorization before reads; OS-owned writer locks; archive duplicate lookup
  before LLM use; recent and archived public thread digest inputs; both project
  goal and current state; scheduled digest/repeated ingestion failure alerts.
- Synchronize project records before digest collection and suppress mentions in
  operational notices. Added launch/recovery regression tests and corrected the
  isolated test-guild smoke procedure.

- Addressed the 2026-09-19 review findings: archive authorization checks guild,
  member policy, source and bot visibility before any read (R01); artifact paths
  are chosen inside the repository lock (R02); an unexpected dirty index stops the
  write and only the intended artifact is committed (R03); a failed push keeps the
  pending state visible until explicit recovery (R04); scheduled work runs off the
  event loop (R05); the scheduler is ready-gated with prompt retry and persisted
  due times (R06); digest content - not just a table of contents - is delivered to
  Discord (R07); one effective guild is used everywhere (R08); lock acquisition
  honors its deadline and Git subprocesses are bounded (R09); the selected message
  and its parent are always kept (R10); bootstrap honors privacy and reports
  permission differences (R11); tests are independent of the Git default branch
  (R12); blank optional environment values mean unset (R13); every digest source
  class keeps budget (R14).
- Operational: `#bot-log` notifications for startup, durable-write failures and
  budget warnings; `llm.on_limit` chooses warn or block; explicit LLM pricing
  overrides; daily news retention pruning; rejecting
  `privacy.persist_raw_discord_messages: true` because raw persistence is not
  implemented.
