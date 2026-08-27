"""
M3 sweep entrypoint — meant to be invoked periodically by the host's own
scheduler (Render's native Cron Job service type in production, plain OS
cron/Task Scheduler for local dev), NOT a long-running daemon itself:
each invocation queries every active profile, runs the due ones, and
exits. This matches docs/architecture.md's "in-process / cron-triggered
sweep" choice for M1-M3 — no APScheduler event loop, no Redis queue,
until M4's actual trigger condition is hit.

Usage:
    python -m scheduler.run_due_profiles

Reuses run_pipeline_for_user() unchanged (the same function the CLI and
the web app's /run endpoint call) — this file only adds what's new for
M3: cron due-ness (packages/core/schedule.py), bounded concurrency across
profiles, per-profile session/failure isolation, and the git-archive step.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from packages.core.pipeline import run_pipeline_for_user
from packages.core.schedule import is_due
from packages.core.source_config import build_sources
from packages.db.crud import (
    get_active_profiles,
    get_existing_job_ids,
    get_latest_run_for_profile,
    save_run,
    upsert_job_posting,
)
from packages.db.models import CandidateProfile
from packages.db.session import SessionLocal
from packages.outputs.git_archive import archive_and_commit
from packages.sources.base import JobSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scheduler")

MAX_CONCURRENT_RUNS = int(os.environ.get("SCHEDULER_MAX_CONCURRENT_RUNS", "3"))


async def _run_one_profile(
    profile: CandidateProfile, sem: asyncio.Semaphore, api_key: str, sources: list[JobSource]
) -> None:
    """Each profile gets its own session/transaction, opened only once
    its semaphore slot is acquired — a bad API key or malformed response
    on one profile's run can never block or corrupt another's
    (docs/architecture.md's per-user failure isolation), and a queued
    profile never holds a DB session open while waiting for a slot."""
    async with sem:
        async with SessionLocal() as session:
            try:
                existing_ids = await get_existing_job_ids(session)
                run_result, scored_jobs = await run_pipeline_for_user(
                    profile=profile.to_pipeline_dict(),
                    sources=sources,
                    existing_job_ids=existing_ids,
                    anthropic_api_key=api_key,
                )
                for scored in scored_jobs:
                    await upsert_job_posting(session, scored)
                run_row = await save_run(session, run_result)
                await session.commit()

                if run_result.status == "success":
                    archive_and_commit(scored_jobs, run_row.id)

                log.info(
                    "profile=%s status=%s fetched=%d kept=%d discarded=%d dead_links=%d",
                    profile.id, run_result.status, run_result.jobs_fetched,
                    run_result.jobs_scored_kept, run_result.jobs_discarded, run_result.dead_links_dropped,
                )
            except Exception:
                # run_pipeline_for_user already catches its own errors and
                # returns a 'failed' RunResult rather than raising — this
                # is the outer safety net for a DB/archive failure around
                # it, so an infrastructure error on one profile still
                # can't take down the sweep for every other profile.
                await session.rollback()
                log.exception("unhandled error running profile=%s", profile.id)


async def run_sweep() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    sources = build_sources()
    if not sources:
        log.error("no sources configured (ADZUNA_APP_ID/KEY or RAPIDAPI_KEY) — nothing to do")
        return 1

    async with SessionLocal() as session:
        profiles = await get_active_profiles(session)
        due: list[CandidateProfile] = []
        for profile in profiles:
            latest = await get_latest_run_for_profile(session, profile.id)
            if is_due(profile.schedule_cron, profile.timezone, latest.started_at if latest else None):
                due.append(profile)

    log.info("sweep: %d active profile(s), %d due", len(profiles), len(due))
    if not due:
        return 0

    sem = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
    await asyncio.gather(*(_run_one_profile(p, sem, api_key, sources) for p in due))
    return 0


def main() -> None:
    sys.exit(asyncio.run(run_sweep()))


if __name__ == "__main__":
    main()
