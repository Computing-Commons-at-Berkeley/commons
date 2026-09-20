"""Small text helpers used across artifact naming and configuration."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")
_NAME_SEPARATORS = re.compile(r"[\s_]+")


def slugify(value: str, *, fallback_prefix: str = "note", max_length: int = 60) -> str:
    """Return a filesystem-safe slug.

    Non-ASCII titles (for example Chinese) have no ASCII remainder, so a short
    stable hash of the original value is used instead. This keeps slugs
    deterministic, which matters for idempotency.
    """

    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_SEPARATORS.sub("-", ascii_only.lower()).strip("-")
    if not slug:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
        slug = f"{fallback_prefix}-{digest}"
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def normalize_channel_name(value: str) -> str:
    """Discord channel names are lowercase with hyphens."""

    name = _NAME_SEPARATORS.sub("-", value.strip().lower())
    name = re.sub(r"-{2,}", "-", name).strip("-")
    if not name:
        raise ValueError("channel name must not be empty")
    return name


def normalize_role_name(value: str) -> str:
    """Role names keep their case but drop surrounding whitespace."""

    name = value.strip()
    if not name:
        raise ValueError("role name must not be empty")
    return name


def unique_slug(base: str, taken: set[str]) -> str:
    """Return base, base-2, base-3, ... until the value is unused."""

    if base not in taken:
        return base
    index = 2
    while f"{base}-{index}" in taken:
        index += 1
    return f"{base}-{index}"
