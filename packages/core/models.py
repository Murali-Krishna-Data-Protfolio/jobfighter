"""
Core data contracts shared by every layer of the pipeline (sources,
scoring, outputs). Framework-agnostic — no FastAPI/SQLAlchemy imports here,
so the CLI, the scheduler, and the future web app can all depend on this
without pulling in HTTP or DB machinery.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


def make_job_id(title: str, company: str, source: str) -> str:
    """Stable id for a posting — same normalisation the old tool used, so
    the same job is recognised as the same job across runs and sources."""
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{source}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


class NormalizedJob(BaseModel):
    """The one schema every JobSource.normalize() must produce. Nothing
    downstream (scoring, dedup, storage, git archive) knows about any
    source-specific field shape beyond this."""

    job_id: str
    title: str
    company: str
    location: str
    country_code: str = "FR"
    salary: str | None = None
    url: str
    description: str = ""
    source: str
    search_query: str = ""


class ScoreResult(BaseModel):
    """Output of the two-tier English-workplace classifier. score is None
    when the job is discarded — never stored, per the fail-closed design."""

    description_is_english: bool
    requires_fluent_english: bool
    reason: str = ""
    score: float | None = None
    link_status: Literal["live", "unconfirmed", "dead"] = "unconfirmed"


class ScoredJob(BaseModel):
    """A NormalizedJob merged with its ScoreResult — what actually gets
    written out (Excel, git archive). Only ever constructed for jobs that
    passed scoring (score is not None) — see pipeline.py."""

    job: NormalizedJob
    result: ScoreResult
    date_seen: date = Field(default_factory=date.today)
    status: str = "Saved"  # application status — "Saved" is correct for a
    # freshly-classified job (M1 CLI); M2's export route overrides this
    # with the user's actual TrackedJob.status, since by then it may no
    # longer be "Saved" (Applied/Interview/Offer/Rejected).


class RunResult(BaseModel):
    """Summary of one pipeline execution for one profile — mirrors the
    `runs` table's columns from the M2+ data model, so the CLI's printed
    summary and the future DB row carry the same shape."""

    profile_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["success", "partial", "failed"] = "success"
    jobs_fetched: int = 0
    jobs_deduped_new: int = 0
    jobs_scored_kept: int = 0
    jobs_discarded: int = 0
    dead_links_dropped: int = 0
    error_summary: str | None = None
