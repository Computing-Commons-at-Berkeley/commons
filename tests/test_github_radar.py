from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from commons.config import WatchEntry
from commons.digest import RadarCandidate, build_candidate_text
from commons.github.run import collect_radar_from_settings
from commons.github.watchlist import collect_radar
from commons.news import db
from commons.settings import Settings

NOW = datetime(2026, 1, 10, tzinfo=UTC)
SINCE = NOW - timedelta(days=7)

WATCHLIST_YAML = """repositories:
  - repo: example/project
    category: berkeley
    reason: Relevant local ML systems project.
    watch:
      releases: true
      issues: false
"""


def make_entry(**overrides: object) -> WatchEntry:
    data: dict[str, object] = {
        "repo": "example/project",
        "category": "berkeley",
        "reason": "Relevant local ML systems project.",
        "watch": {"releases": True, "issues": True},
        "issue_labels": ["good first issue", "help wanted"],
    }
    data.update(overrides)
    return WatchEntry.model_validate(data)


def make_connection(tmp_path: Path):
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)
    return connection


def handler_for_activity(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/releases"):
        return httpx.Response(
            200,
            json=[
                {
                    "name": "v2.0",
                    "html_url": "https://github.com/example/project/releases/tag/v2.0",
                    "published_at": "2026-01-09T00:00:00Z",
                },
                {
                    "name": "v1.0",
                    "html_url": "https://github.com/example/project/releases/tag/v1.0",
                    "published_at": "2025-01-01T00:00:00Z",
                },
            ],
        )
    if request.url.path.endswith("/issues"):
        return httpx.Response(
            200,
            json=[
                {
                    "title": "Fix scheduler",
                    "html_url": "https://github.com/example/project/issues/5",
                    "updated_at": "2026-01-08T00:00:00Z",
                    "labels": [{"name": "good first issue"}],
                },
                {
                    "title": "A pull request",
                    "html_url": "https://github.com/example/project/pull/6",
                    "updated_at": "2026-01-09T00:00:00Z",
                    "pull_request": {},
                },
                {
                    "title": "Ancient issue",
                    "html_url": "https://github.com/example/project/issues/1",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "labels": [],
                },
            ],
        )
    return httpx.Response(404)


def test_collect_radar_filters_and_records_state(tmp_path: Path) -> None:
    connection = make_connection(tmp_path)

    items = collect_radar(
        [make_entry()],
        connection=connection,
        since=SINCE,
        now=NOW,
        transport=httpx.MockTransport(handler_for_activity),
    )

    titles = {item.title for item in items}
    assert "v2.0" in titles
    assert "Fix scheduler" in titles
    assert "v1.0" not in titles
    assert "A pull request" not in titles
    assert "Ancient issue" not in titles

    issue = next(item for item in items if item.kind == "issue")
    assert issue.labels == ["good first issue"]
    assert issue.repo == "example/project"

    state = db.get_watch_state(connection, "example/project")
    assert state is not None
    assert state["last_checked_at"].startswith("2026-01-10")


def test_collect_radar_survives_api_error(tmp_path: Path) -> None:
    connection = make_connection(tmp_path)

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    items = collect_radar(
        [make_entry()],
        connection=connection,
        since=SINCE,
        now=NOW,
        transport=httpx.MockTransport(failing),
    )
    assert items == []
    assert db.get_watch_state(connection, "example/project") is None


def test_collect_radar_from_settings(tmp_path: Path) -> None:
    community = tmp_path / "community"
    (community / "config").mkdir(parents=True)
    (community / "config" / "watchlists.yaml").write_text(WATCHLIST_YAML, encoding="utf-8")
    settings = Settings(
        _env_file=None,
        community_repo_path=community,
        runtime_dir=tmp_path / "runtime",
    )

    items = collect_radar_from_settings(
        settings,
        since=SINCE,
        now=NOW,
        transport=httpx.MockTransport(handler_for_activity),
    )
    assert [item.title for item in items] == ["v2.0"]


def test_build_candidate_text_includes_radar() -> None:
    text = build_candidate_text(
        [],
        radar=[
            RadarCandidate(
                repo="example/project",
                title="v2.0",
                url="https://example.test/r",
                kind="release",
            )
        ],
    )
    assert "## OSS Radar" in text
    assert "example/project [release] v2.0" in text
