# commons

Public, reusable infrastructure for the **Computing Commons at Berkeley**.

This repository contains the *mechanism*: the Discord bot, the archive/project/digest
workflows, news ingestion, GitHub watchlist tooling, and the optional read-only UI.
It deliberately contains **no community state, no secrets, and no member data**.

The private community instance lives in the sibling `community` repository. The two
are separate Git repositories; this one can be cloned and configured to run a
different community, but it will not give you ours.

## Mental model

~~~
Discord (conversation)
   -> bot (this repo)
   -> durable Markdown artifacts + commit/push
   -> private community repo (community/data/...)

external sources -> news ingestion -> SQLite (runtime/news.db)
                                  -> digest -> Git / Discord / UI
~~~

## Install (development)

~~~bash
py -3.13 -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
cp .env.example .env    # then fill it in
~~~

## Run

~~~bash
tc-bot                  # start the Discord bot
tc-sync-discord         # create missing channels/roles from community/config/discord.yaml
pytest
ruff check . && ruff format --check .
~~~

See docs/DEVELOPMENT.md, docs/DEPLOYMENT.md, and docs/OPERATIONS.md.

## Layout

~~~
src/commons/
  settings.py          environment configuration (pydantic-settings)
  logging.py           structured-ish application logging
  config.py            validated community YAML contracts
  errors.py            shared exception types
  text.py              slug/name helpers
  llm.py               one thin LLM module (no provider framework)
  prompts.py           prompt text
  community_repo/      git writer, artifact schemas, Markdown rendering
  discord/             bot shell, commands, archive workflow
  news/                (later) SQLite news pipeline
  github/              (later) watchlist polling
scripts/sync_discord.py
web/                   (later) optional read-only Streamlit UI
tests/
docs/
~~~

## Rules

- Keep it boring and Python-first. Adopt mature libraries; do not rebuild them.
- Modules first; abstractions only after demonstrated need.
- Never commit secrets. .env.example documents every variable.
- Failure degrades convenience, never disables the community.
