# AGENTS.md - commons

Guidance for agents and contributors working in **this** repository.

The sibling `community/` directory is a **separate Git repository**. Its
`docs/MENTAL_MODEL.md` is the frozen v0.1 specification and
`docs/IMPLEMENTATION_PLAN.md` is the working plan. Read both before making
design decisions. Do not redesign the conceptual architecture unless
implementation reveals a genuine contradiction; record such decisions in
`community/docs/DECISIONS.md`.

## What this repository is

Public, reusable infrastructure - "the mechanism". It must never contain:

- secrets, tokens, or credentials of any kind
- community state, member data, or private discussion
- anything so instance-specific that a different community could not configure it

If something is our community's data or configuration, it belongs in
`community/`, not here.

## Layout

~~~
pyproject.toml          packaging, pytest and ruff configuration
src/commons/            importable package (module-first, no service boundaries)
  settings.py           environment configuration (pydantic-settings)
  logging.py            logging setup (never log raw private conversation)
  config.py             validated contracts for community YAML
  text.py               slug/name helpers
  llm.py                one thin LLM module; no provider framework
  prompts.py            prompt text
  digest.py             digest logic (periods, candidate selection, synthesis)
  community_repo/       git writer, schemas, Markdown artifacts, projects, digests
  discord/              bot shell, commands, archive/project/digest workflows, sync
scripts/sync_discord.py CLI wrapper around commons.discord.sync
tests/                  pytest suite
docs/                   DEVELOPMENT.md, DEPLOYMENT.md, OPERATIONS.md
web/                    (later) optional read-only Streamlit UI
~~~

## Git practices (required)

### Repositories

- `commons/` and `community/` are **independent** Git repositories.
- Do **not** initialize Git at the workspace root, merge the repositories, or add
  Git submodules.
- Commit only inside the repository that owns the changed files. Never copy a
  file from one repository into the other by accident.

### Commit messages

- One logical change per commit; keep diffs reviewable.
- Imperative summary line; add a body when the "why" is not obvious.
- Prefixes: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`.
- The bot uses workflow prefixes for durable writes: `archive:`, `project:`,
  `digest:`.
- Examples:
  - `feat(archive): add message context action`
  - `fix(git): abort a failed rebase instead of leaving one behind`
  - `archive: add note on sglang scheduling`

### Branches and history

- `main` is the trunk and must stay green.
- Short-lived topic branches are fine; open a PR when a second maintainer exists.
- Do not force-push `main` and do not rewrite published history.

### Secrets and state

- Secrets live only in `.env` / environment variables; `.env.example` documents
  the contract. Never commit `.env`.
- `runtime/` (SQLite, cache, logs) is rebuildable and never committed.

## Definition of done

- `ruff check .` and `ruff format --check .` pass.
- `pytest` passes.
- New behavior has tests (config validation, artifact generation, slug/path
  generation, Git write behavior, LLM calls through mocks/fakes).
- Discord-facing behavior stays test-guild friendly and the smoke-test steps are
  documented.
- `CHANGELOG.md` is updated under `[Unreleased]`.

## Commands

~~~powershell
# one-time setup
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"

# verify
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
~~~

## Testing philosophy

Do not consider a feature complete because the code looks plausible. The first
success condition is a real Discord discussion becoming a durable
provenance-preserving Markdown artifact in the private repo with reliable Git
persistence and clear failure behavior.
