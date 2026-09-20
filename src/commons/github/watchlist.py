"""Berkeley / OSS radar over the GitHub API (plan sections 34-35).

This is a manually curated watchlist, not an ecosystem crawler. We fetch only
high-level activity - releases and selected issues - and never commit-by-commit.
State is stored in SQLite (watch_state); Git never stores this.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from commons.config import WatchEntry
from commons.logging import get_logger
from commons.news import db

log = get_logger(__name__)

USER_AGENT = "computing-commons/0.1 (+https://github.com/Computing-Commons-at-Berkeley)"
API_ROOT = "https://api.github.com"


@dataclass(frozen=True)
class RadarItem:
    repo: str
    kind: str
    title: str
    url: str
    updated_at: str | None = None
    labels: list[str] = field(default_factory=list)


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def fetch_releases(
    repo: str,
    *,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.get(
            f"{API_ROOT}/repos/{repo}/releases",
            headers=_headers(token),
            params={"per_page": 10},
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def fetch_issues(
    repo: str,
    *,
    since: str | None = None,
    labels: list[str] | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "state": "open",
        "sort": "updated",
        "direction": "desc",
        "per_page": 30,
    }
    if since:
        params["since"] = since
    if labels:
        params["labels"] = ",".join(labels)

    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.get(
            f"{API_ROOT}/repos/{repo}/issues", headers=_headers(token), params=params
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def collect_radar(
    repositories: list[WatchEntry],
    *,
    connection: sqlite3.Connection,
    since: datetime,
    now: datetime | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[RadarItem]:
    """Collect releases and selected issues updated since the given moment.

    A failing repository is logged and skipped; the rest of the radar and the
    digest still happen.
    """

    moment = now or datetime.now(UTC)
    items: list[RadarItem] = []

    for entry in repositories:
        repo_items: list[RadarItem] = []
        try:
            if entry.watch.releases:
                for release in fetch_releases(entry.repo, token=token, transport=transport):
                    published = _parse_ts(release.get("published_at"))
                    if published is None or published < since:
                        continue
                    title = str(release.get("name") or release.get("tag_name") or "").strip()
                    url = str(release.get("html_url") or "").strip()
                    if title and url:
                        repo_items.append(
                            RadarItem(
                                repo=entry.repo,
                                kind="release",
                                title=title,
                                url=url,
                                updated_at=published.isoformat(),
                            )
                        )

            if entry.watch.issues:
                since_iso = since.astimezone(UTC).isoformat().replace("+00:00", "Z")
                for issue in fetch_issues(
                    entry.repo,
                    since=since_iso,
                    labels=entry.issue_labels,
                    token=token,
                    transport=transport,
                ):
                    if "pull_request" in issue:
                        continue
                    updated = _parse_ts(issue.get("updated_at"))
                    if updated is None or updated < since:
                        continue
                    title = str(issue.get("title") or "").strip()
                    url = str(issue.get("html_url") or "").strip()
                    labels = [
                        str(label.get("name"))
                        for label in issue.get("labels", [])
                        if isinstance(label, dict)
                    ]
                    if title and url:
                        repo_items.append(
                            RadarItem(
                                repo=entry.repo,
                                kind="issue",
                                title=title,
                                url=url,
                                updated_at=updated.isoformat(),
                                labels=labels,
                            )
                        )
        except Exception as exc:  # noqa: BLE001 - one repo must not stop the radar
            log.warning("radar fetch for %s failed: %s", entry.repo, exc)
            continue

        db.set_watch_state(
            connection,
            entry.repo,
            last_checked_at=moment.isoformat(),
            state_json=json.dumps({"window_start": since.isoformat()}),
        )
        items.extend(repo_items)

    return items
