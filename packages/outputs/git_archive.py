"""
Commits newly-scored jobs into the separate `jobfighter-data` git repo,
per docs/architecture.md's public-archive design: monthly-chunked JSONL
(archive/YYYY-MM.jsonl), one row per posting, committed via a dedicated
bot identity — never the developer's personal git config. Monthly
chunking from day one is the direct fix for the old tool's Telegraph
CONTENT_TOO_BIG failure at ~500 rows in one blob.

Configured entirely via env vars, all optional — if
JOBFIGHTER_DATA_REPO_PATH is unset, archiving is a documented no-op (so
M1/M2 local dev, CI, and any deployment without the second repo checked
out never need one). A run that already succeeded and was already saved
to Postgres must never be marked failed because of an archive hiccup —
every failure here is caught and logged, never raised, mirroring the
pipeline's own per-run isolation.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

from packages.core.models import ScoredJob

log = logging.getLogger(__name__)

_ARCHIVE_SUBDIR = "archive"


def archive_repo_path() -> Path | None:
    raw = os.environ.get("JOBFIGHTER_DATA_REPO_PATH")
    return Path(raw) if raw else None


def _row_for(scored: ScoredJob) -> dict:
    job, result = scored.job, scored.result
    return {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "description": job.description,
        "source": job.source,
        "search_query": job.search_query,
        "score": result.score,
        "description_is_english": result.description_is_english,
        "requires_fluent_english": result.requires_fluent_english,
        "date_seen": scored.date_seen.isoformat(),
        "date_last_seen": datetime.now(timezone.utc).isoformat(),
    }


def archive_and_commit(scored_jobs: list[ScoredJob], run_id: str) -> str | None:
    """Appends newly-scored jobs to this month's JSONL file and
    commits (+ pushes unless GIT_ARCHIVE_PUSH=false) via a bot identity.
    Returns the commit hexsha on success, None if archiving is
    unconfigured, there was nothing to write, or the commit itself
    failed — never raises."""
    if not scored_jobs:
        return None
    repo_path = archive_repo_path()
    if repo_path is None:
        return None

    try:
        import git  # GitPython — imported lazily, only required when archiving is actually configured

        month_file = repo_path / _ARCHIVE_SUBDIR / f"{date.today().strftime('%Y-%m')}.jsonl"
        month_file.parent.mkdir(parents=True, exist_ok=True)
        with month_file.open("a", encoding="utf-8") as f:
            for scored in scored_jobs:
                f.write(json.dumps(_row_for(scored), ensure_ascii=False) + "\n")

        repo = git.Repo(repo_path)
        with repo.config_writer() as cw:
            cw.set_value("user", "name", os.environ.get("GIT_ARCHIVE_BOT_NAME", "jobfighter-bot"))
            cw.set_value("user", "email", os.environ.get("GIT_ARCHIVE_BOT_EMAIL", "bot@jobfighter.local"))

        rel_path = month_file.relative_to(repo_path).as_posix()
        repo.index.add([rel_path])
        commit = repo.index.commit(f"run {run_id}: +{len(scored_jobs)} jobs — {date.today().isoformat()}")

        if os.environ.get("GIT_ARCHIVE_PUSH", "true").lower() != "false":
            origin = repo.remote(name=os.environ.get("GIT_ARCHIVE_REMOTE", "origin"))
            origin.push()

        return commit.hexsha
    except Exception as e:  # noqa: BLE001 — archiving is best-effort, must never fail an already-saved run
        log.warning("git archive commit failed: %s: %s", type(e).__name__, e)
        return None
