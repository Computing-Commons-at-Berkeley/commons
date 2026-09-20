from __future__ import annotations

from commons.text import normalize_channel_name, slugify, unique_slug


def test_slugify_basic() -> None:
    assert slugify("SGLang scheduling notes") == "sglang-scheduling-notes"


def test_slugify_collapses_separators() -> None:
    assert slugify("  a -- b__c  ") == "a-b-c"


def test_slugify_non_ascii_only_uses_stable_hash() -> None:
    title = "\u4e2d\u6587\u6807\u9898"
    assert slugify(title) == slugify(title)
    assert slugify(title).startswith("note-")


def test_slugify_mixed_cjk_and_ascii_keeps_ascii_tokens() -> None:
    title = "\u8fd9\u4e2a scheduler \u7684 batching policy"
    assert slugify(title) == "scheduler-batching-policy"


def test_slugify_respects_max_length() -> None:
    assert len(slugify("word " * 40)) <= 60


def test_unique_slug_appends_counter() -> None:
    assert unique_slug("note", set()) == "note"
    assert unique_slug("note", {"note"}) == "note-2"
    assert unique_slug("note", {"note", "note-2"}) == "note-3"


def test_normalize_channel_name() -> None:
    assert normalize_channel_name("ML Research") == "ml-research"
    assert normalize_channel_name("build_log") == "build-log"
