"""Small, source-agnostic helpers used by every ingestion module."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pandas as pd


def fips5(value: object) -> str | None:
    """Return a five-character county FIPS or None for an empty value."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.removesuffix(".0")
    if not text.isdigit():
        return None
    return text.zfill(5)


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_naive(value: object, source_tz: str | None = None) -> pd.Timestamp:
    """Parse a timestamp to UTC then drop the timezone for DuckDB storage.

    A timezone-naive source is rejected unless the caller explicitly supplies its
    documented source timezone. This makes timezone assumptions reviewable.
    """
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        if source_tz is None:
            raise ValueError("timezone-naive input requires an explicit source_tz")
        timestamp = timestamp.tz_localize(source_tz)
    return timestamp.tz_convert("UTC").tz_localize(None)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
