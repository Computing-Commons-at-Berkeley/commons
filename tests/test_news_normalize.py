from __future__ import annotations

from commons.news.normalize import canonicalize_url, content_hash


def test_canonicalize_strips_tracking_and_fragment() -> None:
    assert (
        canonicalize_url("https://www.Example.com/Post/?utm_source=x&b=2&a=1#frag")
        == "https://example.com/Post?a=1&b=2"
    )


def test_canonicalize_is_idempotent() -> None:
    url = "https://example.com/a?utm_medium=rss"
    assert canonicalize_url(canonicalize_url(url)) == canonicalize_url(url)


def test_canonicalize_adds_default_scheme() -> None:
    assert canonicalize_url("example.com/a") == "https://example.com/a"


def test_content_hash_is_case_and_space_normalized() -> None:
    assert content_hash("Hello ", " World") == content_hash("hello", "world")
    assert content_hash("a") != content_hash("b")
