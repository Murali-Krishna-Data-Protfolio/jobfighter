"""
run_pipeline_for_user() — the one reusable pipeline entrypoint.

Deliberately framework-agnostic: takes plain data in (a profile dict, a
list of already-configured JobSource instances, a set of already-seen
job_ids, an API key) and returns plain data out (a RunResult + the list of
ScoredJob that passed). It does not know about the CLI, FastAPI, or
SQLAlchemy — that is what lets the exact same function be called from
cli/job_tracker_cli.py today (M1) and from the scheduler/web app once a
real database exists (M2+), with no rewrite — only the caller that
supplies existing_job_ids and persists the result changes.

Step order mirrors the confirmed architecture: fetch -> location filter ->
dedup -> classify (fail-closed, two-tier score) -> link-check -> done.
Location filtering happens BEFORE the Claude call on purpose — no reason to
spend an API call on a job that's already out of scope by geography.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from packages.core.models import NormalizedJob, RunResult, ScoredJob
from packages.scoring.classifier import classify_jobs
from packages.scoring.link_check import check_url
from packages.sources.base import JobSource


async def _fetch_all(
    sources: list[JobSource], queries: list[str], location: str, country_code: str
) -> list[NormalizedJob]:
    """Fetch from every source for every query, deduping by job_id as we
    go — mirrors fetch_all_jobs()'s aggregation in the old tool, one
    source's failure never blocks another (JobSource.fetch() itself never
    raises, per its contract)."""
    seen: set[str] = set()
    out: list[NormalizedJob] = []

    for source in sources:
        for query in queries:
            raw_results = await source.fetch(query, location, country_code)
            for raw in raw_results:
                try:
                    job = source.normalize(raw, query)
                except Exception:
                    continue  # one malformed raw record must not kill the run
                if job.job_id not in seen:
                    seen.add(job.job_id)
                    out.append(job)
            await source.check_rate_limit()

    return out


def _location_filter(jobs: list[NormalizedJob], country_code: str) -> list[NormalizedJob]:
    """Cheap deterministic pre-filter, applied before any Claude spend."""
    return [j for j in jobs if (j.country_code or "").upper() == country_code.upper()]


async def run_pipeline_for_user(
    *,
    profile: dict[str, Any],
    sources: list[JobSource],
    existing_job_ids: set[str],
    anthropic_api_key: str,
    link_check_concurrency: int = 10,
) -> tuple[RunResult, list[ScoredJob]]:
    started_at = datetime.now(timezone.utc)
    profile_id = profile.get("profile_id", "unknown")
    run = RunResult(profile_id=profile_id, started_at=started_at)

    try:
        queries: list[str] = profile.get("target_roles", [])
        location = profile.get("location", "France")
        country_code = profile.get("country_code", "FR")

        # 1. Fetch
        all_jobs = await _fetch_all(sources, queries, location, country_code)
        run.jobs_fetched = len(all_jobs)

        # 1b. Location filter (before dedup/classify — cheapest cut first)
        all_jobs = _location_filter(all_jobs, country_code)

        # 2. Dedup against what this profile has already seen
        new_jobs = [j for j in all_jobs if j.job_id not in existing_job_ids]
        run.jobs_deduped_new = len(new_jobs)

        if not new_jobs:
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            return run, []

        # 3. Classify — fail-closed, two-tier score
        api_key = anthropic_api_key
        classified = classify_jobs(api_key, profile, new_jobs)

        kept: list[ScoredJob] = []
        discarded = 0
        for job, result in classified:
            if result.score is None:
                discarded += 1
                continue
            kept.append(ScoredJob(job=job, result=result))
        run.jobs_discarded = discarded

        # 4. Link-check the survivors (bounded concurrency — this is
        # network-bound, not CPU-bound, so a semaphore-gated gather is the
        # right shape rather than sequential requests).
        sem = asyncio.Semaphore(link_check_concurrency)

        async def _checked(scored: ScoredJob) -> ScoredJob:
            async with sem:
                status, reason = await check_url(scored.job.url)
            scored.result.link_status = status
            if status != "dead":
                return scored
            return scored  # keep dead ones in the return list; caller decides display, but see filter below

        checked = await asyncio.gather(*(_checked(s) for s in kept))
        final = [s for s in checked if s.result.link_status != "dead"]
        run.dead_links_dropped = len(checked) - len(final)
        run.jobs_scored_kept = len(final)

        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        return run, final

    except Exception as e:  # noqa: BLE001 — a whole-run failure must be captured, not raised, so callers
        # (the scheduler in M3) can isolate one user's failure from every other user's run.
        run.status = "failed"
        run.error_summary = f"{type(e).__name__}: {e}"
        run.finished_at = datetime.now(timezone.utc)
        return run, []
