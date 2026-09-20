from __future__ import annotations

from pathlib import Path

import httpx

from commons.news.run import run_ingestion
from commons.settings import Settings

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Hello</title>
  <link>https://example.com/a</link>
  <guid>g1</guid>
  <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
</item>
</channel></rss>"""

SOURCES = """sources:
  - id: example
    type: rss
    url: https://example.com/feed.xml
    category: ml
"""


def make_settings(tmp_path: Path) -> Settings:
    community = tmp_path / "community"
    (community / "config").mkdir(parents=True)
    (community / "config" / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    return Settings(
        _env_file=None,
        community_repo_path=community,
        runtime_dir=tmp_path / "runtime",
    )


def test_run_ingestion_then_dedups(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    first = run_ingestion(settings, transport=transport)
    assert first[0].inserted == 1

    second = run_ingestion(settings, transport=transport)
    assert second[0].inserted == 0
    assert second[0].skipped == 1
