"""
JobSource — the contract every job source implements.

Adding a new source means writing one file with one class and registering
it (see registry.py) — nothing in packages/core or the pipeline ever needs
to change. This is the direct fix for the old tool's problem where adding
a source meant editing job_fetcher.py's fetch_all_jobs() aggregator by hand.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from packages.core.models import NormalizedJob


class JobSource(ABC):
    """Base class for a job source. One instance per configured source
    (a `sources` row in the M2+ schema); `config` holds whatever that
    source needs (API keys, a career-page URL, etc.)."""

    source_type: str = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    async def fetch(self, query: str, location: str, country_code: str) -> list[dict[str, Any]]:
        """Return raw, source-native job dicts for one search query. Must
        never raise on an empty result set — return [] instead. Network/API
        errors should be caught here and logged, also returning []: one
        source having a bad day must not take down the whole fetch step for
        every other source (mirrors the old tool's per-source try/except in
        fetch_all_jobs)."""

    @abstractmethod
    def normalize(self, raw: dict[str, Any], query: str) -> NormalizedJob:
        """Map one source-native raw dict to the standard NormalizedJob
        schema. Should not need network access — pure data mapping."""

    async def check_rate_limit(self) -> None:
        """Politeness/backoff hook, called between calls within a single
        source. Default: no-op — override for sources that need it (the
        old tool's flat time.sleep(0.8) between every platform call is
        replaced by per-source control here, since not every source needs
        the same politeness delay)."""
        return None
