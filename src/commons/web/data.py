"""Read-only data access for the optional local UI (plan sections 40-42).

Everything here reads durable Markdown artifacts and the runtime SQLite database.
Nothing writes, and nothing requires authentication. The UI can be deleted
without affecting the community.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from commons.community_repo.artifacts import parse_knowledge_artifact
from commons.community_repo.digests import parse_digest_artifact
from commons.community_repo.markdown import parse_frontmatter
from commons.community_repo.projects import list_projects
from commons.community_repo.schemas import DigestArtifact, KnowledgeArtifact, ProjectArtifact
from commons.errors import ArtifactError
from commons.news import db as news_db
from commons.news.query import items_for_window

ARTIFACT_DIRS = ("knowledge", "projects", "digests", "resources")


def knowledge_artifacts(data_root: Path) -> list[KnowledgeArtifact]:
    directory = Path(data_root) / "knowledge"
    if not directory.exists():
        return []
    items: list[KnowledgeArtifact] = []
    for path in sorted(directory.glob("*.md")):
        try:
            items.append(parse_knowledge_artifact(path.read_text(encoding="utf-8")))
        except (ArtifactError, OSError):
            continue
    return items


def projects(data_root: Path) -> list[ProjectArtifact]:
    return list_projects(Path(data_root))


def digests(data_root: Path) -> list[DigestArtifact]:
    directory = Path(data_root) / "digests"
    if not directory.exists():
        return []
    items: list[DigestArtifact] = []
    for path in sorted(directory.glob("*.md")):
        try:
            items.append(parse_digest_artifact(path.read_text(encoding="utf-8")))
        except (ArtifactError, OSError):
            continue
    return sorted(items, key=lambda digest: digest.period_end, reverse=True)


def latest_digest(data_root: Path) -> DigestArtifact | None:
    found = digests(data_root)
    return found[0] if found else None


def resources(data_root: Path) -> list[Path]:
    directory = Path(data_root) / "resources"
    return sorted(directory.glob("*.md")) if directory.exists() else []


def news_items(
    db_path: Path,
    window: str = "7d",
    *,
    category: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    connection = news_db.connect(Path(db_path))
    try:
        news_db.init_db(connection)
        return items_for_window(connection, window, category=category, limit=limit)
    finally:
        connection.close()


def watch_state(db_path: Path) -> list[dict[str, Any]]:
    connection = news_db.connect(Path(db_path))
    try:
        news_db.init_db(connection)
        rows = connection.execute(
            "SELECT repo, last_checked_at, state_json FROM watch_state ORDER BY repo"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


@dataclass(frozen=True)
class SearchHit:
    kind: str
    title: str
    location: str
    snippet: str


def _markdown_files(data_root: Path) -> list[Path]:
    files: list[Path] = []
    for name in ARTIFACT_DIRS:
        directory = Path(data_root) / name
        if directory.exists():
            files.extend(sorted(directory.glob("*.md")))
    return files


def _title_for(path: Path, text: str) -> str:
    try:
        data, _body = parse_frontmatter(text)
    except ArtifactError:
        return path.stem
    return str(data.get("title") or path.stem)


def search(data_root: Path, db_path: Path, query: str, *, limit: int = 50) -> list[SearchHit]:
    """Simple case-insensitive search over Markdown artifacts and news metadata.

    Data volume is tiny in v0.1; a full scan is acceptable and avoids building
    indexing infrastructure (plan section 42).
    """

    needle = query.strip().lower()
    if not needle:
        return []

    hits: list[SearchHit] = []
    for path in _markdown_files(data_root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lowered = text.lower()
        index = lowered.find(needle)
        if index < 0:
            continue
        snippet = " ".join(text[max(0, index - 60) : index + 90].split())
        hits.append(
            SearchHit(
                kind=path.parent.name.rstrip("s"),
                title=_title_for(path, text),
                location=path.as_posix(),
                snippet=snippet,
            )
        )
        if len(hits) >= limit:
            return hits

    connection: sqlite3.Connection = news_db.connect(Path(db_path))
    try:
        news_db.init_db(connection)
        rows = connection.execute(
            """
            SELECT title, url, category FROM news_items
            WHERE lower(title) LIKE ? OR lower(url) LIKE ?
            ORDER BY COALESCE(published_at, fetched_at) DESC
            LIMIT ?
            """,
            (f"%{needle}%", f"%{needle}%", limit),
        ).fetchall()
    finally:
        connection.close()
    for row in rows:
        hits.append(
            SearchHit(
                kind="news",
                title=row["title"],
                location=row["url"],
                snippet=row["category"],
            )
        )
    return hits
