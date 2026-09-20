"""Deterministic URL canonicalization and content hashing.

These run before the LLM ever sees an item, and they are the basis of the dedup
rules in plan section 28. Do not add semantic duplicate detection in v0.1.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_EXACT = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
    "source",
}


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TRACKING_EXACT or lowered.startswith("utm_")


def canonicalize_url(url: str) -> str:
    """Lowercase scheme/host, drop tracking params and fragments, sort query."""

    raw = url.strip()
    parts = urlsplit(raw)
    if not parts.netloc and not parts.path.startswith("/"):
        # Schemeless input such as "example.com/a".
        parts = urlsplit("//" + raw)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking(key)
    ]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def content_hash(*parts: str) -> str:
    """Stable hash of normalized parts, used as a last-resort dedup key."""

    joined = "\n".join(part.strip().lower() for part in parts if part and part.strip())
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
