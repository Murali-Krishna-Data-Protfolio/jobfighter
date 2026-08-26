"""
Builds the list of configured JobSource instances from environment
variables. Shared by cli/job_tracker_cli.py and apps/web/routers/dashboard.py
so there's exactly one place that knows which env vars map to which
source — adding a new source here makes it available to both entrypoints
at once.

Per docs/architecture.md's API-budget note: these are account-level keys
shared across every tenant, not per-user secrets — that's intentional for
M2/M3 (a per-user "bring your own key" model is not part of this design).
"""

from __future__ import annotations

import os

from packages.sources.adzuna import AdzunaSource
from packages.sources.base import JobSource
from packages.sources.jsearch import JSearchSource


def build_sources() -> list[JobSource]:
    sources: list[JobSource] = []

    if os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"):
        sources.append(AdzunaSource({
            "app_id": os.environ["ADZUNA_APP_ID"],
            "app_key": os.environ["ADZUNA_APP_KEY"],
        }))

    if os.environ.get("RAPIDAPI_KEY"):
        sources.append(JSearchSource({"rapidapi_key": os.environ["RAPIDAPI_KEY"]}))

    return sources
