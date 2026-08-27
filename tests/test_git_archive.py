"""
Regression tests for packages/outputs/git_archive.py:
1. Unconfigured (no JOBFIGHTER_DATA_REPO_PATH) must be a silent no-op —
   local dev/CI never need a second repo checked out.
2. Configured: writes the current month's JSONL file and produces a real
   commit under a bot identity, never the caller's own git config.
3. A commit failure (e.g. not a git repo at all) must be swallowed, not
   raised — an archive hiccup must never fail an already-saved run.
"""

import json
from datetime import date

import git
import pytest

from packages.core.models import NormalizedJob, ScoreResult, ScoredJob
from packages.outputs import git_archive


def _scored_job(job_id="j1") -> ScoredJob:
    return ScoredJob(
        job=NormalizedJob(
            job_id=job_id, title="Data Analyst", company="Acme", location="Paris",
            url="https://example.com/1", source="adzuna",
        ),
        result=ScoreResult(description_is_english=True, requires_fluent_english=True, score=1.0),
    )


def test_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("JOBFIGHTER_DATA_REPO_PATH", raising=False)
    assert git_archive.archive_and_commit([_scored_job()], run_id="run-1") is None


def test_noop_when_no_scored_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIGHTER_DATA_REPO_PATH", str(tmp_path))
    assert git_archive.archive_and_commit([], run_id="run-1") is None


def test_writes_monthly_jsonl_and_commits_with_bot_identity(monkeypatch, tmp_path):
    repo = git.Repo.init(tmp_path)
    # a fresh init has no commits yet; index.commit() works fine without one

    monkeypatch.setenv("JOBFIGHTER_DATA_REPO_PATH", str(tmp_path))
    monkeypatch.setenv("GIT_ARCHIVE_PUSH", "false")  # no remote configured in this test
    monkeypatch.setenv("GIT_ARCHIVE_BOT_NAME", "jobfighter-bot")
    monkeypatch.setenv("GIT_ARCHIVE_BOT_EMAIL", "bot@jobfighter.local")

    sha = git_archive.archive_and_commit([_scored_job("j1"), _scored_job("j2")], run_id="run-42")

    assert sha is not None
    commit = repo.commit(sha)
    assert commit.author.name == "jobfighter-bot"
    assert commit.author.email == "bot@jobfighter.local"
    assert "run-42" in commit.message
    assert "+2 jobs" in commit.message

    month_file = tmp_path / "archive" / f"{date.today().strftime('%Y-%m')}.jsonl"
    assert month_file.exists()
    lines = month_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["job_id"] == "j1"
    assert row["score"] == 1.0


def test_commit_failure_is_swallowed_not_raised(monkeypatch, tmp_path):
    # tmp_path is NOT a git repo at all — git.Repo(...) raises inside
    # archive_and_commit, which must catch it and return None.
    monkeypatch.setenv("JOBFIGHTER_DATA_REPO_PATH", str(tmp_path))
    monkeypatch.setenv("GIT_ARCHIVE_PUSH", "false")

    result = git_archive.archive_and_commit([_scored_job()], run_id="run-err")
    assert result is None
